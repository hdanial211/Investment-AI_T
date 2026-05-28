"""Per-ticket active trade manager."""

import logging
from datetime import datetime
from typing import Dict, List

from .pattern_usage_tracker import build_pattern_snapshot
from .supabase_sync import SupabaseSync
from .virtual_exit_engine import VirtualExitEngine
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from news_filter import NewsFilter
import config

logger = logging.getLogger(__name__)


class ActiveTradeManager:
    """
    Manages active MT5 positions.
    - Synchronizes MT5 positions with Supabase
    - Applies Virtual Exit Logic (SL/TP/Trailing Stop)
    - Records results and triggers cooling-off when trades close
    """

    def __init__(self, connector, trade_memory, risk_mgr=None):
        self.connector = connector
        self.trade_memory = trade_memory
        self.risk_mgr = risk_mgr
        self.exit_engine = VirtualExitEngine()
        self.supabase = SupabaseSync()
        self.pending_adoptions = {}
        self.news_filter = NewsFilter()

    def manage_symbol(self, symbol: str, positions: List[Dict], indicators: Dict) -> List[Dict]:
        closed = []
        if positions is None:
            logger.warning(f"[{symbol}] manage_symbol received None for positions, skipping cycle.")
            return closed
            
        active_tickets = [pos["ticket"] for pos in positions]
        closed_by_broker = self.trade_memory.sync_with_broker(
            active_tickets, 
            symbol=symbol,
            get_profit_fn=self.connector.get_position_profit
        )
        for closed_state in closed_by_broker:
            self._sync_closed_state(closed_state, event_type="broker_closed")

        current_loop_tickets = set()

        for position in positions:
            ticket = int(position["ticket"])
            current_loop_tickets.add(ticket)
            
            state = self.trade_memory.get_trade_state(ticket)
            if not state:
                # To prevent a race condition where the AI just opened a trade
                # but hasn't saved it to Supabase yet, we delay adoption by 15 loops (~30 sec).
                adoption_info = self.pending_adoptions.get(ticket, {"count": 0, "symbol": symbol})
                count = adoption_info["count"]
                if count < 15:
                    self.pending_adoptions[ticket] = {"count": count + 1, "symbol": symbol}
                    continue 
                    
                # If it's still missing on the next loop, it's genuinely a manual trade
                del self.pending_adoptions[ticket]
                state = self.trade_memory.adopt_broker_position(position)
                # Auto-assign virtual SL/TP for manual trades if missing and enabled
                if self.risk_mgr and (not state.get("virtual_sl") or not state.get("virtual_tp")):
                    try:
                        from account_settings import AccountSettings
                        acct = AccountSettings(getattr(config, 'ACCOUNT_ID', 'acc_1'))
                        
                        if acct.manage_manual_sl or acct.manage_manual_tp:
                            pip_val = self.connector.get_pip_value(symbol)
                            params = self.risk_mgr.get_trade_params(
                                symbol=symbol,
                                action=state["action"],
                                price=state["entry_price"],
                                balance=10000,
                                pip_value=pip_val,
                                contract_size=100,
                                indicators=indicators,
                                trade_style="INTRADAY"
                            )
                            if acct.manage_manual_sl and not state.get("virtual_sl"):
                                state["virtual_sl"] = params["sl"]
                            if acct.manage_manual_tp and not state.get("virtual_tp"):
                                state["virtual_tp"] = params["tp"]
                                
                            state["reason"] = "Manual Trade (Auto-managed)"
                            logger.info(f"[{symbol}] Auto-assigned virtual SL/TP for manual trade {ticket}: SL={state.get('virtual_sl')}, TP={state.get('virtual_tp')}")
                    except Exception as e:
                        logger.warning(f"Failed to auto-assign SL/TP for manual trade {ticket}: {e}")

            state = self.exit_engine.update_state(state, position, indicators)
            state["last_checked_at"] = datetime.now().isoformat()
            self.trade_memory.update_trade_state(ticket, state)
            self.supabase.upsert_active_trade(state)

            trigger = self.exit_engine.get_exit_trigger(state, position)
            
            # Check Advanced News Filter: Close Profitable Trades
            # But only if we don't already have an exit trigger
            if not trigger:
                # We need acct_settings. We can get it from self.connector or self.risk_mgr?
                # Actually, terminal_trade_manager passes acct_settings to RiskManager, but ActiveTradeManager
                # doesn't directly have acct_settings. Let's load it directly.
                from account_settings import AccountSettings
                acct = AccountSettings(getattr(config, 'ACCOUNT_ID', 'acc_1'))
                if acct.news_close_profit:
                    safe, reason = self.news_filter.is_safe_to_trade(symbol)
                    if not safe:
                        # Event is active/upcoming. Are we in profit?
                        profit = float(position.get("profit") or 0.0)
                        if profit > 0:
                            trigger = "NEWS_EVASION_PROFIT"
                            logger.info(f"[{symbol}] Closing ticket {ticket} in profit ({profit}) due to upcoming news: {reason}")
            
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
                closed_state = self.trade_memory.data.get("closed_trades", {}).get(str(ticket), state)
                self._sync_closed_state(closed_state, event_type="virtual_exit", reason=trigger)
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
                self.supabase.upsert_active_trade(state)
                self.supabase.insert_trade_event(ticket, "close_failed", trigger)

        # Remove tickets from pending_adoptions that are no longer in broker (closed externally)
        # Only remove tickets that belong to the current symbol
        self.pending_adoptions = {
            k: v for k, v in self.pending_adoptions.items()
            if v["symbol"] != symbol or k in current_loop_tickets
        }
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
        pattern_snapshot = build_pattern_snapshot(indicators, symbol, action)
        state = self.exit_engine.seed_state(
            ticket=ticket,
            symbol=symbol,
            action=action,
            entry_price=entry_price,
            lot=lot,
            virtual_sl=trade_params.get("sl"),
            virtual_tp=trade_params.get("tp"),
            reason=signal.get("reason", ""),
            trade_style=signal.get("trade_style", "INTRADAY"),
            pattern_snapshot=pattern_snapshot,
        )
        self.trade_memory.add_trade_state(ticket, state)
        self.supabase.upsert_active_trade(state)
        self.supabase.insert_trade_event(ticket, "trade_opened", pattern_snapshot.get("confluence_combo", ""))
        self.supabase.upsert_pattern_stats(self.trade_memory.get_pattern_usage_stats())

    def mark_position_closed(self, ticket: int, symbol: str, profit: float, reason: str) -> None:
        """Close local/sync state for positions closed outside virtual trigger flow."""
        self.trade_memory.mark_trade_closed(ticket, symbol, profit, reason)
        closed_state = self.trade_memory.data.get("closed_trades", {}).get(str(ticket), {})
        self._sync_closed_state(closed_state, event_type=reason, reason=reason)

    def sync_heartbeat(self, cycle: int, message: str = "") -> None:
        self.supabase.upsert_heartbeat(cycle=cycle, message=message)

    def _sync_closed_state(self, closed_state: Dict, event_type: str, reason: str = "") -> None:
        if not closed_state:
            return
        ticket = int(closed_state.get("ticket") or 0)
        if not ticket:
            return
        exit_reason = reason or closed_state.get("exit_reason") or event_type
        self.supabase.mark_trade_closed(closed_state)
        self.supabase.insert_trade_event(ticket, event_type, exit_reason)
        self.supabase.upsert_pattern_stats(self.trade_memory.get_pattern_usage_stats())
