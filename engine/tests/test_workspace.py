from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.workspace import RepositoryWorkspace


def test_workspace_lists_tree_branches_and_commits(git_repository: Path) -> None:
    (git_repository / "src").mkdir()
    (git_repository / "src" / "feature.py").write_text("value = 1\n", encoding="utf-8")
    (git_repository / "notes.txt").write_text("untracked\n", encoding="utf-8")
    git(git_repository, "add", "src/feature.py")
    git(git_repository, "commit", "-m", "Add feature")
    (git_repository / "src" / "feature.py").write_text("value = 2\n", encoding="utf-8")
    git(git_repository, "branch", "other")

    workspace = RepositoryWorkspace()
    tree = workspace.run(git_repository, {"action": "tree"})
    branches = workspace.run(git_repository, {"action": "branches"})
    commits = workspace.run(git_repository, {"action": "commits", "limit": 10})

    by_path = {item["path"]: item for item in tree["items"]}
    assert by_path["src/feature.py"]["status"] == "modified"
    assert by_path["notes.txt"]["status"] == "untracked"
    assert {item["name"] for item in branches["items"]} == {"main", "other"}
    assert branches["current"] == "main"
    assert commits["items"][0]["subject"] == "Add feature"


def test_workspace_file_preview_is_bounded_to_repository(git_repository: Path) -> None:
    (git_repository / "README.md").write_text("# Changed\n", encoding="utf-8")

    preview = RepositoryWorkspace().run(git_repository, {"action": "file", "path": "README.md"})

    assert "# Changed" in preview["content"]
    assert "README.md" in preview["diff"]

    with pytest.raises(CodePreflightError) as error:
        RepositoryWorkspace().run(git_repository, {"action": "file", "path": "../outside"})
    assert error.value.code == "invalid_workspace_path"


def test_pr_detection_requires_github_repository(git_repository: Path) -> None:
    with pytest.raises(CodePreflightError) as error:
        RepositoryWorkspace().run(git_repository, {"action": "pr"})

    assert error.value.code == "github_repository_required"
    assert error.value.recoverable is True
