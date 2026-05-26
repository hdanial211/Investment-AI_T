"""
ai_engine.py - Cloud AI Decision Engine

Responsibilities:
- Build structured prompts with multi-timeframe market data
- Enforce symbol-specific rules (EURUSD vs XAUUSD)
- Call OpenRouter / Hugging Face cloud AI through provider clients
- Optionally use a second model for risk review
- Return BUY / SELL / HOLD signal
"""

import json
import logging
import re
import threading
import time
from typing import Dict, Optional

import config
from ai_clients import AIProviderError, get_client, get_model_for_role, get_provider_sequence
from strategy import format_for_prompt

logger = logging.getLogger(__name__)
_AI_CALL_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

BASE_INSTRUCTION = """You are an elite institutional algorithmic trading AI.
Your objective is to analyze multi-timeframe (MTF) market data and provide a highly accurate trading decision.

CRITICAL JSON OUTPUT RULES:
1. Respond ONLY with a valid JSON object.
2. Format: {"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0-1.0, "trade_style": "SCALPING"|"INTRADAY"|"SWING", "reason": "brief explanation"}
3. No markdown blocks, no extra text.
"""

RISK_REVIEW_INSTRUCTION = """You are a quantitative trading risk reviewer.
Your job is to approve or reject a proposed trade after the primary AI has already produced a signal.

CRITICAL JSON OUTPUT RULES:
1. Respond ONLY with a valid JSON object.
2. Format: {"approved": true|false, "confidence": 0.0-1.0, "reason": "brief explanation"}
3. Approve only when the risk/reward, market regime, trend, and pattern confluence are acceptable.
4. No markdown blocks, no extra text.
"""

SYMBOL_RULES = {
    "EURUSD": """
--- ASSET BEHAVIOR: EURUSD ---
EURUSD is a technical, orderly forex major.
- H4 Trend is KING. Do not trade against the H4 Major Trend.
- Respect H1 Support/Resistance zones.
- Engulfing patterns at S/R zones are highly reliable.
- Look for orderly break & retest.
- Give extra weight to HIGH priority pattern confluence: Double Top/Bottom, Head & Shoulders, Engulfing, Pin Bar, Inside Bar, Symmetrical Triangle, and Bullish/Bearish Flag.
- Treat harmonic patterns as confirmation only unless they align with H4 trend and H1 support/resistance.
- If pattern bias conflicts with H4 trend or price is not near a meaningful level, return HOLD.
- If H4 is sideways or unclear, return HOLD.
""",
    "XAUUSD": """
--- ASSET BEHAVIOR: XAUUSD (GOLD) ---
XAUUSD is highly volatile and prone to institutional manipulation (stop hunts).
- Do not blindly trade breakouts. Gold often stop-runs first, especially in Asia.
- Asia session: prioritize liquidity sweep, Fakey/Hikkake, SMC reversal, and psych-level rejection.
- London/NY sessions: momentum breakouts, opening-range breaks, flags, pennants, and Marubozu continuation become more reliable.
- Give extra weight to HIGH priority Gold confluence: Liquidity Sweep + FVG, Order Block retest, Psych Level Bounce/Break, Pin Bar at key level, Engulfing with volume, Double Top/Bottom, Head & Shoulders, Flags, Symmetrical Triangle, and Rising/Falling Wedge.
- Pin Bars need stronger proof on Gold: 3:1 wick/body and key-level context.
- Engulfing patterns need strong body dominance and should not be traded in the middle of a range.
- If DXY bias is unavailable, do not assume macro confirmation; require stronger local confluence.
- If pattern bias conflicts with H4 trend and there is no liquidity sweep / SMC reversal, return HOLD.
- If price is near a $50/$100 psych level, treat rejection or break-and-retest as important context.
"""
}


def build_prompt(indicators: Dict, bid: float, ask: float, trade_memory=None, symbol: str = "UNKNOWN") -> str:
    symbol = indicators.get("symbol", "")
    
    # Get specific rules based on symbol, fallback to general if unknown
    specific_rules = ""
    for k, v in SYMBOL_RULES.items():
        if k in symbol:
            specific_rules = v
            break

    market_section = format_for_prompt(indicators)
    spread = round(ask - bid, 5)

    prompt = f"""{BASE_INSTRUCTION}
{specific_rules}
--- CURRENT MARKET DATA ---
{market_section}
Bid: {bid}
Ask: {ask}
Spread: {spread}

--- INSTRUCTIONS ---
Evaluate the timeframes logically:
1. Does the trade align with the H4 Major Trend? (If not, HOLD).
2. Is the price near H1 Support/Resistance?
3. What is M30/M15/M5/M1 telling you? M30/M15 define intraday direction; M5/M1 are execution triggers only.
4. Is there a liquidity sweep, valid engulfing, pin bar, inside bar, SMC/FVG setup, psych-level reaction, or other high-priority pair-specific confluence?
5. Decide which trade_style fits best:
   - SCALPING: M1/M5 momentum only, small target, choppy or fast session.
   - INTRADAY: M15/M30 setup aligned with H1/H4 context.
   - SWING: H4/H1 structure dominates and setup can hold longer.
6. Does the detected pattern bias support the action, or is the evidence mixed enough to HOLD?
"""
    
    if trade_memory:
        active_records = trade_memory.get_symbol_active_memory(symbol)
        if active_records:
            prompt += "\n--- TRADE MEMORY (ACTIVE POSITIONS) ---\n"
            prompt += "You currently have the following open positions on this asset:\n"
            for r in active_records:
                prompt += f"- {r['action']} opened because: '{r['reason']}'. Target TP: {r['target']:.5f}\n"
            prompt += "\nEVALUATION REQUIRED: Since you are already in a trade, evaluate if the original thesis (reason) is still valid based on the current market data. If it is still valid and momentum is strong, you may return the same ACTION to add another layer. If the thesis is invalidated, or trend reversed, consider returning HOLD to wait, or the opposite ACTION to hedge/close.\n"

    prompt += "\nReturn the JSON decision now.\n"
    return prompt


def build_risk_review_prompt(
    signal: Dict,
    indicators: Dict,
    trade_params: Dict,
    symbol: str,
) -> str:
    """Build a compact second-opinion prompt for the risk review model."""
    rr_ratio = 0.0
    sl_pips = float(trade_params.get("sl_pips", 0) or 0)
    tp_pips = float(trade_params.get("tp_pips", 0) or 0)
    if sl_pips > 0:
        rr_ratio = round(tp_pips / sl_pips, 2)

    pattern_bias = indicators.get("pattern_bias") or {}
    patterns = indicators.get("detected_patterns") or []
    pattern_lines = []
    for pattern in patterns[:8]:
        pattern_lines.append(
            "- "
            f"[{pattern.get('timeframe')}] {pattern.get('name')} "
            f"({pattern.get('direction')}, confidence {float(pattern.get('confidence', 0)):.2f}, "
            f"priority {pattern.get('priority')})"
        )

    return f"""{RISK_REVIEW_INSTRUCTION}
--- PROPOSED TRADE ---
Symbol: {symbol}
Action: {signal.get('action')}
Primary AI Confidence: {signal.get('confidence')}
Primary AI Reason: {signal.get('reason')}

--- TRADE PARAMETERS ---
Lot: {trade_params.get('lot')}
Stop Loss: {trade_params.get('sl')} ({trade_params.get('sl_pips')} pips)
Take Profit: {trade_params.get('tp')} ({trade_params.get('tp_pips')} pips)
Risk Reward Ratio: {rr_ratio}

--- MARKET CONTEXT ---
Market Regime: {indicators.get('market_regime')} (ADX: {indicators.get('adx')})
H4 Trend: {indicators.get('h4_trend')}
H1 MACD Momentum: {indicators.get('h1_macd_trend')}
M15 RSI: {indicators.get('m15_rsi')}
ATR: {indicators.get('atr')}
Pattern Bias: {pattern_bias.get('bias')} (Bullish Score: {pattern_bias.get('bullish_score')}, Bearish Score: {pattern_bias.get('bearish_score')})
High Priority Pattern Count: {pattern_bias.get('high_priority_count')}

--- DETECTED PATTERNS ---
{chr(10).join(pattern_lines) if pattern_lines else "No pattern confluence detected."}

Return the JSON risk review now.
"""


# ─────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(raw_text: str) -> Optional[Dict]:
    if not raw_text:
        return None

    try:
        return json.loads(raw_text.strip())
    except json.JSONDecodeError:
        pass

    patterns = [
        r'```json\s*(\{.*?\})\s*```',
        r'```\s*(\{.*?\})\s*```',
        r'(\{[^{}]*"action"[^{}]*\})',
        r'(\{.*?\})',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, raw_text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

    return None


def _validate_signal(data: Dict) -> Optional[Dict]:
    if not isinstance(data, dict):
        return None

    action = str(data.get("action", "")).upper().strip()
    if action not in ("BUY", "SELL", "HOLD"):
        logger.warning(f"Invalid action value: '{data.get('action')}'. Defaulting to HOLD.")
        action = "HOLD"

    try:
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    reason = str(data.get("reason", "No reason provided"))[:200]
    trade_style = str(data.get("trade_style", "INTRADAY")).upper().strip()
    if trade_style not in ("SCALPING", "INTRADAY", "SWING"):
        trade_style = "INTRADAY"

    result = {
        "action":     action,
        "confidence": round(confidence, 4),
        "trade_style": trade_style,
        "reason":     reason,
    }

    # Preserve vision AI fields if present
    if "image_bias" in data:
        result["image_bias"] = str(data["image_bias"]).lower().strip()
    if "support" in data and isinstance(data["support"], list):
        result["support"] = data["support"]
    if "resistance" in data and isinstance(data["resistance"], list):
        result["resistance"] = data["resistance"]

    return result


# ─────────────────────────────────────────────────────────────────────────────
# CLOUD AI API CALL
# ─────────────────────────────────────────────────────────────────────────────

def _build_messages(prompt: str) -> list:
    return [{"role": "user", "content": prompt}]


def query_ai_provider(
    prompt: str,
    model: str = None,
    provider: str = None,
    role: str = "main",
    timeout: int = None,
    temperature: float = None,
    max_tokens: int = None,
) -> Optional[str]:
    providers = get_provider_sequence(provider)
    selected_timeout = timeout or config.AI_TIMEOUT
    selected_temperature = config.AI_TEMPERATURE if temperature is None else temperature
    selected_max_tokens = max_tokens or config.AI_MAX_TOKENS

    if _AI_CALL_LOCK.locked():
        logger.info("AI busy. Waiting for current cloud AI call to finish...")

    with _AI_CALL_LOCK:
        for provider_name in providers:
            selected_model = model or get_model_for_role(provider_name, role)
            try:
                client = get_client(provider_name)
            except Exception as e:
                logger.error(f"AI provider setup failed for {provider_name}: {e}")
                continue

            logger.info(
                f"AI locked for provider={provider_name}, model={selected_model}. "
                "Waiting for full response..."
            )

            for attempt in range(1, config.AI_RETRIES + 1):
                try:
                    logger.debug(
                        f"Querying {provider_name} model={selected_model} "
                        f"(attempt {attempt}/{config.AI_RETRIES})..."
                    )
                    raw_text = client.chat_completion(
                        model=selected_model,
                        messages=_build_messages(prompt),
                        temperature=selected_temperature,
                        max_tokens=selected_max_tokens,
                        timeout=selected_timeout,
                    )

                    if raw_text:
                        logger.info(
                            f"AI response completed for provider={provider_name}, "
                            f"model={selected_model}"
                        )
                        return raw_text

                    logger.warning(
                        f"{provider_name} returned empty response "
                        f"(attempt {attempt}/{config.AI_RETRIES})"
                    )

                except AIProviderError as e:
                    level = logger.warning if e.retryable else logger.error
                    level(
                        f"{provider_name} model={selected_model} failed "
                        f"(attempt {attempt}/{config.AI_RETRIES}): {e}"
                    )
                    if not e.retryable:
                        break
                except Exception as e:
                    logger.error(f"{provider_name} unexpected error: {e}")

                if attempt < config.AI_RETRIES:
                    wait = 2 ** attempt
                    logger.info(
                        f"Waiting {wait}s before retrying provider={provider_name}, "
                        f"model={selected_model}..."
                    )
                    time.sleep(wait)

            logger.warning(f"AI provider {provider_name} failed. Trying fallback if available...")

    return None


def _provider_has_credentials(provider: str) -> bool:
    provider = str(provider or "").strip().lower()
    if provider == "openrouter":
        return bool(config.OPENROUTER_API_KEY and config.OPENROUTER_API_KEY != "CHANGE_ME")
    if provider in ("huggingface", "hf"):
        return bool(config.HF_TOKEN and config.HF_TOKEN != "CHANGE_ME")
    return False


def check_ai_health(provider: str = None, role: str = "main") -> bool:
    provider_name = provider or config.AI_PROVIDER
    model = get_model_for_role(provider_name, role)

    if not _provider_has_credentials(provider_name):
        logger.warning(f"Missing API key for AI provider={provider_name}")
        return False

    if not config.AI_STARTUP_HEALTHCHECK:
        logger.info(
            f"AI config ready for provider={provider_name}, model={model}. "
            "Live startup request skipped to save free quota."
        )
        return True

    raw_text = query_ai_provider(
        "Reply with OK only.",
        provider=provider_name,
        role=role,
        timeout=min(config.AI_TIMEOUT, 45),
        temperature=0.0,
        max_tokens=8,
    )
    return bool(raw_text)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_signal(indicators: Dict, bid: float, ask: float, trade_memory=None, symbol: str = "UNKNOWN") -> Dict:
    default_response = {
        "action":       "HOLD",
        "confidence":   0.0,
        "reason":       "AI decision unavailable",
        "raw_response": None,
    }

    try:
        prompt = build_prompt(indicators, bid, ask, trade_memory, symbol)
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return default_response

    raw_text = query_ai_provider(
        prompt,
        role="main",
        temperature=config.AI_TEMPERATURE,
        max_tokens=config.AI_MAX_TOKENS,
    )
    if not raw_text:
        return {**default_response, "reason": "Cloud AI provider unreachable or timed out"}

    parsed = _extract_json(raw_text)
    if not parsed:
        return {**default_response, "reason": "Invalid JSON response", "raw_response": raw_text}

    signal = _validate_signal(parsed)
    if not signal:
        return {**default_response, "reason": "Signal validation failed", "raw_response": raw_text}

    result = {**signal, "raw_response": raw_text}

    logger.info(
        f"AI Signal → {result['action']} | "
        f"Confidence: {result['confidence']:.2f} | "
        f"Reason: {result['reason']}"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MERGE DECISIONS — TEXT AI + VISION AI + PATTERN ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def merge_decisions(
    text_signal: Dict,
    vision_signal: Dict,
    pattern_bias: Dict,
) -> Dict:
    """
    Merge text AI signal, vision AI signal, and pattern engine bias
    into a single final trading decision.

    Conflict resolution:
    1. All three agree → use action, average confidence
    2. Text + patterns agree, vision disagrees → text action, reduce confidence
    3. Vision + patterns agree, text disagrees → HOLD (text is primary)
    4. Text + vision agree, patterns disagree → text action, reduce confidence
    5. All three conflict → HOLD
    6. If any is HOLD, need 2/3 agreement from non-HOLD sources to proceed

    Vision AI fields (image_bias, support, resistance) are always preserved.
    """
    text_action = str(text_signal.get("action", "HOLD")).upper()
    text_conf = float(text_signal.get("confidence", 0.0))
    text_style = text_signal.get("trade_style", "INTRADAY")

    vision_action = str(vision_signal.get("action", "HOLD")).upper()
    vision_conf = float(vision_signal.get("confidence", 0.0))
    vision_bias = str(vision_signal.get("image_bias", "sideways")).lower()

    # Derive pattern action from bias
    bias_str = str(pattern_bias.get("bias", "none")).lower()
    pattern_action = "HOLD"
    if bias_str == "bullish":
        pattern_action = "BUY"
    elif bias_str == "bearish":
        pattern_action = "SELL"

    actions = [text_action, vision_action, pattern_action]
    logger.info(
        f"Merging decisions: text={text_action}({text_conf:.2f}), "
        f"vision={vision_action}({vision_conf:.2f}), "
        f"pattern={pattern_action}({bias_str})"
    )

    # Count non-HOLD votes
    non_hold = [a for a in actions if a != "HOLD"]
    unique_non_hold = set(non_hold)

    final_action = "HOLD"
    final_confidence = 0.0
    merge_reason_parts = []

    if len(unique_non_hold) == 1 and len(non_hold) >= 2:
        # 2 or 3 sources agree on same action
        final_action = non_hold[0]
        final_confidence = (text_conf + vision_conf) / 2

        if len(non_hold) == 3:
            merge_reason_parts.append("all sources agree")
        elif text_action == final_action and pattern_action == final_action:
            merge_reason_parts.append("text+pattern agree, vision neutral/different")
            final_confidence *= 0.85  # slight penalty
        elif text_action == final_action and vision_action == final_action:
            merge_reason_parts.append("text+vision agree, pattern neutral/different")
            final_confidence *= 0.90
        elif vision_action == final_action and pattern_action == final_action:
            # Vision + pattern agree but text disagrees → HOLD (text is primary)
            final_action = "HOLD"
            final_confidence = 0.0
            merge_reason_parts.append("vision+pattern agree but text disagrees, defaulting HOLD")

    elif len(unique_non_hold) > 1:
        # Direct conflict between non-HOLD sources
        final_action = "HOLD"
        final_confidence = 0.0
        merge_reason_parts.append(f"conflict: {', '.join(non_hold)}")

    else:
        # All HOLD or only 1 non-HOLD source
        if text_action != "HOLD" and vision_action == "HOLD" and pattern_action == "HOLD":
            # Only text wants to trade, vision and pattern neutral
            final_action = text_action
            final_confidence = text_conf * 0.75  # reduce confidence without vision/pattern support
            merge_reason_parts.append("text only, vision+pattern neutral")
        else:
            final_action = "HOLD"
            final_confidence = 0.0
            merge_reason_parts.append("insufficient agreement")

    # Build merged result
    merge_reason = "; ".join(merge_reason_parts)
    text_reason = text_signal.get("reason", "")
    vision_reason = vision_signal.get("reason", "")
    combined_reason = f"[Merged: {merge_reason}] Text: {text_reason}"
    if vision_reason and vision_reason != "Vision AI disabled":
        combined_reason += f" | Vision: {vision_reason}"

    result = {
        "action": final_action,
        "confidence": round(max(0.0, min(1.0, final_confidence)), 4),
        "trade_style": text_style,  # text AI determines trade style
        "reason": combined_reason[:400],
        "image_bias": vision_bias,
        "support": vision_signal.get("support", []),
        "resistance": vision_signal.get("resistance", []),
        "raw_response": text_signal.get("raw_response"),
        "vision_raw_response": vision_signal.get("raw_response"),
        "merge_method": merge_reason,
    }

    logger.info(
        f"Merged → {result['action']} | "
        f"Confidence: {result['confidence']:.2f} | "
        f"Method: {merge_reason}"
    )
    return result


def _validate_risk_review(data: Dict) -> Optional[Dict]:
    if not isinstance(data, dict):
        return None

    approved = data.get("approved", False)
    if isinstance(approved, str):
        approved = approved.strip().lower() in ("true", "yes", "approve", "approved")
    else:
        approved = bool(approved)

    try:
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    reason = str(data.get("reason", "No risk review reason provided"))[:220]
    return {
        "approved": approved,
        "confidence": round(confidence, 4),
        "reason": reason,
    }


def review_trade_risk(signal: Dict, indicators: Dict, trade_params: Dict, symbol: str) -> Dict:
    """Ask the optional risk model to approve/reject a proposed trade."""
    default_response = {
        "approved": True,
        "confidence": 0.0,
        "reason": "Risk review disabled",
        "raw_response": None,
    }

    if not config.ENABLE_RISK_REVIEW:
        return default_response

    try:
        prompt = build_risk_review_prompt(signal, indicators, trade_params, symbol)
    except Exception as e:
        logger.error(f"Failed to build risk review prompt: {e}")
        return {
            "approved": False,
            "confidence": 0.0,
            "reason": "Risk review prompt build failed",
            "raw_response": None,
        }

    raw_text = query_ai_provider(
        prompt,
        role="risk",
        timeout=config.AI_TIMEOUT,
        temperature=0.0,
        max_tokens=min(config.AI_MAX_TOKENS, 192),
    )
    if not raw_text:
        return {
            "approved": False,
            "confidence": 0.0,
            "reason": "Risk review provider unreachable or timed out",
            "raw_response": None,
        }

    parsed = _extract_json(raw_text)
    if not parsed:
        return {
            "approved": False,
            "confidence": 0.0,
            "reason": "Invalid JSON from risk review model",
            "raw_response": raw_text,
        }

    review = _validate_risk_review(parsed)
    if not review:
        return {
            "approved": False,
            "confidence": 0.0,
            "reason": "Risk review validation failed",
            "raw_response": raw_text,
        }

    result = {**review, "raw_response": raw_text}
    logger.info(
        f"Risk Review → {'APPROVED' if result['approved'] else 'REJECTED'} | "
        f"Confidence: {result['confidence']:.2f} | "
        f"Reason: {result['reason']}"
    )
    return result
