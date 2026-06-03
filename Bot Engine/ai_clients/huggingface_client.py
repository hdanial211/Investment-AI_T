"""Hugging Face Inference Providers OpenAI-compatible client."""

from typing import Dict, List

try:
    import requests
except ImportError:  # pragma: no cover - launcher installs it before live run.
    requests = None

import config
from .base import AIProviderError


class HuggingFaceClient:
    name = "huggingface"

    def __init__(self, api_key: str = None):
        self.base_url = config.HF_BASE_URL.rstrip("/")
        self.api_key = api_key or config.HF_TOKEN

    def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> str:
        if requests is None:
            raise AIProviderError("requests package is not installed", retryable=False)
        if not self.api_key or self.api_key == "CHANGE_ME":
            raise AIProviderError("HF_TOKEN is missing", retryable=False)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        models_to_try = [model]
        if model.lower() == "auto":
            models_to_try = [
                "Qwen/Qwen2.5-72B-Instruct",
                "meta-llama/Llama-3.3-70B-Instruct",
                "Qwen/Qwen2.5-Coder-32B-Instruct",
                "mistralai/Mixtral-8x7B-Instruct-v0.1"
            ]

        last_error = None
        last_status = None
        last_text = None

        for m in models_to_try:
            payload["model"] = m
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                
                if response.status_code < 400:
                    data = response.json()
                    try:
                        content = data["choices"][0]["message"]["content"]
                        return str(content or "").strip()
                    except (KeyError, IndexError, TypeError) as exc:
                        raise AIProviderError(f"Hugging Face malformed response: {data}") from exc
                else:
                    last_status = response.status_code
                    last_text = response.text[:400]
                    # If it's a hard error (auth, not found), don't retry other models
                    if response.status_code in (400, 401, 403, 404):
                        break
                        
            except requests.exceptions.Timeout as exc:
                last_error = exc
                last_text = "Request timed out"
            except requests.exceptions.RequestException as exc:
                last_error = exc
                last_text = str(exc)

        # If we reach here, all models failed
        if last_status:
            retryable = last_status in (408, 409, 425, 429, 500, 502, 503, 504)
            raise AIProviderError(
                f"Hugging Face HTTP {last_status}: {last_text}",
                retryable=retryable,
            )
        else:
            raise AIProviderError(f"Hugging Face request failed: {last_text}")
