"""Phase 9 live readiness checker.

This script is intentionally conservative. It checks whether the local Windows
machine is prepared for a 24-hour demo/small-lot run without printing secrets.
It does not start MT5, open trades, or call paid AI endpoints.
"""

from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = REPO_ROOT / "Bot Engine"
ENV_FILE = BOT_DIR / ".env"
ENV_EXAMPLE = REPO_ROOT / "Setup" / ".env.example"

REQUIRED_PACKAGES = {
    "requests": "requests",
    "pandas": "pandas",
    "numpy": "numpy",
    "dotenv": "python-dotenv",
    "loguru": "loguru",
    "textual": "textual",
    "rich": "rich",
    "MetaTrader5": "MetaTrader5",
}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def is_blank(value: str | None) -> bool:
    return not value or value.strip() in {"", "CHANGE_ME", "your_password"}


def env_bool(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = values.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


class Reporter:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def ok(self, message: str) -> None:
        print(f"[OK]   {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"[WARN] {message}")

    def fail(self, message: str) -> None:
        self.errors.append(message)
        print(f"[FAIL] {message}")

    def info(self, message: str) -> None:
        print(f"[INFO] {message}")

    def section(self, title: str) -> None:
        print()
        print(f"== {title} ==")


def check_files(report: Reporter) -> None:
    report.section("Project Files")
    for path in [
        REPO_ROOT / "start_bot.bat",
        BOT_DIR / "start_bot.bat",
        BOT_DIR / "main.py",
        BOT_DIR / "dashboard.py",
        REPO_ROOT / "Dashboard" / "index.html",
        REPO_ROOT / "Setup" / "supabase_schema.sql",
        REPO_ROOT / "Setup" / "run_smoke_tests.py",
    ]:
        if path.exists():
            report.ok(f"Found {path.relative_to(REPO_ROOT)}")
        else:
            report.fail(f"Missing {path.relative_to(REPO_ROOT)}")

    if ENV_FILE.exists():
        report.ok("Found Bot Engine/.env")
    else:
        report.fail("Missing Bot Engine/.env. Run Setup/setup_env.bat first.")

    if ENV_EXAMPLE.exists():
        report.ok("Found Setup/.env.example")


def check_python_packages(report: Reporter) -> None:
    report.section("Python")
    report.info(f"Python {sys.version.split()[0]} at {sys.executable}")
    if sys.version_info < (3, 10):
        report.fail("Python 3.10+ is required for the live laptop run.")
    else:
        report.ok("Python version is 3.10+.")

    for import_name, package_name in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(import_name):
            report.ok(f"Package available: {package_name}")
        else:
            message = f"Package missing: {package_name}. Run pip install -r Setup/requirements.txt"
            if package_name == "MetaTrader5" and platform.system() != "Windows":
                report.warn(message)
            else:
                report.fail(message)


def check_env(report: Reporter, values: dict[str, str]) -> None:
    report.section("Local .env")
    if not values:
        report.fail("Cannot validate settings because Bot Engine/.env is missing or empty.")
        return

    for key in ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"]:
        if is_blank(values.get(key)):
            report.fail(f"{key} is missing or still placeholder.")
        else:
            report.ok(f"{key} is set.")

    symbols = [item.strip() for item in values.get("SYMBOLS", "").split(",") if item.strip()]
    if symbols:
        report.ok(f"Trading symbols: {', '.join(symbols)}")
    else:
        report.fail("SYMBOLS is empty.")

    max_risk = parse_float(values.get("MAX_RISK_PERCENT"), 2.0)
    max_lot = parse_float(values.get("MAX_LOT"), 1.0)
    min_lot = parse_float(values.get("MIN_LOT"), 0.01)
    if max_risk > 2.0:
        report.warn(f"MAX_RISK_PERCENT={max_risk} is above Phase 9 recommended demo limit of 2.0.")
    else:
        report.ok(f"MAX_RISK_PERCENT={max_risk}")

    if min_lot <= max_lot <= 0.10:
        report.ok(f"Lot cap suitable for first 24h run: MIN_LOT={min_lot}, MAX_LOT={max_lot}")
    elif max_lot > 0.10:
        report.warn(f"MAX_LOT={max_lot} is high for first 24h validation. Consider 0.01-0.10.")
    else:
        report.fail(f"Invalid lot range: MIN_LOT={min_lot}, MAX_LOT={max_lot}")

    use_broker_sl_tp = env_bool(values, "USE_BROKER_SL_TP", False)
    use_virtual_sl_tp = env_bool(values, "USE_VIRTUAL_SL_TP", True)
    use_virtual_trailing = env_bool(values, "USE_VIRTUAL_TRAILING_STOP", True)
    if not use_broker_sl_tp and not use_virtual_sl_tp:
        report.fail("Both USE_BROKER_SL_TP and USE_VIRTUAL_SL_TP are disabled.")
    elif use_virtual_sl_tp:
        report.ok("Virtual SL/TP enabled.")
    else:
        report.warn("Virtual SL/TP disabled; broker-side SL/TP must be verified.")

    if use_virtual_trailing:
        report.ok("Virtual trailing stop enabled.")
    else:
        report.warn("Virtual trailing stop disabled.")

    provider = values.get("AI_PROVIDER", "openrouter").strip().lower()
    fallback_enabled = env_bool(values, "AI_FALLBACK_ENABLED", False)
    if provider == "openrouter":
        require_secret(report, values, "OPENROUTER_API_KEY")
    elif provider in {"huggingface", "hf"}:
        require_secret(report, values, "HF_TOKEN")
    else:
        report.fail(f"Unsupported AI_PROVIDER={provider}")

    if fallback_enabled:
        require_secret(report, values, "HF_TOKEN", label="HF_TOKEN for fallback")
    else:
        report.warn("AI_FALLBACK_ENABLED=False. Main provider must be reliable for the 24h run.")

    if env_bool(values, "SUPABASE_SYNC_ENABLED", False):
        for key in ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]:
            require_secret(report, values, key)
        if env_bool(values, "PATTERN_USAGE_SYNC_ENABLED", False):
            report.ok("Pattern usage Supabase sync enabled.")
        else:
            report.warn("Supabase enabled but PATTERN_USAGE_SYNC_ENABLED=False.")
    else:
        report.warn("SUPABASE_SYNC_ENABLED=False. Vercel/realtime heartbeat cannot be verified.")


def check_windows_power(report: Reporter) -> None:
    report.section("24-hour Machine")
    if platform.system() != "Windows":
        report.warn("Not running on Windows. Re-run this checker on the trading laptop before live test.")
        return

    report.ok("Running on Windows.")
    try:
        output = subprocess.check_output(["powercfg", "/getactivescheme"], text=True, stderr=subprocess.STDOUT)
        report.info(output.strip())
    except Exception as exc:
        report.warn(f"Could not read Windows power plan: {exc}")

    try:
        output = subprocess.check_output(["powercfg", "/query"], text=True, stderr=subprocess.STDOUT, timeout=10)
        if "Hibernate after" in output or "Sleep after" in output:
            report.info("Power settings readable. Confirm Sleep after = Never while plugged in.")
        else:
            report.warn("Could not identify sleep settings from powercfg output.")
    except Exception as exc:
        report.warn(f"Could not inspect sleep settings: {exc}")


def check_vision_ai(report: Reporter, values: dict[str, str]) -> None:
    """Check Vision AI configuration if enabled."""
    report.section("Vision AI")
    if not env_bool(values, "VISION_AI_ENABLED", False):
        report.warn("VISION_AI_ENABLED=False. Chart vision pipeline is disabled.")
        return

    report.ok("VISION_AI_ENABLED=True")

    # Check CHART_IMAGE_SOURCE
    source = values.get("CHART_IMAGE_SOURCE", "").strip().lower()
    if source in ("mt5_automation", "mt5", "browser_automation"):
        report.ok(f"CHART_IMAGE_SOURCE={source}")
    else:
        report.fail(f"CHART_IMAGE_SOURCE={source} is invalid. Use mt5_automation or browser_automation.")

    # Check screenshot folder
    screenshots_dir = BOT_DIR / values.get("MT5_SCREENSHOT_DIR", "chart_screenshots")
    if screenshots_dir.exists():
        report.ok(f"Screenshot folder exists: {screenshots_dir.relative_to(REPO_ROOT)}")
    else:
        report.warn(f"Screenshot folder not found. Will be created at runtime.")

    # Check vision model
    vision_model = values.get("VISION_AI_MODEL", "")
    if vision_model and vision_model != "CHANGE_ME":
        report.ok(f"VISION_AI_MODEL={vision_model}")
    else:
        report.warn("VISION_AI_MODEL not set. Will use default google/gemini-2.0-flash-001.")

    # Check timeframes
    timeframes = values.get("CHART_IMAGE_TIMEFRAMES", "")
    if timeframes:
        report.ok(f"CHART_IMAGE_TIMEFRAMES={timeframes}")
    else:
        report.warn("CHART_IMAGE_TIMEFRAMES not set. Will use default H4,H1,M30,M15,M5,M1.")

    # Check matplotlib dependency
    if importlib.util.find_spec("matplotlib"):
        report.ok("matplotlib package available for chart rendering fallback.")
    else:
        report.warn("matplotlib package missing. Chart fallback rendering will be unavailable.")

    # Check vision cycle interval
    try:
        interval = int(values.get("VISION_CYCLE_INTERVAL", "1"))
        if interval >= 1:
            report.ok(f"VISION_CYCLE_INTERVAL={interval} (vision runs every {interval} cycle(s))")
        else:
            report.fail("VISION_CYCLE_INTERVAL must be >= 1.")
    except ValueError:
        report.fail("VISION_CYCLE_INTERVAL is not a valid integer.")


def check_supabase_rest(report: Reporter, values: dict[str, str]) -> None:
    report.section("Supabase REST")
    if not env_bool(values, "SUPABASE_SYNC_ENABLED", False):
        report.warn("Skipped because SUPABASE_SYNC_ENABLED=False.")
        return

    url = (values.get("SUPABASE_URL") or "").rstrip("/")
    key = values.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if is_blank(url) or is_blank(key):
        report.fail("Supabase URL/service role key missing.")
        return

    try:
        import requests
    except ImportError:
        report.fail("requests package missing, cannot test Supabase REST.")
        return

    # Verify all 5 tables are accessible
    tables = [
        "bot_heartbeat",
        "active_trades",
        "trade_pattern_usage",
        "pattern_usage_stats",
        "trade_events",
    ]
    timeout = int(values.get("SUPABASE_REQUEST_TIMEOUT", "10"))

    for table in tables:
        endpoint = f"{url}/rest/v1/{table}?select=*&limit=1"
        try:
            response = requests.get(
                endpoint,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                timeout=timeout,
            )
            if response.status_code < 400:
                report.ok(f"Table {table} is readable.")
            else:
                report.fail(f"Table {table} returned HTTP {response.status_code}. Check schema/key/RLS.")
        except Exception as exc:
            report.fail(f"Supabase REST request for {table} failed: {exc}")


def parse_float(raw: str | None, default: float) -> float:
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def require_secret(report: Reporter, values: dict[str, str], key: str, label: str | None = None) -> None:
    name = label or key
    if is_blank(values.get(key)):
        report.fail(f"{name} is missing or still placeholder.")
    else:
        report.ok(f"{name} is set.")


def print_next_steps(report: Reporter) -> None:
    report.section("Result")
    if report.errors:
        print(f"NOT READY: {len(report.errors)} blocking issue(s), {len(report.warnings)} warning(s).")
        print("Fix the [FAIL] items first, then run Setup/live_readiness_check.bat again.")
        return

    if report.warnings:
        print(f"READY WITH WARNINGS: {len(report.warnings)} warning(s).")
    else:
        print("READY: Phase 9 pre-flight checks passed.")

    print("Next: keep laptop plugged in, disable sleep, then run start_bot.bat for the 24-hour demo/small-lot test.")


def main(argv: Iterable[str] | None = None) -> int:
    args = set(argv if argv is not None else sys.argv[1:])
    report = Reporter()
    values = load_env_file(ENV_FILE)

    check_files(report)
    check_python_packages(report)
    check_env(report, values)
    check_vision_ai(report, values)
    check_windows_power(report)

    if "--skip-supabase" in args:
        report.section("Supabase REST")
        report.warn("Skipped by --skip-supabase.")
    else:
        check_supabase_rest(report, values)

    print_next_steps(report)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
