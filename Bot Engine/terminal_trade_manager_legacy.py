import time
import logging
from datetime import datetime

import config
from mt5_connector import MT5Connector
from account_settings import AccountSettings, get_all_enabled_accounts
from trade_management.active_trade_manager import ActiveTradeManager
from risk_manager import RiskManager
from trade_memory import TradeMemory
from file_mutex import MT5Lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("TradeManager")


def manage_one_account(account_id, connector, account_states, cycle):
    """Manage all positions for a single account — acquires MT5Lock independently."""
    if account_id not in account_states:
        account_states[account_id] = {
            "acct_settings": AccountSettings(account_id),
            "risk_mgr": RiskManager(),
            "trade_memory": TradeMemory(account_id),
        }
        account_states[account_id]["active_manager"] = ActiveTradeManager(
            connector,
            account_states[account_id]["trade_memory"],
            account_states[account_id]["risk_mgr"]
        )

    state = account_states[account_id]
    acct_settings = state["acct_settings"]
    active_manager = state["active_manager"]

    config.ACCOUNT_ID = account_id

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

    # Each account gets its own lock — released before moving to next account
    with MT5Lock():
        try:
            if not connector.connect(login=login_val, password=password_val, server=server_val, path=path_val):
                logger.warning(f"[{account_id}] MT5 connection failed.")
                return

            trading_symbols = acct_settings.get_symbols()
            for symbol in trading_symbols:
                open_positions = connector.get_open_positions(symbol)
                if open_positions:
                    logger.info(f"[{account_id}][{symbol}] Managing {len(open_positions)} active position(s)...")
                    closed = active_manager.manage_symbol(symbol, open_positions, indicators={})
                    if closed:
                        logger.info(f"[{account_id}][{symbol}] Closed {len(closed)} position(s).")
        finally:
            connector.disconnect()

    # Brief pause after each account so Terminal 1 gets a window to use MT5
    time.sleep(1)


def run():
    logger.info("============================================================")
    logger.info("   TERMINAL 3: ACTIVE TRADE MANAGER (SL/TP MONITOR)")
    logger.info("============================================================")
    logger.info("Started Trade Manager terminal. Press Ctrl+C to stop.")

    connector = MT5Connector()
    account_states = {}

    cycle = 0
    while True:
        cycle += 1
        try:
            accounts = get_all_enabled_accounts()
            if not accounts:
                logger.info("No active accounts to manage. Waiting...")
                time.sleep(5)
                continue

            for account_id in accounts:
                try:
                    manage_one_account(account_id, connector, account_states, cycle)
                except TimeoutError:
                    logger.warning(f"[{account_id}] MT5 lock busy (Terminal 1 active). Will retry next cycle.")
                except Exception as e:
                    logger.error(f"[{account_id}] Error managing account: {e}", exc_info=True)

            # Wait before next full cycle
            time.sleep(2)

        except KeyboardInterrupt:
            logger.info("Trade Manager terminal stopped.")
            break
        except Exception as e:
            logger.error(f"Error in Trade Manager loop: {e}", exc_info=True)
            time.sleep(5)


if __name__ == "__main__":
    run()
