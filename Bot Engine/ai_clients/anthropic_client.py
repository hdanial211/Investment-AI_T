"""Anthropic chat-completions client."""

from typing import Dict, List

try:
    import requests
except ImportError:
    requests = None

from .base import AIProviderError

class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"

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
            raise AIProviderError("ANTHROPIC_API_KEY is missing", retryable=False)

        # Anthropic messages API requires system prompt to be a top-level parameter
        system_prompt = ""
        anthropic_messages = []
        
        for msg in messages:
            if msg["role"] == "system":
                system_prompt += msg["content"] + "\n"
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
            "temperature": temperature,
        }
        
        if system_prompt:
            payload["system"] = system_prompt.strip()

        try:
            response = requests.post(
                f"{self.base_url}/messages",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise AIProviderError("Anthropic request timed out") from exc
        except requests.exceptions.RequestException as exc:
            raise AIProviderError(f"Anthropic request failed: {exc}") from exc

        if response.status_code >= 400:
            retryable = response.status_code in (408, 409, 425, 429, 500, 502, 503, 504)
            raise AIProviderError(
                f"Anthropic HTTP {response.status_code}: {response.text[:400]}",
                retryable=retryable,
            )

        data = response.json()
        try:
            content = data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError(f"Anthropic malformed response: {data}") from exc

        return str(content or "").strip()
