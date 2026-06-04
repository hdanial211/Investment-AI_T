"""
account_terminal.py - Per-Account Trading Terminal

Each account gets its own instance of this script. It:
1. Connects to its own MT5 instance (unique mt5_path per account)
2. Reads AI signals from Supabase `market_signals` (produced by Master Analyzer)
3. Validates signals against its own Risk Manager + AI Risk Review
4. Executes trades on MT5
5. Manages floating trades: Virtual SL/TP, BE+ Trailing Stop
6. Syncs every action to Supabase immediately (for Dashboard)

Usage: python account_terminal.py <account_id>
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

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AccountTerminal")

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
# SIGNAL PROCESSING
# ─────────────────────────────────────────────────────────────────────────────

def process_signal(
    signal_data: Dict,
    symbol: str,
    connector: MT5Connector,
    risk_mgr: RiskManager,
    trade_memory: TradeMemory,
    active_manager: ActiveTradeManager,
    acct_settings: AccountSettings,
) -> Optional[str]:
    """Process a market signal for a specific symbol. Returns 'traded'|'skipped'|'error'."""
    
    action = signal_data.get("action", "HOLD")
    confidence = float(signal_data.get("confidence", 0.0))
    trade_style = signal_data.get("trade_style", "INTRADAY").upper()
    reason = signal_data.get("reason", "")

    # Build a signal dict compatible with existing risk_mgr
    ai_signal = {
        "action": action,
        "confidence": confidence,
        "trade_style": trade_style,
        "reason": reason,
    }

    # 1. Validate signal
    signal_valid, signal_reason = risk_mgr.validate_signal(ai_signal)
    if not signal_valid:
        logger.info(f"[{symbol}] Signal not actionable: {signal_reason}")
        return "skipped"

    # 1.5 Account-Level Confidence Filter
    if confidence < acct_settings.min_ai_confidence:
        logger.info(f"[{symbol}] AI Confidence {confidence:.2f} below minimum {acct_settings.min_ai_confidence}")
        return "skipped"

    logger.info(
        f"[{symbol}] ✔ Signal: {action} | Style: {trade_style} | "
        f"Confidence: {confidence:.2f} | Reason: {reason}"
    )

    # 2. Session filter
    session_ok, session_reason = risk_mgr.validate_session(trade_style, symbol)
    if not session_ok:
        # Check if the user disabled the Asia Session Block in the dashboard
        if "Asia" in session_reason and not acct_settings.block_asia_session:
            logger.info(f"[{symbol}] Asia session blocked by style, but account settings allowed it. ALLOWING TRADE.")
        else:
            logger.info(f"[{symbol}] {session_reason}")
            return "skipped"

    # 3. Min ATR filter
    indicators_snapshot = signal_data.get("indicators_snapshot") or {}
    # Reconstruct minimal indicators for validation
    indicators = {
        "atr": signal_data.get("atr", 0),
        "adx": indicators_snapshot.get("adx", 0),
        "m15_rsi": indicators_snapshot.get("m15_rsi", 50),
        "h4_trend": indicators_snapshot.get("h4_trend"),
        "h1_macd_trend": indicators_snapshot.get("h1_macd_trend"),
        "market_regime": signal_data.get("market_regime", "RANGING"),
        "detected_patterns": indicators_snapshot.get("detected_patterns", []),
        "sufficient_volatility": True,
    }

    atr_ok, atr_reason = risk_mgr.validate_min_atr(trade_style, symbol, indicators)
    if not atr_ok:
        logger.info(f"[{symbol}] {atr_reason}")
        return "skipped"

    # 4. Account settings check
    if not acct_settings.enabled:
        logger.info(f"[{symbol}] Account disabled. Skipping.")
        return "skipped"

    if not acct_settings.is_style_enabled(trade_style):
        logger.info(f"[{symbol}] Trade style '{trade_style}' disabled. Skipping.")
        return "skipped"

    # 5. Check open positions
    open_positions = connector.get_open_positions(symbol)
    open_pos_count = len(open_positions)

    # Pre-trade risk check
    can_trade, risk_reason = risk_mgr.can_trade(symbol, open_pos_count, indicators, trade_memory, acct_settings)
    if not can_trade:
        logger.info(f"[{symbol}] Trade blocked: {risk_reason}")
        return "skipped"

    # Advanced Daily & Spread Limits
    daily_ok, daily_reason = risk_mgr.check_daily_limits(connector, acct_settings)
    if not daily_ok:
        logger.info(f"[{symbol}] {daily_reason}")
        return "skipped"

    spread_ok, spread_reason = risk_mgr.validate_spread(connector, symbol, acct_settings.max_spread_points)
    if not spread_ok:
        logger.info(f"[{symbol}] {spread_reason}")
        return "skipped"

    # Max trades per style
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
            logger.info(f"[{symbol}] Max {trade_style} trades ({style_max}) reached.")
            return "skipped"

    # Max total trades
    total_max = acct_settings.get_max_total_trades()
    all_positions = connector.get_open_positions()
    if len(all_positions) >= total_max:
        logger.info(f"[{symbol}] Max total trades ({total_max}) reached.")
        return "skipped"

    # 6. Close opposing positions if AI says opposite (and hedging is OFF)
    if not acct_settings.allow_hedging and open_pos_count > 0 and action in ("BUY", "SELL"):
        closed_any = False
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
                    closed_any = True
        if closed_any:
            return "closed"

    # 7. Calculate trade parameters
    account = connector.get_account_info()
    balance = account.get("balance", 10000.0)
    pip_value = connector.get_pip_value(symbol)
    contract = connector.get_contract_size(symbol)

    trade_params = risk_mgr.get_trade_params(
        symbol=symbol,
        action=action,
        price=signal_data.get("ask") if action == "BUY" else signal_data.get("bid"),
        balance=balance,
        pip_value=pip_value,
        contract_size=contract,
        indicators=indicators,
        trade_style=trade_style,
    )

    # 8. R:R validation
    rr_ok, rr_reason = risk_mgr.validate_rr_ratio(
        trade_params["sl_pips"], trade_params["tp_pips"], trade_style, symbol
    )
    if not rr_ok:
        logger.info(f"[{symbol}] {rr_reason}. Skipping.")
        return "skipped"

    # Override lot from account settings
    style_lot = acct_settings.get_lot_for_style(trade_style)
    if style_lot > 0:
        trade_params["lot"] = style_lot

    # 9. AI Risk Review (per-account)
    if config.ENABLE_RISK_REVIEW:
        account_ai_sequence = acct_settings.get_providers_list()
        
        risk_review = review_trade_risk(
            ai_signal, indicators, trade_params, symbol, 
            provider_sequence=account_ai_sequence
        )
        ai_signal["risk_review"] = risk_review
        if not risk_review["approved"]:
            logger.warning(f"[{symbol}] Risk review rejected: {risk_review['reason']}")
            return "skipped"

    # 10. Execute trade!
    tick = connector.get_tick(symbol)
    entry_price = tick["ask"] if action == "BUY" else tick["bid"]

    exec_result = connector.place_order(
        symbol=symbol,
        action=action,
        lot=trade_params["lot"],
        sl_price=trade_params["sl"],
        tp_price=trade_params["tp"],
        comment=f"AI_{confidence:.2f}",
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
        return "traded"
    else:
        logger.error(f"Trade execution failed: {exec_result['message']}")
        return "error"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

TRADE_MANAGEMENT_INTERVAL = 2  # seconds between each management loop

def main():
    global _shutdown_requested

    # Get account_id from command line
    if len(sys.argv) < 2:
        print("Usage: python account_terminal.py <account_id>")
        sys.exit(1)

    account_id = sys.argv[1]
    config.ACCOUNT_ID = account_id

    logger.info("=" * 60)
    logger.info(f"  ACCOUNT TERMINAL — {account_id}")
    logger.info("=" * 60)

    # 0. Live Update System Settings (API keys, AI models)
    system_settings.fetch_and_apply_system_settings()

    # Initialize components
    acct_settings = AccountSettings(account_id)
    connector = MT5Connector()
    risk_mgr = RiskManager()
    trade_memory = TradeMemory(account_id)
    active_manager = ActiveTradeManager(connector, trade_memory, risk_mgr)
    supabase = SupabaseSync()

    # Track which signal_id we last processed (to avoid duplicate entries)
    last_processed_signal = {}  # {symbol: signal_id}

    cycle_count = 0
    startup_done = False

    while not _shutdown_requested:
        cycle_count += 1

        # Check if account is still enabled
        acct_settings.force_refresh()
        
        # Also refresh global system settings (AI models & API keys)
        system_settings.fetch_and_apply_system_settings()

        if not acct_settings.enabled:
            logger.info(f"[{account_id}] Account is DISABLED. Sleeping 30s...")
            time.sleep(30)
            continue

        # Connect to this account's MT5
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
            time.sleep(10)
            continue

        # Startup sync (once)
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

            # Report connection status
            acct_info = connector.get_account_info() or {}
            acct_settings.update_connection_status(
                connected=True,
                error_msg="",
                account_info=acct_info,
                symbol_status={},
            )
            startup_done = True

        # ── Heartbeat ──
        active_manager.sync_heartbeat(cycle_count, message="account_terminal_running")

        # ── PART A: Manage existing trades (SL/TP/BE+/Trailing) ──
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

        # ── PART B: Check for new signals from Master Analyzer ──
        try:
            signals = supabase.fetch_market_signals()
            processed_any = False
            for sig in signals:
                symbol = sig.get("symbol", "")
                signal_id = sig.get("signal_id", "")

                # Skip if we already processed this signal
                if last_processed_signal.get(symbol) == signal_id:
                    continue

                # Skip if this symbol is not in our trading list
                if symbol not in trading_symbols:
                    continue

                # Skip HOLD signals
                if sig.get("action", "HOLD") == "HOLD":
                    last_processed_signal[symbol] = signal_id
                    continue

                logger.info(f"[{account_id}][{symbol}] New signal detected: {sig.get('action')} (ID: {signal_id})")

                try:
                    processed_any = True
                    result = process_signal(
                        sig, symbol, connector, risk_mgr,
                        trade_memory, active_manager, acct_settings,
                    )
                    logger.info(f"[{account_id}][{symbol}] Signal result: {result}")
                except Exception as e:
                    logger.error(f"[{account_id}][{symbol}] Signal processing error: {e}", exc_info=True)

                # Mark as processed regardless of result
                last_processed_signal[symbol] = signal_id

            # Unload GPU memory based on this account's specific provider sequence
            if processed_any:
                from ai_engine import unload_ai
                unload_ai(provider_sequence=acct_settings.get_providers_list())

        except Exception as e:
            logger.error(f"[{account_id}] Error fetching signals: {e}")

        # Sleep before next management cycle
        if not _shutdown_requested:
            time.sleep(TRADE_MANAGEMENT_INTERVAL)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*60}")
    logger.info(f"ACCOUNT TERMINAL [{account_id}] SHUTTING DOWN")
    logger.info(f"{'='*60}")
    connector.disconnect()


if __name__ == "__main__":
    main()
