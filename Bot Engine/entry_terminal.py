"""
entry_terminal.py - Ephemeral Entry Execution Terminal

Each account gets its own instance of this script when a new signal arrives. It:
1. Connects to its own MT5 instance (unique mt5_path per account)
2. Reads the latest AI signal from `latest_signals.json`
3. Validates the signal against Risk Manager + AI Risk Review
4. Executes the trade on MT5
5. Exits immediately after processing

Usage: python entry_terminal.py <account_id>
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
        return "traded"
    else:
        logger.error(f"Trade execution failed: {exec_result['message']}")
        return "error"


# ─────────────────────────────────────────────────────────────────────────────
# MAIN EXECUTION
# ─────────────────────────────────────────────────────────────────────────────

def main():

    # Get account_id from command line
    if len(sys.argv) < 2:
        print("Usage: python account_terminal.py <account_id>")
        sys.exit(1)

    account_id = sys.argv[1]
    config.ACCOUNT_ID = account_id

    logger.info("=" * 60)
    logger.info(f"  ENTRY TERMINAL — {account_id}")
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

    # Track which signal_id we last processed
    last_processed_file = os.path.join(config.LOG_DIR, f"last_processed_{account_id}.json")
    last_processed_signal = {}
    if os.path.exists(last_processed_file):
        try:
            with open(last_processed_file, "r") as f:
                last_processed_signal = json.load(f)
        except:
            pass

    # Check if account is enabled
    acct_settings.force_refresh()
    if not acct_settings.enabled:
        logger.info(f"[{account_id}] Account is DISABLED. Exiting.")
        return

    # Connect to MT5
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
        logger.error(f"[{account_id}] MT5 connection failed. Exiting.")
        return

    trading_symbols = acct_settings.get_symbols()
    
    # Map Master symbols to this account's symbols
    master_settings = AccountSettings("master")
    master_settings.force_refresh()
    master_xau = str(master_settings._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip()
    
    my_xau = str(acct_settings._cache.get("symbol_xauusd", "XAUUSD") or "XAUUSD").strip()
    
    master_to_my_symbol = {}
    if master_xau: master_to_my_symbol[master_xau] = my_xau

    # ── Read signals from local JSON ──
    signals_file = os.path.join(config.LOG_DIR, "latest_signals.json")
    if not os.path.exists(signals_file):
        logger.info(f"[{account_id}] No latest_signals.json found. Exiting.")
        connector.disconnect()
        return

    try:
        with open(signals_file, "r") as f:
            signals = json.load(f)
        
        processed_any = False
        for master_sym, sig in signals.items():
            signal_id = sig.get("signal_id", "")

            # Map symbol
            my_symbol = master_to_my_symbol.get(master_sym)
            if not my_symbol:
                continue

            # Skip if we already processed this signal
            if last_processed_signal.get(my_symbol) == signal_id:
                continue

            # Skip if this symbol is not in our trading list
            if my_symbol not in trading_symbols:
                continue

            # Skip HOLD signals
            if sig.get("action", "HOLD") == "HOLD":
                last_processed_signal[my_symbol] = signal_id
                continue

            logger.info(f"[{account_id}][{my_symbol}] New signal detected: {sig.get('action')} (ID: {signal_id})")

            try:
                processed_any = True
                result = process_signal(
                    sig, my_symbol, connector, risk_mgr,
                    trade_memory, active_manager, acct_settings,
                )
                logger.info(f"[{account_id}][{my_symbol}] Signal result: {result}")
            except Exception as e:
                logger.error(f"[{account_id}][{my_symbol}] Signal processing error: {e}", exc_info=True)

            # Mark as processed regardless of result
            last_processed_signal[my_symbol] = signal_id

        # Save the updated last processed signals
        with open(last_processed_file, "w") as f:
            json.dump(last_processed_signal, f)

        # Unload GPU memory based on this account's specific provider sequence
        if processed_any:
            from ai_engine import unload_ai
            unload_ai(provider_sequence=acct_settings.get_providers_list())

    except Exception as e:
        logger.error(f"[{account_id}] Error processing signals: {e}", exc_info=True)

    # ── SHUTDOWN ──
    logger.info(f"{'='*60}")
    logger.info(f"ENTRY TERMINAL [{account_id}] FINISHED")
    logger.info(f"{'='*60}")
    connector.disconnect()


if __name__ == "__main__":
    main()
