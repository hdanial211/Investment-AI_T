"""
account_settings.py — Reads per-account trading settings from Supabase.

The dashboard writes settings to the `account_settings` table.
The bot reads them every N seconds and applies lot/style/max-trade rules.

Fallback: If Supabase is unreachable or no settings exist,
the bot uses values from the local .env (existing behavior).
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional

import config

logger = logging.getLogger(__name__)

# Default settings that mirror config.py / .env
_DEFAULTS = {
    "account_id": "acc_1",
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
    "symbol_eurusd": "EURUSD",
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
        if self._cache.get("eurusd_enabled", True) not in (False, "false", 0):
            eur = str(self._cache.get("symbol_eurusd", "EURUSD") or "EURUSD").strip()
            symbols.append(eur)
        # Fallback: if user disabled both, at least trade XAUUSD
        if not symbols:
            symbols.append(str(self._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip())
        return symbols

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
        """Fetch settings from Supabase REST API."""
        if not config.SUPABASE_SYNC_ENABLED:
            logger.debug("AccountSettings: Supabase disabled, using local defaults.")
            self._supabase_available = False
            return

        url = config.SUPABASE_URL.rstrip("/")
        key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
        if not url or not key:
            logger.debug("AccountSettings: No Supabase URL/key, using local defaults.")
            self._supabase_available = False
            return

        try:
            import requests

            endpoint = (
                f"{url}/rest/v1/account_settings"
                f"?account_id=eq.{self.account_id}&select=*&limit=1"
            )
            response = requests.get(
                endpoint,
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                },
                timeout=config.SUPABASE_REQUEST_TIMEOUT,
            )

            if response.status_code >= 400:
                logger.warning(
                    f"AccountSettings: Supabase returned {response.status_code}. "
                    f"Using cached/default settings."
                )
                self._supabase_available = False
                return

            data = response.json()
            if not data:
                logger.info(
                    f"AccountSettings: No settings for '{self.account_id}' in Supabase. "
                    f"Using local defaults."
                )
                self._supabase_available = False
                return

            # Merge with defaults (Supabase values take priority)
            row = data[0]
            for k, v in row.items():
                if v is not None:
                    self._cache[k] = v

            self._supabase_available = True
            logger.debug(
                f"AccountSettings: Loaded settings for '{self.account_id}' from Supabase."
            )

        except ImportError:
            logger.warning("AccountSettings: 'requests' package not found.")
            self._supabase_available = False
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
        return [config.ACCOUNT_ID]

    url = config.SUPABASE_URL.rstrip("/")
    key = config.SUPABASE_SERVICE_ROLE_KEY or config.SUPABASE_ANON_KEY
    if not url or not key:
        return [config.ACCOUNT_ID]

    try:
        import requests
        endpoint = f"{url}/rest/v1/account_settings?enabled=eq.true&select=account_id"
        response = requests.get(
            endpoint,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
            },
            timeout=config.SUPABASE_REQUEST_TIMEOUT,
        )
        if response.status_code >= 400:
            return [config.ACCOUNT_ID]
        
        data = response.json()
        if not data:
            return []
            
        return [row["account_id"] for row in data if "account_id" in row]
    except Exception as e:
        logger.warning(f"Failed to fetch enabled accounts: {e}")
        return [config.ACCOUNT_ID]
