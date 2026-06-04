"""Grid Recovery & Averaging Manager."""

import logging
from typing import Dict, List
import config

logger = logging.getLogger(__name__)

class GridManager:
    def __init__(self, connector, trade_memory, risk_mgr=None):
        self.connector = connector
        self.trade_memory = trade_memory
        self.risk_mgr = risk_mgr
        
    def manage_baskets(self, symbol: str, positions: List[Dict], indicators: Dict) -> List[int]:
        """
        Manages grid baskets and returns a list of closed tickets.
        """
        closed_tickets = []
        try:
            from account_settings import AccountSettings
            acct = AccountSettings(getattr(config, 'ACCOUNT_ID', 'acc_1'))
            

            atr = (indicators or {}).get("atr")
            if not atr or atr <= 0:
                return closed_tickets
                
            # Group positions into baskets
            # Key: (action, trade_style)
            baskets = {}
            for pos in positions:
                ticket = int(pos["ticket"])
                state = self.trade_memory.get_trade_state(ticket) or {}
                
                # Skip trades that are already being closed
                if state.get("current_status") == "CLOSE_FAILED":
                    continue
                    
                action = state.get("action") or state.get("direction")
                if not action:
                    action = "BUY" if pos.get("type") == 0 else "SELL"
                    
                trade_style = state.get("trade_style", "INTRADAY")
                
                key = (action, trade_style)
                if key not in baskets:
                    baskets[key] = []
                baskets[key].append({
                    "position": pos,
                    "state": state
                })
                
            for (action, trade_style), items in baskets.items():
                if len(items) == 0:
                    continue
                    
                # Fetch grid settings for this specific style
                grid_settings = acct.get_grid_settings(trade_style)
                if not grid_settings["enabled"]:
                    continue
                    
                # Calculate net profit
                net_profit = sum(float(item["position"].get("profit", 0.0)) for item in items)
                
                # Basket Closure Check
                # Only manage as a basket if there is more than 1 trade
                if len(items) > 1 and net_profit >= 0.10: 
                    logger.info(f"[{symbol}] Basket ({action}, {trade_style}) net profit {net_profit:.2f} >= 0.10. Triggering Basket Closure for {len(items)} trades.")
                    for item in items:
                        tkt = int(item["position"]["ticket"])
                        if self.connector.close_trade(tkt, symbol, comment="Basket Recovery"):
                            profit = float(item["position"].get("profit") or 0.0)
                            if self.risk_mgr:
                                self.risk_mgr.record_trade_result(profit)
                            self.trade_memory.mark_trade_closed(tkt, symbol, profit, "BASKET_RECOVERY")
                            closed_tickets.append(tkt)
                    continue # Skip grid entry since we closed the basket
                    
                # Dynamic Grid Entry Check
                # Find the worst entry we have so far (lowest for BUY, highest for SELL) to measure distance from it
                prices = [float(item["position"]["price_open"]) for item in items]
                current_price = float(items[0]["position"]["price_current"])
                
                grid_distance = grid_settings["atr_multiplier"] * atr
                should_open_grid = False
                
                if action == "BUY":
                    lowest_price = min(prices)
                    if current_price <= (lowest_price - grid_distance):
                        should_open_grid = True
                else:
                    highest_price = max(prices)
                    if current_price >= (highest_price + grid_distance):
                        should_open_grid = True
                        
                if should_open_grid and len(items) < (grid_settings["max_steps"] + 1):
                    # Find the lot of the most recent trade (the one with the lowest price for BUY)
                    if action == "BUY":
                        last_trade = min(items, key=lambda x: float(x["position"]["price_open"]))
                    else:
                        last_trade = max(items, key=lambda x: float(x["position"]["price_open"]))
                        
                    last_lot = float(last_trade["position"]["volume"])
                    new_lot = round(last_lot * grid_settings["lot_multiplier"], 2)
                    
                    # Ensure minimum lot step (0.01)
                    if new_lot < 0.01:
                        new_lot = 0.01
                    if new_lot > 10.0:
                        new_lot = 10.0
                        
                    logger.info(f"[{symbol}] Grid Entry Triggered for ({action}, {trade_style}). Current: {current_price}, Distance required: {grid_distance:.5f}. Opening new {action} with lot {new_lot}")
                    
                    order_ticket = self.connector.place_order(symbol, action, new_lot, comment=f"Grid {len(items)}")
                    if order_ticket:
                        from trade_management.pattern_usage_tracker import build_pattern_snapshot
                        pattern_snapshot = build_pattern_snapshot(indicators, symbol, action)
                        
                        # Seed state so the new trade adopts the correct trade_style and doesn't get treated as manual
                        state = {
                            "ticket": order_ticket,
                            "symbol": symbol,
                            "action": action,
                            "entry_price": current_price,
                            "lot": new_lot,
                            "reason": f"Grid Recovery ({len(items)} layers)",
                            "trade_style": trade_style,
                            "pattern_snapshot": pattern_snapshot,
                            "grid_basket": True,
                            "virtual_sl": None,
                            "virtual_tp": None
                        }
                        
                        # --- Calculate Average Price and Unify Virtual SL/TP ---
                        try:
                            total_volume = sum(float(item["position"]["volume"]) for item in items) + new_lot
                            total_cost = sum(float(item["position"]["price_open"]) * float(item["position"]["volume"]) for item in items) + (current_price * new_lot)
                            avg_price = total_cost / total_volume
                            
                            from style_params import get_style_params
                            style_p = get_style_params(trade_style, symbol)
                            
                            sl_dist = style_p.get("sl_atr_multi", 1.5) * atr
                            tp_dist = style_p.get("tp_atr_multi", 2.0) * atr
                            
                            if action == "BUY":
                                new_sl = round(avg_price - sl_dist, 5)
                                new_tp = round(avg_price + tp_dist, 5)
                            else:
                                new_sl = round(avg_price + sl_dist, 5)
                                new_tp = round(avg_price - tp_dist, 5)
                                
                            logger.info(f"[{symbol}] Basket Average Price updated to {avg_price:.5f}. Unified SL: {new_sl:.5f}, TP: {new_tp:.5f}")
                            
                            state["virtual_sl"] = new_sl
                            state["virtual_tp"] = new_tp
                            
                            # Also update existing layers
                            from trade_management.supabase_sync import SupabaseSync
                            sb = SupabaseSync()
                            
                            for item in items:
                                tkt = int(item["position"]["ticket"])
                                old_state = self.trade_memory.get_trade_state(tkt)
                                if old_state:
                                    old_state["virtual_sl"] = new_sl
                                    old_state["virtual_tp"] = new_tp
                                    # Clear trailing stop logic so it restarts from the new average
                                    old_state["profit_lock_level"] = None
                                    old_state["virtual_trailing_stop"] = None
                                    self.trade_memory.add_trade_state(tkt, old_state)
                                    try:
                                        sb.upsert_active_trade(old_state)
                                    except Exception as e2:
                                        logger.error(f"Failed to upsert old grid trade {tkt}: {e2}")
                                        
                        except Exception as calc_err:
                            logger.error(f"Error calculating unified basket SL/TP: {calc_err}")

                        self.trade_memory.add_trade_state(order_ticket, state)
                        # We also upsert the new trade to supabase to make it permanent
                        try:
                            from trade_management.supabase_sync import SupabaseSync
                            sb = SupabaseSync()
                            sb.upsert_active_trade(state)
                        except Exception as e:
                            logger.error(f"Failed to upsert grid trade {order_ticket} to supabase: {e}")
                            
        except Exception as e:
            logger.error(f"Error in grid manager for {symbol}: {e}")
            
        return closed_tickets
