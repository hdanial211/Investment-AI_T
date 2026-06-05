"""
trade_monitor.py - Active Trade Management Terminal

Each account gets its own instance of this script. It runs 24/7 to:
1. Connect to its own MT5 instance (unique mt5_path per account)
2. Manage floating trades: Virtual SL/TP, BE+, Trailing Stop
3. Sync every action to Supabase immediately (for Dashboard)

Usage: python trade_monitor.py <account_id>
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
    logger.info(f"  TRADE MONITOR — {account_id}")
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

        # (Signal processing removed - handled by entry_terminal.py)

        # Sleep before next management cycle
        if not _shutdown_requested:
            time.sleep(TRADE_MANAGEMENT_INTERVAL)

    # ── SHUTDOWN ──
    logger.info(f"\n{'='*60}")
    logger.info(f"TRADE MONITOR [{account_id}] SHUTTING DOWN")
    logger.info(f"{'='*60}")
    connector.disconnect()


if __name__ == "__main__":
    main()
