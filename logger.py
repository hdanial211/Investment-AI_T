"""
logger.py - Trade & Decision Logging System

Logs:
- Every AI decision (action, confidence, reason)
- Every trade execution (symbol, action, lot, price, SL, TP)
- Errors and system events
- CSV trade journal for analysis
"""

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import config


# ─────────────────────────────────────────────────────────────────────────────
# SETUP APPLICATION LOGGER
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """
    Configure root logger with:
    - File handler (bot.log) — full DEBUG level
    - Console handler — INFO level with colored output
    """
    Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # Capture everything

    # ── File handler ──────────────────────────────────────────────────────
    file_handler = logging.FileHandler(config.APP_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    # ── Console handler ───────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(_ColorFormatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    ))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("trading_bot")


class _ColorFormatter(logging.Formatter):
    """Add ANSI color codes to console log levels."""
    COLORS = {
        "DEBUG":    "\033[36m",   # Cyan
        "INFO":     "\033[32m",   # Green
        "WARNING":  "\033[33m",   # Yellow
        "ERROR":    "\033[31m",   # Red
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE JOURNAL (CSV)
# ─────────────────────────────────────────────────────────────────────────────

# CSV column headers
TRADE_CSV_HEADERS = [
    "timestamp", "symbol", "action", "lot", "entry_price",
    "sl", "tp", "sl_pips", "tp_pips",
    "ai_confidence", "ai_reason",
    "ticket", "status", "profit",
    "balance_after", "consecutive_losses",
    "ema_fast", "ema_slow", "rsi", "macd", "trend",
    "pattern_bias", "detected_patterns",
    "risk_review_approved", "risk_review_reason",
    "raw_ai_response",
]


class TradeLogger:
    """
    Manages the CSV trade journal.
    One row per trade attempt (win, loss, or rejected).
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._ensure_csv()

    def _ensure_csv(self):
        """Create CSV file with headers if it doesn't exist."""
        Path(config.LOG_DIR).mkdir(parents=True, exist_ok=True)

        if not os.path.exists(config.TRADE_LOG_FILE):
            with open(config.TRADE_LOG_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_CSV_HEADERS)
                writer.writeheader()
            self._logger.info(f"Created trade log: {config.TRADE_LOG_FILE}")

    def log_trade(
        self,
        symbol:      str,
        action:      str,
        signal:      Dict,
        trade_params: Optional[Dict],
        exec_result: Optional[Dict],
        indicators:  Dict,
        balance:     float,
        consecutive_losses: int,
        profit:      float = 0.0,
    ):
        """
        Write a complete trade record to CSV.
        Called after every trade attempt (success or failure).
        """
        row = {
            "timestamp":           datetime.now().isoformat(),
            "symbol":              symbol,
            "action":              action,
            "lot":                 trade_params.get("lot", 0)   if trade_params else 0,
            "entry_price":         indicators.get("price", 0),
            "sl":                  trade_params.get("sl", 0)    if trade_params else 0,
            "tp":                  trade_params.get("tp", 0)    if trade_params else 0,
            "sl_pips":             trade_params.get("sl_pips", 0) if trade_params else 0,
            "tp_pips":             trade_params.get("tp_pips", 0) if trade_params else 0,
            "ai_confidence":       signal.get("confidence", 0),
            "ai_reason":           signal.get("reason", ""),
            "ticket":              exec_result.get("ticket", "") if exec_result else "",
            "status":              "FILLED" if (exec_result and exec_result.get("success")) else "REJECTED",
            "profit":              profit,
            "balance_after":       round(balance, 2),
            "consecutive_losses":  consecutive_losses,
            "ema_fast":            indicators.get("ema_fast", 0),
            "ema_slow":            indicators.get("ema_slow", 0),
            "rsi":                 indicators.get("rsi", 0),
            "macd":                indicators.get("macd", 0),
            "trend":               indicators.get("trend", ""),
            "pattern_bias":         (indicators.get("pattern_bias") or {}).get("bias", ""),
            "detected_patterns":    _format_pattern_names(indicators),
            "risk_review_approved": _format_risk_review(signal, "approved"),
            "risk_review_reason":   _format_risk_review(signal, "reason"),
            "raw_ai_response":     (signal.get("raw_response", "") or "")[:200],
        }

        try:
            with open(config.TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_CSV_HEADERS)
                writer.writerow(row)
        except IOError as e:
            self._logger.error(f"Failed to write trade log: {e}")

    def log_skipped(
        self,
        symbol:     str,
        reason:     str,
        signal:     Optional[Dict] = None,
        indicators: Optional[Dict] = None,
    ):
        """Log when a cycle was skipped (no trade taken)."""
        self._logger.debug(f"[{symbol}] SKIPPED: {reason}")

        # Optionally write to CSV with SKIPPED status
        indicators = indicators or {}
        signal     = signal or {}

        row = {
            "timestamp":          datetime.now().isoformat(),
            "symbol":             symbol,
            "action":             "SKIPPED",
            "lot":                0,
            "entry_price":        indicators.get("price", 0),
            "sl":                 0,
            "tp":                 0,
            "sl_pips":            0,
            "tp_pips":            0,
            "ai_confidence":      signal.get("confidence", 0),
            "ai_reason":          reason,
            "ticket":             "",
            "status":             "SKIPPED",
            "profit":             0,
            "balance_after":      0,
            "consecutive_losses": 0,
            "ema_fast":           indicators.get("ema_fast", 0),
            "ema_slow":           indicators.get("ema_slow", 0),
            "rsi":                indicators.get("rsi", 0),
            "macd":               indicators.get("macd", 0),
            "trend":              indicators.get("trend", ""),
            "pattern_bias":        (indicators.get("pattern_bias") or {}).get("bias", ""),
            "detected_patterns":   _format_pattern_names(indicators),
            "risk_review_approved": _format_risk_review(signal, "approved"),
            "risk_review_reason":   _format_risk_review(signal, "reason"),
            "raw_ai_response":    "",
        }
        try:
            with open(config.TRADE_LOG_FILE, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=TRADE_CSV_HEADERS)
                writer.writerow(row)
        except IOError:
            pass


def _format_pattern_names(indicators: Dict) -> str:
    """Compact pattern names for the CSV journal."""
    patterns = indicators.get("detected_patterns") or []
    names = [
        f"{p.get('timeframe')}:{p.get('name')}:{p.get('direction')}"
        for p in patterns[:10]
    ]
    return " | ".join(names)


def _format_risk_review(signal: Dict, field: str) -> str:
    review = signal.get("risk_review") or {}
    if not review:
        return ""
    value = review.get(field, "")
    return str(value)


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

def load_trades():
    """
    Load the trade journal for dashboard views.
    Returns an empty DataFrame with the expected columns if no log exists yet.
    """
    import pandas as pd

    if not os.path.exists(config.TRADE_LOG_FILE):
        return pd.DataFrame(columns=TRADE_CSV_HEADERS)

    try:
        df = pd.read_csv(config.TRADE_LOG_FILE)
    except Exception:
        return pd.DataFrame(columns=TRADE_CSV_HEADERS)

    for column in TRADE_CSV_HEADERS:
        if column not in df.columns:
            df[column] = ""

    return df

def generate_performance_report() -> Dict:
    """
    Read trades.csv and compute performance statistics.
    Returns dict with win rate, avg profit, max drawdown, etc.
    """
    import pandas as pd

    if not os.path.exists(config.TRADE_LOG_FILE):
        return {"error": "No trade log found"}

    try:
        df = pd.read_csv(config.TRADE_LOG_FILE)
    except Exception as e:
        return {"error": str(e)}

    if df.empty:
        return {"error": "No trades recorded yet"}

    # Filter only filled trades
    filled = df[df["status"] == "FILLED"].copy()
    if filled.empty:
        return {"total_cycles": len(df), "filled_trades": 0}

    filled["profit"] = pd.to_numeric(filled["profit"], errors="coerce").fillna(0)

    wins   = filled[filled["profit"] > 0]
    losses = filled[filled["profit"] < 0]

    report = {
        "total_cycles":    len(df),
        "filled_trades":   len(filled),
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate_pct":    round(len(wins) / len(filled) * 100, 2) if len(filled) > 0 else 0,
        "total_profit":    round(filled["profit"].sum(), 2),
        "avg_win":         round(wins["profit"].mean(), 2)   if len(wins) > 0   else 0,
        "avg_loss":        round(losses["profit"].mean(), 2) if len(losses) > 0 else 0,
        "best_trade":      round(filled["profit"].max(), 2),
        "worst_trade":     round(filled["profit"].min(), 2),
        "profit_factor":   round(
            wins["profit"].sum() / abs(losses["profit"].sum()), 2
        ) if len(losses) > 0 and losses["profit"].sum() != 0 else float("inf"),
        "avg_confidence":  round(filled["ai_confidence"].mean(), 4),
        "symbols_traded":  filled["symbol"].unique().tolist(),
    }

    return report
