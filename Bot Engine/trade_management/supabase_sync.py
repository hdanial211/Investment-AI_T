"""Optional Supabase REST sync.

This module is intentionally best-effort: sync failures must never stop trading.
"""

import logging
from datetime import datetime
from typing import Dict

try:
    import requests
except ImportError:  # pragma: no cover - startup checks normally install it.
    requests = None

import config
from .pattern_usage_tracker import build_usage_rows

logger = logging.getLogger(__name__)


class SupabaseSync:
    def __init__(self):
        self.enabled = bool(
            config.SUPABASE_SYNC_ENABLED
            and config.SUPABASE_URL
            and config.SUPABASE_SERVICE_ROLE_KEY
            and config.SUPABASE_SERVICE_ROLE_KEY != "CHANGE_ME"
            and requests is not None
        )
        self.base_url = config.SUPABASE_URL.rstrip("/")
        self.timeout = int(getattr(config, "SUPABASE_REQUEST_TIMEOUT", 10))
        self.headers = {
            "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }
        if config.SUPABASE_SYNC_ENABLED and requests is None:
            logger.warning("Supabase sync disabled because the requests package is not installed.")

    def upsert_heartbeat(self, *, cycle: int = 0, status: str = "online", message: str = "") -> None:
        payload = {
            "machine_id": config.SUPABASE_MACHINE_ID,
            "status": status,
            "last_seen_at": datetime.utcnow().isoformat(),
            "current_cycle": cycle,
            "message": message,
        }
        self._upsert("bot_heartbeat", payload, conflict="machine_id")

    def upsert_active_trade(self, state: Dict) -> None:
        payload = {
            "ticket": state.get("ticket"),
            "symbol": state.get("symbol"),
            "direction": state.get("action") or state.get("direction"),
            "lot": state.get("lot"),
            "entry_price": state.get("entry_price"),
            "floating_profit": state.get("floating_profit"),
            "virtual_sl": state.get("virtual_sl"),
            "virtual_tp": state.get("virtual_tp"),
            "virtual_trailing_stop": state.get("virtual_trailing_stop"),
            "primary_pattern": (state.get("pattern_snapshot") or {}).get("primary_pattern"),
            "pattern_names": (state.get("pattern_snapshot") or {}).get("pattern_names"),
            "pattern_categories": (state.get("pattern_snapshot") or {}).get("pattern_categories"),
            "pattern_timeframes": (state.get("pattern_snapshot") or {}).get("pattern_timeframes"),
            "confluence_combo": (state.get("pattern_snapshot") or {}).get("confluence_combo"),
            "pattern_confidence": (state.get("pattern_snapshot") or {}).get("pattern_confidence"),
            "pattern_count": (state.get("pattern_snapshot") or {}).get("pattern_count"),
            "current_status": state.get("current_status"),
            "original_thesis": state.get("reason"),
            "opened_at": state.get("timestamp"),
            "last_price": state.get("last_price"),
            "profit_lock_level": state.get("profit_lock_level"),
            "max_drawdown": state.get("max_drawdown"),
            "exit_reason": state.get("exit_reason"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._upsert("active_trades", payload, conflict="ticket")
        self.upsert_trade_pattern_usage(
            state.get("ticket"),
            state.get("pattern_snapshot") or {},
            trade_status=str(state.get("current_status") or "open").lower(),
            profit=state.get("profit"),
            exit_reason=state.get("exit_reason") or "",
        )

    def mark_trade_closed(self, state: Dict) -> None:
        payload = {
            "ticket": state.get("ticket"),
            "current_status": "CLOSED",
            "exit_reason": state.get("exit_reason"),
            "floating_profit": state.get("profit"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._upsert("active_trades", payload, conflict="ticket")
        self.upsert_trade_pattern_usage(
            state.get("ticket"),
            state.get("pattern_snapshot") or {},
            trade_status="closed",
            profit=state.get("profit"),
            exit_reason=state.get("exit_reason") or "",
        )

    def upsert_pattern_stats(self, stats: Dict) -> None:
        if not config.PATTERN_USAGE_SYNC_ENABLED:
            return
        for item in (stats or {}).values():
            payload = {**item, "updated_at": datetime.utcnow().isoformat()}
            self._upsert("pattern_usage_stats", payload, conflict="id")

    def upsert_trade_pattern_usage(
        self,
        ticket,
        snapshot: Dict,
        *,
        trade_status: str = "open",
        profit=None,
        exit_reason: str = "",
    ) -> None:
        if not self.enabled or not config.PATTERN_USAGE_SYNC_ENABLED or not ticket:
            return
        for row in build_usage_rows(
            int(ticket),
            snapshot or {},
            trade_status=trade_status,
            profit=profit,
            exit_reason=exit_reason,
        ):
            self._upsert("trade_pattern_usage", row, conflict="id")

    def insert_trade_event(self, ticket: int, event_type: str, reason: str = "") -> None:
        payload = {
            "ticket": ticket,
            "event_type": event_type,
            "reason": reason,
            "created_at": datetime.utcnow().isoformat(),
        }
        self._insert("trade_events", payload)

    def _upsert(self, table: str, payload: Dict, conflict: str = "") -> None:
        if not self.enabled:
            return
        url = f"{self.base_url}/rest/v1/{table}"
        if conflict:
            url = f"{url}?on_conflict={conflict}"
        self._request("POST", url, payload)

    def _insert(self, table: str, payload: Dict) -> None:
        if not self.enabled:
            return
        self._request("POST", f"{self.base_url}/rest/v1/{table}", payload)

    def _request(self, method: str, url: str, payload: Dict) -> None:
        try:
            response = requests.request(method, url, headers=self.headers, json=payload, timeout=self.timeout)
            if response.status_code >= 400:
                logger.warning(f"Supabase sync failed {response.status_code}: {response.text[:240]}")
        except Exception as exc:
            logger.warning(f"Supabase sync error: {exc}")
