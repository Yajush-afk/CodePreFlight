import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.adapters.base import ProviderAdapter
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator


class FakeAdapter:
    def __init__(self, descriptor: ProviderDescriptor, output: dict[str, object]) -> None:
        self.descriptor = descriptor
        self.output = output

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        return json.dumps(self.output)


def descriptor(provider_id: str = "ollama", *, remote: bool = False) -> ProviderDescriptor:
    return ProviderDescriptor(
        id=provider_id,
        name=provider_id.title(),
        kind=ProviderKind.SUBSCRIPTION_CLI if remote else ProviderKind.LOCAL,
        state=ProviderState.READY,
        executable=f"/usr/bin/{provider_id}",
        sends_code_remotely=remote,
    )


def install_adapter(monkeypatch: pytest.MonkeyPatch, adapter: ProviderAdapter) -> None:
    registry = SimpleNamespace(adapter=lambda provider_id: adapter)
    monkeypatch.setattr("codepreflight_engine.review.ProviderRegistry", lambda config: registry)


def test_review_parses_and_verifies_findings(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("def feature():\n    return True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    install_adapter(
        monkeypatch,
        FakeAdapter(
            descriptor(),
            {
                "summary": "One concern.",
                "findings": [
                    {
                        "severity": "warning",
                        "title": "Feature always succeeds",
                        "explanation": "The function has no failure path.",
                        "impact": "Callers cannot detect failure.",
                        "confidence": "high",
                        "evidence": [
                            {
                                "path": "feature.py",
                                "start_line": 1,
                                "end_line": 2,
                                "symbol": "feature",
                            }
                        ],
                        "recommendation": "Handle the failure case.",
                        "suggested_tests": ["Test failure behavior"],
                    }
                ],
            },
        ),
    )
    events: list[str] = []

    result = ReviewOrchestrator().review_staged(
        git_repository, {"provider": "ollama"}, lambda event, payload: events.append(event)
    )

    assert result.summary == "One concern."
    assert result.findings[0].verification.value == "verified"
    assert "finding" in events


def test_remote_provider_requires_explicit_consent(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    install_adapter(
        monkeypatch,
        FakeAdapter(descriptor("codex", remote=True), {"summary": "ok", "findings": []}),
    )

    with pytest.raises(CodePreflightError) as error:
        ReviewOrchestrator().review_staged(
            git_repository, {"provider": "codex"}, lambda event, payload: None
        )

    assert error.value.code == "provider_consent_required"
