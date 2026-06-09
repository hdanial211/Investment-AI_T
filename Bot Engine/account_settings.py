"""
account_settings.py — Reads per-account trading settings from Supabase.

The dashboard writes settings to the `account_settings` table.
The bot reads them every N seconds and applies lot/style/max-trade rules.

Fallback: If Supabase is unreachable or no settings exist,
the bot uses values from the local .env (existing behavior).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, Optional, Any

import config

logger = logging.getLogger(__name__)

SHARED_STATE_FILE = os.path.join(os.path.dirname(__file__), "shared_state.json")

# Default settings that mirror config.py / .env
_DEFAULTS = {
    "account_id": "",
    "account_label": "Default",
    "mt5_login": str(config.MT5_LOGIN),
    "mt5_server": config.MT5_SERVER,
    "mt5_path": config.MT5_PATH,
    "enabled": True,
    "scalping_enabled": False,
    "intraday_enabled": True,
    "swing_enabled": True,
    "scalping_lot": config.MIN_LOT,
    "intraday_lot": config.MIN_LOT,
    "swing_lot": config.MIN_LOT,
    "scalping_max_trades": 0,
    "intraday_max_trades": config.MAX_TRADES_PER_PAIR,
    "swing_max_trades": config.MAX_TRADES_PER_PAIR,
    "max_total_trades": config.MAX_TRADES_PER_PAIR * len(config.SYMBOLS),
    "max_risk_percent": config.MAX_RISK_PERCENT,
    "symbol_xauusd": "XAUUSD",
    "trade_during_events": False,
    "news_close_profit": False,
    "manage_manual_sl": False,
    "manage_manual_tp": False,
    "manage_manual_be": False,
    "block_asia_session": True,
    "max_daily_drawdown_pct": 5.0,
    "daily_profit_target_pct": 2.0,
    "min_ai_confidence": 0.70,
    "max_spread_points": 50,
    "scalping_grid_enabled": False,
    "scalping_grid_atr": 1.0,
    "scalping_grid_lot_mult": 1.0,
    "scalping_grid_max": 3,
    "intraday_grid_enabled": False,
    "intraday_grid_atr": 1.0,
    "intraday_grid_lot_mult": 1.0,
    "intraday_grid_max": 3,
    "swing_grid_enabled": False,
    "swing_grid_atr": 1.0,
    "swing_grid_lot_mult": 1.0,
    "swing_grid_max": 3,
    "allow_hedging": False,
}


class AccountSettings:
    """
    Reads and caches per-account settings from Supabase.

    Settings are refreshed every `fetch_interval` seconds.
    If Supabase is unreachable, the last-known settings (or defaults) are used.
    """

    def __init__(self, account_id: str, fetch_interval: int = 60):
        self.account_id = account_id
        self._cache: Dict = dict(_DEFAULTS)
        self._cache["account_id"] = account_id
        self._last_fetch: float = 0
        self._fetch_interval = fetch_interval
        self._supabase_available = False

    # ── PUBLIC PROPERTIES ─────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Check if this account is enabled for trading."""
        self._maybe_refresh()
        return bool(self._cache.get("enabled", True))

    @property
    def mt5_login(self) -> str:
        """Get MT5 login for this account."""
        self._maybe_refresh()
        return str(self._cache.get("mt5_login", config.MT5_LOGIN))

    @property
    def mt5_password(self) -> str:
        """Get MT5 password for this account."""
        self._maybe_refresh()
        return str(self._cache.get("mt5_password", config.MT5_PASSWORD))

    @property
    def mt5_server(self) -> str:
        """Get MT5 broker server for this account."""
        self._maybe_refresh()
        return str(self._cache.get("mt5_server", config.MT5_SERVER) or config.MT5_SERVER)

    @property
    def trade_during_events(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("trade_during_events", _DEFAULTS["trade_during_events"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def news_close_profit(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("news_close_profit", _DEFAULTS["news_close_profit"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def manage_manual_sl(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("manage_manual_sl", _DEFAULTS["manage_manual_sl"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def manage_manual_tp(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("manage_manual_tp", _DEFAULTS["manage_manual_tp"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def manage_manual_be(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("manage_manual_be", _DEFAULTS["manage_manual_be"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def block_asia_session(self) -> bool:
        self._maybe_refresh()
        val = self._cache.get("block_asia_session", _DEFAULTS["block_asia_session"])
        return str(val).lower() == "true" if isinstance(val, str) else bool(val)

    @property
    def max_daily_drawdown_pct(self) -> float:
        self._maybe_refresh()
        try: return float(self._cache.get("max_daily_drawdown_pct", _DEFAULTS["max_daily_drawdown_pct"]))
        except: return _DEFAULTS["max_daily_drawdown_pct"]

    @property
    def daily_profit_target_pct(self) -> float:
        self._maybe_refresh()
        try: return float(self._cache.get("daily_profit_target_pct", _DEFAULTS["daily_profit_target_pct"]))
        except: return _DEFAULTS["daily_profit_target_pct"]

    @property
    def min_ai_confidence(self) -> float:
        self._maybe_refresh()
        try: return float(self._cache.get("min_ai_confidence", _DEFAULTS["min_ai_confidence"]))
        except: return _DEFAULTS["min_ai_confidence"]

    @property
    def max_spread_points(self) -> int:
        self._maybe_refresh()
        try: return int(self._cache.get("max_spread_points", _DEFAULTS["max_spread_points"]))
        except: return _DEFAULTS["max_spread_points"]
        
    @property
    def allow_hedging(self) -> bool:
        self._maybe_refresh()
        return bool(self._cache.get("allow_hedging", False))

    def get_grid_settings(self, trade_style: str) -> dict:
        """Get grid recovery settings for a specific trade style."""
        self._maybe_refresh()
        prefix = trade_style.lower()
        
        # Helper to get typed val or default
        def _get(key, typ, default):
            v = self._cache.get(f"{prefix}_{key}", default)
            try: return typ(v)
            except: return default

        return {
            "enabled": str(self._cache.get(f"{prefix}_grid_enabled", False)).lower() == "true",
            "atr_multiplier": _get("grid_atr", float, 1.0),
            "lot_multiplier": _get("grid_lot_mult", float, 1.0),
            "max_steps": _get("grid_max", int, 3)
        }

    def get_trailing_settings(self, trade_style: str) -> dict:
        """Get trailing stop and BE settings for a specific trade style."""
        self._maybe_refresh()
        prefix = trade_style.lower()
        
        # Helper to get typed val or default (None if empty/missing)
        def _get_opt(key):
            v = self._cache.get(f"{prefix}_{key}")
            if v is None or str(v).strip() == "":
                return None
            try: return float(v)
            except: return None

        return {
            "be_trigger_pips": _get_opt("be_trigger"),
            "be_offset_pips": _get_opt("be_offset_pips"),
            "trail_start_pips": _get_opt("trail_start"),
            "trail_dist_pips": _get_opt("trail_dist")
        }

    @property
    def mt5_path(self) -> str:
        """Get MT5 terminal path for this account."""
        self._maybe_refresh()
        return str(self._cache.get("mt5_path", config.MT5_PATH) or config.MT5_PATH)

    def get_symbols(self) -> list:
        """Get broker-specific symbol names for this account (only enabled pairs)."""
        self._maybe_refresh()
        symbols = []
        if self._cache.get("xauusd_enabled", True) not in (False, "false", 0):
            xau = str(self._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip()
            symbols.append(xau)
        # Fallback: at least trade XAUUSD
        if not symbols:
            symbols.append(str(self._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip())
        return symbols
        
        
    def get_providers_list(self) -> list:
        """Get the fallback sequence of AI providers for this account.
        
        Supports both formats:
          - Legacy (array): returns the array directly
          - Role-based (object): returns the 'fallbacks' list
        """
        self._maybe_refresh()
        pl = self._cache.get("providers_list")
        if pl and isinstance(pl, list):
            return pl
        if pl and isinstance(pl, dict):
            return pl.get("fallbacks", [])
        return []

    def get_evaluator_config(self) -> Optional[Dict]:
        """Get the Trade Evaluator provider config for this account.
        
        Returns: {"provider": "nvidia", "api_key": "...", "model": "..."} or None
        """
        self._maybe_refresh()
        pl = self._cache.get("providers_list")
        if pl and isinstance(pl, dict):
            cfg = pl.get("evaluator")
            if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                return cfg
        # Legacy fallback: use first provider from flat list
        if pl and isinstance(pl, list) and len(pl) > 0:
            first = pl[0]
            return {
                "provider": first.get("provider"),
                "api_key": first.get("api_key"),
                "model": first.get("risk_model") or first.get("main_model"),
            }
        return None

    def get_risk_config(self) -> Optional[Dict]:
        """Get the Risk Review provider config for this account.
        
        Returns: {"provider": "nvidia", "api_key": "...", "model": "..."} or None
        """
        self._maybe_refresh()
        pl = self._cache.get("providers_list")
        if pl and isinstance(pl, dict):
            cfg = pl.get("risk")
            if cfg and isinstance(cfg, dict) and cfg.get("api_key"):
                return cfg
        # Legacy fallback: use first provider from flat list
        if pl and isinstance(pl, list) and len(pl) > 0:
            first = pl[0]
            return {
                "provider": first.get("provider"),
                "api_key": first.get("api_key"),
                "model": first.get("risk_model") or first.get("main_model"),
            }
        return None

    def get_role_fallbacks(self, for_role: str = None) -> list:
        """Get the fallback providers for this account, filtered by role if specified.
        
        Returns list of provider config dicts.
        """
        self._maybe_refresh()
        pl = self._cache.get("providers_list")
        if pl and isinstance(pl, dict):
            fallbacks = pl.get("fallbacks", [])
            if for_role:
                # Return fallbacks that specifically match the role, or don't have a role assigned
                return [fb for fb in fallbacks if fb.get("for_role") == for_role or not fb.get("for_role")]
            return fallbacks
        # Legacy: return all providers beyond the first
        if pl and isinstance(pl, list) and len(pl) > 1:
            return pl[1:]
        return []

    def is_style_enabled(self, trade_style: str) -> bool:
        """Check if SCALPING/INTRADAY/SWING is enabled for this account."""
        self._maybe_refresh()
        key = f"{trade_style.lower()}_enabled"
        return bool(self._cache.get(key, True))

    def get_lot_for_style(self, trade_style: str) -> float:
        """Get lot size for the given trade style."""
        self._maybe_refresh()
        key = f"{trade_style.lower()}_lot"
        lot = self._cache.get(key, config.MIN_LOT)
        try:
            lot = float(lot)
        except (TypeError, ValueError):
            lot = config.MIN_LOT
        return max(config.MIN_LOT, min(config.MAX_LOT, lot))

    def get_max_trades_for_style(self, trade_style: str) -> int:
        """Get max concurrent trades for the given trade style."""
        self._maybe_refresh()
        key = f"{trade_style.lower()}_max_trades"
        val = self._cache.get(key, config.MAX_TRADES_PER_PAIR)
        try:
            return max(0, int(val))
        except (TypeError, ValueError):
            return config.MAX_TRADES_PER_PAIR

    def get_max_total_trades(self) -> int:
        """Get total max concurrent trades across all styles."""
        self._maybe_refresh()
        val = self._cache.get("max_total_trades", 5)
        try:
            return max(1, int(val))
        except (TypeError, ValueError):
            return 5

    def get_max_risk_percent(self) -> float:
        """Get max risk percentage for this account."""
        self._maybe_refresh()
        val = self._cache.get("max_risk_percent", config.MAX_RISK_PERCENT)
        try:
            return max(0.1, min(5.0, float(val)))
        except (TypeError, ValueError):
            return config.MAX_RISK_PERCENT

    def get_settings_summary(self) -> Dict:
        """Return a summary dict for logging."""
        self._maybe_refresh()
        return {
            "account_id": self.account_id,
            "enabled": self.enabled,
            "mt5_login": self.mt5_login,
            "mt5_password": "***" if self.mt5_password else "",
            "mt5_server": self.mt5_server,
            "scalping": f"{'ON' if self.is_style_enabled('SCALPING') else 'OFF'} | lot={self.get_lot_for_style('SCALPING')} | max={self.get_max_trades_for_style('SCALPING')}",
            "intraday": f"{'ON' if self.is_style_enabled('INTRADAY') else 'OFF'} | lot={self.get_lot_for_style('INTRADAY')} | max={self.get_max_trades_for_style('INTRADAY')}",
            "swing": f"{'ON' if self.is_style_enabled('SWING') else 'OFF'} | lot={self.get_lot_for_style('SWING')} | max={self.get_max_trades_for_style('SWING')}",
            "max_total": self.get_max_total_trades(),
            "source": "supabase" if self._supabase_available else "local_defaults",
        }

    # ── FETCH / CACHE ─────────────────────────────────────────────────────

    def _maybe_refresh(self) -> None:
        """Refresh settings from Supabase if cache is stale."""
        now = time.time()
        if now - self._last_fetch < self._fetch_interval:
            return
        self._last_fetch = now
        self._fetch_from_supabase()

    def _fetch_from_supabase(self) -> None:
        """Fetch settings directly from Supabase."""
        if not config.SUPABASE_SYNC_ENABLED:
            logger.debug("AccountSettings: Supabase disabled, using local defaults.")
            self._supabase_available = False
            return

        try:
            from trade_management.supabase_sync import SupabaseSync
            sync = SupabaseSync()
            my_settings = sync.fetch_account_settings(self.account_id)
            
            if not my_settings:
                logger.debug(
                    f"AccountSettings: No settings for '{self.account_id}' found in Supabase. "
                    f"Using local defaults."
                )
                self._supabase_available = False
                return
                
            # Merge with defaults
            for k, v in my_settings.items():
                if v is not None:
                    self._cache[k] = v
                    
            self._supabase_available = True
            logger.debug(f"AccountSettings: Loaded settings for '{self.account_id}' directly from Supabase.")
            
        except Exception as e:
            logger.warning(f"AccountSettings: fetch failed: {e}. Using cached settings.")
            self._supabase_available = False

    def update_connection_status(
        self,
        connected: bool,
        error_msg: str = "",
        account_info: dict = None,
        symbol_status: dict = None,
    ) -> None:
        """Update the MT5 connection status and diagnostics in Supabase.

        Args:
            connected: True if MT5 connected successfully.
            error_msg: Human-readable error message (Malay-friendly).
            account_info: Dict with balance, equity, leverage, currency, server, name.
            symbol_status: Dict with {symbol: "OK" or error string}.
        """
        if not config.SUPABASE_SYNC_ENABLED:
            return
        url = config.SUPABASE_URL.rstrip("/")
        key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
        if not url or not key:
            return
        try:
            import json as _json
            import requests
            from datetime import datetime

            endpoint = f"{url}/rest/v1/account_settings"
            payload = {
                "account_id": self.account_id,
                "mt5_status": "Connected" if connected else "Failed",
                "mt5_last_error": error_msg,
                "mt5_info": _json.dumps(account_info or {}),
                "mt5_symbol_status": _json.dumps(symbol_status or {}),
                "mt5_checked_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            requests.post(
                endpoint,
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                json=payload,
                timeout=config.SUPABASE_REQUEST_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"AccountSettings: Failed to update connection status: {e}")

    def force_refresh(self) -> None:
        """Force a refresh from Supabase on next property access."""
        self._last_fetch = 0

def get_all_enabled_accounts() -> list[str]:
    """Fetch all account IDs that are enabled from Supabase. Fallback to config.ACCOUNT_ID if failed."""
    if not config.SUPABASE_SYNC_ENABLED:
        if config.ACCOUNT_ID:
            return [config.ACCOUNT_ID]
        return []
        
    try:
        from trade_management.supabase_sync import SupabaseSync
        sync = SupabaseSync()
        enabled = sync.fetch_all_enabled_accounts()
        if enabled:
            return enabled
    except Exception as e:
        logger.warning(f"get_all_enabled_accounts failed: {e}")
        
    if config.ACCOUNT_ID:
        return [config.ACCOUNT_ID]
    return []


def account_has_active_trades(acc_id: str) -> bool:
    """Check if an account has any open positions in Supabase active_trades table."""
    try:
        from trade_management.supabase_sync import SupabaseSync
        sync = SupabaseSync()
        result = sync.client.table("active_trades").select("ticket").eq("account_id", acc_id).execute()
        return len(result.data) > 0
    except Exception as e:
        logger.warning(f"account_has_active_trades check failed for {acc_id}: {e}")
        # If we can't confirm, assume no active trades — safer to allow shutdown
        return False

