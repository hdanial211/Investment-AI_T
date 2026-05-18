"""
ai_engine.py - Ollama AI Decision Engine

Responsibilities:
- Build structured prompts with multi-timeframe market data
- Enforce symbol-specific rules (EURUSD vs XAUUSD)
- Call Ollama REST API (default: qwen2.5:7b)
- Optionally use a second model (default: deepseek-r1:8b) for risk review
- Return BUY / SELL / HOLD signal
"""

import json
import logging
import re
import time
from typing import Dict, Optional

import requests

import config
from strategy import format_for_prompt

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

BASE_INSTRUCTION = """You are an elite institutional algorithmic trading AI.
Your objective is to analyze multi-timeframe (MTF) market data and provide a highly accurate trading decision.

CRITICAL JSON OUTPUT RULES:
1. Respond ONLY with a valid JSON object.
2. Format: {"action": "BUY"|"SELL"|"HOLD", "confidence": 0.0-1.0, "reason": "brief explanation"}
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
3. What is the M15/M5 pattern telling you? Is there a liquidity sweep, valid engulfing, pin bar, inside bar, SMC/FVG setup, psych-level reaction, or other high-priority pair-specific confluence?
4. Does the detected pattern bias support the action, or is the evidence mixed enough to HOLD?
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

    return {
        "action":     action,
        "confidence": round(confidence, 4),
        "reason":     reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA API CALL
# ─────────────────────────────────────────────────────────────────────────────

def _ollama_options(
    temperature: float = None,
    num_predict: int = None,
) -> Dict:
    options = {
        "temperature": config.OLLAMA_TEMPERATURE if temperature is None else temperature,
        "top_p":       config.OLLAMA_TOP_P,
        "num_ctx":     config.OLLAMA_NUM_CTX,
        "num_predict": config.OLLAMA_NUM_PREDICT if num_predict is None else num_predict,
    }

    if config.OLLAMA_NUM_GPU >= 0:
        options["num_gpu"] = config.OLLAMA_NUM_GPU

    return options


def query_ollama(
    prompt: str,
    model: str = None,
    timeout: int = None,
    temperature: float = None,
    num_predict: int = None,
) -> Optional[str]:
    selected_model = model or config.OLLAMA_MODEL
    payload = {
        "model":      selected_model,
        "prompt":     prompt,
        "stream":     False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": _ollama_options(
            temperature=temperature,
            num_predict=num_predict,
        ),
    }

    for attempt in range(1, config.OLLAMA_RETRIES + 1):
        try:
            logger.debug(
                f"Querying Ollama model={selected_model} "
                f"(attempt {attempt}/{config.OLLAMA_RETRIES})..."
            )
            response = requests.post(
                config.OLLAMA_URL,
                json    = payload,
                timeout = timeout or config.OLLAMA_TIMEOUT,
                headers = {"Content-Type": "application/json"},
            )
            response.raise_for_status()

            data = response.json()
            raw_text = data.get("response", "").strip()

            if raw_text:
                return raw_text

            logger.warning(f"Ollama returned empty response (attempt {attempt})")

        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama. Is it running?")
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama request timed out (attempt {attempt})")
        except Exception as e:
            logger.error(f"Ollama unexpected error: {e}")

        if attempt < config.OLLAMA_RETRIES:
            wait = 2 ** attempt
            time.sleep(wait)

    return None


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

    raw_text = query_ollama(
        prompt,
        model=config.OLLAMA_MODEL,
        temperature=config.OLLAMA_TEMPERATURE,
        num_predict=config.OLLAMA_NUM_PREDICT,
    )
    if not raw_text:
        return {**default_response, "reason": "Ollama unreachable or timed out"}

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

    raw_text = query_ollama(
        prompt,
        model=config.OLLAMA_RISK_MODEL,
        timeout=config.OLLAMA_TIMEOUT,
        temperature=0.0,
        num_predict=192,
    )
    if not raw_text:
        return {
            "approved": False,
            "confidence": 0.0,
            "reason": "Risk review model unreachable or timed out",
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


def check_ollama_health(model: str = None) -> bool:
    selected_model = model or config.OLLAMA_MODEL
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return False

        models = resp.json().get("models", [])
        return any(selected_model in m.get("name", "") for m in models)
    except:
        return False
