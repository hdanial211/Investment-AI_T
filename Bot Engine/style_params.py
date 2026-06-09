"""
style_params.py — Per-style, per-symbol trading parameters.

This module is the single source of truth for all style-dependent trading
parameters.  Every other module (risk_manager, ai_engine, virtual_exit_engine,
main) imports from here instead of hard-coding multipliers.

Parameters are derived from two independent strategy research sources covering
XAUUSD across Scalping / Intraday / Swing styles.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# MASTER PARAMETER TABLE
# ─────────────────────────────────────────────────────────────────────────────

STYLE_PARAMS: Dict[str, Dict[str, dict]] = {
    # ──────────────── SCALPING ────────────────
    "SCALPING": {
        "XAUUSD": {
            "min_sl_pips": 20,          # SL minimum 20 pips ($2.00)
            "max_sl_pips": 40,          # SL maximum 40 pips ($4.00)
            "min_tp_pips": 30,          # TP minimum 30 pips ($3.00)
            "max_tp_pips": 60,          # TP maximum 60 pips ($6.00)
            "min_rr": 1.0,              # R:R minimum 1:1
            "risk_percent": 0.5,        # 0.5% risiko per trade
            "be_trigger_pips": 15,
            "be_offset_pips": 2,
            "trail_start_pips": 20,
            "trail_dist_pips": 10,
            "min_atr_pips": 30,         # Jangan scalp jika ATR(M5) < 30
            "allowed_sessions": ["London", "London/NY overlap", "NY"],
            "blocked_sessions": ["Asia", "Off-hours"],
        },
    },

    # ──────────────── INTRADAY ────────────────
    "INTRADAY": {
        "XAUUSD": {
            "min_sl_pips": 50,          # SL minimum 50 pips ($5.00)
            "max_sl_pips": 100,         # SL maximum 100 pips ($10.00)
            "min_tp_pips": 100,         # TP minimum 100 pips ($10.00)
            "max_tp_pips": 200,         # TP maximum 200 pips ($20.00)
            "min_rr": 1.5,
            "risk_percent": 1.5,
            "be_trigger_pips": 40,
            "be_offset_pips": 5,
            "trail_start_pips": 60,
            "trail_dist_pips": 30,
            "min_atr_pips": None,       # No ATR minimum for intraday
            "allowed_sessions": ["London", "London/NY overlap", "NY"],
            "blocked_sessions": ["Asia"],
        },
    },

    # ──────────────── SWING ────────────────
    "SWING": {
        "XAUUSD": {
            "min_sl_pips": 120,         # SL minimum 120 pips ($12.00)
            "max_sl_pips": 250,         # SL maximum 250 pips ($25.00)
            "min_tp_pips": 300,         # TP minimum 300 pips ($30.00)
            "max_tp_pips": 600,         # TP maximum 600 pips ($60.00)
            "min_rr": 2.0,
            "risk_percent": 1.0,
            "be_trigger_pips": 100,
            "be_offset_pips": 10,
            "trail_start_pips": 150,
            "trail_dist_pips": 50,
            "min_atr_pips": None,
            "allowed_sessions": None,   # All sessions OK for swing
            "blocked_sessions": [],
        },
    },
}

# Fallback defaults when style or symbol is not found
_FALLBACK = {
    "min_sl_pips": 20,
    "max_sl_pips": 100,
    "min_tp_pips": 40,
    "max_tp_pips": 200,
    "min_rr": 1.0,
    "risk_percent": 1.0,
    "be_trigger_pips": 20,
    "be_offset_pips": 2,
    "trail_start_pips": 30,
    "trail_dist_pips": 15,
    "min_atr_pips": None,
    "allowed_sessions": None,
    "blocked_sessions": [],
}


# ─────────────────────────────────────────────────────────────────────────────
# LOOKUP HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_symbol(symbol: str) -> str:
    """Map broker-specific symbols (XAUUSDc, etc.) to base names."""
    s = symbol.upper().replace(" ", "")
    if "XAU" in s or "GOLD" in s:
        return "XAUUSD"
    return s[:6]  # best-effort


def get_style_params(trade_style: str, symbol: str) -> dict:
    """
    Lookup parameters for a given trade_style + symbol.

    Returns a dict with all keys guaranteed (falls back to _FALLBACK).
    """
    style = trade_style.upper().strip()
    base_symbol = _normalize_symbol(symbol)

    style_block = STYLE_PARAMS.get(style, {})
    params = style_block.get(base_symbol)

    if params is None:
        # Try first available symbol in this style as fallback
        if style_block:
            first_key = next(iter(style_block))
            params = style_block[first_key]
            logger.debug(
                f"style_params: no entry for {style}/{base_symbol}, "
                f"falling back to {style}/{first_key}"
            )
        else:
            params = _FALLBACK
            logger.debug(
                f"style_params: unknown style '{style}', using global fallback"
            )

    # Merge with fallback to guarantee all keys exist
    merged = dict(_FALLBACK)
    merged.update(params)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# SESSION DETECTION (generic — works for any symbol)
# ─────────────────────────────────────────────────────────────────────────────

def get_current_session(symbol: str = "") -> Dict[str, str]:
    """
    Estimate the current trading session from UTC time.

    Returns {"name": "London", "profile": "..."} etc.
    Session boundaries (UTC):
        Asia:              00:00 – 07:00
        London:            07:00 – 12:00
        London/NY overlap: 12:00 – 16:00
        NY:                16:00 – 21:00
        Off-hours:         21:00 – 00:00
    """
    hour = datetime.utcnow().hour

    if 0 <= hour < 7:
        return {
            "name": "Asia",
            "profile": "Low liquidity; stop-hunt reversal prone; avoid breakout trades",
        }
    if 7 <= hour < 12:
        return {
            "name": "London",
            "profile": "High momentum; breakouts and range expansions are reliable",
        }
    if 12 <= hour < 16:
        return {
            "name": "London/NY overlap",
            "profile": "Highest liquidity; continuation and opening-range breaks get extra weight",
        }
    if 16 <= hour < 21:
        return {
            "name": "NY",
            "profile": "High liquidity; news-driven continuation and reversals both matter",
        }
    return {
        "name": "Off-hours",
        "profile": "Lower liquidity; prefer HOLD unless strong confluence",
    }


def is_session_allowed(trade_style: str, symbol: str, session_name: str = "") -> tuple:
    """
    Check if trading is allowed in the current session for this style/symbol.

    Returns (allowed: bool, reason: str).
    """
    if not session_name:
        session_name = get_current_session(symbol)["name"]

    params = get_style_params(trade_style, symbol)
    blocked = params.get("blocked_sessions") or []

    if session_name in blocked:
        return (
            False,
            f"{trade_style} is blocked during {session_name} session for "
            f"{_normalize_symbol(symbol)}"
        )

    allowed_list = params.get("allowed_sessions")
    if allowed_list is not None and session_name not in allowed_list:
        return (
            False,
            f"{trade_style} only allowed during {allowed_list}, "
            f"current session is {session_name}"
        )

    return True, f"Session {session_name} OK for {trade_style}"
