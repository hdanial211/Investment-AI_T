"""
config.py - Central configuration for the AI Trading Bot
All settings are defined here. Modify this file before running.
"""

import os
from pathlib import Path

# Load .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─────────────────────────────────────────────────────────────────────────────
# MT5 CONNECTION SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN",    "12345678"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD",     "your_password")
MT5_SERVER   = os.getenv("MT5_SERVER",       "Broker-Server")
MT5_PATH     = os.getenv("MT5_PATH",         "")   # e.g. C:/Program Files/MetaTrader 5/terminal64.exe

# ─────────────────────────────────────────────────────────────────────────────
# TRADING SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
SYMBOLS          = os.getenv("SYMBOLS", "XAUUSD,EURUSD").split(",")
PRIMARY_SYMBOL   = SYMBOLS[0]
TIMEFRAME        = os.getenv("TIMEFRAME", "M5")
LOOP_INTERVAL    = int(os.getenv("LOOP_INTERVAL", "60"))
BARS_TO_FETCH    = int(os.getenv("BARS_TO_FETCH", "100"))

# ─────────────────────────────────────────────────────────────────────────────
# RISK MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────
MAX_RISK_PERCENT       = float(os.getenv("MAX_RISK_PERCENT",       "2.0"))
MAX_CONSECUTIVE_LOSSES = int(os.getenv("MAX_CONSECUTIVE_LOSSES",   "3"))
MIN_CONFIDENCE         = float(os.getenv("MIN_CONFIDENCE",         "0.60"))
SL_PIPS                = int(os.getenv("SL_PIPS",                  "50"))
TP_PIPS                = int(os.getenv("TP_PIPS",                  "100"))
MIN_LOT                = float(os.getenv("MIN_LOT",                "0.01"))
MAX_LOT                = float(os.getenv("MAX_LOT",                "1.0"))
MIN_VOLATILITY_PIPS    = int(os.getenv("MIN_VOLATILITY_PIPS",      "5"))

# Dynamic Risk Management & Cooling Off
USE_DYNAMIC_SL         = os.getenv("USE_DYNAMIC_SL",               "True").lower() == "true"
DYNAMIC_SL_MULTIPLIER  = float(os.getenv("DYNAMIC_SL_MULTIPLIER",  "1.5"))
DYNAMIC_TP_MULTIPLIER  = float(os.getenv("DYNAMIC_TP_MULTIPLIER",  "4.5"))
COOLING_OFF_MINUTES    = int(os.getenv("COOLING_OFF_MINUTES",      "15"))

# Trade Layering & Trailing Stop
MAX_TRADES_PER_PAIR    = int(os.getenv("MAX_TRADES_PER_PAIR",      "10"))
USE_TRAILING_STOP      = os.getenv("USE_TRAILING_STOP",            "True").lower() == "true"
TRAILING_STOP_PIPS     = int(os.getenv("TRAILING_STOP_PIPS",       "30"))
TRAILING_STEP_PIPS     = int(os.getenv("TRAILING_STEP_PIPS",       "10"))

# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA AI SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_URL         = os.getenv("OLLAMA_URL",         "http://localhost:11434/api/generate")
OLLAMA_MODEL       = os.getenv("OLLAMA_MODEL",       "qwen2.5:7b")
OLLAMA_RISK_MODEL  = os.getenv("OLLAMA_RISK_MODEL",  "deepseek-r1:8b")
ENABLE_RISK_REVIEW = os.getenv("ENABLE_RISK_REVIEW", "False").lower() == "true"
OLLAMA_TIMEOUT     = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_RETRIES     = int(os.getenv("OLLAMA_RETRIES", "3"))
OLLAMA_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.1"))
OLLAMA_TOP_P       = float(os.getenv("OLLAMA_TOP_P",       "0.9"))
OLLAMA_NUM_CTX     = int(os.getenv("OLLAMA_NUM_CTX",       "4096"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT",   "256"))
OLLAMA_NUM_GPU     = int(os.getenv("OLLAMA_NUM_GPU",       "999"))

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING / OUTPUT
# ─────────────────────────────────────────────────────────────────────────────
LOG_DIR        = os.getenv("LOG_DIR",        "logs")
TRADE_LOG_FILE = os.getenv("TRADE_LOG_FILE", "logs/trades.csv")
APP_LOG_FILE   = os.getenv("APP_LOG_FILE",   "logs/bot.log")
LOG_LEVEL      = os.getenv("LOG_LEVEL",      "INFO")

# ─────────────────────────────────────────────────────────────────────────────
# INDICATOR SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
EMA_FAST    = int(os.getenv("EMA_FAST",    "9"))
EMA_SLOW    = int(os.getenv("EMA_SLOW",    "21"))
RSI_PERIOD  = int(os.getenv("RSI_PERIOD",  "14"))
MACD_FAST   = int(os.getenv("MACD_FAST",   "12"))
MACD_SLOW   = int(os.getenv("MACD_SLOW",   "26"))
MACD_SIGNAL = int(os.getenv("MACD_SIGNAL", "9"))

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
DASHBOARD_REFRESH = int(os.getenv("DASHBOARD_REFRESH", "5"))


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_pip_multiplier(symbol: str = "") -> float:
    """Return pip size for a given symbol."""
    symbol = symbol.upper()
    if "XAU" in symbol or "XAG" in symbol:
        return 0.01
    if "JPY" in symbol:
        return 0.01
    return 0.0001


def validate():
    """Validate critical config values on startup. Returns list of warnings."""
    errors = []
    if MT5_LOGIN == 12345678:
        errors.append("MT5_LOGIN is still the default placeholder. Set your real account number.")
    if MT5_PASSWORD == "your_password":
        errors.append("MT5_PASSWORD is still the default. Set your real password.")
    if MT5_SERVER == "Broker-Server":
        errors.append("MT5_SERVER is still the default. Set your broker's server name.")
    if MAX_RISK_PERCENT > 5.0:
        errors.append(f"MAX_RISK_PERCENT={MAX_RISK_PERCENT}% is dangerously high. Recommended max: 2%")
    return errors
