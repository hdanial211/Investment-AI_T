"""Ollama local AI client.

Connects to a locally running Ollama instance (default: http://localhost:11434).
No API key required — everything runs on your machine.
"""

from typing import Dict, List

try:
    import requests
except ImportError:
    requests = None

from .base import AIProviderError


class OllamaClient:
    name = "ollama"

    def __init__(self, api_key: str = "", base_url: str = ""):
        # api_key is ignored for Ollama but accepted for interface compatibility
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")

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

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.ConnectionError as exc:
            raise AIProviderError(
                f"Cannot connect to Ollama at {self.base_url}. "
                "Is Ollama running? Start it with: ollama serve",
                retryable=True,
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise AIProviderError("Ollama request timed out", retryable=True) from exc
        except requests.exceptions.RequestException as exc:
            raise AIProviderError(f"Ollama request failed: {exc}") from exc

        if response.status_code >= 400:
            retryable = response.status_code in (408, 429, 500, 502, 503, 504)
            raise AIProviderError(
                f"Ollama HTTP {response.status_code}: {response.text[:400]}",
                retryable=retryable,
            )

        data = response.json()
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise AIProviderError(f"Ollama malformed response: {data}") from exc

        return str(content or "").strip()
