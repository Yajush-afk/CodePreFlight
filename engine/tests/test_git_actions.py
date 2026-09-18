from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git_actions import GitActions


def test_safe_switch_previews_and_executes_existing_local_branch(git_repository: Path) -> None:
    git(git_repository, "branch", "feature")
    actions = GitActions()

    preview = actions.run(git_repository, {"action": "switch_preview", "branch": "feature"})

    assert preview["allowed"] is True
    assert preview["currentBranch"] == "main"
    assert preview["targetBranch"] == "feature"
    assert git(git_repository, "branch", "--show-current").strip() == "main"

    result = actions.run(
        git_repository,
        {
            "action": "switch_execute",
            "branch": "feature",
            "approved": True,
            "expectedHead": preview["expectedHead"],
        },
    )

    assert result["branch"] == "feature"
    assert git(git_repository, "branch", "--show-current").strip() == "feature"


def test_switch_rejects_untracked_collision(git_repository: Path) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "collision.txt").write_text("on branch\n", encoding="utf-8")
    git(git_repository, "add", "collision.txt")
    git(git_repository, "commit", "-m", "Add colliding file")
    git(git_repository, "switch", "main")
    (git_repository / "collision.txt").write_text("local\n", encoding="utf-8")

    preview = GitActions().run(git_repository, {"action": "switch_preview", "branch": "feature"})

    assert preview["allowed"] is False
    assert preview["collisions"] == ["collision.txt"]


def test_switch_requires_approval_and_rejects_missing_branch(git_repository: Path) -> None:
    actions = GitActions()
    with pytest.raises(CodePreflightError) as missing:
        actions.run(git_repository, {"action": "switch_preview", "branch": "missing"})
    assert missing.value.code == "local_branch_not_found"

    git(git_repository, "branch", "feature")
    with pytest.raises(CodePreflightError) as approval:
        actions.run(
            git_repository,
            {"action": "switch_execute", "branch": "feature", "approved": False},
        )
    assert approval.value.code == "git_action_approval_required"
