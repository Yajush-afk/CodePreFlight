import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

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
