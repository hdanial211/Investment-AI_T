"""
backtest_engine.py - Standalone Backtesting Engine for Investment-AI_T
=======================================================================
No dependency on Bot Engine modules.
Downloads OHLCV data from MT5 (via CSV export) or Yahoo Finance (yfinance).
Simulates trades using the same style_params as the live bot.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Add Bot Engine to path for style_params and ai_engine ──────────────────────
TESTING_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = TESTING_ROOT.parent
BOT_ENGINE = PROJECT_ROOT / "Bot Engine"
if str(BOT_ENGINE) not in sys.path:
    sys.path.insert(0, str(BOT_ENGINE))

try:
    from style_params import get_style_params, get_current_session
    HAS_STYLE_PARAMS = True
except ImportError:
    HAS_STYLE_PARAMS = False

try:
    from ai_engine import get_ai_signal
    import system_settings
    HAS_AI_ENGINE = True
except ImportError:
    HAS_AI_ENGINE = False

# ── Constants ─────────────────────────────────────────────────────────────────
PIP_SIZE = {"XAUUSD": 0.01, "DEFAULT": 0.0001}
CONTRACT_SIZE = {"XAUUSD": 100.0, "DEFAULT": 100000.0}
STORAGE_DIR = TESTING_ROOT / "storage"
REPORTS_DIR = TESTING_ROOT / "reports"


def _pip_size(symbol: str) -> float:
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return PIP_SIZE["XAUUSD"]
    return PIP_SIZE["DEFAULT"]


def _contract_size(symbol: str) -> float:
    s = symbol.upper()
    if "XAU" in s or "GOLD" in s:
        return CONTRACT_SIZE["XAUUSD"]
    return CONTRACT_SIZE["DEFAULT"]


def _pip_multiplier(symbol: str) -> float:
    return 1.0 / _pip_size(symbol)


def _session_name(hour_utc: int) -> str:
    if 0 <= hour_utc < 7:
        return "Asia"
    if 7 <= hour_utc < 12:
        return "London"
    if 12 <= hour_utc < 16:
        return "London/NY overlap"
    if 16 <= hour_utc < 21:
        return "NY"
    return "Off-hours"


# ── Style Params (fallback if Bot Engine not available) ───────────────────────

_BUILTIN_STYLE_PARAMS = {
    "SCALPING": {
        "XAUUSD": {"sl_atr_multi": 1.0, "tp_atr_multi": 1.5, "min_sl_pips": 20, "max_sl_pips": 80, "min_rr": 1.0, "risk_percent": 0.5},
    },
    "INTRADAY": {
        "XAUUSD": {"sl_atr_multi": 1.5, "tp_atr_multi": 3.0, "min_sl_pips": 50, "max_sl_pips": 250, "min_rr": 2.0, "risk_percent": 1.5},
    },
    "SWING": {
        "XAUUSD": {"sl_atr_multi": 2.5, "tp_atr_multi": 5.0, "min_sl_pips": 150, "max_sl_pips": 300, "min_rr": 2.0, "risk_percent": 1.0},
    },
}


def _get_style_params(trade_style: str, symbol: str) -> dict:
    if HAS_STYLE_PARAMS:
        return get_style_params(trade_style, symbol)
    s = symbol.upper()
    base = "XAUUSD"
    style = trade_style.upper()
    return _BUILTIN_STYLE_PARAMS.get(style, _BUILTIN_STYLE_PARAMS["INTRADAY"]).get(
        base, _BUILTIN_STYLE_PARAMS["INTRADAY"]["XAUUSD"]
    )


# ── OHLCV Data Loading ────────────────────────────────────────────────────────

def _try_import_pandas():
    try:
        import pandas as pd
        import numpy as np
        return pd, np
    except ImportError:
        print("[ERROR] pandas/numpy not installed. Run: pip install pandas numpy")
        sys.exit(1)


def _try_import_yfinance():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        return None


def download_data(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "1h",
) -> Optional[object]:
    """Download OHLCV data from Yahoo Finance (compatible with yfinance 0.2+ and 1.4+)."""
    pd, np = _try_import_pandas()
    yf = _try_import_yfinance()
    if yf is None:
        print("[WARNING] yfinance not installed. Run: pip install yfinance")
        return None

    # Map symbol to Yahoo Finance ticker
    yf_map = {
        "XAUUSD": "GC=F",    # Gold Futures
    }
    s = symbol.upper()
    ticker = yf_map.get(s, s)

    print(f"[DATA] Downloading {symbol} ({ticker}) from Yahoo Finance...")
    try:
        raw = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=True,
            group_by="column",
        )
    except Exception as e:
        print(f"[ERROR] Download failed: {e}")
        return None

    if raw is None or raw.empty:
        print(f"[WARNING] No data returned for {symbol}")
        return None

    # ── Flatten MultiIndex columns (yfinance 1.4+) ────────────────────────
    # yfinance 1.4 returns columns like ('Close', 'GC=F'), ('Open', 'GC=F') etc.
    if isinstance(raw.columns, pd.MultiIndex):
        # Take just the first level (OHLCV name), drop the ticker level
        raw.columns = [col[0].lower() if isinstance(col, tuple) else str(col).lower() for col in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]

    # ── Reset index to get the datetime as a column ───────────────────────
    df = raw.reset_index()

    # Debug: show what columns we actually got
    print(f"[DATA] Columns after reset_index: {list(df.columns)}")

    # ── Find the datetime column (could be 'Datetime', 'Date', 'index', 'Price') ─
    time_col = None
    for candidate in ["datetime", "date", "index", "timestamp", "price"]:
        if candidate in df.columns:
            time_col = candidate
            break

    # If still not found, use the first column (it's almost always the index/datetime)
    if time_col is None:
        time_col = df.columns[0]
        print(f"[DATA] Using first column as time: {time_col}")

    df = df.rename(columns={time_col: "time"})
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_localize(None)

    # ── Select OHLCV columns (volume optional for forex) ─────────────────
    needed = ["time", "open", "high", "low", "close"]
    for col in needed:
        if col not in df.columns:
            print(f"[ERROR] Missing column '{col}'. Available: {list(df.columns)}")
            return None

    if "volume" in df.columns:
        df = df[needed + ["volume"]].dropna(subset=["open", "high", "low", "close"])
    else:
        df = df[needed].dropna()

    df = df.sort_values("time").reset_index(drop=True)

    # Ensure numeric types
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    print(f"[DATA] Got {len(df)} bars for {symbol} | First: {df['time'].iloc[0]} | Last: {df['time'].iloc[-1]}")
    return df



def load_csv_data(csv_path: str) -> Optional[object]:
    """Load MT5-exported CSV (time, open, high, low, close, tick_volume)."""
    pd, np = _try_import_pandas()
    p = Path(csv_path)
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df.columns = [c.lower().strip() for c in df.columns]
    # MT5 exports "Date\tTime" or combined "datetime"
    if "date" in df.columns and "time" not in df.columns:
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
        else:
            df["time"] = pd.to_datetime(df["date"])
    elif "datetime" in df.columns:
        df["time"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("time").reset_index(drop=True)
    return df[["time", "open", "high", "low", "close"]].dropna()


def get_or_download(symbol: str, start: datetime, end: datetime, interval="1h") -> Optional[object]:
    """Load from storage cache or download from Yahoo Finance."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = STORAGE_DIR / f"{symbol}_{interval}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"

    pd, _ = _try_import_pandas()

    if cache_file.exists():
        print(f"[DATA] Loading cached {symbol} from {cache_file.name}")
        return pd.read_csv(cache_file, parse_dates=["time"])

    df = download_data(symbol, start, end, interval)
    if df is not None:
        df.to_csv(cache_file, index=False)
        print(f"[DATA] Saved to {cache_file.name}")
    return df


# ── Technical Indicators ──────────────────────────────────────────────────────

def calc_ema(series, period: int):
    return series.ewm(span=period, adjust=False).mean()


def calc_atr(df, period: int = 14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    import pandas as pd
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def calc_rsi(series, period: int = 14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    import numpy as np
    rs = avg_gain / avg_loss.replace(0, np.finfo(float).eps)
    return 100 - (100 / (1 + rs))


def calc_adx(df, period: int = 14):
    import numpy as np
    import pandas as pd
    high = df["high"]
    low = df["low"]
    close = df["close"]
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    alpha = 1 / period
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1)
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=alpha, adjust=False).mean() / atr.replace(0, 1)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx


def compute_indicators(df, warmup: int = 50) -> object:
    """Add indicator columns to dataframe."""
    pd, _ = _try_import_pandas()
    df = df.copy()
    df["ema9"]   = calc_ema(df["close"], 9)
    df["ema21"]  = calc_ema(df["close"], 21)
    df["ema50"]  = calc_ema(df["close"], 50)
    df["ema200"] = calc_ema(df["close"], 200)
    df["rsi"]    = calc_rsi(df["close"], 14)
    df["atr"]    = calc_atr(df, 14)
    df["adx"]    = calc_adx(df, 14)
    df = df.iloc[warmup:].reset_index(drop=True)
    return df


# ── Signal Generation ─────────────────────────────────────────────────────────

def generate_signal(row, prev_row, trade_style: str) -> dict:
    """
    Deterministic signal engine (no AI) based on indicator confluence.
    Returns {"action": "BUY"|"SELL"|"HOLD", "confidence": float, "reason": str}
    """
    ema9 = row.get("ema9", 0)
    ema21 = row.get("ema21", 0)
    ema50 = row.get("ema50", 0)
    ema200 = row.get("ema200", 0)
    rsi = row.get("rsi", 50)
    adx = row.get("adx", 0)
    close = row.get("close", 0)

    prev_ema9 = prev_row.get("ema9", 0) if prev_row else ema9
    prev_ema21 = prev_row.get("ema21", 0) if prev_row else ema21

    is_trending = adx >= 25
    regime = "TRENDING" if is_trending else "RANGING"

    # ── SCALPING: EMA9/21 crossover on short term ───────────────────────────
    if trade_style == "SCALPING":
        if ema9 > ema21 and prev_ema9 <= prev_ema21 and rsi < 70:
            return {"action": "BUY", "confidence": 0.65 + min(adx / 200, 0.15),
                    "reason": f"EMA9 cross above EMA21, RSI={rsi:.1f}, ADX={adx:.1f}"}
        if ema9 < ema21 and prev_ema9 >= prev_ema21 and rsi > 30:
            return {"action": "SELL", "confidence": 0.65 + min(adx / 200, 0.15),
                    "reason": f"EMA9 cross below EMA21, RSI={rsi:.1f}, ADX={adx:.1f}"}
        return {"action": "HOLD", "confidence": 0.3, "reason": "No EMA cross signal"}

    # ── INTRADAY: EMA trend + RSI momentum ─────────────────────────────────
    if trade_style == "INTRADAY":
        bull = ema9 > ema21 > ema50 and rsi > 50 and rsi < 72 and adx > 20
        bear = ema9 < ema21 < ema50 and rsi < 50 and rsi > 28 and adx > 20
        if bull:
            conf = 0.60 + min((adx - 20) / 100, 0.25)
            return {"action": "BUY", "confidence": round(conf, 3),
                    "reason": f"Bullish EMA stack ({ema9:.5f}>{ema21:.5f}>{ema50:.5f}), RSI={rsi:.1f}"}
        if bear:
            conf = 0.60 + min((adx - 20) / 100, 0.25)
            return {"action": "SELL", "confidence": round(conf, 3),
                    "reason": f"Bearish EMA stack, RSI={rsi:.1f}, ADX={adx:.1f}"}
        return {"action": "HOLD", "confidence": 0.3, "reason": f"No intraday setup, regime={regime}"}

    # ── SWING: Golden/Death Cross on EMA50/200 + trend alignment ───────────
    if trade_style == "SWING":
        prev_ema50 = prev_row.get("ema50", ema50) if prev_row else ema50
        prev_ema200 = prev_row.get("ema200", ema200) if prev_row else ema200
        golden = ema50 > ema200 and prev_ema50 <= prev_ema200
        death = ema50 < ema200 and prev_ema50 >= prev_ema200
        # Also enter on trend continuation after cross
        in_bull_trend = ema50 > ema200 and ema9 > ema21 and rsi > 50 and adx > 20
        in_bear_trend = ema50 < ema200 and ema9 < ema21 and rsi < 50 and adx > 20

        if golden:
            return {"action": "BUY", "confidence": 0.80, "reason": f"Golden Cross EMA50 > EMA200, ADX={adx:.1f}"}
        if death:
            return {"action": "SELL", "confidence": 0.80, "reason": f"Death Cross EMA50 < EMA200, ADX={adx:.1f}"}
        if in_bull_trend:
            return {"action": "BUY", "confidence": 0.60, "reason": f"Bull swing continuation, RSI={rsi:.1f}"}
        if in_bear_trend:
            return {"action": "SELL", "confidence": 0.60, "reason": f"Bear swing continuation, RSI={rsi:.1f}"}
        return {"action": "HOLD", "confidence": 0.3, "reason": "No swing setup"}

    return {"action": "HOLD", "confidence": 0.0, "reason": "Unknown style"}


# ── Trade Simulation ──────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    symbol: str = "XAUUSD"
    trade_styles: List[str] = field(default_factory=lambda: ["SCALPING", "INTRADAY", "SWING"])
    start_balance: float = 10000.0
    fixed_lot: float = 0.01
    use_dynamic_lot: bool = True
    start_date: datetime = field(default_factory=lambda: datetime.now() - timedelta(days=365))
    end_date: datetime = field(default_factory=datetime.now)
    min_confidence: float = 0.55
    min_bars_between_entries: int = 3
    max_open_per_symbol: int = 3
    use_ai: bool = False  # Set to True to call the real Gemini AI for trade filtering


@dataclass
class SimTrade:
    ticket: int
    symbol: str
    trade_style: str
    action: str
    lot: float
    entry_time: datetime
    entry_price: float
    sl: float
    tp: float
    sl_pips: int
    tp_pips: int
    atr: float
    confidence: float
    reason: str
    session: str
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    profit: Optional[float] = None
    r_multiple: Optional[float] = None
    balance_after: Optional[float] = None


def _calc_lot(balance: float, risk_pct: float, sl_pips: int, symbol: str) -> float:
    pip = _pip_size(symbol)
    contract = _contract_size(symbol)
    risk_amt = balance * (risk_pct / 100.0)
    lot = risk_amt / (sl_pips * pip * contract)
    lot = max(0.01, min(100.0, round(lot, 2)))
    return lot


def _calc_trade_params(
    symbol: str,
    action: str,
    price: float,
    atr: float,
    balance: float,
    trade_style: str,
    fixed_lot: float,
    use_dynamic_lot: bool,
) -> dict:
    params = _get_style_params(trade_style, symbol)
    pip_mult = _pip_multiplier(symbol)
    atr_pips = atr * pip_mult

    sl_pips = int(atr_pips * params["sl_atr_multi"])
    sl_pips = max(params["min_sl_pips"], min(params["max_sl_pips"], sl_pips))
    tp_pips = max(int(atr_pips * params["tp_atr_multi"]), sl_pips)

    pip = _pip_size(symbol)
    if action == "BUY":
        sl_price = price - (sl_pips * pip)
        tp_price = price + (tp_pips * pip)
    else:
        sl_price = price + (sl_pips * pip)
        tp_price = price - (tp_pips * pip)

    if use_dynamic_lot:
        lot = _calc_lot(balance, params["risk_percent"], sl_pips, symbol)
    else:
        lot = fixed_lot

    return {
        "sl": round(sl_price, 5),
        "tp": round(tp_price, 5),
        "sl_pips": sl_pips,
        "tp_pips": tp_pips,
        "lot": lot,
    }


def _calc_profit(trade: SimTrade, exit_price: float) -> float:
    direction = 1 if trade.action == "BUY" else -1
    return (exit_price - trade.entry_price) * direction * _contract_size(trade.symbol) * trade.lot


def run_simulation(
    df,        # pandas DataFrame with indicators
    cfg: BacktestConfig,
    trade_style: str,
) -> List[SimTrade]:
    """Run a full backtest simulation for one style."""
    trades: List[SimTrade] = []
    open_trades: List[SimTrade] = []
    balance = cfg.start_balance
    ticket = 100000
    last_entry_bar: int = -999

    rows = df.to_dict("records")

    for i, row in enumerate(rows):
        if i == 0:
            continue

        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        ts = row["time"]
        hour_utc = ts.hour if hasattr(ts, "hour") else 12
        session = _session_name(hour_utc)

        # ── Manage open trades ───────────────────────────────────────────────
        still_open = []
        for trade in open_trades:
            hit_sl = (trade.action == "BUY" and low <= trade.sl) or \
                     (trade.action == "SELL" and high >= trade.sl)
            hit_tp = (trade.action == "BUY" and high >= trade.tp) or \
                     (trade.action == "SELL" and low <= trade.tp)

            if hit_sl:
                trade.exit_time = ts
                trade.exit_price = trade.sl
                trade.exit_reason = "SL"
                trade.profit = round(_calc_profit(trade, trade.sl), 2)
                risk_amt = abs((trade.entry_price - trade.sl) * _contract_size(trade.symbol) * trade.lot)
                trade.r_multiple = round(trade.profit / risk_amt, 4) if risk_amt else 0
                balance += trade.profit
                trade.balance_after = round(balance, 2)
                trades.append(trade)
            elif hit_tp:
                trade.exit_time = ts
                trade.exit_price = trade.tp
                trade.exit_reason = "TP"
                trade.profit = round(_calc_profit(trade, trade.tp), 2)
                risk_amt = abs((trade.entry_price - trade.sl) * _contract_size(trade.symbol) * trade.lot)
                trade.r_multiple = round(trade.profit / risk_amt, 4) if risk_amt else 0
                balance += trade.profit
                trade.balance_after = round(balance, 2)
                trades.append(trade)
            else:
                still_open.append(trade)
        open_trades = still_open

        # ── Generate signal ──────────────────────────────────────────────────
        if i - last_entry_bar < cfg.min_bars_between_entries:
            continue
        if len(open_trades) >= cfg.max_open_per_symbol:
            continue

        prev_row = rows[i - 1]
        signal = generate_signal(row, prev_row, trade_style)

        if signal["action"] == "HOLD" or signal["confidence"] < cfg.min_confidence:
            continue

        # ── Optional: Query REAL Cloud AI ─────────────────────────────────────
        if cfg.use_ai and HAS_AI_ENGINE:
            import time
            
            # Construct a mock indicator dict representing the single-timeframe data
            regime = "TRENDING" if float(row.get("adx", 0)) >= 25 else "RANGING"
            trend = "bullish" if row.get("ema9",0) > row.get("ema21",0) else "bearish"
            
            mock_indicators = {
                "symbol": cfg.symbol,
                "price": close,
                "market_regime": regime,
                "adx": round(float(row.get("adx", 0)), 2),
                "h4_trend": trend, # using 1h as proxy
                "h4_ema50": row.get("ema50", 0),
                "h4_ema200": row.get("ema200", 0),
                "h4_golden_cross": row.get("ema50",0) > row.get("ema200",0),
                "h1_resistance": high * 1.01, # mock
                "h1_support": low * 0.99, # mock
                "h1_macd_trend": trend,
                "m15_rsi": round(float(row.get("rsi", 50)), 2), # proxy
                "m15_liquidity_sweep": "none",
                "m15_pattern": "none",
                "m5_liquidity_sweep": "none",
                "m5_pattern": "none",
                "atr": row.get("atr", 0),
                "pattern_bias": {"bias": "none", "bullish_score": 0, "bearish_score": 0},
                "detected_patterns": [],
                "trading_mode": trade_style
            }

            print(f"\n[AI] Querying Gemini AI for {signal['action']} setup on {ts}...")
            ai_signal = get_ai_signal(mock_indicators, bid=close, ask=close, trade_memory=None, symbol=cfg.symbol)
            
            # Rate limit protection (Google free tier is ~15 RPM)
            time.sleep(4.0) 

            if ai_signal.get("action", "HOLD") == "HOLD":
                print(f"  → AI Rejected: {ai_signal.get('reason')}")
                continue
            
            # Override with AI's decision
            signal = ai_signal
            signal["confidence"] = ai_signal.get("confidence", signal["confidence"])
            signal["reason"] = f"[AI Filtered] {ai_signal.get('reason', '')}"
            print(f"  → AI APPROVED: {signal['action']} ({signal['confidence']})")
            
            if signal["action"] == "HOLD":
                continue

        atr = float(row.get("atr", 0) or 0)
        if atr <= 0:
            continue

        action = signal["action"]
        params = _calc_trade_params(
            cfg.symbol, action, close, atr,
            balance, trade_style, cfg.fixed_lot, cfg.use_dynamic_lot
        )

        # Validate R:R
        rr = params["tp_pips"] / max(params["sl_pips"], 1)
        style_p = _get_style_params(trade_style, cfg.symbol)
        if rr < style_p.get("min_rr", 1.0):
            continue

        ticket += 1
        trade = SimTrade(
            ticket=ticket,
            symbol=cfg.symbol,
            trade_style=trade_style,
            action=action,
            lot=params["lot"],
            entry_time=ts,
            entry_price=close,
            sl=params["sl"],
            tp=params["tp"],
            sl_pips=params["sl_pips"],
            tp_pips=params["tp_pips"],
            atr=atr,
            confidence=signal["confidence"],
            reason=signal["reason"],
            session=session,
        )
        open_trades.append(trade)
        last_entry_bar = i

    # Close remaining trades at end of data
    if rows and open_trades:
        last_row = rows[-1]
        for trade in open_trades:
            trade.exit_time = last_row["time"]
            trade.exit_price = float(last_row["close"])
            trade.exit_reason = "end_of_data"
            trade.profit = round(_calc_profit(trade, float(last_row["close"])), 2)
            risk_amt = abs((trade.entry_price - trade.sl) * _contract_size(trade.symbol) * trade.lot)
            trade.r_multiple = round(trade.profit / risk_amt, 4) if risk_amt else 0
            balance += trade.profit
            trade.balance_after = round(balance, 2)
            trades.append(trade)

    return trades


# ── Stats Calculation ─────────────────────────────────────────────────────────

def calc_stats(trades: List[SimTrade], start_balance: float, symbol: str, style: str) -> dict:
    if not trades:
        return {
            "symbol": symbol, "style": style, "total_trades": 0,
            "wins": 0, "losses": 0, "win_rate": 0, "total_profit": 0,
            "max_drawdown": 0, "profit_factor": 0, "sharpe": 0,
            "avg_r": 0, "best_trade": 0, "worst_trade": 0,
            "start_balance": start_balance, "end_balance": start_balance,
            "return_pct": 0,
        }

    profits = [t.profit for t in trades if t.profit is not None]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    total_profit = sum(profits)
    end_balance = start_balance + total_profit

    # Max drawdown
    balance = start_balance
    peak = start_balance
    max_dd = 0.0
    for t in trades:
        balance += (t.profit or 0)
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Profit factor
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999

    # Simple Sharpe (monthly)
    import math
    if len(profits) > 1:
        mean_p = total_profit / len(profits)
        variance = sum((p - mean_p) ** 2 for p in profits) / len(profits)
        std = math.sqrt(variance)
        sharpe = round(mean_p / std, 2) if std > 0 else 0
    else:
        sharpe = 0

    avg_r = round(sum(t.r_multiple for t in trades if t.r_multiple) / len(trades), 3)

    return {
        "symbol": symbol,
        "style": style,
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "total_profit": round(total_profit, 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "avg_r": avg_r,
        "best_trade": round(max(profits), 2) if profits else 0,
        "worst_trade": round(min(profits), 2) if profits else 0,
        "start_balance": start_balance,
        "end_balance": round(end_balance, 2),
        "return_pct": round((total_profit / start_balance) * 100, 2) if start_balance else 0,
    }


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_full_backtest(cfg: BacktestConfig) -> dict:
    """Run backtest for all styles, return results dict for HTML report."""
    pd, _ = _try_import_pandas()

    print(f"\n{'='*60}")
    print(f"  Investment-AI_T Backtesting Engine")
    print(f"  Symbol: {cfg.symbol} | Period: {cfg.start_date:%Y-%m-%d} to {cfg.end_date:%Y-%m-%d}")
    print(f"  Styles: {', '.join(cfg.trade_styles)}")
    print(f"{'='*60}\n")

    if cfg.use_ai and HAS_AI_ENGINE:
        print("[INFO] Loading API Keys from Supabase (Dashboard Settings)...")
        if system_settings.fetch_and_apply_system_settings():
            print("[INFO] System settings (API Keys) loaded successfully.")
        else:
            print("[WARNING] Failed to load system settings from Supabase. Falling back to .env")

    # Determine interval based on date range
    days = (cfg.end_date - cfg.start_date).days
    interval = "1h" if days <= 365 else "1d"

    df = get_or_download(cfg.symbol, cfg.start_date, cfg.end_date, interval)
    if df is None or len(df) < 100:
        print("[ERROR] Not enough data to run backtest.")
        return {}

    df_ind = compute_indicators(df, warmup=50)

    all_results = {
        "symbol": cfg.symbol,
        "start_date": cfg.start_date.isoformat(),
        "end_date": cfg.end_date.isoformat(),
        "start_balance": cfg.start_balance,
        "generated_at": datetime.now().isoformat(),
        "styles": {},
    }

    for style in cfg.trade_styles:
        print(f"\n[SIM] Running {style} backtest on {cfg.symbol}...")
        trades = run_simulation(df_ind, cfg, style)
        stats = calc_stats(trades, cfg.start_balance, cfg.symbol, style)
        print(f"  ✓ {stats['total_trades']} trades | Win Rate: {stats['win_rate']}% | P&L: ${stats['total_profit']:+.2f}")

        all_results["styles"][style] = {
            "stats": stats,
            "trades": [
                {
                    "ticket": t.ticket,
                    "action": t.action,
                    "entry_time": t.entry_time.isoformat() if hasattr(t.entry_time, "isoformat") else str(t.entry_time),
                    "exit_time": t.exit_time.isoformat() if t.exit_time and hasattr(t.exit_time, "isoformat") else str(t.exit_time) if t.exit_time else None,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "sl": t.sl,
                    "tp": t.tp,
                    "sl_pips": t.sl_pips,
                    "tp_pips": t.tp_pips,
                    "lot": t.lot,
                    "profit": t.profit,
                    "r_multiple": t.r_multiple,
                    "balance_after": t.balance_after,
                    "confidence": t.confidence,
                    "reason": t.reason,
                    "session": t.session,
                    "exit_reason": t.exit_reason,
                }
                for t in trades
            ],
        }

    return all_results
