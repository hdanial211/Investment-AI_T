"""
ai_engine.py - Ollama AI Decision Engine

Responsibilities:
- Build structured prompts with market data
- Call Ollama REST API (qwen2.5-coder:14b)
- Parse and validate JSON response
- Return BUY / SELL / HOLD signal with confidence
- Handle timeouts, retries, and malformed responses
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

SYSTEM_INSTRUCTION = """You are an expert algorithmic trading assistant.
Analyze the provided market data and technical indicators, then return a trading decision.

CRITICAL RULES:
1. Respond ONLY with a valid JSON object — no markdown, no explanation, no extra text.
2. The JSON must have exactly these fields:
   - "action": one of "BUY", "SELL", or "HOLD"
   - "confidence": float between 0.0 and 1.0
   - "reason": brief explanation string (max 100 chars)
3. Do NOT include code blocks, backticks, or any text outside the JSON.

Example valid response:
{"action": "BUY", "confidence": 0.82, "reason": "Bullish EMA cross with RSI recovery from oversold"}
"""


def build_prompt(indicators: Dict, bid: float, ask: float) -> str:
    """
    Construct the full prompt sent to Ollama.
    Includes system instruction + market data formatted clearly.
    """
    market_section = format_for_prompt(indicators)
    spread = round(ask - bid, 5)

    prompt = f"""{SYSTEM_INSTRUCTION}

--- MARKET DATA ---
{market_section}
Bid: {bid}
Ask: {ask}
Spread: {spread}

--- TASK ---
Based on the above market data and indicators, provide your trading decision as a single JSON object.
"""
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# JSON EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(raw_text: str) -> Optional[Dict]:
    """
    Robustly extract JSON from AI response.
    Handles cases where the model adds extra text around the JSON.
    """
    if not raw_text:
        return None

    # 1. Try direct parse first (ideal case)
    try:
        return json.loads(raw_text.strip())
    except json.JSONDecodeError:
        pass

    # 2. Extract JSON object using regex (handles markdown code blocks, extra text)
    patterns = [
        r'```json\s*(\{.*?\})\s*```',   # ```json { } ```
        r'```\s*(\{.*?\})\s*```',        # ``` { } ```
        r'(\{[^{}]*"action"[^{}]*\})',   # Any object with "action" field
        r'(\{.*?\})',                    # Any JSON object (last resort)
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
    """
    Validate and normalize the parsed signal from AI.
    Returns cleaned dict or None if invalid.
    """
    if not isinstance(data, dict):
        return None

    # Validate action field
    action = str(data.get("action", "")).upper().strip()
    if action not in ("BUY", "SELL", "HOLD"):
        logger.warning(f"Invalid action value: '{data.get('action')}'. Defaulting to HOLD.")
        action = "HOLD"

    # Validate confidence
    try:
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
    except (TypeError, ValueError):
        logger.warning("Invalid confidence value. Defaulting to 0.0")
        confidence = 0.0

    # Get reason
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
    """
    Send a prompt to Ollama and return the raw text response.
    Implements retry logic for transient failures.
    """
    payload = {
        "model":  config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature":  0.1,   # Low temperature for consistent trading decisions
            "top_p":        0.9,
            "num_predict":  256,   # Max tokens for response (JSON is short)
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
                logger.debug(f"Ollama raw response: {raw_text[:300]}")
                return raw_text

            logger.warning(f"Ollama returned empty response (attempt {attempt})")

        except requests.exceptions.ConnectionError:
            logger.error(
                f"Cannot connect to Ollama at {config.OLLAMA_URL}. "
                "Is Ollama running? (ollama serve)"
            )
        except requests.exceptions.Timeout:
            logger.warning(f"Ollama request timed out (attempt {attempt})")
        except requests.exceptions.HTTPError as e:
            logger.error(f"Ollama HTTP error: {e}")
        except Exception as e:
            logger.error(f"Ollama unexpected error: {e}")

        if attempt < config.OLLAMA_RETRIES:
            wait = 2 ** attempt  # Exponential backoff: 2s, 4s, 8s
            logger.info(f"Retrying in {wait}s...")
            time.sleep(wait)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PUBLIC INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def get_ai_signal(indicators: Dict, bid: float, ask: float) -> Dict:
    """
    Main entry point for AI signal generation.

    Args:
        indicators: Dict from strategy.calculate_indicators()
        bid:        Current bid price
        ask:        Current ask price

    Returns:
        Dict with keys: action, confidence, reason, raw_response
        Falls back to HOLD on any failure.
    """
    default_response = {
        "action":       "HOLD",
        "confidence":   0.0,
        "reason":       "AI decision unavailable",
        "raw_response": None,
    }

    # Build prompt
    try:
        prompt = build_prompt(indicators, bid, ask)
    except Exception as e:
        logger.error(f"Failed to build prompt: {e}")
        return default_response

    # Call Ollama
    raw_text = query_ollama(prompt)
    if not raw_text:
        logger.warning("No response from Ollama. Returning HOLD.")
        return {**default_response, "reason": "Ollama unreachable or timed out"}

    # Extract JSON
    parsed = _extract_json(raw_text)
    if not parsed:
        logger.warning(f"Could not extract JSON from response: {raw_text[:200]}")
        return {**default_response, "reason": "Invalid JSON response from AI", "raw_response": raw_text}

    # Validate signal
    signal = _validate_signal(parsed)
    if not signal:
        logger.warning("Signal validation failed.")
        return {**default_response, "reason": "Signal validation failed", "raw_response": raw_text}

    result = {**signal, "raw_response": raw_text}

    logger.info(
        f"AI Signal → {result['action']} | "
        f"Confidence: {result['confidence']:.2f} | "
        f"Reason: {result['reason']}"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────────────

def check_ollama_health() -> bool:
    """Verify Ollama is running and the model is available."""
    try:
        resp = requests.get(
            "http://localhost:11434/api/tags",
            timeout=5,
        )
        if resp.status_code != 200:
            return False

        models = resp.json().get("models", [])
        model_names = [m.get("name", "") for m in models]
        available = any(config.OLLAMA_MODEL in name for name in model_names)

        if not available:
            logger.warning(
                f"Model '{config.OLLAMA_MODEL}' not found in Ollama. "
                f"Available: {model_names}. "
                f"Run: ollama pull {config.OLLAMA_MODEL}"
            )
        return available

    except requests.exceptions.ConnectionError:
        logger.error("Ollama is not running. Start with: ollama serve")
        return False
    except Exception as e:
        logger.error(f"Ollama health check error: {e}")
        return False
