from __future__ import annotations

import os
from pathlib import Path

import pytest

from codepreflight_engine.adapters import ProviderRegistry
from codepreflight_engine.config import load_config
from codepreflight_engine.finding_schema import parse_provider_response, provider_output_schema
from codepreflight_engine.readiness import review_readiness

pytestmark = pytest.mark.skipif(
    os.environ.get("CODEPREFLIGHT_LIVE_PROVIDERS") != "1",
    reason="live providers require explicit opt-in and may consume provider usage",
)


@pytest.mark.parametrize(
    "provider_id", ["ollama", "codex", "opencode", "claude", "openai-compatible"]
)
def test_live_provider_returns_structured_review(provider_id: str) -> None:
    selected = os.environ.get("CODEPREFLIGHT_LIVE_PROVIDER")
    if selected and selected != provider_id:
        pytest.skip("another live provider was explicitly selected")
    adapter = ProviderRegistry(load_config(Path.cwd())).adapter(provider_id)
    readiness = review_readiness(adapter.descriptor)
    if readiness["state"] != "ready":
        if selected:
            pytest.fail(f"Selected provider needs setup: {readiness['blockers']}")
        pytest.skip("provider is not ready; no authentication or setup is performed by tests")
    output = adapter.review(
        "Return a concise review with summary 'No change supplied.' and no findings. "
        "Return JSON only.",
        provider_output_schema(),
    )

    assert parse_provider_response(output).findings == []
