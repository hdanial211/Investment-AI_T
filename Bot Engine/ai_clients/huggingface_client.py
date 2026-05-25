"""Hugging Face Inference Providers OpenAI-compatible client."""

from typing import Dict, List

import requests

import config
from .base import AIProviderError


class HuggingFaceClient:
    name = "huggingface"

    def __init__(self):
        self.base_url = config.HF_BASE_URL.rstrip("/")
        self.api_key = config.HF_TOKEN

    def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> str:
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

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise AIProviderError("Hugging Face request timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise AIProviderError(f"Hugging Face request failed: {exc}") from exc

        if response.status_code >= 400:
            retryable = response.status_code in (408, 409, 425, 429, 500, 502, 503, 504)
            raise AIProviderError(
                f"Hugging Face HTTP {response.status_code}: {response.text[:400]}",
                retryable=retryable,
            )

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"Hugging Face malformed response: {data}") from exc

        return str(content or "").strip()
