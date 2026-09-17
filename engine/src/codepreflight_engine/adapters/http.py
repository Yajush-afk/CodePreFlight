from __future__ import annotations

import os
from typing import Any

import httpx

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor


def _post(url: str, *, json: dict[str, Any], headers: dict[str, str] | None = None) -> Any:
    try:
        response = httpx.post(url, json=json, headers=headers, timeout=180)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise CodePreflightError("provider_error", str(error)) from error


class OllamaAdapter:
    def __init__(
        self,
        descriptor: ProviderDescriptor,
        *,
        model: str = "qwen2.5-coder:7b",
        base_url: str = "http://127.0.0.1:11434",
    ) -> None:
        self.descriptor = descriptor
        self.model = model
        self.base_url = base_url

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        value = _post(
            f"{self.base_url.rstrip('/')}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
            },
        )
        if isinstance(value, dict) and isinstance(value.get("response"), str):
            return value["response"]
        raise CodePreflightError("provider_output_invalid", "Ollama returned no review text")


class OpenAICompatibleAdapter:
    def __init__(
        self,
        descriptor: ProviderDescriptor,
        *,
        model: str,
        base_url: str,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.descriptor = descriptor
        self.model = model
        self.base_url = base_url
        self.api_key_env = api_key_env

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise CodePreflightError(
                "provider_not_configured", f"Environment variable {self.api_key_env} is not set"
            )
        value = _post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "codepreflight_review",
                        "strict": True,
                        "schema": schema,
                    },
                },
            },
        )
        try:
            return str(value["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise CodePreflightError(
                "provider_output_invalid", "OpenAI-compatible endpoint returned no review content"
            ) from error
