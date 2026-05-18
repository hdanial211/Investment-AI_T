"""
ai_engine.py - Ollama AI Decision Engine

Responsibilities:
- Build structured prompts with multi-timeframe market data
- Enforce symbol-specific rules (EURUSD vs XAUUSD)
- Call Ollama REST API (qwen2.5-coder:14b)
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

SYMBOL_RULES = {
    "EURUSD": """
--- ASSET BEHAVIOR: EURUSD ---
EURUSD is a technical, orderly forex major.
- H4 Trend is KING. Do not trade against the H4 Major Trend.
- Respect H1 Support/Resistance zones.
- Engulfing patterns at S/R zones are highly reliable.
- Look for orderly break & retest.
- If H4 is sideways or unclear, return HOLD.
""",
    "XAUUSD": """
--- ASSET BEHAVIOR: XAUUSD (GOLD) ---
XAUUSD is highly volatile and prone to institutional manipulation (stop hunts).
- Do not blindly trade breakouts. Expect fakeouts.
- The BEST entries occur after a 'Liquidity Sweep' (price spikes past S/R and reverses rapidly).
- If M15 or M5 shows a liquidity sweep that aligns with the H4 Trend, aggressively enter.
- Do NOT trade engulfing patterns in the middle of a range.
- If no sweep is detected and price is near S/R, prefer HOLD until manipulation occurs.
"""
}


def build_prompt(indicators: Dict, bid: float, ask: float) -> str:
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
3. What is the M15/M5 pattern telling you? Is there a liquidity sweep or valid engulfing?

Return the JSON decision now.
"""
    return prompt


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

def query_ollama(prompt: str) -> Optional[str]:
    payload = {
        "model":  config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature":  0.1,
            "top_p":        0.9,
            "num_predict":  256,
        },
    }

    for attempt in range(1, config.OLLAMA_RETRIES + 1):
        try:
            logger.debug(f"Querying Ollama (attempt {attempt}/{config.OLLAMA_RETRIES})...")
            response = requests.post(
                config.OLLAMA_URL,
                json    = payload,
                timeout = config.OLLAMA_TIMEOUT,
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

def get_ai_signal(indicators: Dict, bid: float, ask: float) -> Dict:
    default_response = {
        "action":       "HOLD",
        "confidence":   0.0,
        "reason":       "AI decision unavailable",
        "raw_response": None,
    }

    try:
        prompt = build_prompt(indicators, bid, ask)
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return default_response

    raw_text = query_ollama(prompt)
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

def check_ollama_health() -> bool:
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            return False

        models = resp.json().get("models", [])
        return any(config.OLLAMA_MODEL in m.get("name", "") for m in models)
    except:
        return False
