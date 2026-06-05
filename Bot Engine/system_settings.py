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
            logger.debug(f"Loaded {len(providers_list)} API providers directly from Supabase.")
        else:
            logger.warning("No providers_list found in Supabase settings.")
        if config.PROVIDERS_CONFIG and len(config.PROVIDERS_CONFIG) > 0:
            master_provider = config.PROVIDERS_CONFIG[0]
            config.MASTER_AI_PROVIDER = master_provider.get("provider")
            config.MASTER_AI_MAIN_MODEL = master_provider.get("main_model")
            config.MASTER_AI_RISK_MODEL = master_provider.get("risk_model")
        else:
            # Fallback
            config.MASTER_AI_PROVIDER = sys_data.get("master_ai_provider")
            config.MASTER_AI_MAIN_MODEL = sys_data.get("master_ai_main_model")
            config.MASTER_AI_RISK_MODEL = sys_data.get("master_ai_risk_model")
            
        # 2. Master Analyzer MT5 Account Settings
        if sys_data.get("master_mt5_login"):
            config.MASTER_MT5_LOGIN = sys_data.get("master_mt5_login")
        if sys_data.get("master_mt5_password"):
            config.MASTER_MT5_PASSWORD = sys_data.get("master_mt5_password")
        if sys_data.get("master_mt5_server"):
            config.MASTER_MT5_SERVER = sys_data.get("master_mt5_server")
        if sys_data.get("master_mt5_path"):
            config.MASTER_MT5_PATH = sys_data.get("master_mt5_path")
            
        return True
        
    except Exception as e:
        logger.error(f"Failed to load system settings from Supabase: {e}")
        return False

