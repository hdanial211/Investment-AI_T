"""Provider selection helpers."""

from typing import List, Dict

import config
from .huggingface_client import HuggingFaceClient
from .openrouter_client import OpenRouterClient
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient
from .ollama_client import OllamaClient

def _normalize_provider(provider: str) -> str:
    return str(provider or "").strip().lower().replace("-", "_")

def get_client(provider_config: Dict):
    provider = _normalize_provider(provider_config.get("provider", ""))
    
    if provider == "openrouter":
        return OpenRouterClient(api_key=provider_config.get("api_key"))
    if provider in ("huggingface", "hf"):
        return HuggingFaceClient(api_key=provider_config.get("api_key"))
    if provider in ("openai", "chatgpt", "deepseek", "grok", "xai", "groq"):
        return OpenAIClient(api_key=provider_config.get("api_key"), provider_type=provider)
    if provider in ("anthropic", "claude"):
        return AnthropicClient(api_key=provider_config.get("api_key"))
    if provider == "ollama":
        return OllamaClient(
            api_key=provider_config.get("api_key", ""),
            base_url=provider_config.get("base_url", "http://localhost:11434"),
        )
        
    raise ValueError(f"Unsupported AI provider: {provider}")

def get_model_for_role(provider_config: Dict, role: str = "main") -> str:
    role = str(role or "main").strip().lower()
    
    if role == "risk":
        model_name = provider_config.get("risk_model") or config.AI_RISK_MODEL
    else:
        model_name = provider_config.get("main_model") or config.AI_MAIN_MODEL
        
    # Auto mode routing: If user selects "auto" in dashboard
    if str(model_name).lower().strip() == "auto":
        provider = _normalize_provider(provider_config.get("provider", ""))
        return get_auto_models_for_provider(provider)[0]
            
    return model_name

def get_auto_models_for_provider(provider: str) -> List[str]:
    provider = _normalize_provider(provider)
    if provider == "groq":
        return [
            "llama-3.3-70b-versatile", 
            "llama-3.1-8b-instant", 
            "llama3-70b-8192", 
            "mixtral-8x7b-32768", 
            "gemma2-9b-it"
        ]
    elif provider in ("huggingface", "hf"):
        return ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Meta-Llama-3-70B-Instruct"]
    elif provider in ("grok", "xai"):
        return ["grok-3-mini-fast", "grok-beta"]
    elif provider == "deepseek":
        return ["deepseek-chat", "deepseek-reasoner"]
    elif provider == "anthropic":
        return ["claude-3.5-haiku-20241022", "claude-3-haiku-20240307"]
    elif provider == "openai":
        return ["gpt-4o-mini", "gpt-3.5-turbo"]
    elif provider == "openrouter":
        return [
            "openrouter/free", 
            "nousresearch/hermes-3-llama-3.1-405b:free", 
            "google/gemini-2.5-flash-free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free"
        ]
    return ["default"]

def get_provider_sequence() -> List[Dict]:
    if config.PROVIDERS_CONFIG and len(config.PROVIDERS_CONFIG) > 0:
        return config.PROVIDERS_CONFIG
        
    # Fallback to old behavior ifPROVIDERS_CONFIG is empty
    providers = []
    primary = _normalize_provider(config.AI_PROVIDER)
    fallback = _normalize_provider(config.AI_FALLBACK_PROVIDER)

    if primary:
        providers.append({"provider": primary})

    if config.AI_FALLBACK_ENABLED and fallback and fallback != primary:
        providers.append({"provider": fallback})

    return providers
