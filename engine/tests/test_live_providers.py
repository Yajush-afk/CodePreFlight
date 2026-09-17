from __future__ import annotations

import os

import pytest

from codepreflight_engine.adapters import ProviderRegistry
from codepreflight_engine.finding_schema import parse_provider_response, provider_output_schema

pytestmark = pytest.mark.skipif(
    os.environ.get("CODEPREFLIGHT_LIVE_PROVIDERS") != "1",
    reason="live providers require explicit opt-in and may consume provider usage",
)


@pytest.mark.parametrize(
    "provider_id", ["ollama", "codex", "opencode", "claude", "openai-compatible"]
)
def test_live_provider_returns_structured_review(provider_id: str) -> None:
    adapter = ProviderRegistry({}).adapter(provider_id)
    output = adapter.review(
        "Return a concise review with summary 'No change supplied.' and no findings. "
        "Return JSON only.",
        provider_output_schema(),
    )

    assert parse_provider_response(output).findings == []
