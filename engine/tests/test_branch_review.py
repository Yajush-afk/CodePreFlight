import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator


class CleanAdapter:
    descriptor = ProviderDescriptor(
        id="fake",
        name="Fake",
        kind=ProviderKind.LOCAL,
        state=ProviderState.READY,
        sends_code_remotely=False,
    )

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        return json.dumps({"summary": "Branch changes are coherent.", "findings": []})


def test_branch_review_compares_against_merge_base(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add feature")
    registry = SimpleNamespace(adapter=lambda provider_id: CleanAdapter())
    monkeypatch.setattr("codepreflight_engine.review.ProviderRegistry", lambda config: registry)

    result = ReviewOrchestrator().review(
        git_repository,
        {"target": "branch", "base": "main", "provider": "fake"},
        lambda event, payload: None,
    )

    assert result.context.target == "branch"
    assert result.context.changed_files == ["feature.py"]
    assert result.context.base_revision
