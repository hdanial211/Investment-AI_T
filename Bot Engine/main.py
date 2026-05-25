"""
main.py - AI Trading Bot Main Entry Point

Orchestrates the full trading loop:
1. Connect to MT5
2. Verify cloud AI provider config is available
3. Loop every N seconds:
   a. Fetch market data
   b. Calculate indicators
   c. Query AI for signal
   d. Validate with risk manager
   e. Execute trade if approved
   f. Log everything
"""

import logging
import signal
import sys
import time
from datetime import datetime
from typing import Optional

import config
from mt5_connector import MT5Connector
from strategy import calculate_multi_indicators
from ai_engine import get_ai_signal, review_trade_risk, check_ai_health
from risk_manager import RiskManager
from logger import setup_logging, TradeLogger, generate_performance_report
from trade_memory import TradeMemory
from trade_management import ActiveTradeManager

# ─────────────────────────────────────────────────────────────────────────────
# INITIALIZE LOGGING FIRST
# ─────────────────────────────────────────────────────────────────────────────
logger = setup_logging()


# ─────────────────────────────────────────────────────────────────────────────
# GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────────────────

_shutdown_requested = False

def _signal_handler(signum, frame):
    """Handle Ctrl+C / SIGTERM gracefully."""
    global _shutdown_requested
    logger.info("Shutdown signal received. Finishing current cycle...")
    _shutdown_requested = True

signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ─────────────────────────────────────────────────────────────────────────────
# SINGLE TRADING CYCLE
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(
    symbol:       str,
    connector:    MT5Connector,
    risk_mgr:     RiskManager,
    trade_logger: TradeLogger,
    trade_memory: TradeMemory,
    active_manager: ActiveTradeManager,
) -> Optional[str]:
    """
    Execute one complete trading cycle for a given symbol.
    Returns: 'traded' | 'skipped' | 'error'
    """
    cycle_start = time.time()
    logger.info(f"{'─'*50}")
    logger.info(f"▶ Cycle start | Symbol: {symbol} | {datetime.now().strftime('%H:%M:%S')}")

    # ── STEP 1: Get tick data ────────────────────────────────────────────────
    tick = connector.get_tick(symbol)
    if not tick:
        logger.error(f"Failed to get tick for {symbol}")
        trade_logger.log_skipped(symbol, "No tick data")
        return "error"

    bid = tick["bid"]
    ask = tick["ask"]
    logger.info(f"Tick: Bid={bid:.5f} | Ask={ask:.5f}")

    # ── STEP 1.5: [Moved Trailing Stop after ATR calculation] ─────────────────

    # ── STEP 2: Get Multi-Timeframe OHLCV bars and calculate indicators ──────
    mdf = connector.get_multi_timeframe(symbol, timeframes=["H4", "H1", "M15", "M5"], bars=100)
    if not mdf or len(mdf) < 4:
        logger.error(f"Failed to get multi-timeframe data for {symbol}")
        trade_logger.log_skipped(symbol, "Missing MTF data")
        return "error"

    indicators = calculate_multi_indicators(mdf, symbol=symbol)
    if not indicators:
        logger.warning(f"Cannot calculate indicators for {symbol}")
        trade_logger.log_skipped(symbol, "Indicator calculation failed")
        return "skipped"

    # ── STEP 2.5: Broker trailing stop only when broker-side SL/TP is enabled ─
    if config.USE_TRAILING_STOP and config.USE_BROKER_SL_TP:
        connector.update_trailing_stop(symbol, atr=indicators.get("atr"))

    # ── STEP 3: Active trade manager checks each open ticket one-by-one ──────
    open_positions = connector.get_open_positions(symbol)
    closed_positions = active_manager.manage_symbol(symbol, open_positions, indicators)
    if closed_positions:
        logger.info(f"[{symbol}] Active manager closed {len(closed_positions)} position(s).")
        return "closed"

    # Refresh positions after possible virtual exits.
    open_positions = connector.get_open_positions(symbol)
    
    # ── STEP 4: Pre-trade risk check ─────────────────────────────────────────
    open_pos_count = len(open_positions)
    can_trade, risk_reason = risk_mgr.can_trade(symbol, open_pos_count, indicators, trade_memory)
    if not can_trade:
        logger.info(f"Trade blocked: {risk_reason}")
        trade_logger.log_skipped(symbol, risk_reason, indicators=indicators)
        return "skipped"

    # ── STEP 5: Query AI ─────────────────────────────────────────────────────
    logger.info("Querying AI model...")
    signal = get_ai_signal(indicators, bid, ask, trade_memory, symbol)

    # ── STEP 6: Validate AI signal ───────────────────────────────────────────
    signal_valid, signal_reason = risk_mgr.validate_signal(signal)
    if not signal_valid:
        logger.info(f"Signal not actionable: {signal_reason}")
        trade_logger.log_skipped(
            symbol, signal_reason,
            signal=signal, indicators=indicators
        )
        return "skipped"

    action = signal["action"]
    logger.info(
        f"✔ Signal approved: {action} | "
        f"Confidence: {signal['confidence']:.2f} | "
        f"Reason: {signal['reason']}"
    )

    # ── STEP 6.5: AI Position Closure ────────────────────────────────────────
    # If we have open positions and the AI thesis is opposite, close them!
    if open_pos_count > 0 and action in ("BUY", "SELL"):
        closed_any = False
        for pos in open_positions:
            if pos["direction"] != action:
                logger.warning(f"[{symbol}] AI signal ({action}) contradicts position {pos['ticket']} ({pos['direction']}). CLOSING POSITION!")
                if connector.close_trade(pos["ticket"], symbol):
                    active_manager.mark_position_closed(
                        pos["ticket"],
                        symbol,
                        profit=pos["profit"],
                        reason="reverse_signal",
                    )
                    closed_any = True
        
        if closed_any:
            logger.info(f"[{symbol}] Waiting for next cycle after closing positions.")
            return "closed"

    # ── STEP 7: Calculate trade parameters ───────────────────────────────────
    account   = connector.get_account_info()
    balance   = account.get("balance", 10000.0)
    pip_value = connector.get_pip_value(symbol)
    contract  = connector.get_contract_size(symbol)

    trade_params = risk_mgr.get_trade_params(
        symbol        = symbol,
        action        = action,
        price         = ask if action == "BUY" else bid,
        balance       = balance,
        pip_value     = pip_value,
        contract_size = contract,
        indicators    = indicators,
    )

    logger.info(
        f"Trade params: Lot={trade_params['lot']} | "
        f"Virtual SL={trade_params['sl']:.5f} | Virtual TP={trade_params['tp']:.5f}"
    )
    if not config.USE_BROKER_SL_TP:
        logger.info("Broker-side SL/TP disabled. Hidden virtual levels will be managed by bot memory.")

    # ── STEP 7.5: Optional second-model risk review ──────────────────────────
    risk_review = review_trade_risk(signal, indicators, trade_params, symbol)
    signal["risk_review"] = risk_review
    if not risk_review["approved"]:
        reason = f"Risk review rejected: {risk_review['reason']}"
        logger.warning(reason)
        trade_logger.log_skipped(
            symbol,
            reason,
            signal=signal,
            indicators=indicators,
        )
        return "skipped"

    # ── STEP 8: Execute trade ─────────────────────────────────────────────────
    exec_result = connector.place_order(
        symbol   = symbol,
        action   = action,
        lot      = trade_params["lot"],
        sl_price = trade_params["sl"],
        tp_price = trade_params["tp"],
        comment  = f"AI_{signal['confidence']:.2f}",
    )

    # ── STEP 9: Log result ────────────────────────────────────────────────────
    trade_logger.log_trade(
        symbol             = symbol,
        action             = action,
        signal             = signal,
        trade_params       = trade_params,
        exec_result        = exec_result,
        indicators         = indicators,
        balance            = balance,
        consecutive_losses = risk_mgr.stats.consecutive_losses,
    )

    if exec_result["success"]:
        entry_price = exec_result.get("price") or (ask if action == "BUY" else bid)
        active_manager.register_new_trade(
            ticket=exec_result["ticket"],
            symbol=symbol,
            action=action,
            entry_price=entry_price,
            lot=trade_params["lot"],
            trade_params=trade_params,
            signal=signal,
            indicators=indicators,
        )
        logger.info(f"✅ Trade executed! Ticket: {exec_result['ticket']}")
        cycle_time = round(time.time() - cycle_start, 2)
        logger.info(f"Cycle completed in {cycle_time}s")
        return "traded"
    else:
        logger.error(f"Trade execution failed: {exec_result['message']}")
        return "error"


# ─────────────────────────────────────────────────────────────────────────────
# STARTUP CHECKS
# ─────────────────────────────────────────────────────────────────────────────

def startup_checks(connector: MT5Connector) -> bool:
    """Run all pre-flight checks before starting the trading loop."""
    logger.info("=" * 60)
    logger.info("  AI TRADING BOT — STARTUP CHECKS")
    logger.info("=" * 60)

    all_ok = True

    for warning in config.validate():
        logger.warning(f"Config warning: {warning}")

    # 1. MT5 connection
    logger.info("Checking MT5 connection...")
    if connector.connect():
        logger.info("✔ MT5 connected")
    else:
        logger.critical("✘ MT5 connection failed")
        all_ok = False

    # 2. Cloud AI
    logger.info(
        f"Checking cloud AI ({config.AI_PROVIDER} / {config.AI_MAIN_MODEL})..."
    )
    if check_ai_health(role="main"):
        logger.info("✔ Cloud AI main model ready")
    else:
        logger.warning("⚠ Cloud AI not ready — bot will run but AI signals may fail")
        # Non-fatal: allow dashboard/demo runs without AI

    if config.ENABLE_RISK_REVIEW:
        logger.info(
            f"Checking cloud AI risk model ({config.AI_PROVIDER} / {config.AI_RISK_MODEL})..."
        )
        if check_ai_health(role="risk"):
            logger.info("✔ Cloud AI risk reviewer ready")
        else:
            logger.warning("⚠ Risk review enabled but risk model is not available")

    # 3. Symbol availability
    for sym in config.SYMBOLS:
        tick = connector.get_tick(sym)
        if tick:
            logger.info(f"✔ Symbol {sym}: Bid={tick['bid']:.5f}")
        else:
            logger.warning(f"⚠ Cannot get tick for {sym}")

    # 4. Account info
    account = connector.get_account_info()
    if account:
        logger.info(
            f"✔ Account: Balance={account.get('balance', 0):.2f} "
            f"{account.get('currency', '')} | "
            f"Leverage=1:{account.get('leverage', 'N/A')}"
        )

    logger.info("=" * 60)
    return all_ok


# ─────────────────────────────────────────────────────────────────────────────
# MAIN TRADING LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Main entry point. Runs the infinite trading loop."""
    global _shutdown_requested

    logger.info("Starting AI Trading Bot...")

    # Initialize components
    connector    = MT5Connector()
    risk_mgr     = RiskManager()
    trade_logger = TradeLogger()
    trade_memory = TradeMemory()
    active_manager = ActiveTradeManager(connector, trade_memory, risk_mgr)

    # Pre-flight checks
    if not startup_checks(connector):
        logger.critical("Startup checks failed. Exiting.")
        sys.exit(1)

    logger.info(f"Trading symbols: {config.SYMBOLS}")
    logger.info(f"Loop interval:   {config.LOOP_INTERVAL}s")
    logger.info(f"Risk per trade:  {config.MAX_RISK_PERCENT}%")
    logger.info(f"Min confidence:  {config.MIN_CONFIDENCE}")
    logger.info("Bot is LIVE. Press Ctrl+C to stop.\n")

    cycle_count = 0

    # ── INFINITE LOOP ────────────────────────────────────────────────────────
    while not _shutdown_requested:
        cycle_count += 1
        logger.info(f"\n{'═'*60}")
        logger.info(f"CYCLE #{cycle_count} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'═'*60}")
        active_manager.sync_heartbeat(cycle_count, message="cycle_started")

        # Check if trading is halted
        if risk_mgr.stats.trading_halted:
            logger.critical(
                f"🛑 Trading is HALTED: {risk_mgr.stats.halt_reason}\n"
                "Manual intervention required. Exiting loop."
            )
            break

        # Run cycle for each configured symbol
        for symbol in config.SYMBOLS:
            if _shutdown_requested:
                break
            try:
                run_cycle(symbol, connector, risk_mgr, trade_logger, trade_memory, active_manager)
            except Exception as e:
                logger.error(f"Unhandled exception in cycle [{symbol}]: {e}", exc_info=True)

        # Print session summary every 10 cycles
        if cycle_count % 10 == 0:
            summary = risk_mgr.get_session_summary()
            logger.info(
                f"\n📊 Session Summary (Cycle #{cycle_count}):\n"
                f"   Trades: {summary['trades_total']} | "
                f"Wins: {summary['trades_win']} | "
                f"Losses: {summary['trades_loss']} | "
                f"Win Rate: {summary['win_rate_pct']}% | "
                f"P&L: {summary['total_pnl']:+.2f}"
            )

        # Sleep until next cycle
        if not _shutdown_requested:
            logger.debug(f"Sleeping {config.LOOP_INTERVAL}s...")
            time.sleep(config.LOOP_INTERVAL)

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("BOT SHUTTING DOWN")
    logger.info("=" * 60)

    # Final performance report
    report = generate_performance_report()
    logger.info("Final Performance Report:")
    for key, val in report.items():
        logger.info(f"  {key}: {val}")

    # Disconnect MT5
    connector.disconnect()
    logger.info("Bot stopped cleanly.")


if __name__ == "__main__":
    main()
