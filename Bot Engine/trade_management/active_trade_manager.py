"""Per-ticket active trade manager."""

import logging
from datetime import datetime
from typing import Dict, List

from .virtual_exit_engine import VirtualExitEngine

logger = logging.getLogger(__name__)


class ActiveTradeManager:
    """Keeps watch over each open ticket and triggers virtual exits."""

    def __init__(self, connector, trade_memory, risk_mgr=None):
        self.connector = connector
        self.trade_memory = trade_memory
        self.risk_mgr = risk_mgr
        self.exit_engine = VirtualExitEngine()

    def manage_symbol(self, symbol: str, positions: List[Dict], indicators: Dict) -> List[Dict]:
        closed = []
        active_tickets = [pos["ticket"] for pos in positions]
        self.trade_memory.sync_with_broker(active_tickets, symbol=symbol)

        for position in positions:
            ticket = int(position["ticket"])
            state = self.trade_memory.get_trade_state(ticket)
            if not state:
                state = self.trade_memory.adopt_broker_position(position)

            state = self.exit_engine.update_state(state, position, indicators)
            state["last_checked_at"] = datetime.now().isoformat()
            self.trade_memory.update_trade_state(ticket, state)

            trigger = self.exit_engine.get_exit_trigger(state, position)
            if not trigger:
                continue

            logger.warning(
                f"[{symbol}] Virtual exit triggered: {trigger} | "
                f"Ticket {ticket} | Price {position.get('price_current')}"
            )
            if self.connector.close_trade(ticket, symbol):
                profit = float(position.get("profit") or 0.0)
                if self.risk_mgr:
                    self.risk_mgr.record_trade_result(profit)
                self.trade_memory.mark_trade_closed(ticket, symbol, profit, trigger)
                closed.append({
                    "ticket": ticket,
                    "symbol": symbol,
                    "profit": profit,
                    "exit_reason": trigger,
                })
            else:
                state["current_status"] = "CLOSE_FAILED"
                state["exit_reason"] = trigger
                state["last_close_failed_at"] = datetime.now().isoformat()
                self.trade_memory.update_trade_state(ticket, state)

        return closed

    def register_new_trade(
        self,
        *,
        ticket: int,
        symbol: str,
        action: str,
        entry_price: float,
        lot: float,
        trade_params: Dict,
        signal: Dict,
        indicators: Dict,
    ) -> None:
        pattern_snapshot = {
            "pattern_bias": indicators.get("pattern_bias"),
            "detected_patterns": (indicators.get("detected_patterns") or [])[:8],
        }
        state = self.exit_engine.seed_state(
            ticket=ticket,
            symbol=symbol,
            action=action,
            entry_price=entry_price,
            lot=lot,
            virtual_sl=trade_params.get("sl"),
            virtual_tp=trade_params.get("tp"),
            reason=signal.get("reason", ""),
            pattern_snapshot=pattern_snapshot,
        )
        self.trade_memory.add_trade_state(ticket, state)
