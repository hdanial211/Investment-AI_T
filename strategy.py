"""
strategy.py - Technical Indicator Calculator

Calculates:
- RSI (Relative Strength Index)
- EMA Fast / Slow (Exponential Moving Average)
- MACD (Moving Average Convergence Divergence)
- Trend detection (bullish / bearish / sideways)
- Volatility check
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR CALCULATIONS (pure numpy/pandas — no TA-Lib dependency)
# ─────────────────────────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder's smoothing method."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(
    series: pd.Series,
    fast:   int = 12,
    slow:   int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calculate MACD line, signal line, and histogram.
    Returns (macd_line, signal_line, histogram)
    """
    ema_fast    = calc_ema(series, fast)
    ema_slow    = calc_ema(series, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range for volatility measure."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1/period, adjust=False).mean()


# ─────────────────────────────────────────────────────────────────────────────
# TREND DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def detect_trend(ema_fast: float, ema_slow: float, rsi: float) -> str:
    """
    Determine market trend based on EMA crossover and RSI.
    Returns: 'bullish' | 'bearish' | 'sideways'
    """
    if ema_fast > ema_slow and rsi > 50:
        return "bullish"
    elif ema_fast < ema_slow and rsi < 50:
        return "bearish"
    else:
        return "sideways"


def check_volatility(atr: float, price: float, min_pips: int = None) -> bool:
    """
    Return True if market has sufficient volatility to trade.
    ATR as percentage of price must exceed threshold.
    """
    threshold = (min_pips or config.MIN_VOLATILITY_PIPS) * config.get_pip_multiplier()
    return atr >= threshold


# ─────────────────────────────────────────────────────────────────────────────
# MAIN INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def calculate_indicators(df: pd.DataFrame, symbol: str = "") -> Optional[Dict]:
    """
    Given an OHLCV DataFrame, compute all indicators.
    Returns a flat dictionary of current indicator values.
    Returns None if not enough data.
    """
    if df is None or len(df) < config.EMA_SLOW + 5:
        logger.warning(f"Not enough bars to calculate indicators ({len(df) if df is not None else 0} bars)")
        return None

    closes = df["close"]

    # ── Calculate indicators ──────────────────────────────────────────────
    ema_fast_series = calc_ema(closes, config.EMA_FAST)
    ema_slow_series = calc_ema(closes, config.EMA_SLOW)
    rsi_series      = calc_rsi(closes, config.RSI_PERIOD)
    macd_line, macd_signal, macd_hist = calc_macd(
        closes,
        config.MACD_FAST,
        config.MACD_SLOW,
        config.MACD_SIGNAL,
    )
    atr_series = calc_atr(df)

    # ── Get latest values ─────────────────────────────────────────────────
    ema_fast = round(float(ema_fast_series.iloc[-1]), 5)
    ema_slow = round(float(ema_slow_series.iloc[-1]), 5)
    rsi      = round(float(rsi_series.iloc[-1]),      2)
    macd     = round(float(macd_line.iloc[-1]),        5)
    macd_sig = round(float(macd_signal.iloc[-1]),      5)
    macd_h   = round(float(macd_hist.iloc[-1]),        5)
    atr      = round(float(atr_series.iloc[-1]),       5)
    price    = round(float(closes.iloc[-1]),            5)

    # ── Trend & momentum signals ──────────────────────────────────────────
    trend          = detect_trend(ema_fast, ema_slow, rsi)
    ema_cross      = "golden_cross" if ema_fast > ema_slow else "death_cross"
    macd_cross     = "bullish" if macd_h > 0 else "bearish"
    rsi_zone       = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
    sufficient_vol = bool(atr > 0)  # Basic volatility check

    # ── Price change (momentum) ───────────────────────────────────────────
    prev_close   = float(closes.iloc[-2]) if len(closes) > 1 else price
    price_change = round(((price - prev_close) / prev_close) * 100, 4)

    indicators = {
        "symbol":          symbol,
        "price":           price,
        "ema_fast":        ema_fast,
        "ema_slow":        ema_slow,
        "rsi":             rsi,
        "macd":            macd,
        "macd_signal":     macd_sig,
        "macd_histogram":  macd_h,
        "atr":             atr,
        "trend":           trend,
        "ema_cross":       ema_cross,
        "macd_cross":      macd_cross,
        "rsi_zone":        rsi_zone,
        "price_change_pct": price_change,
        "sufficient_volatility": sufficient_vol,
        "bars_analyzed":   len(df),
    }

    logger.debug(
        f"[{symbol}] Price={price} | RSI={rsi} | EMA({config.EMA_FAST})={ema_fast} | "
        f"EMA({config.EMA_SLOW})={ema_slow} | MACD={macd:.5f} | Trend={trend}"
    )

    return indicators


def format_for_prompt(indicators: Dict) -> str:
    """Format indicator dict into a human-readable string for the AI prompt."""
    return (
        f"Symbol: {indicators['symbol']}\n"
        f"Current Price: {indicators['price']}\n"
        f"EMA {config.EMA_FAST}: {indicators['ema_fast']}\n"
        f"EMA {config.EMA_SLOW}: {indicators['ema_slow']}\n"
        f"EMA Cross: {indicators['ema_cross']}\n"
        f"RSI ({config.RSI_PERIOD}): {indicators['rsi']} [{indicators['rsi_zone']}]\n"
        f"MACD Line: {indicators['macd']}\n"
        f"MACD Signal: {indicators['macd_signal']}\n"
        f"MACD Histogram: {indicators['macd_histogram']} [{indicators['macd_cross']}]\n"
        f"ATR: {indicators['atr']}\n"
        f"Market Trend: {indicators['trend']}\n"
        f"Price Change: {indicators['price_change_pct']}%\n"
        f"Bars Analyzed: {indicators['bars_analyzed']}"
    )
