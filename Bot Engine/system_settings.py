"""
system_settings.py — Reads global system settings (API keys, models) from Supabase.
Updates config.py dynamically at runtime.
"""

import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)

def fetch_and_apply_system_settings() -> bool:
    """
    Fetches the global system settings from Supabase and overwrites
    config.py parameters (providers_list).
    Returns True if successful, False otherwise.
    """
    try:
        url = config.SUPABASE_URL.rstrip("/")
        key = config.SUPABASE_KEY
        if not url or not key:
            logger.warning("Supabase URL or Key missing in .env. Skipping system settings load.")
            return False

        endpoint = f"{url}/rest/v1/system_settings?id=eq.global&select=*"
        response = requests.get(
            endpoint,
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
            },
            timeout=config.SUPABASE_REQUEST_TIMEOUT,
        )

        if response.status_code < 400 and response.json() and len(response.json()) > 0:
            data = response.json()[0]
            logger.info("Loaded global system settings from Supabase. Overriding config.")

            providers_list = data.get("providers_list", [])
            if isinstance(providers_list, list) and len(providers_list) > 0:
                config.PROVIDERS_CONFIG = providers_list
                logger.info(f"Loaded {len(providers_list)} API providers.")
            else:
                logger.warning("No providers_list found. Will fallback to default config variables.")
                # Fallback to old method just in case
                if data.get("openrouter_api_key"):
                    config.OPENROUTER_API_KEY = data["openrouter_api_key"]
                if data.get("hf_token"):
                    config.HF_TOKEN = data["hf_token"]
                if data.get("ai_provider"):
                    config.AI_PROVIDER = data["ai_provider"].upper()
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

