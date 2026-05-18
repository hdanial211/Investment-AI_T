"""
strategy.py - Advanced Technical Indicator & Pattern Calculator

Calculates:
- Multi-Timeframe Analysis (H4, H1, M15, M5)
- HTF Trend (H4 EMA/Structure)
- S/R Zones (Swing Highs/Lows)
- Liquidity Grabs / Stop Hunts (M15/M5)
- Classic indicators (RSI, MACD, ATR)
"""

import logging
from typing import Dict, Optional, Tuple, List

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# BASIC INDICATORS
# ─────────────────────────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast    = calc_ema(series, fast)
    ema_slow    = calc_ema(series, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high  = df["high"]
    low   = df["low"]
    close = df["close"]

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)

    return tr.ewm(alpha=1/period, adjust=False).mean()

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close = df['close']
    
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / atr)
    
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.finfo(float).eps))
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCED PRICE ACTION CONCEPTS
# ─────────────────────────────────────────────────────────────────────────────

def get_swing_levels(df: pd.DataFrame, lookback: int = 20) -> Tuple[float, float]:
    """Find recent swing high (Resistance) and swing low (Support)."""
    if len(df) < lookback:
        return df['high'].max(), df['low'].min()
    
    recent = df.iloc[-lookback:]
    resistance = recent['high'].max()
    support = recent['low'].min()
    return float(resistance), float(support)


def detect_liquidity_grab(df: pd.DataFrame, resistance: float, support: float, threshold: float) -> str:
    """
    Detect if the latest candle swept liquidity (poked through S/R but closed inside).
    """
    if len(df) < 2:
        return "none"
        
    latest = df.iloc[-1]
    
    # Bearish Grab (Swept high liquidity, but closed lower)
    if latest['high'] > resistance and latest['close'] < resistance - threshold:
        # Pinned above resistance but rejected
        if (latest['high'] - max(latest['open'], latest['close'])) > (abs(latest['open'] - latest['close']) * 1.5):
            return "bearish_sweep_high"
            
    # Bullish Grab (Swept low liquidity, but closed higher)
    if latest['low'] < support and latest['close'] > support + threshold:
        # Pinned below support but rejected
        if (min(latest['open'], latest['close']) - latest['low']) > (abs(latest['open'] - latest['close']) * 1.5):
            return "bullish_sweep_low"
            
    return "none"


def detect_engulfing(df: pd.DataFrame) -> str:
    """Detect bullish or bearish engulfing on the last completed candle."""
    if len(df) < 3:
        return "none"
        
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    
    # Bearish Engulfing
    if prev['close'] > prev['open'] and curr['close'] < curr['open']:
        if curr['open'] >= prev['close'] and curr['close'] < prev['open']:
            return "bearish_engulfing"
            
    # Bullish Engulfing
    if prev['close'] < prev['open'] and curr['close'] > curr['open']:
        if curr['open'] <= prev['close'] and curr['close'] > prev['open']:
            return "bullish_engulfing"
            
    return "none"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN MULTI-TIMEFRAME INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def calculate_multi_indicators(mdf: Dict[str, pd.DataFrame], symbol: str) -> Optional[Dict]:
    """
    Given a dict of OHLCV DataFrames for different timeframes (H4, H1, M15, M5),
    compute strategy context.
    """
    # Ensure we have the base timeframes
    for tf in ["H4", "H1", "M15", "M5"]:
        if tf not in mdf or mdf[tf] is None or mdf[tf].empty:
            logger.warning(f"[{symbol}] Missing {tf} data for multi-timeframe analysis.")
            return None

    df_h4 = mdf["H4"]
    df_h1 = mdf["H1"]
    df_m15 = mdf["M15"]
    df_m5 = mdf["M5"]

    # 1. H4 Trend Analysis (Macro bias)
    h4_ema9 = calc_ema(df_h4['close'], 9).iloc[-1]
    h4_ema21 = calc_ema(df_h4['close'], 21).iloc[-1]
    h4_rsi = calc_rsi(df_h4['close'], 14).iloc[-1]
    
    h4_trend = "sideways"
    if h4_ema9 > h4_ema21 and h4_rsi > 50:
        h4_trend = "bullish"
    elif h4_ema9 < h4_ema21 and h4_rsi < 50:
        h4_trend = "bearish"

    # 2. H1 Support/Resistance & Momentum
    h1_res, h1_sup = get_swing_levels(df_h1, lookback=20)
    macd_line, macd_sig, macd_h = calc_macd(df_h1['close'])
    h1_macd_hist = float(macd_h.iloc[-1])
    h1_macd_trend = "bullish" if h1_macd_hist > 0 else "bearish"
    
    # 2.5 Market Regime (ADX on H1)
    adx_val = float(calc_adx(df_h1).iloc[-1])
    market_regime = "TRENDING" if adx_val >= 25 else "RANGING"

    # 3. M15 Entry Context (Liquidity & Patterns)
    pip_size = config.get_pip_multiplier(symbol)
    m15_sweep = detect_liquidity_grab(df_m15, h1_res, h1_sup, threshold=pip_size*2)
    m15_engulfing = detect_engulfing(df_m15)
    m15_rsi = float(calc_rsi(df_m15['close'], 14).iloc[-1])

    # 4. M5 Micro-Structure (Fast entry)
    m5_sweep = detect_liquidity_grab(df_m5, h1_res, h1_sup, threshold=pip_size)
    m5_engulfing = detect_engulfing(df_m5)
    
    # 5. Core Price Metrics (Using M5 as closest to real-time)
    current_price = float(df_m5['close'].iloc[-1])
    atr_val = float(calc_atr(df_m15).iloc[-1])

    # Compile rich context
    indicators = {
        "symbol": symbol,
        "price": current_price,
        "market_regime": market_regime,
        "adx": round(adx_val, 2),
        "h4_trend": h4_trend,
        "h1_resistance": h1_res,
        "h1_support": h1_sup,
        "h1_macd_trend": h1_macd_trend,
        "m15_rsi": round(m15_rsi, 2),
        "m15_liquidity_sweep": m15_sweep,
        "m15_pattern": m15_engulfing,
        "m5_liquidity_sweep": m5_sweep,
        "m5_pattern": m5_engulfing,
        "atr": round(atr_val, 5),
        "sufficient_volatility": atr_val > (config.MIN_VOLATILITY_PIPS * pip_size)
    }

    logger.debug(f"[{symbol}] H4:{h4_trend} | S:{h1_sup} R:{h1_res} | M15 Sweep:{m15_sweep}")
    return indicators


def format_for_prompt(ind: Dict) -> str:
    """Format the rich multi-timeframe context for the AI prompt."""
    return (
        f"Symbol: {ind['symbol']}\n"
        f"Current Price: {ind['price']:.5f}\n"
        f"\n--- MARKET REGIME ---\n"
        f"Regime: {ind['market_regime']} (ADX: {ind['adx']})\n"
        f"*(Instruction: If TRENDING, prioritize breakouts & trends. If RANGING, prioritize S/R bounces and sweeps)*\n"
        f"\n--- TIMEFRAME: H4 (MACRO TREND) ---\n"
        f"Major Trend: {ind['h4_trend'].upper()}\n"
        f"\n--- TIMEFRAME: H1 (ZONES & MOMENTUM) ---\n"
        f"Resistance Zone: {ind['h1_resistance']:.5f}\n"
        f"Support Zone: {ind['h1_support']:.5f}\n"
        f"MACD Momentum: {ind['h1_macd_trend'].upper()}\n"
        f"\n--- TIMEFRAME: M15 (ENTRY CONTEXT) ---\n"
        f"RSI (14): {ind['m15_rsi']}\n"
        f"Liquidity Sweep Detected: {ind['m15_liquidity_sweep']}\n"
        f"Candle Pattern: {ind['m15_pattern']}\n"
        f"\n--- TIMEFRAME: M5 (MICRO SCALPING) ---\n"
        f"Liquidity Sweep Detected: {ind['m5_liquidity_sweep']}\n"
        f"Candle Pattern: {ind['m5_pattern']}\n"
        f"\n--- RISK METRICS ---\n"
        f"ATR: {ind['atr']}\n"
    )
