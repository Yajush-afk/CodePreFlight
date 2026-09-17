from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator


def ollama_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        id="ollama",
        name="Ollama",
        kind=ProviderKind.LOCAL,
        state=ProviderState.READY,
        executable="/usr/bin/ollama",
        sends_code_remotely=False,
    )


def test_review_builds_context_and_calls_local_provider(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("def feature():\n    return True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    orchestrator = ReviewOrchestrator()
    monkeypatch.setattr(orchestrator, "_provider", lambda _: ollama_descriptor())
    monkeypatch.setattr(orchestrator, "_ollama", lambda context, config: "No findings.")
    events: list[str] = []

    result = orchestrator.review_staged(
        git_repository, {"provider": "ollama"}, lambda event, payload: events.append(event)
    )

    assert result.analysis == "No findings."
    assert result.context.staged_files == ["feature.py"]
    assert events == ["progress", "consent_required", "progress"]


def test_remote_provider_requires_explicit_consent(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    orchestrator = ReviewOrchestrator()
    remote = ProviderDescriptor(
        id="codex",
        name="Codex CLI",
        kind=ProviderKind.SUBSCRIPTION_CLI,
        state=ProviderState.READY,
        executable="/usr/bin/codex",
        sends_code_remotely=True,
    )
    monkeypatch.setattr(orchestrator, "_provider", lambda _: remote)

    with pytest.raises(CodePreflightError) as error:
        orchestrator.review_staged(
            git_repository, {"provider": "codex"}, lambda event, payload: None
        )

    assert error.value.code == "provider_consent_required"
