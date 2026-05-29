"""
run_backtest.py - CLI Runner for Investment-AI_T Backtesting System
====================================================================
Usage:
    python run_backtest.py                          # Quick run with defaults (XAUUSD, all styles)
    python run_backtest.py --symbol EURUSD          # EURUSD only
    python run_backtest.py --symbol XAUUSD EURUSD   # Both symbols
    python run_backtest.py --style INTRADAY         # One style only
    python run_backtest.py --balance 5000           # Custom starting balance
    python run_backtest.py --from 2024-01-01        # Custom start date
    python run_backtest.py --settings               # Open settings UI in browser

Options come from command line OR from backtest_settings.json (saved by settings UI).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from string import Template

# ── Paths ─────────────────────────────────────────────────────────────────────
TESTING_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = TESTING_ROOT / "reports"
SETTINGS_FILE = TESTING_ROOT / "backtest_settings.json"
REPORT_TEMPLATE = TESTING_ROOT / "backtest_report.html"
SETTINGS_PAGE = TESTING_ROOT / "backtest_settings.html"


def load_saved_settings() -> dict:
    """Load settings from backtest_settings.json if it exists."""
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def parse_args(saved: dict) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Investment-AI_T Backtesting System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--symbol", nargs="+",
        default=saved.get("symbols", ["XAUUSD"]),
        help="Symbol(s) to backtest (e.g. XAUUSD EURUSD)",
    )
    parser.add_argument(
        "--style", nargs="+",
        default=saved.get("styles", ["SCALPING", "INTRADAY", "SWING"]),
        choices=["SCALPING", "INTRADAY", "SWING"],
        help="Trade style(s) to test",
    )
    parser.add_argument(
        "--balance", type=float,
        default=saved.get("start_balance", 10000.0),
        help="Starting account balance (default: 10000)",
    )
    parser.add_argument(
        "--lot", type=float,
        default=saved.get("fixed_lot", 0.01),
        help="Fixed lot size when --no-dynamic-lot is used",
    )
    parser.add_argument(
        "--no-dynamic-lot", action="store_true",
        default=not saved.get("use_dynamic_lot", True),
        help="Use fixed lot size instead of risk-based sizing",
    )
    parser.add_argument(
        "--from", dest="start_date",
        default=saved.get("start_date", ""),
        help="Start date (YYYY-MM-DD). Default: 1 year ago",
    )
    parser.add_argument(
        "--to", dest="end_date",
        default=saved.get("end_date", ""),
        help="End date (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--confidence", type=float,
        default=saved.get("min_confidence", 0.55),
        help="Minimum signal confidence threshold (0.0-1.0)",
    )
    parser.add_argument(
        "--no-open", action="store_true",
        help="Do not auto-open the report in browser",
    )
    parser.add_argument(
        "--settings", action="store_true",
        help="Open the settings UI in browser instead of running backtest",
    )
    return parser.parse_args()


def build_report(results: dict, template_path: Path, output_path: Path) -> None:
    """Inject JSON data into HTML template and write the report."""
    template = template_path.read_text(encoding="utf-8")
    data_json = json.dumps(results, indent=2, default=str)
    html = template.replace("__BACKTEST_DATA__", data_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def main() -> int:
    saved = load_saved_settings()
    args = parse_args(saved)

    # ── Open settings UI ─────────────────────────────────────────────────────
    if args.settings:
        if SETTINGS_PAGE.exists():
            print(f"Opening settings: {SETTINGS_PAGE}")
            webbrowser.open(SETTINGS_PAGE.as_uri())
        else:
            print(f"[ERROR] Settings page not found: {SETTINGS_PAGE}")
        return 0

    # ── Parse dates ──────────────────────────────────────────────────────────
    end_date = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    start_date = end_date - timedelta(days=365)

    if args.end_date:
        try:
            end_date = datetime.fromisoformat(args.end_date)
        except ValueError:
            print(f"[ERROR] Invalid end date: {args.end_date}")
            return 1

    if args.start_date:
        try:
            start_date = datetime.fromisoformat(args.start_date)
        except ValueError:
            print(f"[ERROR] Invalid start date: {args.start_date}")
            return 1

    # ── Import engine ────────────────────────────────────────────────────────
    try:
        from backtest_engine import BacktestConfig, run_full_backtest
    except ImportError as e:
        print(f"[ERROR] Could not import backtest_engine: {e}")
        return 1

    symbols = [s.upper() for s in args.symbol]
    styles = [s.upper() for s in args.style]
    use_dynamic_lot = not args.no_dynamic_lot

    # ── Run for each symbol ──────────────────────────────────────────────────
    all_symbol_results = {}

    for symbol in symbols:
        cfg = BacktestConfig(
            symbol=symbol,
            trade_styles=styles,
            start_balance=args.balance,
            fixed_lot=args.lot,
            use_dynamic_lot=use_dynamic_lot,
            start_date=start_date,
            end_date=end_date,
            min_confidence=args.confidence,
        )
        result = run_full_backtest(cfg)
        if result:
            all_symbol_results[symbol] = result

    if not all_symbol_results:
        print("\n[ERROR] Backtest produced no results. Check data availability.")
        return 1

    # ── Combine results ──────────────────────────────────────────────────────
    combined = {
        "symbols": symbols,
        "styles": styles,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "start_balance": args.balance,
        "use_dynamic_lot": use_dynamic_lot,
        "generated_at": datetime.now().isoformat(),
        "results": all_symbol_results,
    }

    # ── Generate report ──────────────────────────────────────────────────────
    if not REPORT_TEMPLATE.exists():
        print(f"[ERROR] Report template not found: {REPORT_TEMPLATE}")
        return 1

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"backtest_{'-'.join(symbols)}_{ts}.html"
    output_path = REPORTS_DIR / output_name

    build_report(combined, REPORT_TEMPLATE, output_path)

    print(f"\n{'='*60}")
    print(f"✅ Backtest complete!")
    print(f"   Report: {output_path}")
    print(f"{'='*60}\n")

    # ── Auto-open report ─────────────────────────────────────────────────────
    if not args.no_open:
        webbrowser.open(output_path.as_uri())

    return 0


if __name__ == "__main__":
    sys.exit(main())
