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
    Reads the global system settings from Supabase and overwrites config.py.
    """
    try:
        from trade_management.supabase_sync import SupabaseSync
        sync = SupabaseSync()
        sys_data = sync.fetch_system_settings()
            
        if not sys_data:
            logger.warning("No system settings found in Supabase.")
            return False
            
        providers_list = sys_data.get("providers_list", [])
        if isinstance(providers_list, list) and len(providers_list) > 0:
            config.PROVIDERS_CONFIG = providers_list
            logger.info(f"Loaded {len(providers_list)} API providers directly from Supabase.")
        else:
            logger.warning("No providers_list found in Supabase settings.")
            
        return True
        
    except Exception as e:
        logger.error(f"Failed to load system settings from Supabase: {e}")
        return False

