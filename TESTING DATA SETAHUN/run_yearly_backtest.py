"""Run the one-year historical backtest and generate the HTML report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
BOT_ENGINE_DIR = PROJECT_ROOT / "Bot Engine"
if str(BOT_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_ENGINE_DIR))

from research.backtest_config import BacktestConfig
from research.backtest_state import choose_backtest_window, save_completed_state
from research.historical_data_collector import collect_mt5_history, load_history, missing_history
from research.report_generator import generate_report
from research.virtual_exit_backtester import run_backtest


class BacktestAlreadyRunning(RuntimeError):
    """Raised when another yearly backtest process owns the lock."""


class BacktestRunLock:
    """Atomic lock file to prevent duplicate yearly backtest runs."""

    def __init__(
        self,
        path: Path,
        *,
        stale_seconds: int = 12 * 60 * 60,
        force_unlock: bool = False,
    ):
        self.path = path
        self.stale_seconds = stale_seconds
        self.force_unlock = force_unlock
        self.acquired = False

    def __enter__(self) -> "BacktestRunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.force_unlock and self.path.exists():
            self.path.unlink()

        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = {
                    "pid": os.getpid(),
                    "started_at": datetime.now().isoformat(timespec="seconds"),
                    "message": "Investment-AI_T yearly backtest is running.",
                }
                os.write(fd, json.dumps(payload, indent=2).encode("utf-8"))
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError as exc:
                if self._is_stale():
                    self.path.unlink()
                    continue
                raise BacktestAlreadyRunning(self._running_message()) from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _is_stale(self) -> bool:
        try:
            age = datetime.now().timestamp() - self.path.stat().st_mtime
        except FileNotFoundError:
            return False
        return age > self.stale_seconds

    def _running_message(self) -> str:
        details: Optional[str] = None
        try:
            details = self.path.read_text(encoding="utf-8").strip()
        except Exception:
            details = None

        message = (
            f"Yearly backtest already running. Lock file: {self.path}\n"
            "No duplicate run started, so CSV/report outputs will not be duplicated.\n"
            "If you are sure the old run crashed, rerun with: python run_yearly_backtest.py --force-unlock"
        )
        if details:
            message += f"\n\nCurrent lock details:\n{details}"
        return message


def _run_pipeline(args, cfg: BacktestConfig, run_mode: str, window_reason: str) -> int:
    print(f"Backtest window: {cfg.start:%Y-%m-%d} -> {cfg.end:%Y-%m-%d}")
    print(f"Run mode: {run_mode}")
    print(window_reason)

    if args.report_only:
        generate_report(cfg)
        print(f"Report generated: {cfg.report_path}")
        return 0

    if run_mode == "no_op":
        generate_report(cfg)
        print("No historical backtest started. Result files were not duplicated.")
        print(f"Report generated: {cfg.report_path}")
        return 0

    history = load_history(cfg)
    missing = missing_history(cfg, history)

    if missing and not args.skip_collect:
        try:
            history = collect_mt5_history(cfg)
            missing = missing_history(cfg, history)
        except Exception as exc:
            generate_report(cfg, pending_reason=str(exc))
            print(f"Backtest pending: {exc}")
            print(f"Report generated: {cfg.report_path}")
            return 2
    elif args.force_collect:
        try:
            history = collect_mt5_history(cfg)
            missing = missing_history(cfg, history)
        except Exception as exc:
            generate_report(cfg, pending_reason=str(exc))
            print(f"Backtest pending: {exc}")
            print(f"Report generated: {cfg.report_path}")
            return 2

    if missing:
        reason = "Missing historical data: " + ", ".join(missing)
        generate_report(cfg, pending_reason=reason)
        print(f"Backtest pending: {reason}")
        print(f"Report generated: {cfg.report_path}")
        return 2

    summary = run_backtest(cfg, history)
    save_completed_state(cfg, run_mode=run_mode, summary=summary)
    generate_report(cfg)
    print("Backtest completed.")
    print(f"Fixed lot trades: {summary['fixed_lot_trades']}")
    print(f"Config risk trades: {summary['config_risk_trades']}")
    print(f"Pattern detections: {summary['pattern_detections']}")
    print(f"Report generated: {cfg.report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Investment-AI_T one-year backtest report generator")
    parser.add_argument("--report-only", action="store_true", help="Only regenerate the HTML report from existing CSV outputs.")
    parser.add_argument("--skip-collect", action="store_true", help="Do not collect MT5 history; require existing storage/history CSV files.")
    parser.add_argument("--force-collect", action="store_true", help="Collect MT5 history again even if local files already exist.")
    parser.add_argument("--force-unlock", action="store_true", help="Remove a stale yearly backtest lock before starting.")
    parser.add_argument("--full-year", action="store_true", help="Ignore previous state and run the configured full-year window.")
    parser.add_argument("--include-gap", action="store_true", help="After a completed baseline, run only the missing historical gap.")
    parser.add_argument("--skip-gap", action="store_true", help="Do not auto-run a missing historical gap.")
    args = parser.parse_args()

    cfg = BacktestConfig.from_env()
    cfg.ensure_dirs()
    cfg, run_mode, window_reason = choose_backtest_window(
        cfg,
        force_full_year=args.full_year,
        include_gap=args.include_gap,
        skip_gap=args.skip_gap,
    )
    cfg.ensure_dirs()

    lock_path = cfg.backtests_dir / "yearly_backtest.lock"
    stale_seconds = int(os.getenv("BACKTEST_LOCK_STALE_SECONDS", str(12 * 60 * 60)))
    try:
        with BacktestRunLock(lock_path, stale_seconds=stale_seconds, force_unlock=args.force_unlock):
            return _run_pipeline(args, cfg, run_mode, window_reason)
    except BacktestAlreadyRunning as exc:
        print(str(exc))
        return 3


if __name__ == "__main__":
    sys.exit(main())
