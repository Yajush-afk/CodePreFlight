from __future__ import annotations

import json
from pathlib import Path

import pytest

from codepreflight_engine.initialize import initialize_repository
from codepreflight_engine.provider_setup import (
    configure_provider,
    provider_models,
    provider_variants,
)
from codepreflight_engine.trust import is_trusted


def test_provider_configuration_previews_without_writing(git_repository: Path) -> None:
    result = configure_provider(
        git_repository,
        provider_id="ollama",
        model="qwen2.5-coder:7b",
        global_scope=False,
        write=False,
    )

    assert result["written"] is False
    assert 'provider = "ollama"' in result["preview"]
    assert "[providers.ollama]" in result["preview"]
    assert 'model = "qwen2.5-coder:7b"' in result["preview"]
    assert not (git_repository / ".codepreflight.toml").exists()


def test_provider_configuration_preserves_settings_and_invalidates_trust(
    git_repository: Path,
) -> None:
    initialize_repository(git_repository, write=True)
    assert is_trusted(git_repository) is True

    configure_provider(
        git_repository,
        provider_id="opencode",
        model=None,
        global_scope=False,
        write=True,
    )

    content = (git_repository / ".codepreflight.toml").read_text(encoding="utf-8")
    assert 'provider = "opencode"' in content
    assert "context_limit = 60000" in content
    assert is_trusted(git_repository) is False


def test_ollama_models_are_reported_without_repository_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codepreflight_engine.provider_setup._run",
        lambda command: (0, "NAME ID SIZE MODIFIED\nqwen2.5-coder:7b abc 4GB now\n", ""),
    )

    result = provider_models("ollama")

    assert result["provider"] == "ollama"
    assert result["models"] == ["qwen2.5-coder:7b"]
    assert result["serviceTier"] == "standard"


def test_codex_models_use_visible_standard_tier_cache_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "models_cache.json"
    cache.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-flagship",
                        "display_name": "Flagship",
                        "visibility": "list",
                        "description": "Most capable",
                        "default_reasoning_level": "low",
                        "supported_reasoning_levels": [
                            {"effort": "low", "description": "Light"},
                            {"effort": "high", "description": "Deep"},
                        ],
                    },
                    {
                        "slug": "gpt-economy",
                        "display_name": "Economy",
                        "visibility": "list",
                        "description": "Lower usage",
                        "default_reasoning_level": "medium",
                        "supported_reasoning_levels": [
                            {"effort": "medium", "description": "Balanced"}
                        ],
                    },
                    {
                        "slug": "gpt-economy-fast",
                        "display_name": "Economy Fast",
                        "visibility": "list",
                        "description": "Speed tier",
                        "supported_reasoning_levels": [],
                    },
                    {
                        "slug": "hidden",
                        "display_name": "Hidden",
                        "visibility": "hide",
                        "description": "Internal",
                        "supported_reasoning_levels": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    result = provider_models("codex")

    assert result["models"] == ["gpt-flagship", "gpt-economy"]
    assert result["serviceTier"] == "standard"
    assert result["details"][1]["description"] == "Lower usage"
    assert provider_variants("codex", "gpt-flagship")["variants"] == ["low", "high"]


def test_opencode_models_and_variants_exclude_fast_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verbose = """openai/gpt-economy
{"variants":{"low":{},"high":{}}}
openai/gpt-economy-fast
{"variants":{"low":{}}}
"""

    def run(command: list[str]) -> tuple[int, str, str]:
        if command == ["opencode", "models"]:
            return 0, "openai/gpt-economy\nopenai/gpt-economy-fast\n", ""
        return 0, verbose, ""

    monkeypatch.setattr("codepreflight_engine.provider_setup._run", run)

    assert provider_models("opencode")["models"] == ["openai/gpt-economy"]
    assert provider_variants("opencode", "openai/gpt-economy")["variants"] == [
        "low",
        "high",
    ]


def test_provider_configuration_saves_variant_and_rejects_fast_model(
    git_repository: Path,
) -> None:
    result = configure_provider(
        git_repository,
        provider_id="codex",
        model="gpt-economy",
        variant="high",
        global_scope=False,
        write=True,
    )

    assert result["variant"] == "high"
    content = (git_repository / ".codepreflight.toml").read_text(encoding="utf-8")
    assert 'model = "gpt-economy"' in content
    assert 'variant = "high"' in content

    with pytest.raises(Exception, match="standard service tier"):
        configure_provider(
            git_repository,
            provider_id="opencode",
            model="openai/gpt-economy-fast",
            variant=None,
            global_scope=False,
            write=False,
        )
