"""Configuration for the one-year historical backtest pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Tuple

import config


TESTING_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = TESTING_ROOT / "storage"
DEFAULT_REPORT_PATH = TESTING_ROOT / "reports" / "data setahun dari 25may2026.html"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _symbols_from_config() -> Tuple[str, ...]:
    symbols = tuple(s.strip().upper() for s in config.SYMBOLS if s.strip())
    return symbols or ("XAUUSD", "EURUSD")


def _one_year_before(value: datetime) -> datetime:
    try:
        return value.replace(year=value.year - 1, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return value.replace(year=value.year - 1, day=28, hour=0, minute=0, second=0, microsecond=0)


def _parse_start_datetime(value: str, default_end: datetime) -> datetime:
    if not value:
        return _one_year_before(default_end)
    return datetime.fromisoformat(value)


def _parse_end_datetime(value: str) -> datetime:
    if not value:
        return datetime.now().replace(microsecond=0)
    parsed = datetime.fromisoformat(value)
    if "T" not in value and " " not in value:
        return parsed.replace(hour=23, minute=59, second=59)
    return parsed


@dataclass(frozen=True)
class BacktestConfig:
    """Small immutable config object used by collector, backtester, and report."""

    start: datetime
    end: datetime
    symbols: Tuple[str, ...]
    timeframes: Tuple[str, ...]
    base_timeframe: str
    warmup_bars: int
    signal_every_bars: int
    min_bars_between_entries: int
    fixed_lot: float
    start_balance: float
    max_open_trades_per_symbol: int
    data_dir: Path
    history_dir: Path
    features_dir: Path
    backtests_dir: Path
    live_dir: Path
    report_path: Path
    allow_demo_data: bool

    @classmethod
    def from_env(cls) -> "BacktestConfig":
        data_dir = Path(os.getenv("BACKTEST_DATA_DIR", str(DEFAULT_DATA_DIR)))
        end_text = os.getenv("BACKTEST_END", "")
        end = _parse_end_datetime(end_text)
        start_text = os.getenv("BACKTEST_START", "")

        return cls(
            start=_parse_start_datetime(start_text, end),
            end=end,
            symbols=_symbols_from_config(),
            timeframes=("M5", "M15", "H1", "H4"),
            base_timeframe=os.getenv("BACKTEST_BASE_TIMEFRAME", "M5").upper(),
            warmup_bars=int(os.getenv("BACKTEST_WARMUP_BARS", "120")),
            signal_every_bars=max(1, int(os.getenv("BACKTEST_SIGNAL_EVERY_BARS", "1"))),
            min_bars_between_entries=max(0, int(os.getenv("BACKTEST_MIN_BARS_BETWEEN_ENTRIES", "12"))),
            fixed_lot=float(os.getenv("BACKTEST_FIXED_LOT", "0.01")),
            start_balance=float(os.getenv("BACKTEST_START_BALANCE", "10000")),
            max_open_trades_per_symbol=int(
                os.getenv("BACKTEST_MAX_OPEN_TRADES_PER_SYMBOL", str(config.MAX_TRADES_PER_PAIR))
            ),
            data_dir=data_dir,
            history_dir=data_dir / "history",
            features_dir=data_dir / "features",
            backtests_dir=data_dir / "backtests",
            live_dir=data_dir / "live",
            report_path=Path(os.getenv("BACKTEST_REPORT_PATH", str(DEFAULT_REPORT_PATH))),
            allow_demo_data=_env_bool("BACKTEST_ALLOW_DEMO_DATA", False),
        )

    @property
    def date_token(self) -> str:
        return f"{self.start:%Y%m%d}_{self.end:%Y%m%d}"

    def ensure_dirs(self) -> None:
        for path in (self.history_dir, self.features_dir, self.backtests_dir, self.live_dir, self.report_path.parent):
            path.mkdir(parents=True, exist_ok=True)
