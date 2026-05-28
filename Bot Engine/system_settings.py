"""
system_settings.py — Reads global system settings (API keys, models) from Supabase.
Updates config.py dynamically at runtime.
"""

import logging
import json
import os
import config

logger = logging.getLogger(__name__)

SHARED_STATE_FILE = os.path.join(os.path.dirname(__file__), "shared_state.json")

def fetch_and_apply_system_settings() -> bool:
    """
    Reads the global system settings from shared_state.json and overwrites config.py.
    Terminal 2 handles fetching from Supabase and writing to this file.
    """
    try:
        if not os.path.exists(SHARED_STATE_FILE):
            logger.warning(f"Shared state file {SHARED_STATE_FILE} not found. Waiting for Terminal 2 to sync.")
            return False
            
        with open(SHARED_STATE_FILE, "r") as f:
            state = json.load(f)
            
        sys_data = state.get("system_settings", {})
        if not sys_data:
            return False
            
        providers_list = sys_data.get("providers_list", [])
        if isinstance(providers_list, list) and len(providers_list) > 0:
            config.PROVIDERS_CONFIG = providers_list
            logger.info(f"Loaded {len(providers_list)} API providers from shared state.")
        else:
            logger.warning("No providers_list found in shared state.")
            
        # We don't auto-detect account ID here anymore; account_settings handles it
        return True
        
    except Exception as e:
        logger.error(f"Failed to load system settings from shared_state.json: {e}")
        return False

