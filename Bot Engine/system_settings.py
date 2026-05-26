"""
system_settings.py — Reads global system settings (API keys, models) from Supabase.
Updates config.py dynamically at runtime.
"""

import logging
from typing import Optional

from supabase import create_client

import config

logger = logging.getLogger(__name__)

def fetch_and_apply_system_settings() -> bool:
    """
    Fetches the global system settings from Supabase and overwrites
    config.py parameters (API keys, AI models).
    Returns True if successful, False otherwise.
    """
    try:
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            logger.warning("Supabase URL or Key missing in .env. Skipping system settings load.")
            return False

        client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        response = client.table("system_settings").select("*").eq("id", "global").execute()

        if response.data and len(response.data) > 0:
            data = response.data[0]
            
            logger.info("Loaded global system settings from Supabase. Overriding config.")

            # Override API Keys if provided
            if data.get("openrouter_api_key"):
                config.OPENROUTER_API_KEY = data["openrouter_api_key"]
            if data.get("hf_token"):
                config.HF_TOKEN = data["hf_token"]
                
            # Override AI Provider
            if data.get("ai_provider"):
                config.AI_PROVIDER = data["ai_provider"].upper()
                
            # Override Models
            if data.get("ai_main_model"):
                config.AI_MAIN_MODEL = data["ai_main_model"]
            if data.get("ai_risk_model"):
                config.AI_RISK_MODEL = data["ai_risk_model"]

            return True
        else:
            logger.info("No global system settings found in Supabase. Using .env defaults.")
            return False

    except Exception as e:
        logger.error(f"Failed to fetch system settings from Supabase: {e}")
        return False
