from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.commit import create_commit, prepare_commit, staged_fingerprint
from codepreflight_engine.errors import CodePreflightError


def test_index_change_during_review_rejects_preparation(git_repository: Path, monkeypatch) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = 1\n")
    git(git_repository, "add", "feature.py")

    def changed_during_review(*args, **kwargs):
        source.write_text("value = 2\n")
        git(git_repository, "add", "feature.py")
        return None

    monkeypatch.setattr(
        "codepreflight_engine.commit.ReviewOrchestrator.review_staged", changed_during_review
    )
    with pytest.raises(CodePreflightError) as error:
        prepare_commit(git_repository, {}, lambda *args: None)
    assert error.value.code == "staged_changes_changed"


def test_commit_requires_explicit_approval(git_repository: Path) -> None:
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")

    with pytest.raises(CodePreflightError) as error:
        create_commit(
            git_repository,
            {
                "approved": False,
                "message": "feat: add feature",
                "fingerprint": staged_fingerprint(git_repository),
            },
        )

    assert error.value.code == "commit_not_approved"


def test_commit_rejects_changed_staged_content(git_repository: Path) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    fingerprint = staged_fingerprint(git_repository)
    source.write_text("value = 2\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")

    with pytest.raises(CodePreflightError) as error:
        create_commit(
            git_repository,
            {
                "approved": True,
                "message": "feat: add feature",
                "fingerprint": fingerprint,
            },
        )

    assert error.value.code == "staged_changes_changed"


def test_commit_creates_commit_after_approval(git_repository: Path) -> None:
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    fingerprint = staged_fingerprint(git_repository)

    result = create_commit(
        git_repository,
        {
            "approved": True,
            "message": "feat: add feature",
            "fingerprint": fingerprint,
        },
    )

    assert result["message"] == "feat: add feature"
    assert git(git_repository, "log", "-1", "--pretty=%s").strip() == "feat: add feature"
