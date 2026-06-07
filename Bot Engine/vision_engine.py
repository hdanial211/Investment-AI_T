"""
vision_engine.py - Vision AI Pipeline

Sends chart screenshots + structured market data to a vision-capable AI model.
Returns strict JSON with action, confidence, trade_style, image_bias,
support/resistance levels, and reason.

Safety:
- Any failure (timeout, bad JSON, missing image, stale screenshot) → HOLD.
- Vision AI cannot override max risk, cooling-off, max trades, or virtual exit safety.
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional

import config
from chart_capture import encode_image_base64, validate_screenshot

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# VISION PROMPT
# ─────────────────────────────────────────────────────────────────────────────

VISION_INSTRUCTION = """You are an elite institutional chart analysis AI.
Analyze the attached chart screenshot(s) along with the structured market data provided.

YOUR TASK:
1. Read the candlestick chart visually. Identify trend direction, key patterns, S/R zones, and momentum.
2. Cross-reference what you see with the text market data provided.
3. Provide a trading decision.

CRITICAL JSON OUTPUT RULES:
1. Respond ONLY with a valid JSON object.
2. Format:
{
  "action": "BUY"|"SELL"|"HOLD",
  "confidence": 0.0-1.0,
  "trade_style": "SCALPING"|"INTRADAY"|"SWING",
  "image_bias": "bullish"|"bearish"|"sideways",
  "support": [list of visible support levels as floats],
  "resistance": [list of visible resistance levels as floats],
  "reason": "brief explanation of what you see in the chart"
}
3. No markdown blocks, no extra text, no preamble.
4. If the chart is unclear, wrong symbol, or you cannot determine direction, return HOLD.
"""

SYMBOL_VISION_RULES = {
    "EURUSD": """
--- ASSET: EURUSD ---
EURUSD is a technical forex major. Look for:
- Clean trend structure with orderly S/R zones.
- EMA crossovers aligned with price action.
- Engulfing / pin bars at key levels.
- If H4 trend is sideways from the chart, return HOLD.
""",
    "XAUUSD": """
--- ASSET: XAUUSD (GOLD) ---
Gold is volatile and prone to stop hunts. Look for:
- Liquidity sweeps (wick spikes beyond S/R that reverse).
- FVG (fair value gaps) as continuation zones.
- Psychological levels ($50/$100 rounds).
- In Asia session: expect manipulation before real move.
- Pin bars need 3:1 wick-to-body and key-level context.
""",
}


# ─────────────────────────────────────────────────────────────────────────────
# VISION SIGNAL FUNCTION
# ─────────────────────────────────────────────────────────────────────────────

def get_vision_signal(
    symbol: str,
    current_price: float,
    indicators: Dict,
    chart_paths: Dict[str, str],
    trade_memory=None,
) -> Dict:
    """
    Send chart screenshot(s) + market context to vision AI.

    Args:
        symbol: Trading symbol (e.g. "XAUUSD")
        current_price: Current bid/ask midpoint
        indicators: Output from calculate_multi_indicators()
        chart_paths: {timeframe: filepath} from chart_capture
        trade_memory: Optional trade memory for context

    Returns:
        Dict with action, confidence, trade_style, image_bias,
        support, resistance, reason.
        Any failure → HOLD with confidence 0.0
    """
    default_response = {
        "action": "HOLD",
        "confidence": 0.0,
        "trade_style": "INTRADAY",
        "image_bias": "sideways",
        "support": [],
        "resistance": [],
        "reason": "Vision AI unavailable",
        "raw_response": None,
    }

    if not config.VISION_AI_ENABLED:
        return {**default_response, "reason": "Vision AI disabled"}

    if not chart_paths:
        return {**default_response, "reason": "No chart screenshots available"}

    # ── Select key timeframes to send (limit API cost) ───────────────────────
    # Priority: H4 > H1 > M15 > M30 > M5 > M1
    priority_order = ["H4", "H1", "M15", "M30", "M5", "M1"]
    selected_paths = {}
    for tf in priority_order:
        if tf in chart_paths:
            path = chart_paths[tf]
            if validate_screenshot(path, symbol):
                selected_paths[tf] = path
            if len(selected_paths) >= 3:  # Max 3 images per call
                break

    if not selected_paths:
        return {**default_response, "reason": "No valid screenshots after validation"}

    # ── Build multimodal message ─────────────────────────────────────────────
    try:
        messages = _build_vision_messages(
            symbol, current_price, indicators, selected_paths, trade_memory,
        )
    except Exception as e:
        logger.error(f"Failed to build vision messages: {e}")
        return {**default_response, "reason": f"Vision prompt build failed: {e}"}

    # ── Call vision AI ───────────────────────────────────────────────────────
    raw_text = _call_vision_ai(messages)
    if not raw_text:
        return {**default_response, "reason": "Vision AI provider unreachable or timed out"}

    # ── Parse and validate response ──────────────────────────────────────────
    parsed = _extract_vision_json(raw_text)
    if not parsed:
        return {
            **default_response,
            "reason": "Invalid JSON from vision AI",
            "raw_response": raw_text,
        }

    validated = _validate_vision_signal(parsed)
    if not validated:
        return {
            **default_response,
            "reason": "Vision signal validation failed",
            "raw_response": raw_text,
        }

    result = {**validated, "raw_response": raw_text}
    logger.info(
        f"Vision AI → {result['action']} | "
        f"Confidence: {result['confidence']:.2f} | "
        f"Image bias: {result['image_bias']} | "
        f"Reason: {result['reason']}"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MESSAGE BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_vision_messages(
    symbol: str,
    current_price: float,
    indicators: Dict,
    chart_paths: Dict[str, str],
    trade_memory=None,
) -> List[Dict]:
    """Build multimodal messages with text + image content blocks."""

    # Get symbol-specific rules
    specific_rules = ""
    for k, v in SYMBOL_VISION_RULES.items():
        if k in symbol.upper():
            specific_rules = v
            break

    # Build text context
    pattern_bias = indicators.get("pattern_bias") or {}
    detected = indicators.get("detected_patterns") or []
    pattern_summary = ""
    if detected:
        top_patterns = detected[:5]
        lines = []
        for p in top_patterns:
            lines.append(
                f"- [{p.get('timeframe')}] {p.get('name')} "
                f"({p.get('direction')}, conf {float(p.get('confidence', 0)):.2f})"
            )
        pattern_summary = "\n".join(lines)
    else:
        pattern_summary = "No pattern confluence detected."

    text_context = f"""{VISION_INSTRUCTION}
{specific_rules}
--- MARKET DATA ---
Symbol: {symbol}
Current Price: {current_price}
H4 Trend: {indicators.get('h4_trend', 'unknown')}
H1 Resistance: {indicators.get('h1_resistance', 'N/A')}
H1 Support: {indicators.get('h1_support', 'N/A')}
H1 MACD Momentum: {indicators.get('h1_macd_trend', 'unknown')}
M15 RSI: {indicators.get('m15_rsi', 'N/A')}
Market Regime: {indicators.get('market_regime', 'unknown')} (ADX: {indicators.get('adx', 'N/A')})
ATR: {indicators.get('atr', 'N/A')}
Pattern Bias: {pattern_bias.get('bias', 'none')} (Bullish: {pattern_bias.get('bullish_score', 0)}, Bearish: {pattern_bias.get('bearish_score', 0)})

--- DETECTED PATTERNS ---
{pattern_summary}

--- CHART SCREENSHOTS ---
The following chart timeframes are attached as images: {', '.join(chart_paths.keys())}

Analyze the chart visually and return the JSON decision now.
"""

    # Build content blocks: text first, then images
    content_blocks = [{"type": "text", "text": text_context}]

    for tf, filepath in chart_paths.items():
        b64_data = encode_image_base64(filepath)
        if b64_data:
            content_blocks.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64_data}",
                },
            })
            logger.debug(f"Attached {tf} chart image ({len(b64_data)} bytes)")

    return [{"role": "user", "content": content_blocks}]


# ─────────────────────────────────────────────────────────────────────────────
# VISION AI CALL
# ─────────────────────────────────────────────────────────────────────────────

def _call_vision_ai(messages: List[Dict]) -> Optional[str]:
    """Call vision-capable AI using the dedicated VISION_PROVIDER_CONFIG."""
    try:
        from ai_clients import get_client, AIProviderError
    except ImportError as e:
        logger.error(f"Cannot import AI clients: {e}")
        return None

    # ── Resolve vision provider config (role-based or fallback) ──────────
    vision_cfg = config.VISION_PROVIDER_CONFIG
    if vision_cfg and vision_cfg.get("api_key"):
        provider_config = {
            "provider": vision_cfg.get("provider", "openrouter"),
            "api_key": vision_cfg["api_key"],
        }
        model = vision_cfg.get("model") or config.VISION_AI_MODEL
    else:
        # Fallback: use MAIN_PROVIDER_CONFIG or legacy AI_PROVIDER
        main_cfg = config.MAIN_PROVIDER_CONFIG
        if main_cfg and main_cfg.get("api_key"):
            provider_config = {
                "provider": main_cfg.get("provider", "openrouter"),
                "api_key": main_cfg["api_key"],
            }
        else:
            provider_name = config.AI_PROVIDER
            provider_config = {"provider": provider_name}
            if provider_name == "openrouter":
                provider_config["api_key"] = config.OPENROUTER_API_KEY
            elif provider_name in ("huggingface", "hf"):
                provider_config["api_key"] = config.HF_TOKEN
        model = config.VISION_AI_MODEL

    timeout = getattr(config, "VISION_AI_TIMEOUT", 60)
    max_tokens = getattr(config, "VISION_AI_MAX_TOKENS", 512)

    try:
        client = get_client(provider_config)
    except Exception as e:
        logger.error(f"Vision AI provider setup failed: {e}")
        return None

    logger.info(
        f"Querying vision AI: provider={provider_config.get('provider')}, model={model}"
    )

    for attempt in range(1, config.AI_RETRIES + 1):
        try:
            raw_text = client.chat_completion(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            if raw_text:
                logger.info(f"Vision AI response received (attempt {attempt})")
                return raw_text

            logger.warning(
                f"Vision AI empty response (attempt {attempt}/{config.AI_RETRIES})"
            )

        except AIProviderError as e:
            logger.warning(
                f"Vision AI error (attempt {attempt}/{config.AI_RETRIES}): {e}"
            )
            if not e.retryable:
                break
        except Exception as e:
            logger.error(f"Vision AI unexpected error: {e}")

        if attempt < config.AI_RETRIES:
            wait = 2 ** attempt
            logger.debug(f"Waiting {wait}s before retrying vision AI...")
            time.sleep(wait)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION & VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_vision_json(raw_text: str) -> Optional[Dict]:
    """Extract JSON from vision AI response text."""
    if not raw_text:
        return None

    # Try direct parse
    try:
        return json.loads(raw_text.strip())
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown blocks or embedded JSON
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


def _validate_vision_signal(data: Dict) -> Optional[Dict]:
    """Validate and normalize vision AI signal."""
    if not isinstance(data, dict):
        return None

    # Action
    action = str(data.get("action", "")).upper().strip()
    if action not in ("BUY", "SELL", "HOLD"):
        logger.warning(f"Vision AI invalid action: '{data.get('action')}'. Defaulting to HOLD.")
        action = "HOLD"

    # Confidence
    try:
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    # Trade style
    trade_style = str(data.get("trade_style", "INTRADAY")).upper().strip()
    if trade_style not in ("SCALPING", "INTRADAY", "SWING"):
        trade_style = "INTRADAY"

    # Image bias
    image_bias = str(data.get("image_bias", "sideways")).lower().strip()
    if image_bias not in ("bullish", "bearish", "sideways"):
        image_bias = "sideways"

    # Support/Resistance levels
    support = _parse_levels(data.get("support"))
    resistance = _parse_levels(data.get("resistance"))

    # Reason
    reason = str(data.get("reason", "No vision reason provided"))[:300]

    return {
        "action": action,
        "confidence": round(confidence, 4),
        "trade_style": trade_style,
        "image_bias": image_bias,
        "support": support,
        "resistance": resistance,
        "reason": reason,
    }


def _parse_levels(raw) -> List[float]:
    """Parse support/resistance level list from AI output."""
    if not raw:
        return []
    if not isinstance(raw, (list, tuple)):
        return []

    levels = []
    for item in raw[:10]:  # Max 10 levels
        try:
            val = float(item)
            if val > 0:
                levels.append(round(val, 5))
        except (TypeError, ValueError):
            continue

    return sorted(levels)
