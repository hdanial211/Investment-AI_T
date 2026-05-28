import time
import logging
import json
import requests
from datetime import datetime
import os

import config
from trade_management.supabase_sync import SupabaseSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DataSync")

SHARED_STATE_FILE = os.path.join(os.path.dirname(__file__), "shared_state.json")

def fetch_all_supabase_data():
    """Fetches all system and account settings from Supabase and writes them to a local JSON file."""
    url = config.SUPABASE_URL.rstrip("/")
    key = config.SUPABASE_ANON_KEY
    if not url or not key:
        logger.warning("Supabase URL or Key missing. Cannot sync data.")
        return False
        
    state = {
        "system_settings": {},
        "account_settings": {},
        "enabled_accounts": [],
        "last_updated": time.time()
    }
    
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    
    try:
        # 1. Fetch System Settings
        sys_endpoint = f"{url}/rest/v1/system_settings?id=eq.global&select=*"
        sys_res = requests.get(sys_endpoint, headers=headers, timeout=config.SUPABASE_REQUEST_TIMEOUT)
        if sys_res.status_code < 400 and sys_res.json():
            state["system_settings"] = sys_res.json()[0]
            
        # 2. Fetch Account Settings
        acc_endpoint = f"{url}/rest/v1/account_settings?select=*"
        acc_res = requests.get(acc_endpoint, headers=headers, timeout=config.SUPABASE_REQUEST_TIMEOUT)
        if acc_res.status_code < 400 and acc_res.json():
            for acc in acc_res.json():
                acc_id = acc.get("account_id")
                if acc_id:
                    state["account_settings"][acc_id] = acc
                    if acc.get("enabled", False):
                        state["enabled_accounts"].append(acc_id)
                        
        # Atomically write to shared state file
        temp_file = SHARED_STATE_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(temp_file, SHARED_STATE_FILE)
        
        return True
    except Exception as e:
        logger.error(f"Error fetching from Supabase: {e}")
        return False

def run():
    logger.info("============================================================")
    logger.info("   TERMINAL 2: DATA SYNC & SUPABASE MANAGER")
    logger.info("============================================================")
    logger.info("Started Data Sync terminal. Press Ctrl+C to stop.")
    
    supabase = SupabaseSync()
    
    cycle = 0
    while True:
        cycle += 1
        try:
            logger.info(f"--- Sync Cycle #{cycle} ---")
            
            if fetch_all_supabase_data():
                logger.info("✅ Successfully synced all settings to shared_state.json")
            else:
                logger.warning("Failed to sync settings from Supabase this cycle.")
            
            # Send generic heartbeat
            try:
                # Need to read enabled accounts from our fresh file
                with open(SHARED_STATE_FILE, "r") as f:
                    state = json.load(f)
                    for acc in state.get("enabled_accounts", []):
                        supabase.insert_trade_event(
                            ticket=0, 
                            event_type="data_sync_heartbeat", 
                            reason=f"Account {acc} data sync active"
                        )
            except Exception:
                pass
            
            time.sleep(10) # Run every 10 seconds
            
        except KeyboardInterrupt:
            logger.info("Data Sync terminal stopped.")
            break
        except Exception as e:
            logger.error(f"Error in Data Sync loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run()
