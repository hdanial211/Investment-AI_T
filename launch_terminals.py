import os
import sys
import time
import logging
from dotenv import load_dotenv

# Ensure Bot Engine is in path
sys.path.append(os.path.join(os.path.dirname(__file__), "Bot Engine"))

try:
    from mt5_connector import mt5_conn
except ImportError:
    print("Error: Could not import mt5_connector. Make sure you run this from the project root.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Launcher")

def launch():
    load_dotenv()
    
    mt5_path = os.getenv("MT5_TERMINAL_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
    account = os.getenv("MT5_ACCOUNT")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")
    
    if not all([account, password, server]):
        logger.error("Missing MT5 credentials in .env file. Please check MT5_ACCOUNT, MT5_PASSWORD, and MT5_SERVER.")
        sys.exit(1)
        
    try:
        login_int = int(account)
    except ValueError:
        logger.error("MT5_ACCOUNT must be a number.")
        sys.exit(1)

    logger.info(f"Attempting to launch MT5 terminal from: {mt5_path}")
    logger.info(f"Logging into account: {login_int} on server: {server}")
    
    success = mt5_conn.initialize(path=mt5_path, login=login_int, password=password, server=server)
    
    if success:
        logger.info("Successfully launched and logged into MT5.")
        # We don't shut down here. We leave it open so the EA and Python can use it.
    else:
        logger.error("Failed to launch or login to MT5. Check credentials and path.")
        sys.exit(1)

if __name__ == "__main__":
    launch()
