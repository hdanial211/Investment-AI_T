"""State helpers for duplicate-safe yearly backtest windows."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
import os

from research.backtest_config import BacktestConfig


STATE_FILE_NAME = "yearly_backtest_state.json"
LIVE_DATA_STATE_FILE_NAME = "live_data_state.json"


def state_path(cfg: BacktestConfig) -> Path:
    return cfg.backtests_dir / STATE_FILE_NAME


def live_data_state_path(cfg: BacktestConfig) -> Path:
    return cfg.live_dir / LIVE_DATA_STATE_FILE_NAME


def load_state(cfg: BacktestConfig) -> dict:
    path = state_path(cfg)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_live_data_state(cfg: BacktestConfig) -> dict:
    path = live_data_state_path(cfg)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _parse_datetime(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _latest_live_coverage_end(cfg: BacktestConfig) -> Optional[datetime]:
    """
    Read the future live/realtime data checkpoint.

    The live engine can update TESTING DATA SETAHUN/storage/live/live_data_state.json with either:
    - covered_until
    - last_realtime_data_at
    - last_seen_at

    If this reaches today's requested end, the yearly runner does not replay
    that period again.
    """
    live_state = load_live_data_state(cfg)
    candidates = [
        _parse_datetime(live_state.get("covered_until")),
        _parse_datetime(live_state.get("last_realtime_data_at")),
        _parse_datetime(live_state.get("last_seen_at")),
    ]
    candidates = [value for value in candidates if value is not None]
    if not candidates:
        return None
    return max(candidates)


def save_completed_state(cfg: BacktestConfig, *, run_mode: str, summary: dict) -> None:
    path = state_path(cfg)
    payload = {
        "last_completed_start": cfg.start.isoformat(),
        "last_completed_end": cfg.end.isoformat(),
        "last_completed_at": datetime.now().isoformat(timespec="seconds"),
        "run_mode": run_mode,
        "symbols": list(cfg.symbols),
        "timeframes": list(cfg.timeframes),
        "fixed_lot_trades": summary.get("fixed_lot_trades", 0),
        "config_risk_trades": summary.get("config_risk_trades", 0),
        "pattern_detections": summary.get("pattern_detections", 0),
        "note": (
            "Future default runs continue from the last completed/live data date. "
            "If live data covers the gap, the run becomes a no-op."
        ),
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def choose_backtest_window(
    cfg: BacktestConfig,
    *,
    force_full_year: bool = False,
    include_gap: bool = False,
    skip_gap: bool = False,
) -> Tuple[BacktestConfig, str, str]:
    """
    Decide the safe run window.

    First run uses the normal one-year window. Later default runs continue from
    the latest completed/live data date if the bot has been offline long enough.
    If live data already covers the gap, the run becomes a no-op.
    """
    state = load_state(cfg)
    last_end_text = state.get("last_completed_end")
    auto_gap_days = float(os.getenv("BACKTEST_AUTO_GAP_AFTER_DAYS", "1"))
    live_grace_hours = float(os.getenv("BACKTEST_LIVE_COVERAGE_GRACE_HOURS", "6"))

    if force_full_year or not last_end_text:
        return cfg, "full_year", "No previous completed yearly baseline found."

    try:
        last_end = datetime.fromisoformat(last_end_text)
    except ValueError:
        return cfg, "full_year", "Previous state is unreadable; running full configured window."

    if cfg.end <= last_end:
        no_op_cfg = replace(cfg, start=last_end, end=last_end)
        return no_op_cfg, "no_op", "No new days to test since the last completed yearly baseline."

    live_coverage_end = _latest_live_coverage_end(cfg)
    coverage_end = max(value for value in (last_end, live_coverage_end) if value is not None)

    if not include_gap:
        grace_seconds = live_grace_hours * 60 * 60
        live_covers_end = live_coverage_end is not None and (cfg.end.timestamp() - live_coverage_end.timestamp()) <= grace_seconds
        if live_covers_end or skip_gap:
            no_op_cfg = replace(cfg, start=coverage_end, end=coverage_end)
            reason = (
                "Live realtime data already covers the period after the yearly baseline."
                if live_covers_end
                else "Historical gap intentionally skipped."
            )
            return no_op_cfg, "no_op", reason

        gap_days = max(0.0, (cfg.end - coverage_end).total_seconds() / 86400)
        if gap_days < auto_gap_days:
            no_op_cfg = replace(cfg, start=coverage_end, end=coverage_end)
            return (
                no_op_cfg,
                "no_op",
                (
                    f"Only {gap_days:.2f} day(s) are missing since last completed/live data. "
                    f"Auto-gap starts after {auto_gap_days:g} day(s)."
                ),
            )

        gap_cfg = replace(cfg, start=coverage_end, end=cfg.end)
        return (
            gap_cfg,
            "auto_gap",
            (
                f"No live coverage found up to today. Continuing from last completed/live data "
                f"({coverage_end:%Y-%m-%d %H:%M}) to {cfg.end:%Y-%m-%d %H:%M}."
            ),
        )

    gap_cfg = replace(cfg, start=coverage_end, end=cfg.end)
    return gap_cfg, "incremental_gap", f"Running only the gap from {coverage_end:%Y-%m-%d} to {cfg.end:%Y-%m-%d}."
