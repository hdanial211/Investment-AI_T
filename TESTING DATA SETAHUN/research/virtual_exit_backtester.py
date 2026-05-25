"""Chronological pattern backtester with virtual SL/TP/trailing exits."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

import config
from research.backtest_config import BacktestConfig
from research.historical_data_collector import HistoryBundle
from risk_manager import RiskManager
from strategy import calculate_multi_indicators


def _contract_size(symbol: str) -> float:
    symbol = symbol.upper()
    if "XAU" in symbol or "GOLD" in symbol:
        return 100.0
    return 100000.0


def _spread_point(symbol: str) -> float:
    symbol = symbol.upper()
    if "XAU" in symbol or "GOLD" in symbol:
        return 0.01
    if "JPY" in symbol:
        return 0.001
    return 0.00001


def _entry_price(symbol: str, action: str, row: pd.Series) -> float:
    spread_price = float(row.get("spread", 0) or 0) * _spread_point(symbol)
    close = float(row["close"])
    if action == "BUY":
        return close + (spread_price / 2)
    return close - (spread_price / 2)


def _session_name(ts: pd.Timestamp) -> str:
    hour = int(ts.hour)
    if 7 <= hour < 15:
        return "Asia"
    if 15 <= hour < 21:
        return "London"
    if 21 <= hour or hour < 5:
        return "New York"
    return "Transition"


def _timeframe_minutes(timeframe: str) -> int:
    timeframe = timeframe.upper()
    if timeframe.startswith("M"):
        return int(timeframe[1:])
    if timeframe.startswith("H"):
        return int(timeframe[1:]) * 60
    if timeframe.startswith("D"):
        return int(timeframe[1:] or "1") * 1440
    return 5


def _pattern_names(patterns: Iterable[dict], limit: int = 8) -> List[str]:
    names = []
    for pattern in patterns:
        name = str(pattern.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _combo_key(patterns: Iterable[dict]) -> str:
    names = _pattern_names(patterns, limit=3)
    return " + ".join(names) if names else "No Pattern"


def _build_signal(indicators: dict) -> dict:
    patterns = indicators.get("detected_patterns") or []
    pattern_bias = indicators.get("pattern_bias") or {}
    bias = str(pattern_bias.get("bias", "mixed")).lower()

    if not patterns:
        return {"action": "HOLD", "confidence": 0.0, "reason": "No detected pattern confluence"}

    bullish = float(pattern_bias.get("bullish_score", 0) or 0)
    bearish = float(pattern_bias.get("bearish_score", 0) or 0)
    net = bullish - bearish
    high_count = int(pattern_bias.get("high_priority_count", 0) or 0)

    if bias not in {"bullish", "bearish"} or abs(net) < 0.45:
        return {"action": "HOLD", "confidence": 0.35, "reason": "Pattern bias is mixed"}

    action = "BUY" if bias == "bullish" else "SELL"
    confidence = min(0.95, 0.50 + min(abs(net), 3.0) / 6.0 + min(high_count, 3) * 0.04)

    h4_trend = str(indicators.get("h4_trend", "sideways")).lower()
    conflicts_h4 = (action == "BUY" and h4_trend == "bearish") or (action == "SELL" and h4_trend == "bullish")
    if conflicts_h4 and high_count < 2:
        confidence -= 0.25

    reason = (
        f"Historical pattern replay: {bias} bias, net={net:.2f}, "
        f"high_priority={high_count}, h4={h4_trend}"
    )
    return {"action": action, "confidence": round(max(0.0, confidence), 4), "reason": reason}


@dataclass
class SimTrade:
    ticket: int
    mode: str
    symbol: str
    action: str
    lot: float
    entry_time: pd.Timestamp
    entry_price: float
    sl: float
    tp: float
    virtual_sl: float
    sl_pips: int
    tp_pips: int
    atr: float
    confidence: float
    signal_reason: str
    patterns: List[dict]
    pattern_names: List[str]
    combo: str
    session: str
    timeframe: str = "M5"


@dataclass
class ModeState:
    name: str
    balance: float
    open_trades: List[SimTrade] = field(default_factory=list)
    closed_rows: List[dict] = field(default_factory=list)
    audit: Dict[str, int] = field(default_factory=dict)

    def count(self, key: str, amount: int = 1) -> None:
        self.audit[key] = self.audit.get(key, 0) + amount


def _profit(trade: SimTrade, exit_price: float) -> float:
    direction = 1 if trade.action == "BUY" else -1
    return (exit_price - trade.entry_price) * direction * _contract_size(trade.symbol) * trade.lot


def _close_trade(state: ModeState, trade: SimTrade, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
    pnl = _profit(trade, exit_price)
    risk_amount = abs((trade.entry_price - trade.sl) * _contract_size(trade.symbol) * trade.lot)
    r_multiple = pnl / risk_amount if risk_amount else 0.0
    state.balance += pnl
    state.count(f"exit_{reason}")

    state.closed_rows.append({
        "mode": trade.mode,
        "ticket": trade.ticket,
        "symbol": trade.symbol,
        "action": trade.action,
        "lot": round(trade.lot, 2),
        "entry_time": trade.entry_time.isoformat(),
        "exit_time": exit_time.isoformat(),
        "entry_price": round(trade.entry_price, 5),
        "exit_price": round(exit_price, 5),
        "initial_sl": round(trade.sl, 5),
        "initial_tp": round(trade.tp, 5),
        "final_virtual_sl": round(trade.virtual_sl, 5),
        "sl_pips": trade.sl_pips,
        "tp_pips": trade.tp_pips,
        "exit_reason": reason,
        "profit": round(pnl, 2),
        "r_multiple": round(r_multiple, 4),
        "balance_after": round(state.balance, 2),
        "confidence": trade.confidence,
        "signal_reason": trade.signal_reason,
        "session": trade.session,
        "timeframe": trade.timeframe,
        "day_of_week": trade.entry_time.day_name(),
        "pattern_names": " | ".join(trade.pattern_names),
        "patterns_json": json.dumps(trade.patterns, default=str),
        "combo": trade.combo,
    })


def _update_virtual_trailing(trade: SimTrade, close_price: float) -> None:
    if not config.USE_TRAILING_STOP or trade.atr <= 0:
        return

    stage1_distance = 0.5 * trade.atr
    stage2_distance = 1.5 * trade.atr
    trail_distance = 1.0 * trade.atr

    if trade.action == "BUY":
        profit_distance = close_price - trade.entry_price
        if profit_distance > stage2_distance:
            trade.virtual_sl = max(trade.virtual_sl, close_price - trail_distance)
        elif profit_distance > stage1_distance:
            trade.virtual_sl = max(trade.virtual_sl, trade.entry_price)
    else:
        profit_distance = trade.entry_price - close_price
        if profit_distance > stage2_distance:
            trade.virtual_sl = min(trade.virtual_sl, close_price + trail_distance)
        elif profit_distance > stage1_distance:
            trade.virtual_sl = min(trade.virtual_sl, trade.entry_price)


def _manage_open_trades(state: ModeState, row: pd.Series, event_time: pd.Timestamp) -> None:
    remaining: List[SimTrade] = []
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    now = event_time

    for trade in state.open_trades:
        exit_reason: Optional[str] = None
        exit_price: Optional[float] = None

        # Conservative rule: if SL and TP are both touched in the same candle,
        # count SL first. This avoids inflated historical results.
        if trade.action == "BUY":
            if low <= trade.virtual_sl:
                exit_reason = "virtual_sl"
                exit_price = trade.virtual_sl
            elif high >= trade.tp:
                exit_reason = "virtual_tp"
                exit_price = trade.tp
        else:
            if high >= trade.virtual_sl:
                exit_reason = "virtual_sl"
                exit_price = trade.virtual_sl
            elif low <= trade.tp:
                exit_reason = "virtual_tp"
                exit_price = trade.tp

        if exit_reason and exit_price is not None:
            _close_trade(state, trade, now, exit_price, exit_reason)
        else:
            _update_virtual_trailing(trade, close)
            remaining.append(trade)

    state.open_trades = remaining


def _close_opposite_trades(state: ModeState, symbol: str, action: str, row: pd.Series, event_time: pd.Timestamp) -> None:
    remaining: List[SimTrade] = []
    exit_price = float(row["close"])
    now = event_time

    for trade in state.open_trades:
        if trade.symbol == symbol and trade.action != action:
            _close_trade(state, trade, now, exit_price, "reverse_signal")
        else:
            remaining.append(trade)

    state.open_trades = remaining


def _slice_mdf(history: Dict[str, pd.DataFrame], indexes: Dict[str, np.ndarray], now: pd.Timestamp, bars: int) -> Dict[str, pd.DataFrame]:
    mdf: Dict[str, pd.DataFrame] = {}
    now64 = np.datetime64(now)
    for timeframe, df in history.items():
        times = indexes[timeframe]
        pos = int(np.searchsorted(times, now64, side="right"))
        if pos <= 0:
            continue
        start = max(0, pos - bars)
        mdf[timeframe] = df.iloc[start:pos].copy()
    return mdf


def _append_detection_rows(rows: List[dict], timestamp: pd.Timestamp, symbol: str, patterns: List[dict]) -> None:
    for pattern in patterns:
        rows.append({
            "timestamp": timestamp.isoformat(),
            "symbol": symbol,
            "timeframe": pattern.get("timeframe", ""),
            "pattern_name": pattern.get("name", ""),
            "category": pattern.get("category", ""),
            "direction": pattern.get("direction", ""),
            "confidence": pattern.get("confidence", 0),
            "priority": pattern.get("priority", ""),
        })


def _open_trade(
    state: ModeState,
    ticket: int,
    symbol: str,
    action: str,
    row: pd.Series,
    indicators: dict,
    signal: dict,
    risk_mgr: RiskManager,
    entry_time: pd.Timestamp,
    fixed_lot: float,
) -> SimTrade:
    entry = _entry_price(symbol, action, row)
    contract = _contract_size(symbol)
    trade_params = risk_mgr.get_trade_params(
        symbol=symbol,
        action=action,
        price=entry,
        balance=state.balance,
        pip_value=config.get_pip_multiplier(symbol),
        contract_size=contract,
        indicators=indicators,
    )

    if state.name == "fixed_lot":
        trade_params["lot"] = fixed_lot

    trade_params["lot"] = round(float(trade_params["lot"]), 2)
    patterns = list(indicators.get("detected_patterns") or [])
    compact_patterns = [
        {
            "name": p.get("name", ""),
            "category": p.get("category", ""),
            "direction": p.get("direction", ""),
            "timeframe": p.get("timeframe", ""),
            "confidence": p.get("confidence", 0),
            "priority": p.get("priority", ""),
        }
        for p in patterns
    ]

    return SimTrade(
        ticket=ticket,
        mode=state.name,
        symbol=symbol,
        action=action,
        lot=float(trade_params["lot"]),
        entry_time=entry_time,
        entry_price=entry,
        sl=float(trade_params["sl"]),
        tp=float(trade_params["tp"]),
        virtual_sl=float(trade_params["sl"]),
        sl_pips=int(trade_params["sl_pips"]),
        tp_pips=int(trade_params["tp_pips"]),
        atr=float(indicators.get("atr", 0) or 0),
        confidence=float(signal.get("confidence", 0) or 0),
        signal_reason=str(signal.get("reason", "")),
        patterns=compact_patterns,
        pattern_names=_pattern_names(compact_patterns),
        combo=_combo_key(compact_patterns),
        session=_session_name(entry_time),
    )


def _write_csv(path, rows: List[dict]) -> pd.DataFrame:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp_path, index=False)
    tmp_path.replace(path)
    return df


def _explode_pattern_trades(trades: pd.DataFrame) -> pd.DataFrame:
    rows: List[dict] = []
    if trades.empty:
        return pd.DataFrame(rows)

    for _, trade in trades.iterrows():
        try:
            patterns = json.loads(trade.get("patterns_json", "[]"))
        except Exception:
            patterns = []
        for pattern in patterns:
            rows.append({
                "mode": trade.get("mode", ""),
                "symbol": trade.get("symbol", ""),
                "timeframe": pattern.get("timeframe", ""),
                "pattern_name": pattern.get("name", ""),
                "category": pattern.get("category", ""),
                "direction": pattern.get("direction", ""),
                "confidence": pattern.get("confidence", 0),
                "profit": trade.get("profit", 0),
                "r_multiple": trade.get("r_multiple", 0),
                "session": trade.get("session", ""),
                "day_of_week": trade.get("day_of_week", ""),
            })
    return pd.DataFrame(rows)


def _build_pattern_ranking(detections: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if detections.empty:
        return pd.DataFrame()

    detected = (
        detections.groupby(["symbol", "timeframe", "pattern_name", "category"], dropna=False)
        .size()
        .reset_index(name="detected_count")
    )

    exploded = _explode_pattern_trades(trades)
    if exploded.empty:
        detected["used_in_trade_count"] = 0
        detected["win_count"] = 0
        detected["loss_count"] = 0
        detected["win_rate_pct"] = 0.0
        detected["net_profit"] = 0.0
        detected["avg_r"] = 0.0
        detected["avg_confidence"] = 0.0
        return detected.sort_values(["detected_count"], ascending=False)

    grouped = exploded.groupby(["symbol", "timeframe", "pattern_name", "category"], dropna=False)
    used = grouped.agg(
        used_in_trade_count=("profit", "size"),
        win_count=("profit", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum())),
        loss_count=("profit", lambda s: int((pd.to_numeric(s, errors="coerce") < 0).sum())),
        net_profit=("profit", lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).sum(), 2)),
        avg_r=("r_multiple", lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).mean(), 4)),
        avg_confidence=("confidence", lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).mean(), 4)),
    ).reset_index()
    used["win_rate_pct"] = used.apply(
        lambda r: round((r["win_count"] / r["used_in_trade_count"] * 100), 2) if r["used_in_trade_count"] else 0,
        axis=1,
    )

    ranking = detected.merge(used, on=["symbol", "timeframe", "pattern_name", "category"], how="left").fillna(0)
    return ranking.sort_values(["net_profit", "win_rate_pct", "used_in_trade_count"], ascending=[False, False, False])


def _build_combo_ranking(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "combo" not in trades.columns:
        return pd.DataFrame()

    grouped = trades.groupby(["mode", "symbol", "combo"], dropna=False)
    combo = grouped.agg(
        used_in_trade_count=("profit", "size"),
        win_count=("profit", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum())),
        loss_count=("profit", lambda s: int((pd.to_numeric(s, errors="coerce") < 0).sum())),
        net_profit=("profit", lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).sum(), 2)),
        avg_r=("r_multiple", lambda s: round(pd.to_numeric(s, errors="coerce").fillna(0).mean(), 4)),
    ).reset_index()
    combo["win_rate_pct"] = combo.apply(
        lambda r: round((r["win_count"] / r["used_in_trade_count"] * 100), 2) if r["used_in_trade_count"] else 0,
        axis=1,
    )
    return combo.sort_values(["net_profit", "win_rate_pct"], ascending=[False, False])


def run_backtest(cfg: BacktestConfig, history: HistoryBundle) -> dict:
    """Run the full historical replay and write CSV outputs."""
    cfg.ensure_dirs()
    fixed_state = ModeState("fixed_lot", cfg.start_balance)
    risk_state = ModeState("config_risk", cfg.start_balance)
    states = [fixed_state, risk_state]
    risk_mgr = RiskManager()
    detection_rows: List[dict] = []
    feature_rows: List[dict] = []
    ticket_counter = 100000
    last_entry_bar: Dict[Tuple[str, str], int] = {}

    for symbol in cfg.symbols:
        symbol_history = history.get(symbol, {})
        base = symbol_history.get(cfg.base_timeframe)
        if base is None or base.empty:
            continue

        symbol_history = {
            tf: df.copy().sort_values("time").reset_index(drop=True)
            for tf, df in symbol_history.items()
            if tf in cfg.timeframes and df is not None and not df.empty
        }
        indexes = {}
        for tf, df in symbol_history.items():
            close_times = pd.to_datetime(df["time"]) + pd.Timedelta(minutes=_timeframe_minutes(tf))
            indexes[tf] = close_times.to_numpy(dtype="datetime64[ns]")

        for bar_index, row in base.iterrows():
            now = pd.Timestamp(row["time"]) + pd.Timedelta(minutes=_timeframe_minutes(cfg.base_timeframe))
            for state in states:
                _manage_open_trades(state, row, now)

            if bar_index < cfg.warmup_bars or bar_index % cfg.signal_every_bars != 0:
                continue

            mdf = _slice_mdf(symbol_history, indexes, now, bars=max(cfg.warmup_bars, 150))
            if len(mdf) < len(cfg.timeframes):
                continue

            indicators = calculate_multi_indicators(mdf, symbol=symbol)
            if not indicators:
                continue

            patterns = list(indicators.get("detected_patterns") or [])
            _append_detection_rows(detection_rows, now, symbol, patterns)
            signal = _build_signal(indicators)

            feature_rows.append({
                "timestamp": now.isoformat(),
                "symbol": symbol,
                "session": _session_name(now),
                "signal_action": signal["action"],
                "signal_confidence": signal["confidence"],
                "signal_reason": signal["reason"],
                "h4_trend": indicators.get("h4_trend", ""),
                "market_regime": indicators.get("market_regime", ""),
                "adx": indicators.get("adx", 0),
                "m15_rsi": indicators.get("m15_rsi", 0),
                "atr": indicators.get("atr", 0),
                "pattern_bias": (indicators.get("pattern_bias") or {}).get("bias", ""),
                "pattern_count": len(patterns),
                "pattern_names": " | ".join(_pattern_names(patterns, limit=12)),
            })

            for state in states:
                if signal["action"] == "HOLD":
                    state.count("signal_hold")
                    continue

                state.count(f"signal_{signal['action'].lower()}")
                open_for_symbol = [t for t in state.open_trades if t.symbol == symbol]
                can_trade, risk_reason = risk_mgr.can_trade(symbol, len(open_for_symbol), indicators, trade_memory=None)
                if not can_trade:
                    state.count(f"risk_blocked_{risk_reason}")
                    continue

                valid, reason = risk_mgr.validate_signal(signal)
                if not valid:
                    state.count(f"signal_rejected_{reason}")
                    continue

                last_key = (state.name, symbol)
                previous_entry_bar = last_entry_bar.get(last_key, -10**9)
                if bar_index - previous_entry_bar < cfg.min_bars_between_entries:
                    state.count("skipped_min_bars_between_entries")
                    continue

                if len(open_for_symbol) >= cfg.max_open_trades_per_symbol:
                    state.count("skipped_max_open_trades")
                    continue

                _close_opposite_trades(state, symbol, signal["action"], row, now)
                ticket_counter += 1
                trade = _open_trade(
                    state,
                    ticket_counter,
                    symbol,
                    signal["action"],
                    row,
                    indicators,
                    signal,
                    risk_mgr,
                    now,
                    cfg.fixed_lot,
                )
                state.open_trades.append(trade)
                last_entry_bar[last_key] = bar_index
                state.count("trade_opened")

        # Close any remaining open trades for this symbol at the last base close.
        if not base.empty:
            final_row = base.iloc[-1]
            final_time = pd.Timestamp(final_row["time"]) + pd.Timedelta(minutes=_timeframe_minutes(cfg.base_timeframe))
            for state in states:
                still_open = []
                for trade in state.open_trades:
                    if trade.symbol == symbol:
                        _close_trade(state, trade, final_time, float(final_row["close"]), "end_of_data")
                    else:
                        still_open.append(trade)
                state.open_trades = still_open

    fixed_df = _write_csv(cfg.backtests_dir / "trades_fixed_lot.csv", fixed_state.closed_rows)
    risk_df = _write_csv(cfg.backtests_dir / "trades_config_risk.csv", risk_state.closed_rows)
    trades_df = pd.concat([fixed_df, risk_df], ignore_index=True) if not fixed_df.empty or not risk_df.empty else pd.DataFrame()
    detections_df = _write_csv(cfg.features_dir / "pattern_detections.csv", detection_rows)
    _write_csv(cfg.features_dir / "pattern_dataset.csv", feature_rows)

    pattern_ranking = _build_pattern_ranking(detections_df, trades_df)
    pattern_ranking.to_csv(cfg.backtests_dir / "pattern_ranking.csv", index=False)

    combo_ranking = _build_combo_ranking(trades_df)
    combo_ranking.to_csv(cfg.backtests_dir / "pattern_combo_ranking.csv", index=False)

    audit_rows = []
    for state in states:
        for key, count in sorted(state.audit.items()):
            audit_rows.append({"mode": state.name, "event": key, "count": count})
    _write_csv(cfg.backtests_dir / "decision_audit.csv", audit_rows)

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start": cfg.start.isoformat(),
        "end": cfg.end.isoformat(),
        "symbols": list(cfg.symbols),
        "timeframes": list(cfg.timeframes),
        "fixed_lot_trades": int(len(fixed_df)),
        "config_risk_trades": int(len(risk_df)),
        "pattern_detections": int(len(detections_df)),
        "method": "historical_pattern_replay_virtual_exits",
        "notes": [
            "No live orders were sent.",
            "SL/TP/trailing are simulated virtually.",
            "If SL and TP touch in the same candle, SL is counted first.",
            "AI calls are not replayed by default; the backtest uses deterministic pattern-bias replay.",
        ],
    }
    (cfg.backtests_dir / "backtest_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
