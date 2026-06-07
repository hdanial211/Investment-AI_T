"""
config.py - Central configuration for the AI Trading Bot.

Since we are 100% Cloud-Native, most settings are pulled from Supabase.
Only critical infrastructure variables remain here.
"""

import os

def _env_bool(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on")

# ─────────────────────────────────────────────────────────────────────────────
# MT5 CONNECTION SETTINGS (Default)
# ─────────────────────────────────────────────────────────────────────────────
MT5_LOGIN    = int(os.getenv("MT5_LOGIN",    "12345678"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD",     "your_password")
MT5_SERVER   = os.getenv("MT5_SERVER",       "Broker-Server")
MT5_PATH     = os.getenv("MT5_PATH",         "")   # e.g. C:/Program Files/MetaTrader 5/terminal64.exe

# ─────────────────────────────────────────────────────────────────────────────
# MASTER ANALYZER MT5 SETTINGS (Dedicated MT5 for market analysis)
# ─────────────────────────────────────────────────────────────────────────────
MASTER_MT5_LOGIN    = os.getenv("MASTER_MT5_LOGIN",    "")
MASTER_MT5_PASSWORD = os.getenv("MASTER_MT5_PASSWORD", "")
MASTER_MT5_SERVER   = os.getenv("MASTER_MT5_SERVER",   "")
MASTER_MT5_PATH     = os.getenv("MASTER_MT5_PATH",     "")

# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT ID (for multi-account settings via Supabase)
# ─────────────────────────────────────────────────────────────────────────────
ACCOUNT_ID   = os.getenv("ACCOUNT_ID",       "acc_1").strip()

# ─────────────────────────────────────────────────────────────────────────────
# TRADING SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
SYMBOLS          = os.getenv("SYMBOLS", "XAUUSD").split(",")
PRIMARY_SYMBOL   = SYMBOLS[0]
TIMEFRAME        = os.getenv("TIMEFRAME", "M5")
LOOP_INTERVAL    = int(os.getenv("LOOP_INTERVAL", "60"))
BARS_TO_FETCH    = int(os.getenv("BARS_TO_FETCH", "100"))

TRADING_MODE     = os.getenv("TRADING_MODE", "INTRADAY").upper() # SCALPING, INTRADAY, SWING

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
DYNAMIC_TP_MULTIPLIER  = float(os.getenv("DYNAMIC_TP_MULTIPLIER",  "2.5"))
COOLING_OFF_MINUTES    = int(os.getenv("COOLING_OFF_MINUTES",      "15"))

# Trade Layering & Trailing Stop
MAX_TRADES_PER_PAIR    = int(os.getenv("MAX_TRADES_PER_PAIR",      "10"))
USE_TRAILING_STOP      = os.getenv("USE_TRAILING_STOP",            "True").lower() == "true"
TRAILING_STOP_PIPS     = int(os.getenv("TRAILING_STOP_PIPS",       "30"))
TRAILING_STEP_PIPS     = int(os.getenv("TRAILING_STEP_PIPS",       "10"))

# ─────────────────────────────────────────────────────────────────────────────
# CLOUD AI SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
AI_PROVIDER          = os.getenv("AI_PROVIDER", "openrouter").strip().lower()
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "huggingface").strip().lower()
AI_FALLBACK_ENABLED  = _env_bool("AI_FALLBACK_ENABLED", "True")

OPENROUTER_API_KEY  = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Investment-AI_T").strip()
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://github.com/hdanial211/Investment-AI_T").strip()

HF_TOKEN    = os.getenv("HF_TOKEN", "").strip()
HF_BASE_URL = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1").strip()

AI_MAIN_MODEL     = os.getenv("AI_MAIN_MODEL", "openai/gpt-oss-20b:free").strip()
AI_RISK_MODEL     = os.getenv("AI_RISK_MODEL", "openai/gpt-oss-120b:free").strip()
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "qwen/qwen3-next-80b-a3b-instruct:free").strip()
HF_MAIN_MODEL     = os.getenv("HF_MAIN_MODEL", "Qwen/Qwen3-4B-Instruct-2507").strip()
HF_RISK_MODEL     = os.getenv("HF_RISK_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B").strip()

ENABLE_RISK_REVIEW = _env_bool("ENABLE_RISK_REVIEW", "True")
AI_TIMEOUT          = int(os.getenv("AI_TIMEOUT", "300"))
AI_RETRIES          = int(os.getenv("AI_RETRIES", "2"))
AI_TEMPERATURE      = float(os.getenv("AI_TEMPERATURE", "0.1"))
AI_MAX_TOKENS       = int(os.getenv("AI_MAX_TOKENS", "256"))
AI_STARTUP_HEALTHCHECK = _env_bool("AI_STARTUP_HEALTHCHECK", "False")

# Dynamic Providers Configuration injected from Supabase
PROVIDERS_CONFIG = []  # Legacy flat list — kept for backward compatibility

MASTER_AI_PROVIDER = None
MASTER_AI_MAIN_MODEL = None
MASTER_AI_RISK_MODEL = None

# ── Role-Based Provider Configs (v4 architecture) ────────────────────────────
# Each role has its own provider + API key + model to avoid quota exhaustion.
# Injected from Supabase system_settings.providers_list (role-based format).
MAIN_PROVIDER_CONFIG = None       # {"provider": "nvidia", "api_key": "...", "model": "..."}
VISION_PROVIDER_CONFIG = None     # {"provider": "nvidia", "api_key": "...", "model": "..."}
MASTER_FALLBACK_PROVIDERS = []    # [{"provider": "groq", "api_key": "...", "model": "auto"}, ...]

# ─────────────────────────────────────────────────────────────────────────────
# FUTURE VISION AI / CHART SCREENSHOT SETTINGS
# ─────────────────────────────────────────────────────────────────────────────
VISION_AI_ENABLED        = _env_bool("VISION_AI_ENABLED", "False")
CHART_IMAGE_SOURCE       = os.getenv("CHART_IMAGE_SOURCE", "mt5_automation").strip().lower()
if CHART_IMAGE_SOURCE == "mt5":
    CHART_IMAGE_SOURCE = "mt5_automation"
CHART_IMAGE_TIMEFRAMES   = os.getenv("CHART_IMAGE_TIMEFRAMES", "H4,H1,M30,M15,M5,M1").split(",")
TRADINGVIEW_CHART_URL    = os.getenv("TRADINGVIEW_CHART_URL", "").strip()
MT5_SCREENSHOT_DIR       = os.getenv("MT5_SCREENSHOT_DIR", "chart_screenshots").strip()
VISION_AI_MODEL          = os.getenv("VISION_AI_MODEL", "google/gemini-2.0-flash-001").strip()
VISION_AI_MAX_TOKENS     = int(os.getenv("VISION_AI_MAX_TOKENS", "512"))
VISION_AI_TIMEOUT        = int(os.getenv("VISION_AI_TIMEOUT", "60"))
SCREENSHOT_MAX_AGE_SECONDS = int(os.getenv("SCREENSHOT_MAX_AGE_SECONDS", "120"))
VISION_CYCLE_INTERVAL    = int(os.getenv("VISION_CYCLE_INTERVAL", "1"))  # run vision every N cycles

# ─────────────────────────────────────────────────────────────────────────────
# SUPABASE CONNECTION SETTINGS (100% Cloud-Native)
# No .env used! Enter your Service Role Key below manually!
# ─────────────────────────────────────────────────────────────────────────────
SUPABASE_URL              = "https://kusyjtpcjyflxgfcqenb.supabase.co"
SUPABASE_ANON_KEY         = "sb_publishable_Pdf-F-j3PH3keLsZ8ZoEZA_tbotGoxM"
SUPABASE_SERVICE_ROLE_KEY = "SILA_LETAK_SERVICE_ROLE_KEY_ANDA_DI_SINI"  # <-- Masukkan key anda!
SUPABASE_SYNC_ENABLED     = True
SUPABASE_MACHINE_ID       = os.getenv("SUPABASE_MACHINE_ID", "laptop-main").strip()
SUPABASE_REQUEST_TIMEOUT  = int(os.getenv("SUPABASE_REQUEST_TIMEOUT", "10"))

USE_BROKER_SL_TP              = _env_bool("USE_BROKER_SL_TP", "False")
USE_VIRTUAL_SL_TP             = _env_bool("USE_VIRTUAL_SL_TP", "True")
USE_VIRTUAL_TRAILING_STOP     = _env_bool("USE_VIRTUAL_TRAILING_STOP", "True")
VIRTUAL_EXIT_CHECK_INTERVAL   = int(os.getenv("VIRTUAL_EXIT_CHECK_INTERVAL", "10"))
PATTERN_USAGE_SYNC_ENABLED    = _env_bool("PATTERN_USAGE_SYNC_ENABLED", "True")
PATTERN_PRIMARY_LIMIT         = int(os.getenv("PATTERN_PRIMARY_LIMIT", "1"))
PATTERN_CONFLUENCE_LIMIT      = int(os.getenv("PATTERN_CONFLUENCE_LIMIT", "8"))
PATTERN_STATS_UPDATE_INTERVAL = int(os.getenv("PATTERN_STATS_UPDATE_INTERVAL", "10"))

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
        return 0.01  # Gold/Silver standard pip (1 pip = 0.01 points)
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
    if AI_PROVIDER == "openrouter" and OPENROUTER_API_KEY in ("", "CHANGE_ME"):
        errors.append("OPENROUTER_API_KEY is missing. Add it to local .env.")
    if AI_PROVIDER in ("huggingface", "hf") and HF_TOKEN in ("", "CHANGE_ME"):
        errors.append("HF_TOKEN is missing. Add it to local .env.")
    if AI_FALLBACK_ENABLED and AI_FALLBACK_PROVIDER in ("huggingface", "hf") and HF_TOKEN in ("", "CHANGE_ME"):
        errors.append("HF_TOKEN is missing, so Hugging Face fallback will be unavailable.")
    if not USE_BROKER_SL_TP and not USE_VIRTUAL_SL_TP:
        errors.append("Both broker SL/TP and virtual SL/TP are disabled. This is unsafe.")
    if VISION_AI_ENABLED:
        if CHART_IMAGE_SOURCE not in ("mt5_automation", "browser_automation"):
            errors.append(f"CHART_IMAGE_SOURCE={CHART_IMAGE_SOURCE} is invalid. Use mt5_automation or browser_automation.")
        if not VISION_AI_MODEL:
            errors.append("VISION_AI_MODEL is empty but VISION_AI_ENABLED=True.")
    return errors
