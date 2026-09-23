import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.intelligence import RepositoryIntelligence
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState


class ExplanationAdapter:
    descriptor = ProviderDescriptor(
        id="fake",
        name="Fake",
        kind=ProviderKind.LOCAL,
        state=ProviderState.READY,
        sends_code_remotely=False,
    )

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        return json.dumps(
            {
                "summary": "The staged function now returns a useful value.",
                "before": "No function existed.",
                "after": "feature returns true.",
                "side_effects": ["Callers can use the result."],
                "evidence": [
                    {"path": "feature.py", "line": 2},
                    {"path": "invented.py", "line": 99},
                ],
            }
        )


class HistoryAdapter:
    def __init__(self, commit: str, *, answer_mode: bool = False) -> None:
        self.commit = commit
        self.answer_mode = answer_mode
        self.prompts: list[str] = []
        self.descriptor = ExplanationAdapter.descriptor

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        self.prompts.append(prompt)
        if self.answer_mode:
            return json.dumps(
                {
                    "answer": "The validation was introduced by the cited commit.",
                    "evidence": [{"path": "feature.py", "line": 1, "commit": self.commit}],
                }
            )
        return json.dumps(
            {
                "summary": "The cited commit introduced the current behavior.",
                "evidence": [{"path": "feature.py", "line": 1, "commit": self.commit}],
            }
        )


class RemoteExplanationAdapter(ExplanationAdapter):
    descriptor = ProviderDescriptor(
        id="remote-fake",
        name="Remote fake",
        kind=ProviderKind.SUBSCRIPTION_CLI,
        state=ProviderState.READY,
        sends_code_remotely=True,
    )


def test_diff_explanation_verifies_evidence(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "feature.py").write_text(
        "def feature():\n    return True\n", encoding="utf-8"
    )
    git(git_repository, "add", "feature.py")
    registry = SimpleNamespace(adapter=lambda provider_id: ExplanationAdapter())
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )

    result = RepositoryIntelligence().run(git_repository, {"mode": "diff", "provider": "fake"})

    assert result["result"]["summary"].startswith("The staged function")
    assert result["result"]["evidence"] == [{"path": "feature.py", "line": 2, "commit": None}]


def test_finding_details_are_local_and_evidence_grounded(git_repository: Path) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = False\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")

    result = RepositoryIntelligence().run(
        git_repository,
        {
            "mode": "finding",
            "target": "staged",
            "path": "feature.py",
            "suggestedTests": ["pytest tests/test_feature.py"],
        },
    )

    detail = result["result"]
    assert detail["path"] == "feature.py"
    assert "+value = False" in detail["evidenceDiff"]
    assert detail["history"] == []
    assert detail["suggestedTests"] == ["pytest tests/test_feature.py"]


def test_history_explanation_requires_commit_that_touched_file(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "feature.py").write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Introduce feature behavior")
    commit = git(git_repository, "rev-parse", "HEAD").strip()
    adapter = HistoryAdapter(commit)
    registry = SimpleNamespace(adapter=lambda provider_id: adapter)
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )

    result = RepositoryIntelligence().run(
        git_repository, {"mode": "history", "path": "feature.py", "provider": "fake"}
    )

    assert result["result"]["evidence"][0]["commit"] == commit
    assert "commit " + commit in adapter.prompts[0]


def test_historical_question_includes_git_history(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "feature.py").write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Introduce feature behavior")
    commit = git(git_repository, "rev-parse", "HEAD").strip()
    (git_repository / "feature.py").write_text("value = False\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    adapter = HistoryAdapter(commit, answer_mode=True)
    registry = SimpleNamespace(adapter=lambda provider_id: adapter)
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )

    result = RepositoryIntelligence().run(
        git_repository,
        {
            "mode": "ask",
            "question": "Which commit introduced this behavior?",
            "provider": "fake",
        },
    )

    assert result["result"]["evidence"][0]["commit"] == commit
    assert "Relevant Git history" in adapter.prompts[0]


def test_history_rejects_commit_unrelated_to_cited_file(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = git(git_repository, "rev-parse", "HEAD").strip()
    (git_repository / "feature.py").write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Introduce feature behavior")
    adapter = HistoryAdapter(unrelated)
    registry = SimpleNamespace(adapter=lambda provider_id: adapter)
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )

    with pytest.raises(CodePreflightError, match="must cite a commit"):
        RepositoryIntelligence().run(
            git_repository, {"mode": "history", "path": "feature.py", "provider": "fake"}
        )


def test_remote_question_discloses_context_before_requesting_consent(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "feature.py").write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    registry = SimpleNamespace(adapter=lambda provider_id: RemoteExplanationAdapter())
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )
    monkeypatch.setattr("codepreflight_engine.intelligence.is_trusted", lambda root: True)
    events: list[tuple[str, dict[str, object]]] = []

    with pytest.raises(CodePreflightError) as error:
        RepositoryIntelligence().run(
            git_repository,
            {"mode": "ask", "question": "What changed?", "provider": "remote-fake"},
            lambda event, payload: events.append((event, payload)),
        )

    assert error.value.code == "provider_consent_required"
    assert events[0][0] == "consent_required"
    assert events[0][1]["manifest"]["total_characters"] > 0  # type: ignore[index]


def test_full_scan_finding_follow_up_uses_review_evidence_without_staged_changes(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("def validate(token):\n    return bool(token)\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add validation")
    adapter = HistoryAdapter(git(git_repository, "rev-parse", "HEAD").strip(), answer_mode=True)
    registry = SimpleNamespace(adapter=lambda provider_id: adapter)
    monkeypatch.setattr(
        "codepreflight_engine.intelligence.ProviderRegistry", lambda config: registry
    )

    result = RepositoryIntelligence().run(
        git_repository,
        {
            "mode": "ask",
            "target": "review",
            "question": "How should we fix finding 2?",
            "provider": "fake",
            "reviewContext": {
                "target": "full",
                "summary": "The repository was scanned.",
                "findings": [
                    {
                        "id": "finding-2",
                        "index": 2,
                        "title": "Empty tokens pass validation",
                        "explanation": "The validator accepts whitespace.",
                        "verification": "verified",
                        "evidence": [{"path": "feature.py", "start_line": 2}],
                    }
                ],
            },
        },
    )

    assert result["result"]["answer"]
    assert "Empty tokens pass validation" in adapter.prompts[0]
    assert "Selected finding 2" in adapter.prompts[0]
    assert "feature.py lines" in adapter.prompts[0]
    assert "return bool(token)" in adapter.prompts[0]
