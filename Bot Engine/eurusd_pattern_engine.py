"""
eurusd_pattern_engine.py - EURUSD pattern detection helpers.

The project currently keeps strategy code in a single strategy.py module, so this
file acts as a lightweight pattern engine without introducing a conflicting
strategy/ package. All detectors are heuristic and dependency-light: pandas and
numpy only, no TA-Lib required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


Pattern = Dict[str, object]
PIP_SIZE = 0.0001


@dataclass(frozen=True)
class Candle:
    open: float
    high: float
    low: float
    close: float
    body: float
    range: float
    upper: float
    lower: float
    direction: str

    @property
    def body_ratio(self) -> float:
        return self.body / self.range if self.range else 0.0


def scan_eurusd_patterns(
    mdf: Dict[str, pd.DataFrame],
    symbol: str = "EURUSD",
    max_patterns: int = 18,
) -> List[Pattern]:
    """
    Scan EURUSD multi-timeframe data and return active pattern confluence.

    The returned list is serializable and intentionally compact so it can be
    added directly to the AI prompt.
    """
    if "EURUSD" not in symbol.upper():
        return []

    results: List[Pattern] = []
    tf_weights = {
        "H4": 1.00,
        "H1": 0.95,
        "M15": 0.90,
        "M5": 0.82,
    }

    for timeframe in ("H4", "H1", "M15", "M5"):
        df = _clean_ohlc(mdf.get(timeframe))
        if df is None or len(df) < 8:
            continue

        weight = tf_weights[timeframe]
        results.extend(_detect_candlestick_patterns(df, timeframe, weight))
        results.extend(_detect_price_action_patterns(df, timeframe, weight))
        results.extend(_detect_additional_concepts(df, timeframe, weight))

        if len(df) >= 30:
            results.extend(_detect_chart_patterns(df, timeframe, weight))
        if len(df) >= 40:
            results.extend(_detect_harmonic_patterns(df, timeframe, weight))

    return _rank_patterns(_dedupe_patterns(results), max_patterns=max_patterns)


def summarize_pattern_bias(patterns: Sequence[Pattern], mdf: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, object]:
    """Return a compact bullish/bearish/neutral score summary."""
    bullish = 0.0
    bearish = 0.0
    neutral = 0.0
    high_priority = []
    
    session_info = {"name": "unknown", "profile": ""}
    if mdf:
        from session_filter import detect_session
        session_info = detect_session(mdf, "EURUSD")

    for pattern in patterns:
        confidence = float(pattern.get("confidence", 0.0))
        direction = str(pattern.get("direction", "neutral")).lower()
        priority = str(pattern.get("priority", "medium")).lower()
        weight = 1.2 if priority == "high" else 0.85 if priority == "lower" else 1.0

        if direction == "bullish":
            bullish += confidence * weight
        elif direction == "bearish":
            bearish += confidence * weight
        else:
            neutral += confidence * 0.5

        if priority == "high":
            high_priority.append(pattern.get("name", ""))

    net = bullish - bearish
    if abs(net) < 0.35:
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
        "session": session_info.get("name"),
        "session_profile": session_info.get("profile"),
    }


# ---------------------------------------------------------------------------
# Candlestick patterns
# ---------------------------------------------------------------------------


def _detect_candlestick_patterns(df: pd.DataFrame, timeframe: str, tf_weight: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    c2 = _candle(df, -3)
    c3 = _candle(df, -4) if len(df) >= 4 else None
    c4 = _candle(df, -5) if len(df) >= 5 else None

    if c0 is None or c1 is None or c2 is None:
        return patterns

    trend = _trend(df.iloc[:-1])
    tol = _price_tolerance(df)
    avg_body = _avg_body(df)
    long_body = c0.body >= avg_body * 1.15
    small_body = c0.body_ratio <= 0.35
    doji = _is_doji(c0)
    hammer_shape = _is_hammer_shape(c0)
    inverted_shape = _is_inverted_hammer_shape(c0)

    # Single candle patterns.
    if doji:
        patterns.append(_pattern("Doji", "neutral", "neutral", "candlestick", 0.58, timeframe, "Open and close are nearly equal."))
        if c0.lower >= c0.range * 0.62 and c0.upper <= c0.range * 0.12:
            patterns.append(_pattern("Dragonfly Doji", "bullish reversal", "bullish", "candlestick", 0.68, timeframe, "Long lower wick doji shows rejection below."))
        if c0.upper >= c0.range * 0.62 and c0.lower <= c0.range * 0.12:
            patterns.append(_pattern("Gravestone Doji", "bearish reversal", "bearish", "candlestick", 0.68, timeframe, "Long upper wick doji shows rejection above."))
        if c0.upper >= c0.range * 0.32 and c0.lower >= c0.range * 0.32:
            patterns.append(_pattern("Long-Legged Doji", "neutral", "neutral", "candlestick", 0.60, timeframe, "Long shadows show high indecision."))
        if trend == "down" and c0.lower > c0.upper * 1.3:
            patterns.append(_pattern("Southern Doji", "bullish reversal", "bullish", "candlestick", 0.62, timeframe, "Doji after a decline with stronger lower rejection."))
        if trend == "up" and c0.upper > c0.lower * 1.3:
            patterns.append(_pattern("Northern Doji", "bearish reversal", "bearish", "candlestick", 0.62, timeframe, "Doji after a rise with stronger upper rejection."))

    if hammer_shape:
        if trend == "down":
            patterns.append(_pattern("Hammer", "bullish reversal", "bullish", "candlestick", 0.74, timeframe, "Long lower wick after downtrend."))
        if trend == "up":
            patterns.append(_pattern("Hanging Man", "bearish reversal", "bearish", "candlestick", 0.67, timeframe, "Hammer shape after uptrend."))

    if inverted_shape:
        if trend == "down":
            patterns.append(_pattern("Inverted Hammer", "bullish reversal", "bullish", "candlestick", 0.67, timeframe, "Long upper wick after downtrend."))
        if trend == "up":
            patterns.append(_pattern("Shooting Star", "bearish reversal", "bearish", "candlestick", 0.74, timeframe, "Long upper wick after uptrend."))

    if _is_marubozu(c0):
        if c0.direction == "bullish":
            patterns.append(_pattern("Bullish Marubozu", "bullish continuation", "bullish", "candlestick", 0.70, timeframe, "Strong bullish body with minimal shadows."))
        elif c0.direction == "bearish":
            patterns.append(_pattern("Bearish Marubozu", "bearish continuation", "bearish", "candlestick", 0.70, timeframe, "Strong bearish body with minimal shadows."))

    if small_body and c0.upper >= c0.body * 0.8 and c0.lower >= c0.body * 0.8:
        patterns.append(_pattern("Spinning Top", "neutral", "neutral", "candlestick", 0.56, timeframe, "Small body with balanced upper and lower shadows."))

    if c0.body_ratio <= 0.25 and c0.upper >= avg_body * 1.1 and c0.lower >= avg_body * 1.1:
        patterns.append(_pattern("High Wave", "neutral", "neutral", "candlestick", 0.58, timeframe, "Small body with very large shadows."))

    if long_body and c0.direction == "bullish" and _near(c0.open, c0.low, tol) and c0.close >= c0.high - tol:
        patterns.append(_pattern("Bullish Belt-Hold Line", "bullish reversal", "bullish", "candlestick", 0.66, timeframe, "Bullish candle opens near low and closes near high."))
    if long_body and c0.direction == "bearish" and _near(c0.open, c0.high, tol) and c0.close <= c0.low + tol:
        patterns.append(_pattern("Bearish Belt-Hold Line", "bearish reversal", "bearish", "candlestick", 0.66, timeframe, "Bearish candle opens near high and closes near low."))

    # Double candle patterns.
    if _bullish_engulfing(c1, c0):
        patterns.append(_pattern("Bullish Engulfing", "bullish reversal", "bullish", "candlestick", 0.84, timeframe, "Bullish body engulfs previous bearish body.", priority="high"))
    if _bearish_engulfing(c1, c0):
        patterns.append(_pattern("Bearish Engulfing", "bearish reversal", "bearish", "candlestick", 0.84, timeframe, "Bearish body engulfs previous bullish body.", priority="high"))

    if c1.direction == "bearish" and c0.direction == "bullish" and _body_inside(c0, c1):
        patterns.append(_pattern("Bullish Harami", "bullish reversal", "bullish", "candlestick", 0.68, timeframe, "Small bullish body inside prior bearish body."))
    if c1.direction == "bullish" and c0.direction == "bearish" and _body_inside(c0, c1):
        patterns.append(_pattern("Bearish Harami", "bearish reversal", "bearish", "candlestick", 0.68, timeframe, "Small bearish body inside prior bullish body."))
    if c1.direction == "bearish" and _is_doji(c0) and _body_inside(c0, c1):
        patterns.append(_pattern("Bullish Harami Cross", "bullish reversal", "bullish", "candlestick", 0.70, timeframe, "Doji inside prior bearish body."))
    if c1.direction == "bullish" and _is_doji(c0) and _body_inside(c0, c1):
        patterns.append(_pattern("Bearish Harami Cross", "bearish reversal", "bearish", "candlestick", 0.70, timeframe, "Doji inside prior bullish body."))

    c1_mid = (c1.open + c1.close) / 2
    if c1.direction == "bearish" and c0.direction == "bullish" and c0.open < c1.low and c0.close > c1_mid:
        patterns.append(_pattern("Piercing Line", "bullish reversal", "bullish", "candlestick", 0.76, timeframe, "Bullish candle closes beyond midpoint of prior bearish candle."))
    if c1.direction == "bullish" and c0.direction == "bearish" and c0.open > c1.high and c0.close < c1_mid:
        patterns.append(_pattern("Dark Cloud Cover", "bearish reversal", "bearish", "candlestick", 0.76, timeframe, "Bearish candle closes beyond midpoint of prior bullish candle."))

    if c1.direction == "bearish" and c0.direction == "bullish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Bullish Counterattack", "bullish reversal", "bullish", "candlestick", 0.62, timeframe, "Opposite candles close near the same level."))
    if c1.direction == "bullish" and c0.direction == "bearish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Bearish Counterattack", "bearish reversal", "bearish", "candlestick", 0.62, timeframe, "Opposite candles close near the same level."))

    if _is_marubozu(c1) and _is_marubozu(c0) and c1.direction == "bearish" and c0.direction == "bullish" and c0.open > c1.open:
        patterns.append(_pattern("Bullish Kicking", "bullish reversal", "bullish", "candlestick", 0.72, timeframe, "Bearish marubozu followed by bullish marubozu gap up."))
    if _is_marubozu(c1) and _is_marubozu(c0) and c1.direction == "bullish" and c0.direction == "bearish" and c0.open < c1.open:
        patterns.append(_pattern("Bearish Kicking", "bearish reversal", "bearish", "candlestick", 0.72, timeframe, "Bullish marubozu followed by bearish marubozu gap down."))

    if c1.direction == "bearish" and c0.direction == "bearish" and _body_inside(c0, c1):
        patterns.append(_pattern("Homing Pigeon", "bullish reversal", "bullish", "candlestick", 0.58, timeframe, "Smaller bearish body contained inside prior bearish body."))
    if c1.direction == "bearish" and c0.direction == "bearish" and _near(c0.close, c1.close, tol):
        patterns.append(_pattern("Matching Low", "bullish reversal", "bullish", "candlestick", 0.58, timeframe, "Two bearish closes are nearly equal."))

    if c1.direction == "bearish" and c0.direction == "bullish" and _near(c0.close, c1.low, tol):
        patterns.append(_pattern("On-Neck", "bullish continuation", "bullish", "candlestick", 0.55, timeframe, "Bullish close near prior bearish low."))
    if c1.direction == "bearish" and c0.direction == "bullish" and c0.close < c1.close and c0.close > c1.low:
        patterns.append(_pattern("In-Neck", "bullish continuation", "bullish", "candlestick", 0.55, timeframe, "Bullish close slightly below prior bearish close."))
    if c1.direction == "bearish" and c0.direction == "bullish" and c0.close < c1_mid and c0.close > c1.close:
        patterns.append(_pattern("Thrusting", "bullish continuation", "bullish", "candlestick", 0.56, timeframe, "Bullish candle closes inside prior body but below midpoint."))

    if c1.direction == "bearish" and c0.direction == "bullish" and _near(c0.open, c1.open, tol):
        patterns.append(_pattern("Bullish Separating Lines", "bullish continuation", "bullish", "candlestick", 0.60, timeframe, "Bullish candle opens near prior bearish open."))
    if c1.direction == "bullish" and c0.direction == "bearish" and _near(c0.open, c1.open, tol):
        patterns.append(_pattern("Bearish Separating Lines", "bearish continuation", "bearish", "candlestick", 0.60, timeframe, "Bearish candle opens near prior bullish open."))

    if _near(c1.high, c0.high, tol):
        patterns.append(_pattern("Tweezer Top", "bearish reversal", "bearish", "candlestick", 0.69, timeframe, "Two adjacent highs reject the same level.", priority="high"))
    if _near(c1.low, c0.low, tol):
        patterns.append(_pattern("Tweezer Bottom", "bullish reversal", "bullish", "candlestick", 0.69, timeframe, "Two adjacent lows reject the same level.", priority="high"))

    # Triple and complex candle patterns.
    if _morning_star(c2, c1, c0):
        patterns.append(_pattern("Morning Star", "bullish reversal", "bullish", "candlestick", 0.80, timeframe, "Bearish candle, small middle candle, bullish recovery.", priority="medium"))
    if _evening_star(c2, c1, c0):
        patterns.append(_pattern("Evening Star", "bearish reversal", "bearish", "candlestick", 0.80, timeframe, "Bullish candle, small middle candle, bearish rejection.", priority="medium"))
    if _morning_star(c2, c1, c0) and _is_doji(c1):
        patterns.append(_pattern("Morning Doji Star", "bullish reversal", "bullish", "candlestick", 0.82, timeframe, "Morning star with doji as the middle candle."))
    if _evening_star(c2, c1, c0) and _is_doji(c1):
        patterns.append(_pattern("Evening Doji Star", "bearish reversal", "bearish", "candlestick", 0.82, timeframe, "Evening star with doji as the middle candle."))
    if _is_doji(c1) and c1.low < c2.low and c1.low < c0.low and c0.direction == "bullish":
        patterns.append(_pattern("Abandoned Baby Bottom", "bullish reversal", "bullish", "candlestick", 0.70, timeframe, "Doji isolated below adjacent candles."))
    if _is_doji(c1) and c1.high > c2.high and c1.high > c0.high and c0.direction == "bearish":
        patterns.append(_pattern("Abandoned Baby Top", "bearish reversal", "bearish", "candlestick", 0.70, timeframe, "Doji isolated above adjacent candles."))

    if _three_white_soldiers(c2, c1, c0, avg_body):
        patterns.append(_pattern("Three White Soldiers", "bullish reversal", "bullish", "candlestick", 0.80, timeframe, "Three strong bullish candles close progressively higher."))
    if _three_black_crows(c2, c1, c0, avg_body):
        patterns.append(_pattern("Three Black Crows", "bearish reversal", "bearish", "candlestick", 0.80, timeframe, "Three strong bearish candles close progressively lower."))

    if c2.direction == "bearish" and c1.direction == "bullish" and _body_inside(c1, c2) and c0.close > c2.high:
        patterns.append(_pattern("Three Inside Up", "bullish reversal", "bullish", "candlestick", 0.74, timeframe, "Bullish harami confirmed by breakout."))
    if c2.direction == "bullish" and c1.direction == "bearish" and _body_inside(c1, c2) and c0.close < c2.low:
        patterns.append(_pattern("Three Inside Down", "bearish reversal", "bearish", "candlestick", 0.74, timeframe, "Bearish harami confirmed by breakdown."))
    if _bullish_engulfing(c2, c1) and c0.direction == "bullish" and c0.close > c1.close:
        patterns.append(_pattern("Three Outside Up", "bullish reversal", "bullish", "candlestick", 0.76, timeframe, "Bullish engulfing confirmed by a higher close."))
    if _bearish_engulfing(c2, c1) and c0.direction == "bearish" and c0.close < c1.close:
        patterns.append(_pattern("Three Outside Down", "bearish reversal", "bearish", "candlestick", 0.76, timeframe, "Bearish engulfing confirmed by a lower close."))

    if c4 and c3 and _rising_three_methods(c4, c3, c2, c1, c0):
        patterns.append(_pattern("Rising Three Methods", "bullish continuation", "bullish", "candlestick", 0.72, timeframe, "Bullish impulse, three small pullback bars, continuation close."))
    if c4 and c3 and _falling_three_methods(c4, c3, c2, c1, c0):
        patterns.append(_pattern("Falling Three Methods", "bearish continuation", "bearish", "candlestick", 0.72, timeframe, "Bearish impulse, three small pullback bars, continuation close."))
    if c3 and _three_line_strike_bullish(c3, c2, c1, c0):
        patterns.append(_pattern("Bullish Three-Line Strike", "bullish continuation", "bullish", "candlestick", 0.64, timeframe, "Three bullish candles followed by a large bearish strike."))
    if c3 and _three_line_strike_bearish(c3, c2, c1, c0):
        patterns.append(_pattern("Bearish Three-Line Strike", "bearish continuation", "bearish", "candlestick", 0.64, timeframe, "Three bearish candles followed by a large bullish strike."))
    if c2.high < c1.low and c0.direction == "bearish" and c0.close > c2.high and c0.close < c1.close:
        patterns.append(_pattern("Upside Gap Three Methods", "bullish continuation", "bullish", "candlestick", 0.58, timeframe, "Upside gap is partly filled without full breakdown."))
    if c2.low > c1.high and c0.direction == "bullish" and c0.close < c2.low and c0.close > c1.close:
        patterns.append(_pattern("Downside Gap Three Methods", "bearish continuation", "bearish", "candlestick", 0.58, timeframe, "Downside gap is partly filled without full breakout."))
    if c2.direction == "bullish" and c1.low > c2.high and c0.direction == "bearish" and c0.close > c2.high:
        patterns.append(_pattern("Upward Gapping Tasuki", "bullish continuation", "bullish", "candlestick", 0.58, timeframe, "Bearish pullback remains above upside gap."))
    if c2.direction == "bearish" and c1.high < c2.low and c0.direction == "bullish" and c0.close < c2.low:
        patterns.append(_pattern("Downward Gapping Tasuki", "bearish continuation", "bearish", "candlestick", 0.58, timeframe, "Bullish pullback remains below downside gap."))
    if c3 and c2 and c1 and c0 and all(c.direction == "bearish" for c in (c3, c2, c1)) and c0.direction == "bullish" and c0.close > c1.open:
        patterns.append(_pattern("Concealing Baby Swallow", "bullish reversal", "bullish", "candlestick", 0.55, timeframe, "Cluster of bearish candles followed by bullish engulfing pressure."))
    if c3 and _breakaway_bullish(c3, c2, c1, c0):
        patterns.append(_pattern("Bullish Breakaway", "bullish reversal", "bullish", "candlestick", 0.60, timeframe, "Downside sequence loses momentum and reverses."))
    if c3 and _breakaway_bearish(c3, c2, c1, c0):
        patterns.append(_pattern("Bearish Breakaway", "bearish reversal", "bearish", "candlestick", 0.60, timeframe, "Upside sequence loses momentum and reverses."))
    if c2.direction == "bullish" and c1.direction == "bullish" and c0.direction == "bullish" and c2.body > c1.body > c0.body and c2.upper < c1.upper < c0.upper:
        patterns.append(_pattern("Advance Block", "neutral", "bearish", "candlestick", 0.60, timeframe, "Bullish advance is weakening with longer upper wicks."))
    if c2.direction == "bearish" and c1.direction == "bullish" and c0.direction == "bearish" and _near(c2.close, c0.close, tol):
        patterns.append(_pattern("Stick Sandwich", "bullish reversal", "bullish", "candlestick", 0.58, timeframe, "Bearish closes match around a bullish middle candle."))

    return patterns


# ---------------------------------------------------------------------------
# Price action patterns
# ---------------------------------------------------------------------------


def _detect_price_action_patterns(df: pd.DataFrame, timeframe: str, tf_weight: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    c2 = _candle(df, -3)
    c3 = _candle(df, -4) if len(df) >= 4 else None

    if c0 is None or c1 is None or c2 is None:
        return patterns

    # EURUSD Pin bars need 2:1 ratio
    is_pin_bullish = c0.lower >= c0.body * 2 and c0.upper <= c0.body * 0.5
    is_pin_bearish = c0.upper >= c0.body * 2 and c0.lower <= c0.body * 0.5

    if is_pin_bullish:
        patterns.append(_pattern("Pin Bar Bullish", "reversal", "bullish", "price_action", 0.78, timeframe, "Lower wick is at least twice the candle body (EURUSD 2:1 ratio).", priority="high"))
    if is_pin_bearish:
        patterns.append(_pattern("Pin Bar Bearish", "reversal", "bearish", "price_action", 0.78, timeframe, "Upper wick is at least twice the candle body (EURUSD 2:1 ratio).", priority="high"))

    if c0.high <= c1.high and c0.low >= c1.low:
        patterns.append(_pattern("Inside Bar", "continuation/reversal", "neutral", "price_action", 0.70, timeframe, "Current range sits inside previous candle.", priority="high"))
    if c0.high > c1.high and c0.low < c1.low:
        direction = "bullish" if c0.close > c0.open else "bearish" if c0.close < c0.open else "neutral"
        patterns.append(_pattern("Outside Bar", "reversal", direction, "price_action", 0.72, timeframe, "Current range fully expands beyond previous candle."))

    if c3 and c2.high <= c3.high and c2.low >= c3.low:
        if c1.low < c2.low and c0.close > c2.high:
            patterns.append(_pattern("Fakey Bullish", "reversal", "bullish", "price_action", 0.76, timeframe, "Inside bar breaks down then reverses above mother bar.", priority="high"))
            patterns.append(_pattern("Hikkake Bullish", "reversal", "bullish", "price_action", 0.74, timeframe, "False downside break of inside bar reverses upward."))
        if c1.high > c2.high and c0.close < c2.low:
            patterns.append(_pattern("Fakey Bearish", "reversal", "bearish", "price_action", 0.76, timeframe, "Inside bar breaks up then reverses below mother bar.", priority="high"))
            patterns.append(_pattern("Hikkake Bearish", "reversal", "bearish", "price_action", 0.74, timeframe, "False upside break of inside bar reverses downward."))

    if c2.direction == "bearish" and c1.high <= c2.high and c1.low >= c2.low and c0.direction == "bullish" and c0.close > c2.high:
        patterns.append(_pattern("Three Bar Reversal Bullish", "reversal", "bullish", "price_action", 0.74, timeframe, "Bearish bar, inside bar, bullish breakout."))
    if c2.direction == "bullish" and c1.high <= c2.high and c1.low >= c2.low and c0.direction == "bearish" and c0.close < c2.low:
        patterns.append(_pattern("Three Bar Reversal Bearish", "reversal", "bearish", "price_action", 0.74, timeframe, "Bullish bar, inside bar, bearish breakdown."))

    if _is_hammer_shape(c1) and c0.high <= c1.high and c0.low >= c1.low:
        patterns.append(_pattern("Pin Bar + Inside Bar Combo", "reversal/continuation", "bullish", "price_action", 0.72, timeframe, "Inside bar forms after bullish pin bar rejection."))
    if _is_inverted_hammer_shape(c1) and c0.high <= c1.high and c0.low >= c1.low:
        patterns.append(_pattern("Pin Bar + Inside Bar Combo Bearish", "reversal/continuation", "bearish", "price_action", 0.72, timeframe, "Inside bar forms after bearish pin bar rejection."))
    if (_is_hammer_shape(c0) or _is_inverted_hammer_shape(c0)) and c0.high <= c1.high and c0.low >= c1.low:
        direction = "bullish" if _is_hammer_shape(c0) else "bearish"
        patterns.append(_pattern("Inside Pin Bar Combo", "reversal/continuation", direction, "price_action", 0.72, timeframe, "Pin bar also sits inside previous candle."))

    if c0.direction == "bullish" and c0.upper <= c0.range * 0.08:
        patterns.append(_pattern("Shaved Bar Bullish", "continuation", "bullish", "price_action", 0.62, timeframe, "Bullish close has almost no upper wick."))
    if c0.direction == "bearish" and c0.lower <= c0.range * 0.08:
        patterns.append(_pattern("Shaved Bar Bearish", "continuation", "bearish", "price_action", 0.62, timeframe, "Bearish close has almost no lower wick."))

    if _bullish_engulfing(c1, c0) or (c0.direction == "bullish" and c0.high > c1.high and c0.low < c1.low):
        patterns.append(_pattern("Engulfing Bar Bullish", "reversal", "bullish", "price_action", 0.78, timeframe, "Bullish candle engulfs body or range.", priority="high"))
    if _bearish_engulfing(c1, c0) or (c0.direction == "bearish" and c0.high > c1.high and c0.low < c1.low):
        patterns.append(_pattern("Engulfing Bar Bearish", "reversal", "bearish", "price_action", 0.78, timeframe, "Bearish candle engulfs body or range.", priority="high"))

    if c1.direction == "bearish" and c0.direction == "bullish" and c0.close > c1.open:
        patterns.append(_pattern("2-Bar Reversal Bullish", "reversal", "bullish", "price_action", 0.72, timeframe, "Bullish candle closes above previous bearish open."))
    if c1.direction == "bullish" and c0.direction == "bearish" and c0.close < c1.open:
        patterns.append(_pattern("2-Bar Reversal Bearish", "reversal", "bearish", "price_action", 0.72, timeframe, "Bearish candle closes below previous bullish open."))

    return patterns


# ---------------------------------------------------------------------------
# Classical chart patterns
# ---------------------------------------------------------------------------


def _detect_chart_patterns(df: pd.DataFrame, timeframe: str, tf_weight: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    pivots = _pivots(df.tail(90), left=2, right=2)
    if len(pivots) < 3:
        return patterns

    close = float(df["close"].iloc[-1])
    tol = max(_price_tolerance(df) * 2.0, _atr(df).iloc[-1] * 0.18)

    patterns.extend(_detect_double_triple_patterns(pivots, close, tol, timeframe))
    patterns.extend(_detect_head_shoulders(pivots, close, tol, timeframe))
    patterns.extend(_detect_triangle_wedge_rectangle(df, pivots, timeframe))
    patterns.extend(_detect_flag_pennant_measured(df, pivots, timeframe))
    patterns.extend(_detect_rounding_patterns(df, timeframe))

    c0 = _candle(df, -1)
    c1 = _candle(df, -2)
    if c0 and c1:
        if _near(c0.low, c1.low, tol):
            patterns.append(_pattern("Pipe Bottom", "bullish reversal", "bullish", "chart", 0.62, timeframe, "Two adjacent lows form a pipe bottom."))
        if _near(c0.high, c1.high, tol):
            patterns.append(_pattern("Pipe Top", "bearish reversal", "bearish", "chart", 0.62, timeframe, "Two adjacent highs form a pipe top."))
        if c1.lower > c1.body * 2 and c0.direction == "bullish" and c0.close > c1.open:
            patterns.append(_pattern("Horn Bottom", "bullish reversal", "bullish", "chart", 0.62, timeframe, "Spike lower wick followed by strong bullish reversal."))
        if c1.upper > c1.body * 2 and c0.direction == "bearish" and c0.close < c1.open:
            patterns.append(_pattern("Horn Top", "bearish reversal", "bearish", "chart", 0.62, timeframe, "Spike upper wick followed by strong bearish reversal."))

    gap = _gap_direction(df)
    prev_gap = _gap_direction(df.iloc[:-1]) if len(df) > 3 else None
    if prev_gap == "up" and gap == "down":
        patterns.append(_pattern("Island Reversal Top", "bearish reversal", "bearish", "chart", 0.58, timeframe, "Gap up followed by gap down."))
    if prev_gap == "down" and gap == "up":
        patterns.append(_pattern("Island Reversal Bottom", "bullish reversal", "bullish", "chart", 0.58, timeframe, "Gap down followed by gap up."))

    return patterns


def _detect_double_triple_patterns(
    pivots: Sequence[Tuple[int, str, float]],
    close: float,
    tol: float,
    timeframe: str,
) -> List[Pattern]:
    patterns: List[Pattern] = []
    last = list(pivots)[-7:]

    for window in (last[-3:],):
        if len(window) == 3:
            p0, p1, p2 = window
            if p0[1] == "H" and p1[1] == "L" and p2[1] == "H" and _near(p0[2], p2[2], tol):
                confirmed = close < p1[2]
                patterns.append(_pattern("Double Top", "bearish reversal", "bearish", "chart", 0.78 if confirmed else 0.68, timeframe, "Two similar highs with neckline support.", priority="high"))
            if p0[1] == "L" and p1[1] == "H" and p2[1] == "L" and _near(p0[2], p2[2], tol):
                confirmed = close > p1[2]
                patterns.append(_pattern("Double Bottom", "bullish reversal", "bullish", "chart", 0.78 if confirmed else 0.68, timeframe, "Two similar lows with neckline resistance.", priority="high"))

    if len(last) >= 5:
        p = last[-5:]
        if [x[1] for x in p] == ["H", "L", "H", "L", "H"] and max(p[0][2], p[2][2], p[4][2]) - min(p[0][2], p[2][2], p[4][2]) <= tol * 1.5:
            patterns.append(_pattern("Triple Top", "bearish reversal", "bearish", "chart", 0.72, timeframe, "Three highs reject the same resistance area."))
        if [x[1] for x in p] == ["L", "H", "L", "H", "L"] and max(p[0][2], p[2][2], p[4][2]) - min(p[0][2], p[2][2], p[4][2]) <= tol * 1.5:
            patterns.append(_pattern("Triple Bottom", "bullish reversal", "bullish", "chart", 0.72, timeframe, "Three lows reject the same support area."))

    return patterns


def _detect_head_shoulders(
    pivots: Sequence[Tuple[int, str, float]],
    close: float,
    tol: float,
    timeframe: str,
) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(pivots) < 5:
        return patterns

    p = list(pivots)[-5:]
    types = [x[1] for x in p]

    if types == ["H", "L", "H", "L", "H"]:
        ls, nl1, head, nl2, rs = p
        neckline = (nl1[2] + nl2[2]) / 2
        if head[2] > ls[2] + tol and head[2] > rs[2] + tol and _near(ls[2], rs[2], tol * 2.0):
            confirmed = close < neckline
            patterns.append(_pattern("Head and Shoulders", "bearish reversal", "bearish", "chart", 0.82 if confirmed else 0.70, timeframe, "Three peaks with a higher head and neckline support.", priority="high"))

    if types == ["L", "H", "L", "H", "L"]:
        ls, nl1, head, nl2, rs = p
        neckline = (nl1[2] + nl2[2]) / 2
        if head[2] < ls[2] - tol and head[2] < rs[2] - tol and _near(ls[2], rs[2], tol * 2.0):
            confirmed = close > neckline
            patterns.append(_pattern("Inverse Head and Shoulders", "bullish reversal", "bullish", "chart", 0.82 if confirmed else 0.70, timeframe, "Three troughs with a lower head and neckline resistance.", priority="high"))

    return patterns


def _detect_triangle_wedge_rectangle(
    df: pd.DataFrame,
    pivots: Sequence[Tuple[int, str, float]],
    timeframe: str,
) -> List[Pattern]:
    patterns: List[Pattern] = []
    highs = [(i, p) for i, t, p in pivots if t == "H"][-5:]
    lows = [(i, p) for i, t, p in pivots if t == "L"][-5:]
    if len(highs) < 2 or len(lows) < 2:
        return patterns

    high_slope = _slope(highs)
    low_slope = _slope(lows)
    atr = max(float(_atr(df).iloc[-1]), PIP_SIZE)
    flat = atr * 0.03
    close = float(df["close"].iloc[-1])
    high_range = max(p for _, p in highs) - min(p for _, p in highs)
    low_range = max(p for _, p in lows) - min(p for _, p in lows)

    if abs(high_slope) <= flat and low_slope > flat:
        patterns.append(_pattern("Ascending Triangle", "bullish continuation", "bullish", "chart", 0.74, timeframe, "Flat resistance with rising support.", priority="high"))
    if abs(low_slope) <= flat and high_slope < -flat:
        patterns.append(_pattern("Descending Triangle", "bearish continuation", "bearish", "chart", 0.74, timeframe, "Flat support with falling resistance.", priority="high"))
    if high_slope < -flat and low_slope > flat:
        patterns.append(_pattern("Symmetrical Triangle", "bilateral", "neutral", "chart", 0.72, timeframe, "Converging lower highs and higher lows.", priority="high"))
    if high_slope > flat and low_slope < -flat:
        patterns.append(_pattern("Broadening Formation Megaphone", "bilateral", "neutral", "chart", 0.64, timeframe, "Higher highs and lower lows create a broadening structure."))
        patterns.append(_pattern("Expanding Triangle", "bilateral", "neutral", "chart", 0.62, timeframe, "Diverging highs and lows."))

    if high_range <= atr * 0.55 and low_range <= atr * 0.55:
        direction = "bullish" if close > np.mean([p for _, p in highs]) else "bearish" if close < np.mean([p for _, p in lows]) else "neutral"
        name = "Rectangle Bullish" if direction == "bullish" else "Rectangle Bearish" if direction == "bearish" else "Rectangle"
        patterns.append(_pattern(name, "continuation", direction, "chart", 0.66, timeframe, "Price is boxed between horizontal support and resistance."))

    converging = abs(high_slope - low_slope) > flat and (highs[-1][1] - lows[-1][1]) < (highs[0][1] - lows[0][1])
    diverging = (highs[-1][1] - lows[-1][1]) > (highs[0][1] - lows[0][1])

    if high_slope < -flat and low_slope < -flat and converging:
        patterns.append(_pattern("Falling Wedge", "bullish reversal", "bullish", "chart", 0.72, timeframe, "Downsloping converging trendlines.", priority="medium"))
    if high_slope > flat and low_slope > flat and converging:
        patterns.append(_pattern("Rising Wedge", "bearish reversal", "bearish", "chart", 0.72, timeframe, "Upsloping converging trendlines.", priority="medium"))
    if high_slope > flat and low_slope > flat and diverging:
        patterns.append(_pattern("Broadening Wedge Ascending", "bilateral", "bearish", "chart", 0.60, timeframe, "Ascending range is widening."))
    if high_slope < -flat and low_slope < -flat and diverging:
        patterns.append(_pattern("Broadening Wedge Descending", "bilateral", "bullish", "chart", 0.60, timeframe, "Descending range is widening."))

    if len(highs) >= 3 and len(lows) >= 3:
        first_spread = abs(highs[0][1] - lows[0][1])
        mid_spread = abs(highs[len(highs) // 2][1] - lows[len(lows) // 2][1])
        last_spread = abs(highs[-1][1] - lows[-1][1])
        if mid_spread > first_spread and last_spread < mid_spread:
            direction = "bearish" if close < np.mean([p for _, p in lows[-2:]]) else "bullish"
            patterns.append(_pattern("Diamond Top" if direction == "bearish" else "Diamond Bottom", "reversal", direction, "chart", 0.58, timeframe, "Broadening structure contracts into a diamond-like range."))

    return patterns


def _detect_flag_pennant_measured(
    df: pd.DataFrame,
    pivots: Sequence[Tuple[int, str, float]],
    timeframe: str,
) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 24:
        return patterns

    close = df["close"].astype(float)
    atr = max(float(_atr(df).iloc[-1]), PIP_SIZE)
    flagpole = close.iloc[-14] - close.iloc[-24]
    pullback = close.iloc[-1] - close.iloc[-8]
    consolidation_range = float(df["high"].iloc[-8:].max() - df["low"].iloc[-8:].min())

    if flagpole > atr * 2.0 and pullback < 0 and consolidation_range < abs(flagpole) * 0.55:
        patterns.append(_pattern("Bullish Flag", "bullish continuation", "bullish", "chart", 0.76, timeframe, "Strong impulse up followed by controlled downward channel.", priority="high"))
    if flagpole < -atr * 2.0 and pullback > 0 and consolidation_range < abs(flagpole) * 0.55:
        patterns.append(_pattern("Bearish Flag", "bearish continuation", "bearish", "chart", 0.76, timeframe, "Strong impulse down followed by controlled upward channel.", priority="high"))
    if abs(flagpole) > atr * 2.0 and consolidation_range < abs(flagpole) * 0.35:
        direction = "bullish" if flagpole > 0 else "bearish"
        patterns.append(_pattern("Bullish Pennant" if direction == "bullish" else "Bearish Pennant", "continuation", direction, "chart", 0.70, timeframe, "Strong impulse followed by tight contraction.", priority="high"))

    if len(pivots) >= 3:
        a, b, c = list(pivots)[-3:]
        leg1 = b[2] - a[2]
        leg2 = c[2] - b[2]
        if leg1 > 0 and leg2 < 0 and 0.30 <= abs(leg2 / leg1) <= 0.68:
            patterns.append(_pattern("Measured Move Up", "bullish continuation", "bullish", "chart", 0.62, timeframe, "Up leg followed by a controlled Fibonacci-style retracement."))
        if leg1 < 0 and leg2 > 0 and 0.30 <= abs(leg2 / leg1) <= 0.68:
            patterns.append(_pattern("Measured Move Down", "bearish continuation", "bearish", "chart", 0.62, timeframe, "Down leg followed by a controlled Fibonacci-style retracement."))

    if close.iloc[-24] - close.iloc[-14] > atr * 2 and close.iloc[-1] < close.iloc[-8]:
        patterns.append(_pattern("Dead-Cat Bounce", "bearish continuation", "bearish", "chart", 0.58, timeframe, "Sharp fall, weak bounce, renewed selling pressure."))
    if _cup_with_handle(df, bullish=True):
        patterns.append(_pattern("Cup with Handle", "bullish continuation", "bullish", "chart", 0.58, timeframe, "Rounded base with a smaller handle pullback."))
    if _cup_with_handle(df, bullish=False):
        patterns.append(_pattern("Inverted Cup with Handle", "bearish continuation", "bearish", "chart", 0.58, timeframe, "Rounded top with a smaller handle bounce."))

    return patterns


def _detect_rounding_patterns(df: pd.DataFrame, timeframe: str) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 35:
        return patterns

    close = df["close"].astype(float).iloc[-35:].to_numpy()
    x = np.arange(len(close))
    try:
        a, b, _ = np.polyfit(x, close, 2)
    except Exception:
        return patterns

    span = float(np.max(close) - np.min(close))
    if span <= PIP_SIZE * 5:
        return patterns

    if a > 0 and close[-1] > close[len(close) // 2]:
        patterns.append(_pattern("Rounding Bottom", "bullish reversal", "bullish", "chart", 0.56, timeframe, "Slow U-shaped recovery is visible."))
    if a < 0 and close[-1] < close[len(close) // 2]:
        patterns.append(_pattern("Rounding Top", "bearish reversal", "bearish", "chart", 0.56, timeframe, "Slow inverted U-shaped rollover is visible."))
    if a < 0 and close[-1] < np.polyval([a, b, close[0]], x[-1]):
        patterns.append(_pattern("Bump-and-Run Reversal Top", "bearish reversal", "bearish", "chart", 0.54, timeframe, "Acceleration above trend appears to be failing."))
    if a > 0 and close[-1] > np.polyval([a, b, close[0]], x[-1]):
        patterns.append(_pattern("Bump-and-Run Reversal Bottom", "bullish reversal", "bullish", "chart", 0.54, timeframe, "Acceleration below trend appears to be recovering."))
    return patterns


# ---------------------------------------------------------------------------
# Harmonic patterns
# ---------------------------------------------------------------------------


def _detect_harmonic_patterns(df: pd.DataFrame, timeframe: str, tf_weight: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    pivots = _pivots(df.tail(120), left=3, right=3)
    if len(pivots) < 4:
        return patterns

    last4 = list(pivots)[-4:]
    patterns.extend(_detect_abcd(last4, timeframe))

    if len(pivots) < 5:
        return patterns

    x, a, b, c, d = list(pivots)[-5:]
    types = [p[1] for p in (x, a, b, c, d)]
    if types not in (["L", "H", "L", "H", "L"], ["H", "L", "H", "L", "H"]):
        return patterns

    bullish = types == ["L", "H", "L", "H", "L"]
    direction = "bullish" if bullish else "bearish"
    xa = abs(a[2] - x[2])
    ab = abs(b[2] - a[2])
    bc = abs(c[2] - b[2])
    cd = abs(d[2] - c[2])
    if min(xa, ab, bc, cd) <= 0:
        return patterns

    ab_xa = ab / xa
    bc_ab = bc / ab
    cd_bc = cd / bc
    ad_xa = abs(a[2] - d[2]) / xa
    d_beyond_x = (bullish and d[2] < x[2]) or (not bullish and d[2] > x[2])
    xd_xa = abs(d[2] - x[2]) / xa

    def add(name: str, confidence: float, reason: str) -> None:
        patterns.append(_pattern(f"{name} {'Bullish' if bullish else 'Bearish'}", "harmonic reversal", direction, "harmonic", confidence, timeframe, reason, priority="medium"))

    if _between(ab_xa, 0.55, 0.72) and _between(bc_ab, 0.382, 0.886) and _between(cd_bc, 1.13, 1.75) and _between(ad_xa, 0.70, 0.88):
        add("Gartley", 0.66, "XA/AB/BC/CD ratios align with a Gartley reversal zone.")
    if _between(ab_xa, 0.35, 0.55) and _between(bc_ab, 0.382, 0.886) and _between(cd_bc, 1.50, 2.80) and _between(ad_xa, 0.80, 0.95):
        add("Bat", 0.64, "Deep D retracement and controlled AB retracement align with Bat.")
    if _between(ab_xa, 0.68, 0.88) and d_beyond_x and _between(xd_xa, 0.15, 0.45) and _between(cd_bc, 1.50, 2.90):
        add("Butterfly", 0.62, "D extends beyond X after a deep AB retracement.")
    if _between(ab_xa, 0.35, 0.65) and d_beyond_x and _between(xd_xa, 0.45, 0.90) and cd_bc >= 2.2:
        add("Crab", 0.60, "D extends beyond X with a strong CD extension.")
    if d_beyond_x and xd_xa >= 0.85 and cd_bc >= 2.4:
        add("Deep Crab", 0.58, "Very deep extension beyond X suggests a Deep Crab zone.")
    if _between(ab_xa, 0.35, 0.65) and _between(bc_ab, 1.05, 1.75) and _between(ad_xa, 0.65, 0.92):
        add("Shark", 0.57, "Extended BC leg with D returning into a reversal zone.")
    if _between(ab_xa, 0.35, 0.65) and _between(bc_ab, 1.20, 1.48) and _between(ad_xa, 0.70, 0.86):
        add("Cypher", 0.60, "BC extension and D retracement align with Cypher proportions.")
    if _between(abs(d[2] - c[2]) / abs(c[2] - b[2]), 0.45, 0.58) and _between(cd_bc, 0.45, 2.35):
        add("5-0", 0.54, "Final leg is near a 50 percent retracement of the prior move.")

    if len(pivots) >= 6:
        drives = list(pivots)[-6:]
        lows = [p for p in drives if p[1] == "L"]
        highs = [p for p in drives if p[1] == "H"]
        if len(lows) >= 3 and lows[-1][2] < lows[-2][2] < lows[-3][2]:
            patterns.append(_pattern("Three Drives Bullish", "harmonic reversal", "bullish", "harmonic", 0.55, timeframe, "Three progressively lower drives suggest exhaustion."))
        if len(highs) >= 3 and highs[-1][2] > highs[-2][2] > highs[-3][2]:
            patterns.append(_pattern("Three Drives Bearish", "harmonic reversal", "bearish", "harmonic", 0.55, timeframe, "Three progressively higher drives suggest exhaustion."))

    if patterns and _between(ab_xa, 0.15, 1.25):
        patterns.append(_pattern("Anti-Gartley / Anti-Bat / Anti-Crab / Anti-Butterfly Zone", "harmonic reversal", direction, "harmonic", 0.50, timeframe, "Inverse harmonic family zone detected from recent pivots.", priority="lower"))

    return patterns


def _detect_abcd(pivots: Sequence[Tuple[int, str, float]], timeframe: str) -> List[Pattern]:
    if len(pivots) < 4:
        return []
    a, b, c, d = pivots[-4:]
    types = [x[1] for x in (a, b, c, d)]
    if types not in (["H", "L", "H", "L"], ["L", "H", "L", "H"]):
        return []
    ab = abs(b[2] - a[2])
    bc = abs(c[2] - b[2])
    cd = abs(d[2] - c[2])
    if min(ab, bc, cd) <= 0:
        return []
    if _between(bc / ab, 0.382, 0.886) and _between(cd / bc, 1.13, 2.618):
        bullish = types == ["H", "L", "H", "L"]
        return [_pattern("ABCD Bullish" if bullish else "ABCD Bearish", "harmonic reversal", "bullish" if bullish else "bearish", "harmonic", 0.62, timeframe, "ABCD legs fit common Fibonacci retracement and extension ranges.", priority="medium")]
    return []


# ---------------------------------------------------------------------------
# Additional concepts
# ---------------------------------------------------------------------------


def _detect_additional_concepts(df: pd.DataFrame, timeframe: str, tf_weight: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    if len(df) < 22:
        return patterns

    close = float(df["close"].iloc[-1])
    recent = df.iloc[-21:-1]
    support = float(recent["low"].min())
    resistance = float(recent["high"].max())
    atr = float(_atr(df).iloc[-1])
    tol = max(_price_tolerance(df), atr * 0.12)

    if abs(close - support) <= tol:
        patterns.append(_pattern("Support Level Retest", "support/resistance", "bullish", "market_structure", 0.68, timeframe, "Price is testing recent horizontal support.", priority="high"))
    if abs(close - resistance) <= tol:
        patterns.append(_pattern("Resistance Level Retest", "support/resistance", "bearish", "market_structure", 0.68, timeframe, "Price is testing recent horizontal resistance.", priority="high"))

    highs = _pivots(df.tail(60), left=2, right=2)
    high_pts = [(i, p) for i, t, p in highs if t == "H"][-4:]
    low_pts = [(i, p) for i, t, p in highs if t == "L"][-4:]
    if len(high_pts) >= 2:
        slope = _slope(high_pts)
        projected = _project_line(high_pts, len(df.tail(60)) - 1)
        if projected and abs(close - projected) <= tol:
            direction = "bearish" if slope <= 0 else "neutral"
            patterns.append(_pattern("Trendline Resistance", "trendline", direction, "market_structure", 0.58, timeframe, "Price is near projected resistance trendline."))
    if len(low_pts) >= 2:
        slope = _slope(low_pts)
        projected = _project_line(low_pts, len(df.tail(60)) - 1)
        if projected and abs(close - projected) <= tol:
            direction = "bullish" if slope >= 0 else "neutral"
            patterns.append(_pattern("Trendline Support", "trendline", direction, "market_structure", 0.58, timeframe, "Price is near projected support trendline."))

    if len(high_pts) >= 2 and len(low_pts) >= 2:
        high_slope = _slope(high_pts)
        low_slope = _slope(low_pts)
        if abs(high_slope - low_slope) <= max(atr * 0.03, PIP_SIZE * 0.2):
            direction = "bullish" if high_slope > 0 else "bearish" if high_slope < 0 else "neutral"
            channel_name = "Ascending Price Channel" if direction == "bullish" else "Descending Price Channel" if direction == "bearish" else "Ranging Price Channel"
            patterns.append(_pattern(channel_name, "price channel", direction, "market_structure", 0.56, timeframe, "Recent swing highs and lows form a near-parallel channel."))

    patterns.extend(_detect_fibonacci_levels(df, timeframe, close, tol))

    gap = _gap_direction(df)
    if gap == "up":
        patterns.append(_pattern("Gap Up", "gap", "bullish", "market_structure", 0.54, timeframe, "Latest open gaps above previous close."))
    elif gap == "down":
        patterns.append(_pattern("Gap Down", "gap", "bearish", "market_structure", 0.54, timeframe, "Latest open gaps below previous close."))

    c0 = _candle(df, -1)
    if c0:
        if c0.high > resistance and c0.close < resistance - tol:
            patterns.append(_pattern("Liquidity Sweep High / Stop Hunt", "false breakout", "bearish", "market_structure", 0.78, timeframe, "Price swept prior highs then closed back below.", priority="high"))
        if c0.low < support and c0.close > support + tol:
            patterns.append(_pattern("Liquidity Sweep Low / Stop Hunt", "false breakout", "bullish", "market_structure", 0.78, timeframe, "Price swept prior lows then closed back above.", priority="high"))

    return patterns


def _detect_fibonacci_levels(df: pd.DataFrame, timeframe: str, close: float, tol: float) -> List[Pattern]:
    patterns: List[Pattern] = []
    pivots = _pivots(df.tail(80), left=3, right=3)
    if len(pivots) < 2:
        return patterns

    p1, p2 = pivots[-2], pivots[-1]
    high = max(p1[2], p2[2])
    low = min(p1[2], p2[2])
    span = high - low
    if span <= PIP_SIZE * 5:
        return patterns

    levels = {
        "23.6": high - span * 0.236,
        "38.2": high - span * 0.382,
        "50.0": high - span * 0.500,
        "61.8": high - span * 0.618,
        "78.6": high - span * 0.786,
    }
    for label, price in levels.items():
        if abs(close - price) <= tol:
            direction = "bullish" if p2[1] == "H" else "bearish"
            patterns.append(_pattern(f"Fibonacci Retracement {label}%", "fibonacci retracement", direction, "market_structure", 0.56, timeframe, f"Price is near the {label}% retracement of the latest swing."))

    extension_up = high + span * 0.272
    extension_down = low - span * 0.272
    if abs(close - extension_up) <= tol:
        patterns.append(_pattern("Fibonacci Extension 127.2%", "fibonacci extension", "bullish", "market_structure", 0.54, timeframe, "Price is near the 127.2% upside extension."))
    if abs(close - extension_down) <= tol:
        patterns.append(_pattern("Fibonacci Extension 127.2% Down", "fibonacci extension", "bearish", "market_structure", 0.54, timeframe, "Price is near the 127.2% downside extension."))
    return patterns


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _clean_ohlc(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        return None
    clean = df.copy()
    for col in required:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")
    clean = clean.dropna(subset=list(required)).reset_index(drop=True)
    return clean if not clean.empty else None


def _pattern(
    name: str,
    kind: str,
    direction: str,
    category: str,
    confidence: float,
    timeframe: str,
    reason: str,
    bars_ago: int = 0,
    priority: str = "medium",
) -> Pattern:
    return {
        "name": name,
        "type": kind,
        "direction": direction,
        "category": category,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "timeframe": timeframe,
        "bars_ago": bars_ago,
        "priority": priority,
        "reason": reason,
    }


def _candle(df: pd.DataFrame, idx: int) -> Optional[Candle]:
    if len(df) < abs(idx):
        return None
    row = df.iloc[idx]
    o = float(row["open"])
    h = float(row["high"])
    l = float(row["low"])
    c = float(row["close"])
    rng = max(h - l, PIP_SIZE / 10)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    direction = "bullish" if c > o else "bearish" if c < o else "neutral"
    return Candle(o, h, l, c, body, rng, max(upper, 0.0), max(lower, 0.0), direction)


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean().fillna(tr.mean())


def _avg_body(df: pd.DataFrame, lookback: int = 20) -> float:
    body = (df["close"].astype(float) - df["open"].astype(float)).abs()
    value = float(body.tail(lookback).mean())
    return max(value, PIP_SIZE / 10)


def _price_tolerance(df: pd.DataFrame) -> float:
    atr = float(_atr(df).iloc[-1]) if len(df) >= 2 else PIP_SIZE * 5
    return max(PIP_SIZE * 1.5, atr * 0.08)


def _near(a: float, b: float, tolerance: float) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def _between(value: float, lower: float, upper: float) -> bool:
    return lower <= value <= upper


def _trend(df: pd.DataFrame, lookback: int = 12) -> str:
    if df is None or len(df) < max(lookback, 4):
        return "sideways"
    closes = df["close"].astype(float).tail(lookback).to_numpy()
    x = np.arange(len(closes))
    slope = float(np.polyfit(x, closes, 1)[0])
    atr = max(float(_atr(df).iloc[-1]), PIP_SIZE)
    move = slope * lookback
    if move > atr * 0.45:
        return "up"
    if move < -atr * 0.45:
        return "down"
    return "sideways"


def _is_doji(c: Candle) -> bool:
    return c.body_ratio <= 0.10


def _is_hammer_shape(c: Candle) -> bool:
    return c.body_ratio <= 0.38 and c.lower >= max(c.body * 2.0, c.range * 0.45) and c.upper <= c.range * 0.25


def _is_inverted_hammer_shape(c: Candle) -> bool:
    return c.body_ratio <= 0.38 and c.upper >= max(c.body * 2.0, c.range * 0.45) and c.lower <= c.range * 0.25


def _is_marubozu(c: Candle) -> bool:
    return c.body_ratio >= 0.88 and c.upper <= c.range * 0.08 and c.lower <= c.range * 0.08


def _body_bounds(c: Candle) -> Tuple[float, float]:
    return min(c.open, c.close), max(c.open, c.close)


def _body_inside(inner: Candle, outer: Candle) -> bool:
    inner_low, inner_high = _body_bounds(inner)
    outer_low, outer_high = _body_bounds(outer)
    return inner_low >= outer_low and inner_high <= outer_high


def _bullish_engulfing(prev: Candle, curr: Candle) -> bool:
    prev_low, prev_high = _body_bounds(prev)
    curr_low, curr_high = _body_bounds(curr)
    return prev.direction == "bearish" and curr.direction == "bullish" and curr_low <= prev_low and curr_high >= prev_high


def _bearish_engulfing(prev: Candle, curr: Candle) -> bool:
    prev_low, prev_high = _body_bounds(prev)
    curr_low, curr_high = _body_bounds(curr)
    return prev.direction == "bullish" and curr.direction == "bearish" and curr_high >= prev_high and curr_low <= prev_low


def _morning_star(c2: Candle, c1: Candle, c0: Candle) -> bool:
    midpoint = (c2.open + c2.close) / 2
    return c2.direction == "bearish" and c1.body_ratio <= 0.35 and c0.direction == "bullish" and c0.close > midpoint


def _evening_star(c2: Candle, c1: Candle, c0: Candle) -> bool:
    midpoint = (c2.open + c2.close) / 2
    return c2.direction == "bullish" and c1.body_ratio <= 0.35 and c0.direction == "bearish" and c0.close < midpoint


def _three_white_soldiers(c2: Candle, c1: Candle, c0: Candle, avg_body: float) -> bool:
    return all(c.direction == "bullish" and c.body >= avg_body * 0.8 for c in (c2, c1, c0)) and c2.close < c1.close < c0.close


def _three_black_crows(c2: Candle, c1: Candle, c0: Candle, avg_body: float) -> bool:
    return all(c.direction == "bearish" and c.body >= avg_body * 0.8 for c in (c2, c1, c0)) and c2.close > c1.close > c0.close


def _rising_three_methods(c4: Candle, c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    middle_inside = all(c.high < c4.high and c.low > c4.low for c in (c3, c2, c1))
    return c4.direction == "bullish" and all(c.direction == "bearish" for c in (c3, c2, c1)) and c0.direction == "bullish" and middle_inside and c0.close > c4.high


def _falling_three_methods(c4: Candle, c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    middle_inside = all(c.high < c4.high and c.low > c4.low for c in (c3, c2, c1))
    return c4.direction == "bearish" and all(c.direction == "bullish" for c in (c3, c2, c1)) and c0.direction == "bearish" and middle_inside and c0.close < c4.low


def _three_line_strike_bullish(c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    return all(c.direction == "bullish" for c in (c3, c2, c1)) and c3.close < c2.close < c1.close and c0.direction == "bearish" and c0.close < c3.open


def _three_line_strike_bearish(c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    return all(c.direction == "bearish" for c in (c3, c2, c1)) and c3.close > c2.close > c1.close and c0.direction == "bullish" and c0.close > c3.open


def _breakaway_bullish(c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    return c3.direction == "bearish" and c2.close < c3.close and c1.close < c2.close and c0.direction == "bullish" and c0.close > c2.open


def _breakaway_bearish(c3: Candle, c2: Candle, c1: Candle, c0: Candle) -> bool:
    return c3.direction == "bullish" and c2.close > c3.close and c1.close > c2.close and c0.direction == "bearish" and c0.close < c2.open


def _pivots(df: pd.DataFrame, left: int = 2, right: int = 2) -> List[Tuple[int, str, float]]:
    highs = df["high"].astype(float).to_numpy()
    lows = df["low"].astype(float).to_numpy()
    raw: List[Tuple[int, str, float]] = []
    for i in range(left, len(df) - right):
        high_window = highs[i - left : i + right + 1]
        low_window = lows[i - left : i + right + 1]
        if highs[i] >= np.max(high_window):
            raw.append((i, "H", float(highs[i])))
        if lows[i] <= np.min(low_window):
            raw.append((i, "L", float(lows[i])))

    raw.sort(key=lambda x: x[0])
    compressed: List[Tuple[int, str, float]] = []
    for pivot in raw:
        if not compressed or compressed[-1][1] != pivot[1]:
            compressed.append(pivot)
            continue
        last = compressed[-1]
        if pivot[1] == "H" and pivot[2] > last[2]:
            compressed[-1] = pivot
        elif pivot[1] == "L" and pivot[2] < last[2]:
            compressed[-1] = pivot
    return compressed


def _slope(points: Sequence[Tuple[int, float]]) -> float:
    if len(points) < 2:
        return 0.0
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    try:
        return float(np.polyfit(x, y, 1)[0])
    except Exception:
        return 0.0


def _project_line(points: Sequence[Tuple[int, float]], x_value: int) -> Optional[float]:
    if len(points) < 2:
        return None
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    try:
        slope, intercept = np.polyfit(x, y, 1)
        return float(slope * x_value + intercept)
    except Exception:
        return None


def _gap_direction(df: pd.DataFrame) -> Optional[str]:
    if len(df) < 2:
        return None
    prev_close = float(df["close"].iloc[-2])
    curr_open = float(df["open"].iloc[-1])
    atr = float(_atr(df).iloc[-1])
    threshold = max(PIP_SIZE * 2.0, atr * 0.16)
    if curr_open - prev_close > threshold:
        return "up"
    if prev_close - curr_open > threshold:
        return "down"
    return None


def _cup_with_handle(df: pd.DataFrame, bullish: bool) -> bool:
    if len(df) < 45:
        return False
    close = df["close"].astype(float).iloc[-45:].to_numpy()
    left = close[:15]
    middle = close[15:32]
    handle = close[32:]
    if bullish:
        return np.mean(middle) < np.mean(left) and np.mean(handle[-5:]) > np.mean(middle) and np.max(handle) < np.max(left) * 1.003
    return np.mean(middle) > np.mean(left) and np.mean(handle[-5:]) < np.mean(middle) and np.min(handle) > np.min(left) * 0.997


def _dedupe_patterns(patterns: Iterable[Pattern]) -> List[Pattern]:
    best: Dict[Tuple[str, str], Pattern] = {}
    for pattern in patterns:
        key = (str(pattern.get("timeframe", "")), str(pattern.get("name", "")))
        existing = best.get(key)
        if existing is None or float(pattern.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
            best[key] = pattern
    return list(best.values())


def _rank_patterns(patterns: Sequence[Pattern], max_patterns: int) -> List[Pattern]:
    tf_rank = {"H4": 4, "H1": 3, "M15": 2, "M5": 1}
    priority_rank = {"high": 3, "medium": 2, "lower": 1}
    return sorted(
        patterns,
        key=lambda p: (
            priority_rank.get(str(p.get("priority", "medium")), 2),
            float(p.get("confidence", 0.0)),
            tf_rank.get(str(p.get("timeframe", "")), 0),
        ),
        reverse=True,
    )[:max_patterns]
