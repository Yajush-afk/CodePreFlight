from pathlib import Path

from conftest import git

from codepreflight_engine.repository import RepositoryInspector


def test_snapshot_categorizes_worktree_changes(git_repository: Path) -> None:
    (git_repository / "README.md").write_text("# Changed\n", encoding="utf-8")
    (git_repository / "staged.py").write_text("value = 1\n", encoding="utf-8")
    (git_repository / "untracked.ts").write_text("export const value = 1;\n", encoding="utf-8")
    git(git_repository, "add", "staged.py")

    snapshot = RepositoryInspector().inspect(git_repository)
    files = {item.path: item for item in snapshot.files}

    assert snapshot.branch == "main"
    assert files["README.md"].unstaged is True
    assert files["staged.py"].staged is True
    assert files["untracked.ts"].untracked is True
    assert snapshot.project.languages == ["Python"]


def test_snapshot_supports_detached_head(git_repository: Path) -> None:
    git(git_repository, "checkout", "--detach")

    snapshot = RepositoryInspector().inspect(git_repository)

    assert snapshot.branch is None
    assert snapshot.detached_head is not None


def test_snapshot_works_from_repository_subdirectory(git_repository: Path) -> None:
    nested = git_repository / "src" / "nested"
    nested.mkdir(parents=True)

    snapshot = RepositoryInspector().inspect(nested)

    assert snapshot.root == str(git_repository.resolve())
