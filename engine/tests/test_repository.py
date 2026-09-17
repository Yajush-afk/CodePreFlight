import subprocess
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
    assert snapshot.remotes == []
    assert snapshot.github is None


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


def test_snapshot_reports_renamed_deleted_and_ignored_paths(git_repository: Path) -> None:
    (git_repository / ".gitignore").write_text("cache/\n", encoding="utf-8")
    (git_repository / "delete-me.txt").write_text("remove me\n", encoding="utf-8")
    git(git_repository, "add", ".gitignore", "delete-me.txt")
    git(git_repository, "commit", "-m", "Add status fixtures")
    git(git_repository, "mv", "README.md", "RENAMED.md")
    (git_repository / "delete-me.txt").unlink()
    (git_repository / "cache").mkdir()
    (git_repository / "cache" / "result.bin").write_text("ignored\n", encoding="utf-8")

    snapshot = RepositoryInspector().inspect(git_repository)
    files = {item.path: item for item in snapshot.files}

    assert files["RENAMED.md"].kind.value == "renamed"
    assert files["RENAMED.md"].previous_path == "README.md"
    assert files["delete-me.txt"].kind.value == "deleted"
    assert files["cache/"].ignored is True


def test_snapshot_supports_unborn_repository(tmp_path: Path) -> None:
    git(tmp_path, "init", "-b", "main")

    snapshot = RepositoryInspector().inspect(tmp_path)

    assert snapshot.branch == "main"
    assert snapshot.detached_head is None
    assert snapshot.merge_base is None
    assert snapshot.files == []


def test_snapshot_reports_conflicts(git_repository: Path) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "README.md").write_text("feature\n", encoding="utf-8")
    git(git_repository, "commit", "-am", "Change on feature")
    git(git_repository, "switch", "main")
    (git_repository / "README.md").write_text("main\n", encoding="utf-8")
    git(git_repository, "commit", "-am", "Change on main")
    merge = subprocess.run(
        ["git", "merge", "feature"],
        cwd=git_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert merge.returncode != 0

    snapshot = RepositoryInspector().inspect(git_repository)

    assert snapshot.conflicts == ["README.md"]
    assert (
        next(item for item in snapshot.files if item.path == "README.md").kind.value == "unmerged"
    )


def test_snapshot_parses_github_remote_and_merge_base(git_repository: Path) -> None:
    git(git_repository, "remote", "add", "origin", "git@github.com:octo/code-preflight.git")
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add feature")

    snapshot = RepositoryInspector().inspect(git_repository)

    assert snapshot.base_branch == "main"
    assert snapshot.merge_base == git(git_repository, "rev-parse", "main").strip()
    assert snapshot.github is not None
    assert snapshot.github.owner == "octo"
    assert snapshot.github.name == "code-preflight"


def test_snapshot_calculates_ahead_and_behind_without_fetching(git_repository: Path) -> None:
    remote = git_repository.parent / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    git(git_repository, "remote", "add", "origin", str(remote))
    git(git_repository, "push", "-u", "origin", "main")
    (git_repository / "local.txt").write_text("ahead\n", encoding="utf-8")
    git(git_repository, "add", "local.txt")
    git(git_repository, "commit", "-m", "Local commit")

    ahead = RepositoryInspector().inspect(git_repository)
    assert (ahead.ahead, ahead.behind) == (1, 0)

    git(git_repository, "push")
    git(git_repository, "update-ref", "refs/heads/main", "HEAD~1")
    behind = RepositoryInspector().inspect(git_repository)
    assert (behind.ahead, behind.behind) == (0, 1)
