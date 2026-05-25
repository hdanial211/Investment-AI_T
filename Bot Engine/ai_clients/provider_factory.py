"""Provider selection helpers."""

from typing import List

import config
from .huggingface_client import HuggingFaceClient
from .openrouter_client import OpenRouterClient


def _normalize_provider(provider: str) -> str:
    return str(provider or "").strip().lower().replace("-", "_")


def get_client(provider: str):
    provider = _normalize_provider(provider)
    if provider == "openrouter":
        return OpenRouterClient()
    if provider in ("huggingface", "hf"):
        return HuggingFaceClient()
    raise ValueError(f"Unsupported AI provider: {provider}")


def get_model_for_role(provider: str, role: str = "main") -> str:
    provider = _normalize_provider(provider)
    role = str(role or "main").strip().lower()

    if provider in ("huggingface", "hf"):
        if role == "risk":
            return config.HF_RISK_MODEL or config.HF_MAIN_MODEL or config.AI_RISK_MODEL
        return config.HF_MAIN_MODEL or config.AI_FALLBACK_MODEL or config.AI_MAIN_MODEL

    if role == "risk":
        return config.AI_RISK_MODEL
    return config.AI_MAIN_MODEL


def get_provider_sequence(primary: str = None) -> List[str]:
    providers = []
    primary_provider = _normalize_provider(primary or config.AI_PROVIDER)
    fallback_provider = _normalize_provider(config.AI_FALLBACK_PROVIDER)

    if primary_provider:
        providers.append(primary_provider)

    if config.AI_FALLBACK_ENABLED and fallback_provider and fallback_provider not in providers:
        providers.append(fallback_provider)

    return providers
