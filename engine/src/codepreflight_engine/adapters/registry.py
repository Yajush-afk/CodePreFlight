from __future__ import annotations

import os
from typing import Any

from codepreflight_engine.adapters.base import ProviderAdapter
from codepreflight_engine.adapters.cli import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    OpenCodeCliAdapter,
)
from codepreflight_engine.adapters.http import OllamaAdapter, OpenAICompatibleAdapter
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderState
from codepreflight_engine.providers import discover_providers


class ProviderRegistry:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.descriptors = {item.id: item for item in discover_providers()}

    def adapter(self, provider_id: str) -> ProviderAdapter:
        descriptor = self.descriptors.get(provider_id)
        if not descriptor:
            raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
        provider_config = self.config.get("providers", {}).get(provider_id, {})
        timeout = int(provider_config.get("timeout_seconds", 180))
        if provider_id == "ollama":
            return OllamaAdapter(
                descriptor,
                model=str(provider_config.get("model", "qwen2.5-coder:7b")),
                base_url=str(provider_config.get("base_url", "http://127.0.0.1:11434")),
            )
        if provider_id == "codex":
            return CodexCliAdapter(descriptor, timeout=timeout)
        if provider_id == "claude":
            return ClaudeCliAdapter(descriptor, timeout=timeout)
        if provider_id == "opencode":
            return OpenCodeCliAdapter(descriptor, timeout=timeout)
        if provider_id == "openai-compatible":
            api_key_env = str(provider_config.get("api_key_env", "OPENAI_API_KEY"))
            if os.environ.get(api_key_env):
                descriptor = descriptor.model_copy(
                    update={"state": ProviderState.READY, "detail": f"uses {api_key_env}"}
                )
            return OpenAICompatibleAdapter(
                descriptor,
                model=str(provider_config.get("model", "gpt-4.1-mini")),
                base_url=str(provider_config.get("base_url", "https://api.openai.com/v1")),
                api_key_env=api_key_env,
            )
        raise CodePreflightError("unsupported_provider", f"Unsupported provider: {provider_id}")
