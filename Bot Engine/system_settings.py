"""
system_settings.py — Reads global system settings (API keys, models) from Supabase.
Updates config.py dynamically at runtime.

Supports two providers_list formats:
  - Legacy (array): [{"provider": "nvidia", "api_key": "...", "main_model": "...", "risk_model": "..."}, ...]
  - Role-based (object): {"main": {...}, "vision": {...}, "fallbacks": [...]}
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
            
        providers_list = sys_data.get("providers_list")
        
        if isinstance(providers_list, dict):
            # ── NEW: Role-based format ────────────────────────────────────
            _apply_role_based_providers(providers_list)
        elif isinstance(providers_list, list) and len(providers_list) > 0:
            # ── LEGACY: Flat array format (backward compatible) ───────────
            _apply_legacy_providers(providers_list)
        else:
            logger.warning("No providers_list found in Supabase settings.")
        
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


def _apply_role_based_providers(providers: dict) -> None:
    """Parse role-based providers_list format (v4 architecture).
    
    Expected format:
    {
        "main": {"provider": "nvidia", "api_key": "...", "model": "..."},
        "vision": {"provider": "nvidia", "api_key": "...", "model": "..."},
        "fallbacks": [{"provider": "groq", "api_key": "...", "model": "auto"}, ...]
    }
    """
    main_cfg = providers.get("main")
    vision_cfg = providers.get("vision")
    fallbacks = providers.get("fallbacks", [])
    
    # Set role-based configs
    if main_cfg and isinstance(main_cfg, dict):
        config.MAIN_PROVIDER_CONFIG = main_cfg
        config.MASTER_AI_PROVIDER = main_cfg.get("provider")
        config.MASTER_AI_MAIN_MODEL = main_cfg.get("model")
        logger.info(
            f"Main Model: {main_cfg.get('provider')} / {main_cfg.get('model')}"
        )
    
    if vision_cfg and isinstance(vision_cfg, dict):
        config.VISION_PROVIDER_CONFIG = vision_cfg
        # Also update the legacy VISION_AI_MODEL for backward compat
        if vision_cfg.get("model"):
            config.VISION_AI_MODEL = vision_cfg["model"]
        logger.info(
            f"Vision Model: {vision_cfg.get('provider')} / {vision_cfg.get('model')}"
        )
    
    if isinstance(fallbacks, list):
        config.MASTER_FALLBACK_PROVIDERS = fallbacks
    
    # Build legacy PROVIDERS_CONFIG for any code still using it
    legacy_list = []
    if main_cfg:
        legacy_entry = {
            "provider": main_cfg.get("provider"),
            "api_key": main_cfg.get("api_key"),
            "main_model": main_cfg.get("model"),
            "risk_model": main_cfg.get("model"),  # fallback: use main model
        }
        legacy_list.append(legacy_entry)
    for fb in fallbacks:
        legacy_list.append(fb)
    config.PROVIDERS_CONFIG = legacy_list
    
    logger.debug(
        f"Loaded role-based providers: main={bool(main_cfg)}, "
        f"vision={bool(vision_cfg)}, fallbacks={len(fallbacks)}"
    )


def _apply_legacy_providers(providers_list: list) -> None:
    """Parse legacy flat array format (backward compatible).
    
    Expected format:
    [{"provider": "nvidia", "api_key": "...", "main_model": "...", "risk_model": "..."}, ...]
    """
    config.PROVIDERS_CONFIG = providers_list
    logger.debug(f"Loaded {len(providers_list)} API providers (legacy format).")
    
    master_provider = providers_list[0]
    config.MASTER_AI_PROVIDER = master_provider.get("provider")
    config.MASTER_AI_MAIN_MODEL = master_provider.get("main_model")
    config.MASTER_AI_RISK_MODEL = master_provider.get("risk_model")
    
    # Also populate role-based configs from legacy format for forward compat
    config.MAIN_PROVIDER_CONFIG = {
        "provider": master_provider.get("provider"),
        "api_key": master_provider.get("api_key"),
        "model": master_provider.get("main_model"),
    }
    config.MASTER_FALLBACK_PROVIDERS = providers_list[1:] if len(providers_list) > 1 else []
