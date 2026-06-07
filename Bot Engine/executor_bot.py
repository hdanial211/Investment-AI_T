"""
executor_bot.py — Per-Account Executor (Always-On)

Combines the functionality of:
  - entry_terminal.py  (execute trade commands from Analyzer)
  - trade_monitor.py   (manage active trades: SL/TP/BE+/Trailing)

Each account gets its own instance. It:
  1. Connects to its own MT5 terminal and stays connected 24/7
  2. Polls Supabase `trade_commands` every 5s for pending orders
  3. Manages active trades every 2s (Virtual SL/TP, BE+, Trailing Stop)
  4. Detects manual trades and auto-adopts them
  5. Syncs everything back to Supabase for the Dashboard

Usage: python executor_bot.py <account_id>
"""

import logging
import signal
import os
import sys
import time
import json
from datetime import datetime, timezone
from typing import Optional, Dict, List

import config
from mt5_connector import MT5Connector
from risk_manager import RiskManager
from trade_memory import TradeMemory
from trade_management.active_trade_manager import ActiveTradeManager
from trade_management.supabase_sync import SupabaseSync
from account_settings import AccountSettings
from ai_engine import review_trade_risk
import system_settings
from logger import setup_logging

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logger = setup_logging()

# ─────────────────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────────────────
_shutdown_requested = False

def _signal_handler(signum, frame):
    global _shutdown_requested
    logger.info("Shutdown signal received. Finishing current cycle...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ─────────────────────────────────────────────────────────────────────────────
# COMMAND PROCESSOR: Execute trade commands from Supabase
# ─────────────────────────────────────────────────────────────────────────────

def execute_open_trade(
    payload: Dict,
    symbol: str,
    connector: MT5Connector,
    risk_mgr: RiskManager,
    trade_memory: TradeMemory,
    active_manager: ActiveTradeManager,
    acct_settings: AccountSettings,
    account_id: str,
) -> Dict:
    """Execute an OPEN_TRADE command. Returns result dict."""

    action = payload.get("action", "HOLD")
    confidence = float(payload.get("confidence", 0.0))
    trade_style = payload.get("trade_style", "INTRADAY").upper()
    reason = payload.get("reason", "")

    ai_signal = {
        "action": action,
        "confidence": confidence,
        "trade_style": trade_style,
        "reason": reason,
    }

    # 1. Validate signal
    signal_valid, signal_reason = risk_mgr.validate_signal(ai_signal)
    if not signal_valid:
        return {"success": False, "reason": f"Signal invalid: {signal_reason}"}

    # 2. Account-level confidence filter
    if confidence < acct_settings.min_ai_confidence:
        return {"success": False, "reason": f"Confidence {confidence:.2f} < min {acct_settings.min_ai_confidence}"}

    # 3. Style enabled check
    if not acct_settings.is_style_enabled(trade_style):
        return {"success": False, "reason": f"Style {trade_style} disabled"}

    # 4. Session filter
    session_ok, session_reason = risk_mgr.validate_session(trade_style, symbol)
    if not session_ok:
        if "Asia" in session_reason and not acct_settings.block_asia_session:
            pass  # User allowed Asia session
        else:
            return {"success": False, "reason": session_reason}

    # 5. ATR filter
    indicators = {
        "atr": payload.get("atr", 0),
        "adx": payload.get("adx", 0),
        "m15_rsi": payload.get("m15_rsi", 50),
        "h4_trend": payload.get("h4_trend"),
        "h1_macd_trend": payload.get("h1_macd_trend"),
        "market_regime": payload.get("market_regime", "RANGING"),
        "detected_patterns": payload.get("detected_patterns", []),
        "sufficient_volatility": True,
    }

    atr_ok, atr_reason = risk_mgr.validate_min_atr(trade_style, symbol, indicators)
    if not atr_ok:
        return {"success": False, "reason": atr_reason}

    # 6. Open positions check
    open_positions = connector.get_open_positions(symbol)
    open_pos_count = len(open_positions)

    can_trade, risk_reason = risk_mgr.can_trade(symbol, open_pos_count, indicators, trade_memory, acct_settings)
    if not can_trade:
        return {"success": False, "reason": risk_reason}

    # 7. Daily & spread limits
    daily_ok, daily_reason = risk_mgr.check_daily_limits(connector, acct_settings)
    if not daily_ok:
        return {"success": False, "reason": daily_reason}

    spread_ok, spread_reason = risk_mgr.validate_spread(connector, symbol, acct_settings.max_spread_points)
    if not spread_ok:
        return {"success": False, "reason": spread_reason}

    # 8. Max trades per style
    style_max = acct_settings.get_max_trades_for_style(trade_style)
    if style_max > 0:
        current_style_count = 0
        for p in open_positions:
            ticket = p.get("ticket")
            state = trade_memory.get_trade_state(ticket) if trade_memory else None
            p_style = state.get("trade_style", "INTRADAY").upper() if state else "INTRADAY"
            if p_style == trade_style:
                current_style_count += 1
        if current_style_count >= style_max:
            return {"success": False, "reason": f"Max {trade_style} trades ({style_max}) reached"}

    # 9. Max total trades
    total_max = acct_settings.get_max_total_trades()
    all_positions = connector.get_open_positions()
    if len(all_positions) >= total_max:
        return {"success": False, "reason": f"Max total trades ({total_max}) reached"}

    # 10. Close opposing positions if hedging is OFF
    if not acct_settings.allow_hedging and open_pos_count > 0 and action in ("BUY", "SELL"):
        for pos in open_positions:
            if pos["direction"] != action:
                logger.warning(
                    f"[{symbol}] AI signal ({action}) contradicts position "
                    f"{pos['ticket']} ({pos['direction']}). CLOSING!"
                )
                if connector.close_trade(pos["ticket"], symbol, comment="reverse_signal"):
                    active_manager.mark_position_closed(
                        pos["ticket"], symbol,
                        profit=pos["profit"],
                        reason="reverse_signal",
                    )

    # 11. Calculate trade parameters
    account = connector.get_account_info()
    balance = account.get("balance", 10000.0)
    pip_value = connector.get_pip_value(symbol)
    contract = connector.get_contract_size(symbol)

    tick = connector.get_tick(symbol)
    if not tick:
        return {"success": False, "reason": "Cannot get tick data"}

    price = tick["ask"] if action == "BUY" else tick["bid"]

    trade_params = risk_mgr.get_trade_params(
        symbol=symbol,
        action=action,
        price=price,
        balance=balance,
        pip_value=pip_value,
        contract_size=contract,
        indicators=indicators,
        trade_style=trade_style,
    )

    # R:R validation
    rr_ok, rr_reason = risk_mgr.validate_rr_ratio(
        trade_params["sl_pips"], trade_params["tp_pips"], trade_style, symbol
    )
    if not rr_ok:
        return {"success": False, "reason": rr_reason}

    # Override lot from account settings
    style_lot = acct_settings.get_lot_for_style(trade_style)
    if style_lot > 0:
        trade_params["lot"] = style_lot

    # 12. AI Risk Review (per-account — uses dedicated Risk API key)
    if config.ENABLE_RISK_REVIEW:
        risk_config = acct_settings.get_risk_config()
        if risk_config:
            # v4 role-based: single dedicated risk provider
            account_ai_sequence = [risk_config] + acct_settings.get_role_fallbacks(for_role="risk")
        else:
            # Legacy: flat provider list
            account_ai_sequence = acct_settings.get_providers_list()
        risk_review = review_trade_risk(
            ai_signal, indicators, trade_params, symbol,
            provider_sequence=account_ai_sequence
        )
        ai_signal["risk_review"] = risk_review
        if not risk_review["approved"]:
            return {"success": False, "reason": f"Risk review rejected: {risk_review['reason']}"}

    # 13. Execute trade!
    entry_price = tick["ask"] if action == "BUY" else tick["bid"]

    exec_result = connector.place_order(
        symbol=symbol,
        action=action,
        lot=trade_params["lot"],
        sl_price=trade_params["sl"],
        tp_price=trade_params["tp"],
        comment=f"{trade_style}_{confidence:.2f}",
    )

    if exec_result["success"]:
        actual_price = exec_result.get("price") or entry_price
        active_manager.register_new_trade(
            ticket=exec_result["ticket"],
            symbol=symbol,
            action=action,
            entry_price=actual_price,
            lot=trade_params["lot"],
            trade_params=trade_params,
            signal=ai_signal,
            indicators=indicators,
        )
        logger.info(f"✅ Trade executed! Ticket: {exec_result['ticket']}")
        return {"success": True, "ticket": exec_result["ticket"], "price": actual_price}
    else:
        return {"success": False, "reason": f"MT5 error: {exec_result['message']}"}


def execute_close_trade(
    payload: Dict,
    connector: MT5Connector,
    active_manager: ActiveTradeManager,
    account_id: str,
) -> Dict:
    """Execute a CLOSE_TRADE command."""
    ticket = payload.get("ticket")
    symbol = payload.get("symbol", "")
    reason = payload.get("reason", "ai_eval_close")

    if not ticket:
        return {"success": False, "reason": "No ticket specified"}

    if connector.close_trade(int(ticket), symbol, comment=reason):
        active_manager.mark_position_closed(
            int(ticket), symbol, profit=0.0, reason=reason
        )
        logger.info(f"✅ Trade {ticket} closed. Reason: {reason}")
        return {"success": True, "ticket": ticket}
    else:
        return {"success": False, "reason": f"MT5 failed to close ticket {ticket}"}


def execute_update_sl_tp(
    payload: Dict,
    connector: MT5Connector,
    trade_memory: TradeMemory,
    account_id: str,
) -> Dict:
    """Execute an UPDATE_SL_TP command."""
    ticket = int(payload.get("ticket", 0))
    new_sl = payload.get("sl")
    new_tp = payload.get("tp")
    reason = payload.get("reason", "ai_eval_update")

    if not ticket:
        return {"success": False, "reason": "No ticket specified"}

    # Update in trade_memory (virtual SL/TP)
    state = trade_memory.get_trade_state(ticket)
    if state:
        if new_sl is not None:
            state["virtual_sl"] = float(new_sl)
        if new_tp is not None:
            state["virtual_tp"] = float(new_tp)
        trade_memory.update_trade_state(ticket, state)

        # Also sync to Supabase
        from trade_management.supabase_sync import SupabaseSync
        sync = SupabaseSync()
        sync.upsert_active_trade(state)

        logger.info(f"✅ Trade {ticket} updated: SL={new_sl}, TP={new_tp}. Reason: {reason}")
        return {"success": True, "ticket": ticket, "sl": new_sl, "tp": new_tp}
    else:
        return {"success": False, "reason": f"Trade {ticket} not found in memory"}


# ─────────────────────────────────────────────────────────────────────────────
# SYMBOL MAPPER: Map Master Analyzer symbols to this account's symbols
# ─────────────────────────────────────────────────────────────────────────────

def build_symbol_mapper(acct_settings: AccountSettings) -> Dict[str, str]:
    """Build a mapping from Master Analyzer symbols to this account's broker symbols."""
    master_settings = AccountSettings("master")
    master_settings.force_refresh()

    master_xau = str(master_settings._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip()
    master_eur = str(master_settings._cache.get("symbol_eurusd", "EURUSD") or "EURUSD").strip()

    my_xau = str(acct_settings._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip()
    my_eur = str(acct_settings._cache.get("symbol_eurusd", "EURUSD") or "EURUSD").strip()

    mapper = {}
    if master_xau:
        mapper[master_xau] = my_xau
    if master_eur:
        mapper[master_eur] = my_eur
    return mapper


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_POLL_INTERVAL = 5    # seconds — check for new commands
TRADE_MGMT_INTERVAL = 2     # seconds — manage active trades
SETTINGS_REFRESH_INTERVAL = 60  # seconds — refresh account settings

def main():
    global _shutdown_requested

    # Get account_id from command line
    if len(sys.argv) < 2:
        print("Usage: python executor_bot.py <account_id>")
        sys.exit(1)

    account_id = sys.argv[1]
    config.ACCOUNT_ID = account_id

    logger.info("=" * 60)
    logger.info(f"  EXECUTOR BOT — {account_id}")
    logger.info("=" * 60)

    # 0. Load system settings (API keys)
    system_settings.fetch_and_apply_system_settings()

    # Initialize components
    acct_settings = AccountSettings(account_id)
    acct_settings.force_refresh()
    connector = MT5Connector()
    risk_mgr = RiskManager()
    trade_memory = TradeMemory(account_id)
    active_manager = ActiveTradeManager(connector, trade_memory, risk_mgr)
    supabase = SupabaseSync()

    cycle_count = 0
    last_command_poll = 0
    last_settings_refresh = 0
    startup_done = False

    while not _shutdown_requested:
        cycle_count += 1
        now = time.time()

        # ── Refresh settings periodically ──
        if now - last_settings_refresh > SETTINGS_REFRESH_INTERVAL:
            acct_settings.force_refresh()
            system_settings.fetch_and_apply_system_settings()
            last_settings_refresh = now

        # ── Check if account is still enabled ──
        if not acct_settings.enabled:
            logger.info(f"[{account_id}] Account is DISABLED. Sleeping 30s...")
            time.sleep(30)
            continue

        # ── Connect to MT5 (once, stays connected) ──
        if not connector.is_connected():
            login_val = None
            password_val = None
            server_val = None
            path_val = None
            s_login = acct_settings.mt5_login
            if s_login and s_login != "12345678" and s_login != "":
                try:
                    login_val = int(s_login)
                    password_val = acct_settings.mt5_password
                    server_val = acct_settings.mt5_server
                    path_val = acct_settings.mt5_path
                except ValueError:
                    pass

            mt5_ok = connector.connect(
                login=login_val, password=password_val,
                server=server_val, path=path_val,
            )
            if not mt5_ok:
                logger.warning(f"[{account_id}] MT5 connection failed. Retrying in 10s...")
                acct_settings.update_connection_status(connected=False, error_msg="Failed to connect to MT5 Terminal")
                time.sleep(10)
                continue

            logger.info(f"[{account_id}] ✅ Connected to MT5 Terminal. Staying connected 24/7.")
            acct_info = connector.get_account_info() or {}
            acct_settings.update_connection_status(connected=True, error_msg="", account_info=acct_info)

        # ── Startup sync (once) ──
        if not startup_done:
            logger.info(f"[{account_id}] Performing Startup Sync...")
            try:
                db_trades = active_manager.supabase.fetch_active_trades(account_id)
                mt5_positions = connector.get_open_positions()
                mt5_tickets = [str(p["ticket"]) for p in mt5_positions]
                cleaned = 0
                for db_trade in db_trades:
                    t_str = str(db_trade["ticket"])
                    if t_str not in mt5_tickets:
                        logger.info(f"[{account_id}] Sync: Trade {t_str} not in MT5. Closing in Supabase.")
                        db_trade["current_status"] = "CLOSED"
                        db_trade["exit_reason"] = "broker_closed"
                        active_manager.supabase.mark_trade_closed(db_trade)
                        if t_str in trade_memory.data.get("active_trades", {}):
                            trade_memory.mark_trade_closed(
                                int(t_str), db_trade.get("symbol", ""), 0.0, "broker_closed"
                            )
                        cleaned += 1
                if cleaned:
                    logger.info(f"[{account_id}] Sync: Cleaned {cleaned} stuck trade(s).")
                else:
                    logger.info(f"[{account_id}] Sync: All trades are synced correctly.")
            except Exception as e:
                logger.error(f"[{account_id}] Startup sync failed: {e}")
            startup_done = True

        # ── Heartbeat ──
        active_manager.sync_heartbeat(cycle_count, message="executor_running")

        # ══════════════════════════════════════════════════════════════════════
        # PART A: Poll & execute trade commands from Supabase
        # ══════════════════════════════════════════════════════════════════════
        if now - last_command_poll >= COMMAND_POLL_INTERVAL:
            last_command_poll = now

            # Build symbol mapper
            sym_map = build_symbol_mapper(acct_settings)
            trading_symbols = acct_settings.get_symbols()

            try:
                commands = supabase.fetch_pending_commands(account_id)
                for cmd in commands:
                    if _shutdown_requested:
                        break

                    cmd_id = cmd.get("id")
                    cmd_type = cmd.get("command_type")
                    cmd_symbol = cmd.get("symbol", "")
                    cmd_payload = cmd.get("payload", {})

                    # Map symbol from Master to this account's broker
                    my_symbol = sym_map.get(cmd_symbol, cmd_symbol)

                    # Skip if symbol not in our trading list
                    if my_symbol and my_symbol not in trading_symbols:
                        supabase.update_command_status(cmd_id, "skipped", {"reason": f"Symbol {my_symbol} not enabled"})
                        continue

                    # Mark as processing
                    supabase.update_command_status(cmd_id, "processing")

                    logger.info(f"[{account_id}] Processing command: {cmd_type} {my_symbol}")

                    try:
                        if cmd_type == "OPEN_TRADE":
                            result = execute_open_trade(
                                cmd_payload, my_symbol, connector, risk_mgr,
                                trade_memory, active_manager, acct_settings, account_id
                            )
                        elif cmd_type == "CLOSE_TRADE":
                            cmd_payload["symbol"] = my_symbol
                            result = execute_close_trade(
                                cmd_payload, connector, active_manager, account_id
                            )
                        elif cmd_type == "UPDATE_SL_TP":
                            result = execute_update_sl_tp(
                                cmd_payload, connector, trade_memory, account_id
                            )
                        else:
                            result = {"success": False, "reason": f"Unknown command type: {cmd_type}"}

                        status = "completed" if result.get("success") else "failed"
                        supabase.update_command_status(cmd_id, status, result)

                    except Exception as e:
                        logger.error(f"[{account_id}] Command execution error: {e}", exc_info=True)
                        supabase.update_command_status(cmd_id, "failed", {"reason": str(e)})

            except Exception as e:
                logger.error(f"[{account_id}] Command polling error: {e}", exc_info=True)

        # ══════════════════════════════════════════════════════════════════════
        # PART B: Manage active trades (SL/TP/BE+/Trailing/News)
        # ══════════════════════════════════════════════════════════════════════
        trading_symbols = acct_settings.get_symbols()
        for symbol in trading_symbols:
            if _shutdown_requested:
                break
            open_positions = connector.get_open_positions(symbol)
            if open_positions:
                try:
                    # Get fresh indicators for trailing stop calculations
                    mdf = connector.get_multi_timeframe(symbol, timeframes=["M5", "M1"], bars=50)
                    indicators = {}
                    if mdf and len(mdf) >= 1:
                        from strategy import calculate_multi_indicators
                        indicators = calculate_multi_indicators(mdf, symbol=symbol) or {}

                    closed = active_manager.manage_symbol(symbol, open_positions, indicators)
                    if closed:
                        logger.info(f"[{account_id}][{symbol}] Closed {len(closed)} position(s).")
                except Exception as e:
                    logger.error(f"[{account_id}][{symbol}] Trade management error: {e}", exc_info=True)

        # ── Sleep ──
        if not _shutdown_requested:
            time.sleep(TRADE_MGMT_INTERVAL)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*60}")
    logger.info(f"EXECUTOR BOT [{account_id}] SHUTTING DOWN")
    logger.info(f"{'='*60}")
    connector.disconnect()


if __name__ == "__main__":
    main()
