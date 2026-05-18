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

logger = logging.getLogger(__name__)

class TradeMemory:
    def __init__(self):
        self.memory_file = os.path.join(config.LOG_DIR, "trade_memory.json")
        self.data = {
            "active_trades": {},  # ticket_id (str) -> dict(symbol, action, reason, target)
            "cooling_off": {}     # symbol -> timestamp (isoformat)
        }
        self._load()

    def _load(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r") as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load trade memory: {e}")

    def _save(self):
        os.makedirs(config.LOG_DIR, exist_ok=True)
        try:
            with open(self.memory_file, "w") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save trade memory: {e}")

    def add_trade(self, ticket: int, symbol: str, action: str, reason: str, target_tp: float):
        """Record the thesis/reason for a newly opened trade."""
        self.data["active_trades"][str(ticket)] = {
            "symbol": symbol,
            "action": action,
            "reason": reason,
            "target": target_tp,
            "timestamp": datetime.now().isoformat()
        }
        self._save()

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
            last_trade_time = datetime.fromisoformat(last_trade_time_str)
            elapsed = datetime.now() - last_trade_time
            
            if elapsed < cool_down_duration:
                remaining = int((cool_down_duration - elapsed).total_seconds() / 60)
                return True, f"Cooling off for {remaining} more minutes"
        except Exception:
            pass
            
        return False, ""

    def sync_with_broker(self, active_tickets: list):
        """
        Compare active broker tickets with local memory.
        If a ticket is in memory but NOT in broker, it means it closed.
        We must trigger a cooling off for its symbol.
        """
        active_str_tickets = [str(t) for t in active_tickets]
        memory_tickets = list(self.data["active_trades"].keys())
        
        for mt in memory_tickets:
            if mt not in active_str_tickets:
                sym = self.data["active_trades"][mt]["symbol"]
                logger.info(f"[{sym}] Trade {mt} closed. Initiating cooling-off period.")
                self.remove_trade_and_cool_off(int(mt), sym)
