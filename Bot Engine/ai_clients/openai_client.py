"""OpenAI and DeepSeek chat-completions client."""

from typing import Dict, List

try:
    import requests
except ImportError:
    requests = None

from .base import AIProviderError

class OpenAIClient:
    name = "openai"

    def __init__(self, api_key: str, provider_type: str = "openai"):
        self.api_key = api_key
        self.provider_type = provider_type.lower()
        
        if self.provider_type == "deepseek":
            self.base_url = "https://api.deepseek.com/v1"
        else:
            self.base_url = "https://api.openai.com/v1"

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
            raise AIProviderError(f"{self.provider_type.upper()}_API_KEY is missing", retryable=False)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise AIProviderError(f"{self.provider_type} request timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise AIProviderError(f"{self.provider_type} request failed: {exc}") from exc

        if response.status_code >= 400:
            retryable = response.status_code in (408, 409, 425, 429, 500, 502, 503, 504)
            raise AIProviderError(
                f"{self.provider_type} HTTP {response.status_code}: {response.text[:400]}",
                retryable=retryable,
            )

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"{self.provider_type} malformed response: {data}") from exc

        return str(content or "").strip()
