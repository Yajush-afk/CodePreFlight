from __future__ import annotations

from pathlib import Path

import pytest

from codepreflight_engine.initialize import initialize_repository
from codepreflight_engine.provider_setup import configure_provider, provider_models
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

    assert result == {"provider": "ollama", "models": ["qwen2.5-coder:7b"]}
