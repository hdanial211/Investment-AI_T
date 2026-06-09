"""Optional Supabase REST sync.

This module is intentionally best-effort: sync failures must never stop trading.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

import config

logger = logging.getLogger(__name__)


class SupabaseSync:
    def __init__(self):
        self.enabled = bool(
            getattr(config, "SUPABASE_SYNC_ENABLED", True)
            and getattr(config, "SUPABASE_URL", "")
            and getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")
            and getattr(config, "SUPABASE_SERVICE_ROLE_KEY", "") != "CHANGE_ME"
            and requests is not None
        )
        self.base_url = getattr(config, "SUPABASE_URL", "").rstrip("/")
        self.timeout = int(getattr(config, "SUPABASE_REQUEST_TIMEOUT", 10))
        self.headers = {
            "apikey": getattr(config, "SUPABASE_SERVICE_ROLE_KEY", ""),
            "Authorization": f"Bearer {getattr(config, 'SUPABASE_SERVICE_ROLE_KEY', '')}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }
        if getattr(config, "SUPABASE_SYNC_ENABLED", True) and requests is None:
            logger.warning("Supabase sync disabled because the requests package is not installed.")

    def upsert_heartbeat(self, *, cycle: int = 0, status: str = "online", message: str = "") -> None:
        account_id = getattr(config, "ACCOUNT_ID", "acc_1")
        payload = {
            "account_id": account_id,
            "enabled": True,
            "last_seen_bot": datetime.utcnow().isoformat()
        }
        self._upsert("account_settings", payload, conflict="account_id")

    def upsert_active_trade(self, state: Dict) -> bool:
        """
        Upsert trade data to Supabase active_trades table.
        Returns False if HTTP 409 Conflict (Duplicate signal) is encountered, True otherwise.
        """
        payload = {
            "ticket": state.get("ticket"),
            "account_id": state.get("account_id") or getattr(config, "ACCOUNT_ID", "acc_1"),
            "symbol": state.get("symbol"),
            "direction": state.get("action") or state.get("direction"),
            "lot": state.get("lot"),
            "trade_style": state.get("trade_style"),
            "virtual_sl": state.get("virtual_sl"),
            "virtual_tp": state.get("virtual_tp"),
            "be_offset_pips": state.get("be_offset_pips"),
            "trail_start_pips": state.get("trail_start_pips"),
            "trail_dist_pips": state.get("trail_dist_pips"),
            "entry_price": state.get("entry_price"),
            "average_entry_price": state.get("average_entry_price"),
            "layer_index": state.get("layer_index", 1),
            "basket_id": state.get("basket_id"),
            "magic_number": state.get("magic_number"),
            "current_profit": state.get("floating_profit") or state.get("current_profit"),
            "closing_requested": state.get("closing_requested", False),
            "close_requested_by": state.get("close_requested_by"),
            "close_requested_at": state.get("close_requested_at"),
            "current_status": state.get("current_status", "OPEN"),
            "signal_id": state.get("signal_id"),
            "opened_at": state.get("timestamp") or datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        response = self._upsert("active_trades", payload, conflict="ticket")
        if response and response.status_code == 409:
            logger.warning(f"Trade already exists (HTTP 409 Conflict) for signal: {state.get('signal_id')}")
            return False
        return True

    def mark_trade_closed(self, state: Dict) -> None:
        # First remove from active_trades if we want to move it (or we can just leave it to EA to delete, but let's sync)
        # Actually in V4, Python marks closing_requested = True, and EA deletes. 
        # But if Python does the close, we insert to closed_trades.
        payload = {
            "ticket": state.get("ticket"),
            "account_id": state.get("account_id") or getattr(config, "ACCOUNT_ID", "acc_1"),
            "symbol": state.get("symbol"),
            "direction": state.get("action") or state.get("direction"),
            "lot": state.get("lot"),
            "trade_style": state.get("trade_style"),
            "pnl": state.get("profit") or state.get("floating_profit"),
            "close_reason": state.get("exit_reason", "AI Close"),
            "closed_at": datetime.utcnow().isoformat()
        }
        self._insert("closed_trades", payload)
        
        # Then delete from active_trades to avoid duplicate tracking
        if self.enabled and state.get("ticket"):
            url = f"{self.base_url}/rest/v1/active_trades?ticket=eq.{state.get('ticket')}"
            try:
                requests.delete(url, headers=self.headers, timeout=self.timeout)
            except Exception as e:
                logger.warning(f"Failed to delete active_trade after close: {e}")

    def fetch_active_trades(self, account_id: str) -> List[Dict]:
        """Fetch all trades from Supabase that are OPEN for this account."""
        if not self.enabled:
            return []
        url = f"{self.base_url}/rest/v1/active_trades?account_id=eq.{account_id}&current_status=eq.OPEN"
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Failed to fetch active trades from Supabase: {response.text[:240]}")
        except Exception as e:
            logger.warning(f"Error fetching active trades from Supabase: {e}")
        return []

    def fetch_system_settings(self) -> Dict:
        if not self.enabled:
            return {}
        url = f"{self.base_url}/rest/v1/system_settings"
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                settings = {}
                for row in data:
                    settings[row.get("key_name")] = row.get("key_value")
                return settings
        except Exception as e:
            logger.warning(f"Error fetching system_settings: {e}")
        return {}

    def fetch_account_settings(self, account_id: str) -> Dict:
        if not self.enabled:
            return {}
        url = f"{self.base_url}/rest/v1/account_settings?account_id=eq.{account_id}&select=*"
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                return data[0] if data else {}
        except Exception as e:
            logger.warning(f"Error fetching account_settings: {e}")
        return {}

    def fetch_all_enabled_accounts(self) -> List[str]:
        if not self.enabled:
            return ["acc_1"]
        url = f"{self.base_url}/rest/v1/account_settings?select=account_id,enabled"
        try:
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
            if response.status_code == 200:
                return [acc["account_id"] for acc in response.json() if acc.get("enabled", False)]
        except Exception as e:
            logger.warning(f"Error fetching enabled accounts: {e}")
        return ["acc_1"]

    def upsert_market_signal(self, signal_data: Dict) -> None:
        """Upsert a raw AI signal to market_signals."""
        payload = {
            "symbol": signal_data.get("symbol"),
            "direction": signal_data.get("action"),
            "trade_style": signal_data.get("trade_style"),
            "raw_ai_response": signal_data,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._insert("market_signals", payload)

    def broadcast_signal_to_accounts(self, accounts: List[str], signal_data: Dict) -> None:
        """Distribute a valid entry signal to all enabled accounts in 'signals' table."""
        if not self.enabled or not accounts:
            return
        
        payloads = []
        for acc in accounts:
            payloads.append({
                "signal_id": signal_data.get("signal_id"),
                "account_id": acc,
                "symbol": signal_data.get("symbol"),
                "direction": signal_data.get("action"),
                "trade_style": signal_data.get("trade_style"),
                "confidence": signal_data.get("confidence"),
                "is_active": True,
                "created_at": datetime.utcnow().isoformat()
            })
        
        url = f"{self.base_url}/rest/v1/signals"
        self._request("POST", url, payloads)

    def fetch_pending_signals(self, account_id: str) -> List[Dict]:
        """Trade Evaluator reads pending entry signals for its account."""
        if not self.enabled:
            return []
        url = f"{self.base_url}/rest/v1/signals?account_id=eq.{account_id}&is_active=eq.true&order=created_at.asc"
        try:
            resp = requests.get(url, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"fetch_pending_signals error: {e}")
        return []

    def mark_signal_processed(self, signal_id: str, account_id: str) -> None:
        if not self.enabled:
            return
        url = f"{self.base_url}/rest/v1/signals?signal_id=eq.{signal_id}&account_id=eq.{account_id}"
        patch = {"is_active": False}
        try:
            requests.patch(url, headers=self.headers, json=patch, timeout=self.timeout)
        except Exception as e:
            logger.warning(f"mark_signal_processed error: {e}")

    def _upsert(self, table: str, payload: Dict, conflict: str = "") -> Optional[requests.Response]:
        if not self.enabled:
            return None
        url = f"{self.base_url}/rest/v1/{table}"
        if conflict:
            url = f"{url}?on_conflict={conflict}"
        return self._request("POST", url, payload)

    def _insert(self, table: str, payload: Dict) -> Optional[requests.Response]:
        if not self.enabled:
            return None
        return self._request("POST", f"{self.base_url}/rest/v1/{table}", payload)

    def _request(self, method: str, url: str, payload: Dict) -> Optional[requests.Response]:
        try:
            response = requests.request(method, url, headers=self.headers, json=payload, timeout=self.timeout)
            if response.status_code == 409:
                # Duplicate constraint hit
                return response
            if response.status_code >= 400:
                logger.warning(f"Supabase sync failed {response.status_code}: {response.text[:240]}")
            return response
        except Exception as exc:
            logger.warning(f"Supabase sync error: {exc}")
            return None
