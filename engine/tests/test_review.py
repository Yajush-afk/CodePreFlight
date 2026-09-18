import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.adapters.base import ProviderAdapter
from codepreflight_engine.adapters.fake import FakeProviderAdapter
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator
from codepreflight_engine.trust import trust_repository


class FakeAdapter:
    def __init__(self, descriptor: ProviderDescriptor, output: dict[str, object]) -> None:
        self.descriptor = descriptor
        self.output = output
        self.calls = 0

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        self.calls += 1
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
    events: list[tuple[str, dict[str, object]]] = []

    result = ReviewOrchestrator().review_staged(
        git_repository,
        {"provider": "ollama"},
        lambda event, payload: events.append((event, payload)),
    )

    assert result.summary == "One concern."
    assert result.findings[0].verification.value == "verified"
    event_names = [event for event, _ in events]
    assert "finding" in event_names
    assert event_names.index("consent_required") < event_names.index("provider_delta")
    disclosure = next(payload for event, payload in events if event == "consent_required")
    assert disclosure["manifest"]["total_characters"] > 0  # type: ignore[index]


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
    trust_repository(git_repository)

    with pytest.raises(CodePreflightError) as error:
        ReviewOrchestrator().review_staged(
            git_repository, {"provider": "codex"}, lambda event, payload: None
        )

    assert error.value.code == "provider_consent_required"


def test_authenticated_cli_requires_repository_trust(
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
            git_repository,
            {"provider": "codex", "remoteApproved": True},
            lambda event, payload: None,
        )

    assert error.value.code == "repository_not_trusted"


def test_review_cache_avoids_repeating_provider_request(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    adapter = FakeAdapter(descriptor(), {"summary": "No concerns.", "findings": []})
    install_adapter(monkeypatch, adapter)

    first = ReviewOrchestrator().review_staged(
        git_repository, {"provider": "ollama"}, lambda event, payload: None
    )
    second = ReviewOrchestrator().review_staged(
        git_repository, {"provider": "ollama"}, lambda event, payload: None
    )

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert adapter.calls == 1

    source.write_text("value = False\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    changed = ReviewOrchestrator().review_staged(
        git_repository, {"provider": "ollama"}, lambda event, payload: None
    )

    assert changed.cache_hit is False
    assert adapter.calls == 2


def test_review_repairs_malformed_structured_output_once(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    responses = iter(["not json", json.dumps({"summary": "Repaired.", "findings": []})])
    adapter = FakeProviderAdapter(lambda prompt, schema: next(responses))
    install_adapter(monkeypatch, adapter)
    events: list[tuple[str, dict[str, object]]] = []

    result = ReviewOrchestrator().review_staged(
        git_repository,
        {"provider": "fake", "noCache": True},
        lambda event, payload: events.append((event, payload)),
    )

    assert result.status == "completed"
    assert result.summary == "Repaired."
    assert len(adapter.requests) == 2
    assert "Preserve only claims already present" in adapter.requests[1][0]
    assert any(
        payload.get("repair") is True for event, payload in events if event == "provider_delta"
    )


def test_review_preserves_failed_provider_output_after_repair(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    adapter = FakeProviderAdapter("still not json")
    install_adapter(monkeypatch, adapter)

    result = ReviewOrchestrator().review_staged(
        git_repository, {"provider": "fake", "noCache": True}, lambda event, payload: None
    )

    assert result.status == "failed"
    assert result.blocking is False
    assert result.findings == []
    assert result.failure is not None
    assert result.failure.provider_response == "still not json"
    assert result.failure.attempts == 2
    assert len(adapter.requests) == 2


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        ("fast", "obvious defects in changed lines"),
        ("standard", "complete branch interaction"),
        ("deep", "architecture and broad system effects"),
    ],
)
def test_review_depths_have_distinct_focus(depth: str, expected: str) -> None:
    prompt = ReviewOrchestrator()._prompt("diff", depth, [])

    assert expected in prompt


def test_review_supports_local_commit_against_first_parent(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add feature")
    revision = git(git_repository, "rev-parse", "HEAD").strip()
    adapter = FakeAdapter(descriptor(), {"summary": "Commit reviewed.", "findings": []})
    install_adapter(monkeypatch, adapter)

    result = ReviewOrchestrator().review(
        git_repository,
        {"target": "commit", "revision": revision, "provider": "ollama"},
        lambda event, payload: None,
    )

    assert result.summary == "Commit reviewed."
    assert result.context.target == "commit"
    assert result.context.revision == revision
    assert "first parent" in result.context.content.lower()
