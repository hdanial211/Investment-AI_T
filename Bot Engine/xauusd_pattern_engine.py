"""
xauusd_pattern_engine.py - XAUUSD / Gold pattern detection helpers.

Gold behaves differently from forex majors: wider intraday ranges, stronger
session effects, frequent stop hunts, and respect for $50/$100 psychological
levels. This module keeps those XAU-specific assumptions separate from the
EURUSD scanner while reusing shared OHLC/pivot helpers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from eurusd_pattern_engine import (
    Pattern,
    _atr,
    _avg_body,
    _bearish_engulfing,
    _between,
    _body_inside,
    _bullish_engulfing,
    _candle,
    _clean_ohlc,
    _dedupe_patterns,
    _detect_chart_patterns,
    _detect_harmonic_patterns,
    _evening_star,
    _falling_three_methods,
    _gap_direction,
    _is_doji,
    _is_marubozu,
    _morning_star,
    _near,
    _pattern,
    _pivots,
    _price_tolerance,
    _rank_patterns,
    _rising_three_methods,
    _slope,
    _three_black_crows,
    _three_white_soldiers,
    _trend,
)


GOLD_POINT = 0.01


def scan_xauusd_patterns(
    mdf: Dict[str, pd.DataFrame],
    symbol: str = "XAUUSD",
    max_patterns: int = 22,
) -> List[Pattern]:
    """Scan XAUUSD multi-timeframe data with Gold-specific filters."""
    if "XAU" not in symbol.upper() and "GOLD" not in symbol.upper():
        return []

    from session_filter import detect_session
    session = detect_session(mdf, symbol)
    dxy_bias = "unavailable"
    current_price = _latest_price(mdf)
    results: List[Pattern] = []

    for timeframe in ("H4", "H1", "M15", "M5"):
        df = _clean_ohlc(mdf.get(timeframe))
        if df is None or len(df) < 8:
            continue

        results.extend(_detect_xau_candlestick_patterns(df, timeframe))
        results.extend(_detect_xau_price_action_patterns(df, timeframe))
        results.extend(_detect_xau_smc_patterns(df, timeframe, session))
        results.extend(_detect_gold_specific_patterns(df, timeframe, session, current_price))

        if len(df) >= 30:
            results.extend(_boost_generic_gold_patterns(_detect_chart_patterns(df, timeframe, 1.0)))
        if len(df) >= 40:
            results.extend(_boost_generic_gold_patterns(_detect_harmonic_patterns(df, timeframe, 1.0)))

    weighted = _apply_gold_context_weights(results, session=session, dxy_bias=dxy_bias)
    return _rank_patterns(_dedupe_patterns(weighted), max_patterns=max_patterns)


def summarize_xauusd_pattern_bias(patterns: Sequence[Pattern], mdf: Dict[str, pd.DataFrame]) -> Dict[str, object]:
    """Summarize XAUUSD pattern confluence with session and psych-level context."""
    from session_filter import detect_session
    session = detect_session(mdf, "XAUUSD")
    price = _latest_price(mdf)
    nearest_50 = _nearest_psych_level(price, 50.0) if price else None
    nearest_100 = _nearest_psych_level(price, 100.0) if price else None

    bullish = 0.0
    bearish = 0.0
    neutral = 0.0
    high_priority: List[str] = []

    for pattern in patterns:
        confidence = float(pattern.get("confidence", 0.0))
        direction = str(pattern.get("direction", "neutral")).lower()
        priority = str(pattern.get("priority", "medium")).lower()
        weight = 1.35 if priority == "high" else 0.65 if priority in ("lower", "avoid") else 1.0

        if direction == "bullish":
            bullish += confidence * weight
        elif direction == "bearish":
            bearish += confidence * weight
        else:
            neutral += confidence * 0.45

        if priority == "high":
            high_priority.append(str(pattern.get("name", "")))

    net = bullish - bearish
    if abs(net) < 0.45:
        bias = "mixed"
    else:
        bias = "bullish" if net > 0 else "bearish"

    return {
        "bias": bias,
        "bullish_score": round(bullish, 2),
        "bearish_score": round(bearish, 2),
        "neutral_score": round(neutral, 2),
        "net_score": round(net, 2),
        "high_priority_count": len(high_priority),
        "high_priority_patterns": high_priority[:6],
        "session": session.get("name", "unknown"),
        "session_profile": session.get("profile", ""),
        "dxy_bias": "unavailable",
        "nearest_psych_50": nearest_50,
        "nearest_psych_100": nearest_100,
    }




# ---------------------------------------------------------------------------
# XAU-specific candlestick and price action
# ---------------------------------------------------------------------------


def _detect_xau_candlestick_patterns(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    c2 = _candle(df, -3)
    c3 = _candle(df, -4) if len(df) >= 4 else None
    c4 = _candle(df, -5) if len(df) >= 5 else None
    if c0 is None or c1 is None or c2 is None:
        return patterns

    trend = _trend(df.iloc[:-1])
    tol = _xau_tolerance(df)
    avg_body = _avg_body(df)
    volume_spike = _volume_spike(df)
    near_psych = _is_near_psych_level(c0.close, df)
    rsi = _rsi(df["close"].astype(float)).iloc[-1]

    if _xau_hammer(c0):
        confidence = 0.78 + (0.08 if near_psych else 0.0) + (0.05 if volume_spike else 0.0)
        if trend == "down" or near_psych:
            patterns.append(_pattern("Hammer at Gold Key Level", "bullish reversal", "bullish", "candlestick", confidence, timeframe, "3:1 lower wick rejection; stronger if near $50/$100 support.", priority="high"))
        if trend == "up" and rsi > 70 and near_psych:
            patterns.append(_pattern("Hanging Man at Gold Resistance", "bearish reversal", "bearish", "candlestick", 0.72, timeframe, "Hammer shape after uptrend with RSI extreme near psych resistance.", priority="medium"))

    if _xau_shooting_shape(c0):
        confidence = 0.80 + (0.08 if near_psych else 0.0) + (0.05 if volume_spike else 0.0)
        if trend == "up" or near_psych:
            patterns.append(_pattern("Shooting Star at Gold Key Level", "bearish reversal", "bearish", "candlestick", confidence, timeframe, "3:1 upper wick rejection; common before large Gold reversals.", priority="high"))
        if trend == "down":
            patterns.append(_pattern("Inverted Hammer", "bullish reversal", "bullish", "candlestick", 0.62, timeframe, "Upper wick after decline; requires next candle confirmation on Gold."))

    if _is_doji(c0):
        confidence = 0.58 + (0.08 if near_psych else 0.0)
        patterns.append(_pattern("Doji", "neutral", "neutral", "candlestick", confidence, timeframe, "Indecision; meaningful on Gold mainly after volatility spikes or at key levels."))
        if c0.lower >= c0.range * 0.62 and c0.upper <= c0.range * 0.15:
            patterns.append(_pattern("Dragonfly Doji at Gold Support", "bullish reversal", "bullish", "candlestick", 0.74, timeframe, "Doji with long lower rejection; strong at psych support.", priority="high" if near_psych else "medium"))
        if c0.upper >= c0.range * 0.62 and c0.lower <= c0.range * 0.15:
            patterns.append(_pattern("Gravestone Doji at Gold Resistance", "bearish reversal", "bearish", "candlestick", 0.74, timeframe, "Doji with long upper rejection; strong at psych resistance.", priority="high" if near_psych else "medium"))
        if c0.upper >= c0.range * 0.30 and c0.lower >= c0.range * 0.30:
            patterns.append(_pattern("Long-Legged Doji", "neutral", "neutral", "candlestick", 0.48, timeframe, "Common Asia-session noise unless it appears at a key level.", priority="avoid"))
        if trend == "down" and c0.lower > c0.upper * 1.3:
            patterns.append(_pattern("Southern Doji", "bullish reversal", "bullish", "candlestick", 0.68, timeframe, "Doji after decline with stronger lower rejection."))
        if trend == "up" and c0.upper > c0.lower * 1.3:
            patterns.append(_pattern("Northern Doji", "bearish reversal", "bearish", "candlestick", 0.68, timeframe, "Doji after rally with stronger upper rejection."))

    if _is_marubozu(c0):
        direction = "bullish" if c0.direction == "bullish" else "bearish"
        name = "Bullish Marubozu Institutional Momentum" if direction == "bullish" else "Bearish Marubozu Institutional Momentum"
        patterns.append(_pattern(name, f"{direction} continuation", direction, "candlestick", 0.70 + (0.05 if volume_spike else 0), timeframe, "Full-bodied Gold candle suggests institutional momentum.", priority="medium"))

    if c0.body_ratio <= 0.35 and c0.upper >= c0.body and c0.lower >= c0.body:
        patterns.append(_pattern("Spinning Top", "neutral", "neutral", "candlestick", 0.35, timeframe, "Avoid on XAUUSD unless supported by stronger confluence.", priority="avoid"))
    if c0.body_ratio <= 0.25 and c0.upper >= avg_body * 1.2 and c0.lower >= avg_body * 1.2:
        patterns.append(_pattern("High Wave", "neutral", "neutral", "candlestick", 0.35, timeframe, "Often appears after Gold news spikes; not an entry by itself.", priority="avoid"))

    if c0.direction == "bullish" and c0.body >= avg_body * 1.2 and _near(c0.open, c0.low, tol):
        patterns.append(_pattern("Bullish Belt-Hold Line at Gold Support", "bullish reversal", "bullish", "candlestick", 0.66, timeframe, "Long bullish candle opens near low; valid near support/order block."))
    if c0.direction == "bearish" and c0.body >= avg_body * 1.2 and _near(c0.open, c0.high, tol):
        patterns.append(_pattern("Bearish Belt-Hold Line at Gold Resistance", "bearish reversal", "bearish", "candlestick", 0.66, timeframe, "Long bearish candle opens near high; valid near resistance."))

    if _bullish_engulfing(c1, c0) and c0.body >= c1.body * 1.2:
        patterns.append(_pattern("Bullish Engulfing Gold Confirmed", "bullish reversal", "bullish", "candlestick", 0.86 + (0.04 if volume_spike else 0), timeframe, "Engulfing body is at least 1.2x prior candle; high-priority Gold reversal.", priority="high"))
    if _bearish_engulfing(c1, c0) and c0.body >= c1.body * 1.2:
        patterns.append(_pattern("Bearish Engulfing Gold Confirmed", "bearish reversal", "bearish", "candlestick", 0.86 + (0.04 if volume_spike else 0), timeframe, "Engulfing body is at least 1.2x prior candle; high-priority Gold reversal.", priority="high"))

    if c1.direction == "bearish" and c0.direction == "bullish" and _body_inside(c0, c1):
        patterns.append(_pattern("Bullish Harami", "bullish reversal", "bullish", "candlestick", 0.55 + (0.08 if near_psych else 0), timeframe, "Gold harami needs psych/support confirmation."))
    if c1.direction == "bullish" and c0.direction == "bearish" and _body_inside(c0, c1):
        patterns.append(_pattern("Bearish Harami", "bearish reversal", "bearish", "candlestick", 0.55 + (0.08 if near_psych else 0), timeframe, "Gold harami needs resistance confirmation."))
    if c1.direction == "bearish" and _is_doji(c0) and _body_inside(c0, c1):
        patterns.append(_pattern("Bullish Harami Cross", "bullish reversal", "bullish", "candlestick", 0.66, timeframe, "Doji inside bearish body; stronger at support."))
    if c1.direction == "bullish" and _is_doji(c0) and _body_inside(c0, c1):
        patterns.append(_pattern("Bearish Harami Cross", "bearish reversal", "bearish", "candlestick", 0.66, timeframe, "Doji inside bullish body; stronger at resistance."))

    midpoint = (c1.open + c1.close) / 2
    if c1.direction == "bearish" and c0.direction == "bullish" and c0.close > midpoint:
        patterns.append(_pattern("Piercing Line Gold", "bullish reversal", "bullish", "candlestick", 0.76, timeframe, "Bullish candle closes past midpoint of prior bearish body.", priority="medium"))
    if c1.direction == "bullish" and c0.direction == "bearish" and c0.close < midpoint:
        patterns.append(_pattern("Dark Cloud Cover Gold", "bearish reversal", "bearish", "candlestick", 0.76, timeframe, "Bearish candle closes past midpoint of prior bullish body.", priority="medium"))

    if c1.direction == "bearish" and c0.direction == "bullish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Bullish Counterattack", "bullish reversal", "bullish", "candlestick", 0.58, timeframe, "Rare but valid close-level counterattack."))
    if c1.direction == "bullish" and c0.direction == "bearish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Bearish Counterattack", "bearish reversal", "bearish", "candlestick", 0.58, timeframe, "Rare but valid close-level counterattack."))
    if _is_marubozu(c1) and _is_marubozu(c0) and c1.direction == "bearish" and c0.direction == "bullish" and c0.open > c1.open:
        patterns.append(_pattern("Bullish Kicking News Reversal", "bullish reversal", "bullish", "candlestick", 0.64, timeframe, "Gold kicking pattern often appears after major news."))
    if _is_marubozu(c1) and _is_marubozu(c0) and c1.direction == "bullish" and c0.direction == "bearish" and c0.open < c1.open:
        patterns.append(_pattern("Bearish Kicking News Reversal", "bearish reversal", "bearish", "candlestick", 0.64, timeframe, "Gold kicking pattern often appears after major news."))
    if c1.direction == "bearish" and c0.direction == "bearish" and _body_inside(c0, c1):
        patterns.append(_pattern("Homing Pigeon", "bullish reversal", "bullish", "candlestick", 0.42, timeframe, "Lower relevance for XAU scalping.", priority="lower"))
    if c1.direction == "bearish" and c0.direction == "bearish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Matching Low at Gold Support", "bullish reversal", "bullish", "candlestick", 0.62, timeframe, "Repeated bearish closes show selling pressure fading."))
    if c1.direction != c0.direction and _near(c0.open, c1.open, tol):
        direction = "bullish" if c0.direction == "bullish" else "bearish"
        patterns.append(_pattern(f"{direction.title()} Separating Lines", f"{direction} continuation", direction, "candlestick", 0.54, timeframe, "Only useful on Gold if aligned with MA200 or strong trend."))

    if _near(c1.high, c0.high, tol):
        patterns.append(_pattern("Tweezer Top at Gold Resistance", "bearish reversal", "bearish", "candlestick", 0.78 + (0.05 if near_psych else 0), timeframe, "Gold often rejects repeated highs at psych resistance.", priority="high"))
    if _near(c1.low, c0.low, tol):
        patterns.append(_pattern("Tweezer Bottom at Gold Support", "bullish reversal", "bullish", "candlestick", 0.78 + (0.05 if near_psych else 0), timeframe, "Gold often rejects repeated lows at psych support.", priority="high"))

    if _morning_star(c2, c1, c0):
        patterns.append(_pattern("Morning Star Gold", "bullish reversal", "bullish", "candlestick", 0.82 + (0.05 if volume_spike else 0), timeframe, "Powerful three-candle Gold reversal; stronger with volume.", priority="medium"))
    if _evening_star(c2, c1, c0):
        patterns.append(_pattern("Evening Star Gold", "bearish reversal", "bearish", "candlestick", 0.82 + (0.05 if volume_spike else 0), timeframe, "Powerful three-candle Gold reversal; stronger with volume.", priority="medium"))
    if _morning_star(c2, c1, c0) and _is_doji(c1):
        patterns.append(_pattern("Morning Doji Star Gold", "bullish reversal", "bullish", "candlestick", 0.84, timeframe, "Morning star with doji middle candle."))
    if _evening_star(c2, c1, c0) and _is_doji(c1):
        patterns.append(_pattern("Evening Doji Star Gold", "bearish reversal", "bearish", "candlestick", 0.84, timeframe, "Evening star with doji middle candle."))
    if _is_doji(c1) and c1.low < c2.low and c1.low < c0.low and c0.direction == "bullish":
        patterns.append(_pattern("Abandoned Baby Bottom Gold", "bullish reversal", "bullish", "candlestick", 0.72, timeframe, "Rare but reliable bottoming signal on Gold."))
    if _is_doji(c1) and c1.high > c2.high and c1.high > c0.high and c0.direction == "bearish":
        patterns.append(_pattern("Abandoned Baby Top Gold", "bearish reversal", "bearish", "candlestick", 0.72, timeframe, "Rare but reliable topping signal on Gold."))
    if _three_white_soldiers(c2, c1, c0, avg_body):
        patterns.append(_pattern("Three White Soldiers Gold Momentum", "bullish reversal", "bullish", "candlestick", 0.78 + (0.05 if volume_spike else 0), timeframe, "Strong institutional-style bullish momentum."))
    if _three_black_crows(c2, c1, c0, avg_body):
        patterns.append(_pattern("Three Black Crows Gold Momentum", "bearish reversal", "bearish", "candlestick", 0.78 + (0.05 if volume_spike else 0), timeframe, "Strong institutional-style bearish momentum."))
    if c2.direction == "bearish" and c1.direction == "bullish" and _body_inside(c1, c2) and c0.close > c2.high:
        patterns.append(_pattern("Three Inside Up Gold", "bullish reversal", "bullish", "candlestick", 0.68 + (0.06 if near_psych else 0), timeframe, "Valid if near support/psych level."))
    if c2.direction == "bullish" and c1.direction == "bearish" and _body_inside(c1, c2) and c0.close < c2.low:
        patterns.append(_pattern("Three Inside Down Gold", "bearish reversal", "bearish", "candlestick", 0.68 + (0.06 if near_psych else 0), timeframe, "Valid if near resistance/psych level."))
    if _bullish_engulfing(c2, c1) and c0.direction == "bullish" and c0.close > c1.close:
        patterns.append(_pattern("Three Outside Up Gold", "bullish reversal", "bullish", "candlestick", 0.78, timeframe, "Gold engulfing continuation confirmation."))
    if _bearish_engulfing(c2, c1) and c0.direction == "bearish" and c0.close < c1.close:
        patterns.append(_pattern("Three Outside Down Gold", "bearish reversal", "bearish", "candlestick", 0.78, timeframe, "Gold engulfing continuation confirmation."))
    if c4 and c3 and _rising_three_methods(c4, c3, c2, c1, c0):
        patterns.append(_pattern("Rising Three Methods Gold", "bullish continuation", "bullish", "candlestick", 0.74, timeframe, "Reliable H4/Daily-style continuation structure."))
    if c4 and c3 and _falling_three_methods(c4, c3, c2, c1, c0):
        patterns.append(_pattern("Falling Three Methods Gold", "bearish continuation", "bearish", "candlestick", 0.74, timeframe, "Reliable H4/Daily-style continuation structure."))
    if c2.direction == "bullish" and c1.direction == "bullish" and c0.direction == "bullish" and c2.body > c1.body > c0.body and c2.upper < c1.upper < c0.upper:
        patterns.append(_pattern("Advance Block Gold Warning", "bearish bias", "bearish", "candlestick", 0.64, timeframe, "Bullish momentum is weakening with growing upper wicks."))

    return patterns


def _detect_xau_price_action_patterns(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    c2 = _candle(df, -3)
    c3 = _candle(df, -4) if len(df) >= 4 else None
    if c0 is None or c1 is None or c2 is None:
        return patterns

    near_key = _is_near_psych_level(c0.close, df) or _near_recent_level(df)
    if _xau_hammer(c0) and near_key:
        patterns.append(_pattern("Pin Bar Bullish at Key Level", "reversal", "bullish", "price_action", 0.86, timeframe, "Gold pin bar uses stricter 3:1 wick/body and key-level filter.", priority="high"))
    if _xau_shooting_shape(c0) and near_key:
        patterns.append(_pattern("Pin Bar Bearish at Key Level", "reversal", "bearish", "price_action", 0.86, timeframe, "Gold bearish pin bar uses stricter 3:1 wick/body and key-level filter.", priority="high"))
    if c0.high <= c1.high and c0.low >= c1.low:
        patterns.append(_pattern("Inside Bar Gold", "continuation/reversal", "neutral", "price_action", 0.64, timeframe, "Watch breakout direction; London breakouts are strongest.", priority="medium"))
    if c0.high > c1.high and c0.low < c1.low:
        direction = "bullish" if c0.close > c0.open else "bearish" if c0.close < c0.open else "neutral"
        patterns.append(_pattern(f"Outside Bar Gold {direction.title()}", "reversal", direction, "price_action", 0.72, timeframe, "Gold outside bar is stricter than body engulfing."))
    if c3 and c2.high <= c3.high and c2.low >= c3.low:
        if c1.low < c2.low and c0.close > c2.high:
            patterns.append(_pattern("Fakey Bullish Stop-Run", "reversal", "bullish", "price_action", 0.84, timeframe, "Inside bar false break down reverses upward; very relevant to Gold.", priority="high"))
            patterns.append(_pattern("Hikkake Bullish", "reversal", "bullish", "price_action", 0.78, timeframe, "False downside break of an inside bar reverses."))
        if c1.high > c2.high and c0.close < c2.low:
            patterns.append(_pattern("Fakey Bearish Stop-Run", "reversal", "bearish", "price_action", 0.84, timeframe, "Inside bar false break up reverses downward; very relevant to Gold.", priority="high"))
            patterns.append(_pattern("Hikkake Bearish", "reversal", "bearish", "price_action", 0.78, timeframe, "False upside break of an inside bar reverses."))
    if c2.direction == "bearish" and c1.high <= c2.high and c1.low >= c2.low and c0.direction == "bullish" and c0.close > c2.high:
        patterns.append(_pattern("Three Bar Reversal Bullish Gold", "reversal", "bullish", "price_action", 0.76, timeframe, "One of the core Gold price-action reversal structures.", priority="medium"))
    if c2.direction == "bullish" and c1.high <= c2.high and c1.low >= c2.low and c0.direction == "bearish" and c0.close < c2.low:
        patterns.append(_pattern("Three Bar Reversal Bearish Gold", "reversal", "bearish", "price_action", 0.76, timeframe, "One of the core Gold price-action reversal structures.", priority="medium"))
    if (_xau_hammer(c0) or _xau_shooting_shape(c0)) and c0.high <= c1.high and c0.low >= c1.low:
        direction = "bullish" if _xau_hammer(c0) else "bearish"
        patterns.append(_pattern(f"Inside Pin Bar Combo {direction.title()}", "reversal/continuation", direction, "price_action", 0.80, timeframe, "Pin bar also sits inside previous candle; strong XAU confluence.", priority="high"))
    if c1 and (_xau_hammer(c1) or _xau_shooting_shape(c1)) and c0.high <= c1.high and c0.low >= c1.low:
        direction = "bullish" if _xau_hammer(c1) else "bearish"
        patterns.append(_pattern(f"Pin Bar + Inside Bar Combo {direction.title()}", "reversal/continuation", direction, "price_action", 0.78, timeframe, "Inside bar forms after a Gold pin bar at a key level."))
    if c0.direction == "bullish" and c0.upper <= c0.range * 0.08:
        patterns.append(_pattern("Shaved Bar Bullish Momentum", "continuation", "bullish", "price_action", 0.64, timeframe, "Minimal upper wick shows strong buy-side momentum."))
    if c0.direction == "bearish" and c0.lower <= c0.range * 0.08:
        patterns.append(_pattern("Shaved Bar Bearish Momentum", "continuation", "bearish", "price_action", 0.64, timeframe, "Minimal lower wick shows strong sell-side momentum."))
    if _bullish_engulfing(c1, c0) and c0.body >= c1.body * 1.2:
        patterns.append(_pattern("Engulfing Bar Bullish Gold", "reversal", "bullish", "price_action", 0.84, timeframe, "Body engulf exceeds Gold threshold.", priority="high"))
    if _bearish_engulfing(c1, c0) and c0.body >= c1.body * 1.2:
        patterns.append(_pattern("Engulfing Bar Bearish Gold", "reversal", "bearish", "price_action", 0.84, timeframe, "Body engulf exceeds Gold threshold.", priority="high"))
    if c1.direction == "bearish" and c0.direction == "bullish" and c0.close > c1.open:
        patterns.append(_pattern("2-Bar Reversal Bullish Gold", "reversal", "bullish", "price_action", 0.68, timeframe, "Simple reversal works best at key levels."))
    if c1.direction == "bullish" and c0.direction == "bearish" and c0.close < c1.open:
        patterns.append(_pattern("2-Bar Reversal Bearish Gold", "reversal", "bearish", "price_action", 0.68, timeframe, "Simple reversal works best at key levels."))
    return patterns


# ---------------------------------------------------------------------------
# Smart Money Concepts and Gold-specific patterns
# ---------------------------------------------------------------------------


def _detect_xau_smc_patterns(df: pd.DataFrame, timeframe: str, session: Dict[str, str]) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 24:
        return patterns

    c0 = _candle(df, -1)
    if c0 is None:
        return patterns

    pivots = _pivots(df.tail(80), left=2, right=2)
    highs = [p for p in pivots if p[1] == "H"]
    lows = [p for p in pivots if p[1] == "L"]
    close = c0.close
    atr = float(_atr(df).iloc[-1])
    recent = df.iloc[-21:-1]
    prior_high = float(recent["high"].max())
    prior_low = float(recent["low"].min())
    tol = max(atr * 0.14, 0.8)

    sweep_high = c0.high > prior_high and c0.close < prior_high - tol
    sweep_low = c0.low < prior_low and c0.close > prior_low + tol
    if sweep_high:
        patterns.append(_pattern("Liquidity Sweep High / Stop Hunt", "SMC reversal", "bearish", "smc", 0.90, timeframe, "Gold swept buy-side liquidity then closed back below prior highs.", priority="high"))
    if sweep_low:
        patterns.append(_pattern("Liquidity Sweep Low / Stop Hunt", "SMC reversal", "bullish", "smc", 0.90, timeframe, "Gold swept sell-side liquidity then closed back above prior lows.", priority="high"))

    if highs:
        last_high = highs[-1][2]
        if close > last_high + tol:
            direction = "bullish"
            name = "BOS Bullish" if _trend(df.iloc[:-1]) == "up" else "CHoCH / MSS Bullish"
            priority = "high" if "CHoCH" in name else "medium"
            patterns.append(_pattern(name, "SMC continuation/reversal", direction, "smc", 0.78, timeframe, "Close broke the latest structural swing high.", priority=priority))
    if lows:
        last_low = lows[-1][2]
        if close < last_low - tol:
            direction = "bearish"
            name = "BOS Bearish" if _trend(df.iloc[:-1]) == "down" else "CHoCH / MSS Bearish"
            priority = "high" if "CHoCH" in name else "medium"
            patterns.append(_pattern(name, "SMC continuation/reversal", direction, "smc", 0.78, timeframe, "Close broke the latest structural swing low.", priority=priority))

    fvg = _detect_fvg(df, timeframe)
    patterns.extend(fvg)
    if sweep_low and any(p.get("direction") == "bullish" and "FVG" in str(p.get("name")) for p in fvg):
        patterns.append(_pattern("Liquidity Grab + FVG Entry Bullish", "SMC reversal", "bullish", "smc", 0.92, timeframe, "Sell-side sweep followed by bullish imbalance; classic Gold SMC setup.", priority="high"))
    if sweep_high and any(p.get("direction") == "bearish" and "FVG" in str(p.get("name")) for p in fvg):
        patterns.append(_pattern("Liquidity Grab + FVG Entry Bearish", "SMC reversal", "bearish", "smc", 0.92, timeframe, "Buy-side sweep followed by bearish imbalance; classic Gold SMC setup.", priority="high"))

    patterns.extend(_detect_order_blocks(df, timeframe))
    patterns.extend(_detect_breaker_mitigation(df, timeframe))
    patterns.extend(_detect_inducement(df, timeframe))

    if session.get("name") == "Asia" and (sweep_high or sweep_low):
        direction = "bearish" if sweep_high else "bullish"
        patterns.append(_pattern("SMC Session-Based Pattern Asia Stop-Run", "session filter", direction, "smc", 0.82, timeframe, "Asia session sweep supports stop-run reversal logic.", priority="high"))

    return patterns


def _detect_gold_specific_patterns(
    df: pd.DataFrame,
    timeframe: str,
    session: Dict[str, str],
    current_price: Optional[float],
) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 30:
        return patterns

    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    if c0 is None or c1 is None:
        return patterns

    close = c0.close
    atr = float(_atr(df).iloc[-1])
    tol = _xau_tolerance(df)
    nearest_50 = _nearest_psych_level(close, 50.0)
    nearest_100 = _nearest_psych_level(close, 100.0)

    if nearest_50 is not None and abs(close - nearest_50) <= tol:
        direction = "bullish" if c0.lower > c0.upper else "bearish" if c0.upper > c0.lower else "neutral"
        patterns.append(_pattern("Psych Level Bounce $50", "gold-specific", direction, "gold_specific", 0.80, timeframe, f"Price is reacting around Gold $50 level {nearest_50:.2f}.", priority="high"))
    if nearest_100 is not None and abs(close - nearest_100) <= tol:
        direction = "bullish" if c0.lower > c0.upper else "bearish" if c0.upper > c0.lower else "neutral"
        patterns.append(_pattern("Psych Level Bounce $100", "gold-specific", direction, "gold_specific", 0.84, timeframe, f"Price is reacting around major Gold $100 level {nearest_100:.2f}.", priority="high"))

    prev_close = float(df["close"].iloc[-2])
    for level in (nearest_50, nearest_100):
        if level is None:
            continue
        if prev_close < level < close and c0.low <= level + tol:
            patterns.append(_pattern("Psych Level Break & Retest Bullish", "gold-specific", "bullish", "gold_specific", 0.82, timeframe, f"Gold broke and retested psych level {level:.2f}.", priority="high"))
        if prev_close > level > close and c0.high >= level - tol:
            patterns.append(_pattern("Psych Level Break & Retest Bearish", "gold-specific", "bearish", "gold_specific", 0.82, timeframe, f"Gold broke and retested psych level {level:.2f}.", priority="high"))

    patterns.extend(_detect_session_opening_breakout(df, timeframe, session))
    patterns.extend(_detect_asian_range_breakout(df, timeframe, session))

    prev_range = c1.range
    if prev_range > atr * 2.0 and c0.direction != c1.direction and c0.body > c1.body * 0.35:
        direction = c0.direction
        patterns.append(_pattern(f"News Spike Reversal {direction.title()}", "gold-specific", direction, "gold_specific", 0.78, timeframe, "Previous candle range exceeded 2x ATR and reversed within the next bar.", priority="high"))

    ma = _ma_context(df)
    patterns.extend(_detect_ma_patterns(df, timeframe, ma))

    rsi = _rsi(df["close"].astype(float)).iloc[-1]
    if rsi > 70 or rsi < 30:
        direction = "bearish" if rsi > 70 else "bullish"
        patterns.append(_pattern("RSI Extreme First Touch Filter", "gold-specific filter", direction, "gold_specific", 0.52, timeframe, "Gold often overshoots first MA touch when RSI is extreme; require extra confirmation.", priority="lower"))

    if _volume_spike(df):
        direction = c0.direction if c0.direction != "neutral" else "neutral"
        patterns.append(_pattern("Volume Spike + Pattern Confirmation", "gold-specific", direction, "gold_specific", 0.66, timeframe, "Current volume exceeds recent average; validates strong candlestick signals.", priority="medium"))

    if current_price:
        patterns.append(_pattern("DXY Divergence Check Unavailable", "macro filter", "neutral", "gold_specific", 0.30, timeframe, "No DXY feed is available in this repo; avoid assuming macro confirmation.", priority="lower"))

    return patterns


def _detect_fvg(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 3:
        return patterns
    c2 = _candle(df, -3)
    c1 = _candle(df, -2)
    c0 = _candle(df, -1)
    if c0 is None or c1 is None or c2 is None:
        return patterns

    atr = float(_atr(df).iloc[-1])
    min_gap = max(atr * 0.12, 0.5)
    if c0.low - c2.high > min_gap:
        patterns.append(_pattern("Bullish Fair Value Gap", "SMC imbalance", "bullish", "smc", 0.78, timeframe, "Three-candle bullish imbalance; likely mitigation zone.", priority="high"))
    if c2.low - c0.high > min_gap:
        patterns.append(_pattern("Bearish Fair Value Gap", "SMC imbalance", "bearish", "smc", 0.78, timeframe, "Three-candle bearish imbalance; likely mitigation zone.", priority="high"))

    # Inversion FVG: price closes back through a prior imbalance zone.
    if len(df) >= 8:
        for i in range(max(2, len(df) - 8), len(df) - 2):
            left_high = float(df["high"].iloc[i - 2])
            left_low = float(df["low"].iloc[i - 2])
            right_high = float(df["high"].iloc[i])
            right_low = float(df["low"].iloc[i])
            if right_low > left_high and c0.close < left_high:
                patterns.append(_pattern("Inversion FVG Bearish", "SMC entry", "bearish", "smc", 0.70, timeframe, "Prior bullish FVG inverted after mitigation.", priority="medium"))
                break
            if right_high < left_low and c0.close > left_low:
                patterns.append(_pattern("Inversion FVG Bullish", "SMC entry", "bullish", "smc", 0.70, timeframe, "Prior bearish FVG inverted after mitigation.", priority="medium"))
                break
    return patterns


def _detect_order_blocks(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    atr = float(_atr(df).iloc[-1])
    close = float(df["close"].iloc[-1])
    tol = max(atr * 0.25, 1.0)

    for i in range(max(1, len(df) - 18), len(df) - 3):
        candle_open = float(df["open"].iloc[i])
        candle_close = float(df["close"].iloc[i])
        candle_high = float(df["high"].iloc[i])
        candle_low = float(df["low"].iloc[i])
        impulse = float(df["close"].iloc[i + 3]) - candle_close
        if candle_close < candle_open and impulse > atr * 1.2 and candle_low - tol <= close <= candle_high + tol:
            patterns.append(_pattern("Bullish Order Block Retest", "SMC support/resistance", "bullish", "smc", 0.78, timeframe, "Price retests last bearish candle before bullish impulse.", priority="high"))
            break
        if candle_close > candle_open and impulse < -atr * 1.2 and candle_low - tol <= close <= candle_high + tol:
            patterns.append(_pattern("Bearish Order Block Retest", "SMC support/resistance", "bearish", "smc", 0.78, timeframe, "Price retests last bullish candle before bearish impulse.", priority="high"))
            break
    return patterns


def _detect_breaker_mitigation(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 25:
        return patterns
    pivots = _pivots(df.tail(60), left=2, right=2)
    close = float(df["close"].iloc[-1])
    atr = float(_atr(df).iloc[-1])
    tol = max(atr * 0.18, 0.8)

    highs = [p for p in pivots if p[1] == "H"]
    lows = [p for p in pivots if p[1] == "L"]
    if highs:
        broken_high = highs[-1][2]
        if close > broken_high and float(df["low"].iloc[-1]) <= broken_high + tol:
            patterns.append(_pattern("Breaker Block Bullish", "SMC support/resistance", "bullish", "smc", 0.68, timeframe, "Broken resistance is acting as support after MSS/BOS."))
    if lows:
        broken_low = lows[-1][2]
        if close < broken_low and float(df["high"].iloc[-1]) >= broken_low - tol:
            patterns.append(_pattern("Breaker Block Bearish", "SMC support/resistance", "bearish", "smc", 0.68, timeframe, "Broken support is acting as resistance after MSS/BOS."))
    if any("Fair Value Gap" in str(p.get("name")) for p in _detect_fvg(df, timeframe)):
        patterns.append(_pattern("Mitigation Block", "SMC support/resistance", "neutral", "smc", 0.58, timeframe, "Recent imbalance is available for mitigation/retest."))
    return patterns


def _detect_inducement(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 12:
        return patterns
    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    c2 = _candle(df, -3)
    if c0 is None or c1 is None or c2 is None:
        return patterns
    atr = float(_atr(df).iloc[-1])
    if c1.high > max(float(df["high"].iloc[-8:-2].max()), c2.high) and c0.close < c1.low and c1.range < atr * 1.4:
        patterns.append(_pattern("Inducement Bearish", "SMC trap", "bearish", "smc", 0.70, timeframe, "Small buy-side break appears to have trapped breakout buyers.", priority="medium"))
    if c1.low < min(float(df["low"].iloc[-8:-2].min()), c2.low) and c0.close > c1.high and c1.range < atr * 1.4:
        patterns.append(_pattern("Inducement Bullish", "SMC trap", "bullish", "smc", 0.70, timeframe, "Small sell-side break appears to have trapped breakout sellers.", priority="medium"))
    return patterns


def _detect_session_opening_breakout(df: pd.DataFrame, timeframe: str, session: Dict[str, str]) -> List[Pattern]:
    patterns: List[Pattern] = []
    if session.get("name") not in ("London", "London/NY overlap", "NY") or "time" not in df.columns:
        return patterns

    clean = df.copy()
    clean["time"] = pd.to_datetime(clean["time"], errors="coerce")
    clean = clean.dropna(subset=["time"])
    if clean.empty:
        return patterns

    latest = clean.iloc[-1]
    latest_time = latest["time"]
    session_start_hour = 7 if session.get("name") == "London" else 12 if session.get("name") == "London/NY overlap" else 16
    session_rows = clean[clean["time"].dt.date == latest_time.date()]
    opening = session_rows[
        (session_rows["time"].dt.hour == session_start_hour)
        & (session_rows["time"].dt.minute <= 30)
    ]
    if opening.empty:
        return patterns

    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())
    close = float(latest["close"])
    if close > opening_high:
        patterns.append(_pattern("Session Opening Range Breakout Bullish", "gold-specific", "bullish", "gold_specific", 0.82, timeframe, "Gold broke above the first 15-30 minutes of London/NY range.", priority="high"))
    if close < opening_low:
        patterns.append(_pattern("Session Opening Range Breakout Bearish", "gold-specific", "bearish", "gold_specific", 0.82, timeframe, "Gold broke below the first 15-30 minutes of London/NY range.", priority="high"))
    return patterns


def _detect_asian_range_breakout(df: pd.DataFrame, timeframe: str, session: Dict[str, str]) -> List[Pattern]:
    patterns: List[Pattern] = []
    if session.get("name") not in ("London", "London/NY overlap") or "time" not in df.columns:
        return patterns
    clean = df.copy()
    clean["time"] = pd.to_datetime(clean["time"], errors="coerce")
    clean = clean.dropna(subset=["time"])
    if clean.empty:
        return patterns
    latest = clean.iloc[-1]
    same_day = clean[clean["time"].dt.date == latest["time"].date()]
    asia = same_day[(same_day["time"].dt.hour >= 0) & (same_day["time"].dt.hour < 7)]
    if asia.empty:
        return patterns
    asia_high = float(asia["high"].max())
    asia_low = float(asia["low"].min())
    close = float(latest["close"])
    if close > asia_high:
        patterns.append(_pattern("Asian Range Breakout London Bullish", "gold-specific", "bullish", "gold_specific", 0.84, timeframe, "London broke above Asian range; common XAU continuation setup.", priority="high"))
    if close < asia_low:
        patterns.append(_pattern("Asian Range Breakout London Bearish", "gold-specific", "bearish", "gold_specific", 0.84, timeframe, "London broke below Asian range; common XAU continuation setup.", priority="high"))
    return patterns


def _detect_ma_patterns(df: pd.DataFrame, timeframe: str, ma: Dict[str, float]) -> List[Pattern]:
    patterns: List[Pattern] = []
    if not ma:
        return patterns
    c0 = _candle(df, -1)
    if c0 is None:
        return patterns
    close = c0.close
    atr = float(_atr(df).iloc[-1])
    tol = max(atr * 0.16, 0.8)
    ma_values = [ma["ema13"], ma["ema21"], ma["ema75"], ma["ema100"]]
    compression = float(np.std(ma_values))
    if compression / max(close, 1.0) < 0.0012:
        patterns.append(_pattern("MA Compression Pattern", "gold-specific", "neutral", "gold_specific", 0.68, timeframe, "EMA13/21/75/100 are compressed; Gold often expands after compression.", priority="medium"))

    perfect_bull = ma["ema13"] > ma["ema21"] > ma["ema75"] > ma["ema100"]
    perfect_bear = ma["ema13"] < ma["ema21"] < ma["ema75"] < ma["ema100"]
    if perfect_bull and abs(close - ma["ema21"]) <= tol and c0.lower > c0.upper:
        patterns.append(_pattern("21MA Touch in Bullish Perfect Order", "gold-specific", "bullish", "gold_specific", 0.78, timeframe, "Bullish perfect order with rejection at EMA21.", priority="high"))
    if perfect_bear and abs(close - ma["ema21"]) <= tol and c0.upper > c0.lower:
        patterns.append(_pattern("21MA Touch in Bearish Perfect Order", "gold-specific", "bearish", "gold_specific", 0.78, timeframe, "Bearish perfect order with rejection at EMA21.", priority="high"))
    for key in ("ema75", "ema100"):
        if abs(close - ma[key]) <= tol:
            direction = "bullish" if c0.lower > c0.upper else "bearish" if c0.upper > c0.lower else "neutral"
            patterns.append(_pattern(f"75MA / 100MA Pullback {key.upper()}", "gold-specific", direction, "gold_specific", 0.70, timeframe, f"Price is rejecting around {key.upper()} pullback zone.", priority="medium"))
    return patterns


# ---------------------------------------------------------------------------
# Context and helper functions
# ---------------------------------------------------------------------------


def _apply_gold_context_weights(
    patterns: Iterable[Pattern],
    session: Dict[str, str],
    dxy_bias: str,
) -> List[Pattern]:
    adjusted: List[Pattern] = []
    session_name = session.get("name", "")
    for pattern in patterns:
        p = dict(pattern)
        confidence = float(p.get("confidence", 0.0))
        name = str(p.get("name", ""))
        category = str(p.get("category", ""))
        priority = str(p.get("priority", "medium"))

        if session_name == "Asia" and any(token in name for token in ("Liquidity Sweep", "Stop-Run", "Fakey", "Hikkake")):
            confidence += 0.08
        if session_name == "Asia" and any(token in name for token in ("Breakout", "Flag", "Pennant")):
            confidence -= 0.08
        if session_name in ("London", "London/NY overlap", "NY") and any(token in name for token in ("Breakout", "Flag", "Pennant", "Marubozu")):
            confidence += 0.07
        if "Psych Level" in name or "Order Block" in name or "Fair Value Gap" in name:
            confidence += 0.04
        if priority == "avoid":
            confidence = min(confidence, 0.40)

        p["confidence"] = round(max(0.0, min(1.0, confidence)), 2)
        p["session"] = session_name
        p["dxy_bias"] = dxy_bias
        adjusted.append(p)
    return adjusted


def _boost_generic_gold_patterns(patterns: Iterable[Pattern]) -> List[Pattern]:
    high_names = (
        "Double Top",
        "Double Bottom",
        "Head and Shoulders",
        "Inverse Head and Shoulders",
        "Bullish Flag",
        "Bearish Flag",
        "Symmetrical Triangle",
        "Falling Wedge",
        "Rising Wedge",
    )
    boosted: List[Pattern] = []
    for pattern in patterns:
        p = dict(pattern)
        name = str(p.get("name", ""))
        if any(key in name for key in high_names):
            p["priority"] = "high"
            p["confidence"] = round(min(1.0, float(p.get("confidence", 0.0)) + 0.06), 2)
        if p.get("category") == "harmonic":
            p["priority"] = "medium"
            p["reason"] = f"{p.get('reason')} Gold harmonic patterns require London/NY or strong key-level confirmation."
        boosted.append(p)
    return boosted


def _xau_hammer(candle) -> bool:
    return (
        candle.body_ratio <= 0.34
        and candle.lower >= max(candle.body * 3.0, candle.range * 0.55)
        and candle.upper <= candle.range * 0.22
    )


def _xau_shooting_shape(candle) -> bool:
    return (
        candle.body_ratio <= 0.34
        and candle.upper >= max(candle.body * 3.0, candle.range * 0.55)
        and candle.lower <= candle.range * 0.22
    )


def _xau_tolerance(df: pd.DataFrame) -> float:
    atr = float(_atr(df).iloc[-1]) if len(df) >= 2 else 2.0
    return max(1.2, atr * 0.20)


def _volume_spike(df: pd.DataFrame, lookback: int = 14, multiplier: float = 1.2) -> bool:
    volume_col = "volume" if "volume" in df.columns else "tick_volume" if "tick_volume" in df.columns else None
    if volume_col is None or len(df) < lookback + 1:
        return False
    volume = pd.to_numeric(df[volume_col], errors="coerce").fillna(0)
    avg = float(volume.iloc[-lookback - 1 : -1].mean())
    return avg > 0 and float(volume.iloc[-1]) >= avg * multiplier


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
    return 100 - (100 / (1 + rs))


def _ma_context(df: pd.DataFrame) -> Dict[str, float]:
    if len(df) < 100:
        return {}
    close = df["close"].astype(float)
    return {
        "ema13": float(close.ewm(span=13, adjust=False).mean().iloc[-1]),
        "ema21": float(close.ewm(span=21, adjust=False).mean().iloc[-1]),
        "ema75": float(close.ewm(span=75, adjust=False).mean().iloc[-1]),
        "ema100": float(close.ewm(span=100, adjust=False).mean().iloc[-1]),
    }


def _nearest_psych_level(price: Optional[float], step: float) -> Optional[float]:
    if price is None:
        return None
    return round(price / step) * step


def _is_near_psych_level(price: float, df: pd.DataFrame) -> bool:
    tol = _xau_tolerance(df)
    return any(
        level is not None and abs(price - level) <= tol
        for level in (_nearest_psych_level(price, 50.0), _nearest_psych_level(price, 100.0))
    )


def _near_recent_level(df: pd.DataFrame) -> bool:
    if len(df) < 22:
        return False
    close = float(df["close"].iloc[-1])
    recent = df.iloc[-21:-1]
    support = float(recent["low"].min())
    resistance = float(recent["high"].max())
    tol = _xau_tolerance(df)
    return abs(close - support) <= tol or abs(close - resistance) <= tol


def _latest_price(mdf: Dict[str, pd.DataFrame]) -> Optional[float]:
    for timeframe in ("M5", "M15", "H1", "H4"):
        df = _clean_ohlc(mdf.get(timeframe))
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])
    return None


def _latest_time(mdf: Dict[str, pd.DataFrame]) -> Optional[datetime]:
    for timeframe in ("M5", "M15", "H1", "H4"):
        df = mdf.get(timeframe)
        if df is None or df.empty or "time" not in df.columns:
            continue
        value = pd.to_datetime(df["time"].iloc[-1], errors="coerce")
        if pd.notna(value):
            return value.to_pydatetime()
    return None
