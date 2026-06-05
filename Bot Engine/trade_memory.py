"""
trade_memory.py - Manages Trade Memory & Cooling-off periods.

Stores the AI's thesis (reason) for entering a trade so it can be evaluated later.
Also tracks when symbols were last traded to enforce cooling-off periods.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import config
from trade_management.pattern_usage_tracker import update_stats_on_close, update_stats_on_open
from file_mutex import MemoryLock

logger = logging.getLogger(__name__)

class TradeMemory:
    def __init__(self, account_id: str):
        self.account_id = account_id
        self.memory_file = os.path.join(config.LOG_DIR, f"trade_memory_{account_id}.json")
        self.data = {
            "active_trades": {},  # ticket_id (str) -> dict(symbol, action, reason, target)
            "closed_trades": {},
            "pattern_usage_stats": {},
            "cooling_off": {}     # symbol -> {timestamp, duration}
        }
        self._load()
        self.data.setdefault("active_trades", {})
        self.data.setdefault("closed_trades", {})
        self.data.setdefault("pattern_usage_stats", {})
        self.data.setdefault("cooling_off", {})
        self._purge_expired_cooloffs()

    def _purge_expired_cooloffs(self):
        """Remove any expired cooling-off entries (leftover from previous sessions)."""
        expired = []
        for symbol, cool_data in self.data.get("cooling_off", {}).items():
            try:
                if isinstance(cool_data, str):
                    ts = cool_data
                    dur = config.COOLING_OFF_MINUTES
                else:
                    ts = cool_data["timestamp"]
                    dur = cool_data["duration"]
                elapsed = datetime.now() - datetime.fromisoformat(ts).replace(tzinfo=None)
                if elapsed >= timedelta(minutes=dur):
                    expired.append(symbol)
            except Exception:
                expired.append(symbol)
        
        if expired:
            for sym in expired:
                del self.data["cooling_off"][sym]
                logger.info(f"[{sym}] Expired cooling-off cleared on startup.")
            self._save()

    def _load(self):
        """Fetch active trades and pattern usage stats from Supabase."""
        try:
            from trade_management.supabase_sync import SupabaseSync
            sync = SupabaseSync()
            
            # Fetch active trades
            trades = sync.fetch_active_trades(self.account_id)
            self.data["active_trades"] = {}
            for t in trades:
                # Map Supabase columns back to internal state dict format
                state = {
                    "ticket": t.get("ticket"),
                    "symbol": t.get("symbol"),
                    "action": t.get("direction"),
                    "direction": t.get("direction"),
                    "lot": t.get("lot"),
                    "entry_price": t.get("entry_price"),
                    "floating_profit": t.get("floating_profit"),
                    "virtual_sl": t.get("virtual_sl"),
                    "virtual_tp": t.get("virtual_tp"),
                    "virtual_trailing_stop": t.get("virtual_trailing_stop"),
                    "current_status": t.get("current_status"),
                    "reason": t.get("original_thesis"),
                    "timestamp": t.get("opened_at"),
                    "last_price": t.get("last_price"),
                    "profit_lock_level": t.get("profit_lock_level"),
                    "max_drawdown": t.get("max_drawdown"),
                    "exit_reason": t.get("exit_reason"),
                    "trade_style": t.get("trade_style"),
                    "vision_bias": t.get("vision_bias"),
                    "trail_activation_price": t.get("trail_activation_price"),
                    "pattern_snapshot": {
                        "primary_pattern": t.get("primary_pattern"),
                        "pattern_names": t.get("pattern_names"),
                        "pattern_categories": t.get("pattern_categories"),
                        "pattern_timeframes": t.get("pattern_timeframes"),
                        "confluence_combo": t.get("confluence_combo"),
                        "pattern_confidence": t.get("pattern_confidence"),
                        "pattern_count": t.get("pattern_count"),
                    }
                }
                self.data["active_trades"][str(t["ticket"])] = state
                
            # Fetch pattern usage stats
            stats = sync.fetch_pattern_usage_stats()
            self.data["pattern_usage_stats"] = stats
            
        except Exception as e:
            logger.warning(f"TradeMemory: Failed to load from Supabase: {e}")

    def _save(self):
        """No longer used. Updates are pushed directly to Supabase via ActiveTradeManager or add_trade."""
        pass

    def add_trade(
        self,
        ticket: int,
        symbol: str,
        action: str,
        reason: str,
        target_tp: float,
        entry_price: float = None,
        lot: float = None,
        virtual_sl: float = None,
        virtual_tp: float = None,
        pattern_snapshot: Dict = None,
    ):
        """Record the thesis/reason for a newly opened trade."""
        state = {
            "ticket": int(ticket),
            "account_id": self.account_id,
            "symbol": symbol,
            "action": action,
            "direction": action,
            "reason": reason,
            "target": target_tp,
            "timestamp": datetime.now().isoformat(),
            "entry_price": entry_price,
            "lot": lot,
            "virtual_sl": virtual_sl,
            "virtual_tp": virtual_tp,
            "virtual_trailing_stop": None,
            "trail_activation_price": None,
            "profit_lock_level": None,
            "max_favorable_price": entry_price,
            "max_drawdown": 0.0,
            "current_status": "OPEN",
            "exit_reason": None,
            "pattern_snapshot": pattern_snapshot or {},
            "last_ai_eval_time": datetime.now().isoformat(),
        }
        self.data["active_trades"][str(ticket)] = state
        if pattern_snapshot:
            self.data["pattern_usage_stats"] = update_stats_on_open(
                self.data.get("pattern_usage_stats", {}),
                int(ticket),
                pattern_snapshot,
            )
        self._save()

    def add_trade_state(self, ticket: int, state: Dict):
        """Store a complete active-trade state object."""
        key = str(ticket)
        is_new_trade = key not in self.data["active_trades"]
        self.data["active_trades"][key] = state
        if is_new_trade:
            self.data["pattern_usage_stats"] = update_stats_on_open(
                self.data.get("pattern_usage_stats", {}),
                int(ticket),
                state.get("pattern_snapshot") or {},
            )
        self._save()

    def get_trade_state(self, ticket: int) -> Optional[Dict]:
        """Return stored active-trade state for one ticket."""
        key = str(ticket)
        if key not in self.data["active_trades"]:
            # Reload from disk in case another process (like Terminal 1) just added it
            self._load()
        return self.data["active_trades"].get(key)

    def update_trade_state(self, ticket: int, updates: Dict):
        """Merge updates into an active-trade state."""
        key = str(ticket)
        current = self.data["active_trades"].get(key, {})
        current.update(updates)
        self.data["active_trades"][key] = current
        self._save()

    def adopt_broker_position(self, position: Dict) -> Dict:
        """
        Create memory for a broker position that exists but was not opened by
        this bot instance, so it can still be monitored.
        """
        ticket = int(position["ticket"])
        key = str(ticket)
        
        # Auto-Recovery: If it was mistakenly marked as closed due to MT5 sync error,
        # restore it from closed_trades!
        if key in self.data.get("closed_trades", {}):
            state = self.data["closed_trades"].pop(key)
            state["current_status"] = "OPEN"
            state["exit_reason"] = None
            self.data["active_trades"][key] = state
            self._save()
            logger.info(f"Auto-recovered AI trade {ticket} from closed history.")
            return state

        state = {
            "ticket": ticket,
            "account_id": self.account_id,
            "symbol": position.get("symbol"),
            "action": position.get("direction"),
            "direction": position.get("direction"),
            "reason": "Adopted open broker position",
            "target": position.get("tp") or None,
            "timestamp": datetime.now().isoformat(),
            "entry_price": position.get("price_open"),
            "lot": position.get("volume"),
            "virtual_sl": position.get("sl") or None,
            "virtual_tp": position.get("tp") or None,
            "virtual_trailing_stop": None,
            "trail_activation_price": None,
            "profit_lock_level": None,
            "max_favorable_price": position.get("price_open"),
            "max_drawdown": 0.0,
            "current_status": "ADOPTED",
            "exit_reason": None,
            "trade_style": "MANUAL",
            "pattern_snapshot": {},
            "last_ai_eval_time": datetime.now().isoformat(),
        }
        self.data["active_trades"][str(ticket)] = state
        self._save()
        return state

    def get_trade_reason(self, ticket: int) -> Optional[str]:
        """Get the original thesis for a trade."""
        trade = self.data["active_trades"].get(str(ticket))
        return trade["reason"] if trade else None
        
    def get_symbol_active_memory(self, symbol: str) -> list:
        """Get all active memory records for a specific symbol."""
        records = []
        for ticket, info in self.data["active_trades"].items():
            if info["symbol"] == symbol:
                records.append(info)
        return records

    def mark_trade_closed(self, ticket: int, symbol: str, profit: float = 0.0, exit_reason: str = "closed"):
        """Move an active trade to closed history and start cooling-off."""
        key = str(ticket)
        state = self.data["active_trades"].get(key, {})
        snapshot = state.get("pattern_snapshot") or {}
        snapshot["ticket"] = int(ticket)
        state.update({
            "current_status": "CLOSED",
            "exit_reason": exit_reason,
            "profit": round(float(profit or 0.0), 2),
            "closed_at": datetime.now().isoformat(),
        })
        self.data.setdefault("closed_trades", {})[key] = state
        # Refresh stats from Supabase to avoid overwriting another terminal's data
        try:
            from trade_management.supabase_sync import SupabaseSync
            sync = SupabaseSync()
            stats = sync.fetch_pattern_usage_stats()
            if stats:
                self.data["pattern_usage_stats"] = stats
        except Exception:
            pass

        self.data["pattern_usage_stats"] = update_stats_on_close(
            self.data.get("pattern_usage_stats", {}),
            snapshot,
            profit,
            exit_reason,
        )
        self.remove_trade_and_cool_off(ticket, symbol, profit=profit)

    def get_pattern_usage_stats(self) -> Dict:
        return self.data.get("pattern_usage_stats", {})

    def get_dashboard_snapshot(self) -> Dict:
        """Return the current local state used by dashboard views."""
        return {
            "active_trades": self.data.get("active_trades", {}),
            "closed_trades": self.data.get("closed_trades", {}),
            "pattern_usage_stats": self.data.get("pattern_usage_stats", {}),
            "cooling_off": self.data.get("cooling_off", {}),
        }

    def remove_trade_and_cool_off(self, ticket: int, symbol: str, profit: float = 0.0):
        """Remove a closed trade from memory and start cooling-off period."""
        if str(ticket) in self.data["active_trades"]:
            del self.data["active_trades"][str(ticket)]
            
        # Adaptive Cool-down: 5 mins if win, 15 mins if loss
        duration = 5 if profit > 0 else config.COOLING_OFF_MINUTES
        
        self.data["cooling_off"][symbol] = {
            "timestamp": datetime.now().isoformat(),
            "duration": duration
        }
        self._save()

    def is_cooling_off(self, symbol: str) -> Tuple[bool, str]:
        """Check if a symbol is currently in a cooling-off period."""
        if symbol not in self.data["cooling_off"]:
            return False, ""
            
        cool_data = self.data["cooling_off"][symbol]
        
        # Backwards compatibility if old format (just string timestamp)
        if isinstance(cool_data, str):
            last_trade_time_str = cool_data
            cool_down_duration = timedelta(minutes=config.COOLING_OFF_MINUTES)
        else:
            last_trade_time_str = cool_data["timestamp"]
            cool_down_duration = timedelta(minutes=cool_data["duration"])
            
        try:
            last_trade_time = datetime.fromisoformat(last_trade_time_str).replace(tzinfo=None)
            elapsed = datetime.now() - last_trade_time
            
            if elapsed < cool_down_duration:
                remaining_secs = (cool_down_duration - elapsed).total_seconds()
                remaining_mins = int(remaining_secs / 60)
                remaining_s = int(remaining_secs % 60)
                return True, f"Cooling off for {remaining_mins}m {remaining_s}s"
        except Exception:
            pass
        
        # Expired — remove entry so we don't check again
        del self.data["cooling_off"][symbol]
        self._save()
        return False, ""

    def sync_with_broker(self, active_tickets: list, symbol: str = None, get_close_info_fn=None):
        """
        Compare active broker tickets with local memory.
        If a ticket is in memory but NOT in broker, it means it closed.
        We must trigger a cooling off for its symbol.
        """
        active_str_tickets = [str(t) for t in active_tickets]
        memory_tickets = list(self.data["active_trades"].keys())
        closed_states = []
        
        for mt in memory_tickets:
            if symbol and self.data["active_trades"][mt].get("symbol") != symbol:
                continue
            if mt not in active_str_tickets:
                sym = self.data["active_trades"][mt]["symbol"]
                profit = 0.0
                exit_reason = "broker_closed"
                
                if get_close_info_fn:
                    try:
                        close_info = get_close_info_fn(int(mt))
                        profit = close_info.get("profit", 0.0)
                        comment = (close_info.get("comment") or "").lower()
                        
                        if "so:" in comment:
                            exit_reason = "Stop Out (Margin Call)"
                        elif "sl:" in comment:
                            exit_reason = "Broker SL"
                        elif "tp:" in comment:
                            exit_reason = "Broker TP"
                        elif "virtual_sl" in comment:
                            exit_reason = "virtual_sl"
                        elif "virtual_tp" in comment:
                            exit_reason = "virtual_tp"
                        elif "profit_lock" in comment:
                            exit_reason = "profit_lock"
                        elif "virtual_trailing_stop" in comment:
                            exit_reason = "virtual_trailing_stop"
                        elif "reverse_signal" in comment:
                            exit_reason = "reverse_signal"
                            
                    except Exception as e:
                        logger.error(f"Failed to fetch close info for trade {mt}: {e}")
                        
                logger.info(f"[{sym}] Trade {mt} closed ({exit_reason}). Initiating cooling-off period.")
                self.mark_trade_closed(int(mt), sym, profit=profit, exit_reason=exit_reason)
                closed = self.data.get("closed_trades", {}).get(mt)
                if closed:
                    closed_states.append(closed)

        return closed_states
