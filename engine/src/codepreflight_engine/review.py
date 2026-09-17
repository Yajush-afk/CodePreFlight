from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from .config import load_config
from .context import ContextBuilder
from .errors import CodePreflightError
from .models import ProviderDescriptor, ProviderState, ReviewPreparation
from .providers import discover_providers
from .trust import is_trusted

EventEmitter = Callable[[str, dict[str, Any]], None]


class ReviewOrchestrator:
    def review_staged(
        self,
        root: Path,
        payload: dict[str, Any],
        emit: EventEmitter,
    ) -> ReviewPreparation:
        config = load_config(root)
        if config.get("checks") and not is_trusted(root):
            raise CodePreflightError(
                "repository_not_trusted",
                "This repository configuration contains executable checks; "
                "run `preflight init --write` or approve it before review",
            )
        emit("progress", {"message": "Building focused staged context"})
        context = ContextBuilder().build(root, config)
        provider_id = str(
            payload.get("provider") or config.get("review", {}).get("provider", "ollama")
        )
        provider = self._provider(provider_id)
        if provider.state not in {ProviderState.INSTALLED, ProviderState.READY}:
            raise CodePreflightError(
                "provider_unavailable", f"Provider {provider.name} is {provider.state.value}"
            )
        emit(
            "consent_required",
            {
                "provider": provider.model_dump(mode="json"),
                "contextCharacters": context.manifest.total_characters,
                "redactions": context.manifest.redactions,
            },
        )
        if provider.sends_code_remotely and not bool(payload.get("remoteApproved")):
            raise CodePreflightError(
                "provider_consent_required",
                f"{provider.name} may send code remotely; rerun with --approve "
                "after reviewing the disclosure",
                recoverable=True,
            )
        if provider.id != "ollama":
            raise CodePreflightError(
                "provider_review_pending",
                f"{provider.name} review execution is added in Phase 3; "
                "use Ollama for the Phase 2 workflow",
            )
        emit("progress", {"message": "Requesting local Ollama review"})
        analysis = self._ollama(context.content, config)
        return ReviewPreparation(provider=provider, context=context, analysis=analysis)

    def _provider(self, provider_id: str) -> ProviderDescriptor:
        providers = {provider.id: provider for provider in discover_providers()}
        if provider_id not in providers:
            raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
        return providers[provider_id]

    def _ollama(self, context: str, config: dict[str, Any]) -> str:
        model = str(config.get("providers", {}).get("ollama", {}).get("model", "qwen2.5-coder:7b"))
        base_url = str(
            config.get("providers", {}).get("ollama", {}).get("base_url", "http://127.0.0.1:11434")
        )
        prompt = (
            "Review this staged change for correctness, security, regressions, and missing tests. "
            "Be concise, cite file paths and lines, and avoid style-only comments.\n\n" + context
        )
        try:
            response = httpx.post(
                f"{base_url.rstrip('/')}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise CodePreflightError("provider_error", f"Ollama review failed: {error}") from error
        value = response.json()
        analysis = value.get("response") if isinstance(value, dict) else None
        if not isinstance(analysis, str) or not analysis.strip():
            raise CodePreflightError("provider_output_invalid", "Ollama returned no review text")
        return analysis.strip()
