from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git_operations import GitOperationService


def configure_remote(repository: Path) -> Path:
    remote = repository.parent / f"{repository.name}-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "-u", "origin", "main")
    return remote


def clone_peer(remote: Path) -> Path:
    peer = remote.parent / f"{remote.stem}-peer"
    subprocess.run(
        ["git", "clone", str(remote), str(peer)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.test")
    return peer


def peer_commit(peer: Path, content: str, message: str) -> str:
    (peer / "README.md").write_text(content, encoding="utf-8")
    git(peer, "add", "README.md")
    git(peer, "commit", "-m", message)
    git(peer, "push", "origin", "main")
    return git(peer, "rev-parse", "HEAD").strip()


def test_fetch_is_local_only_until_approved_and_updates_tracking_ref(
    git_repository: Path,
) -> None:
    remote = configure_remote(git_repository)
    peer = clone_peer(remote)
    remote_head = peer_commit(peer, "# Peer\n", "Peer update")
    old_tracking = git(git_repository, "rev-parse", "refs/remotes/origin/main").strip()
    service = GitOperationService(git_repository)

    plan = service.plan("fetch_remote", {"remote": "origin"})

    assert plan.credential_helper_involvement is True
    assert git(git_repository, "rev-parse", "refs/remotes/origin/main").strip() == old_tracking
    service.execute(plan.id, {"approved": True})
    assert git(git_repository, "rev-parse", "refs/remotes/origin/main").strip() == remote_head


def test_pull_is_fast_forward_only_and_requires_clean_worktree(
    git_repository: Path,
) -> None:
    remote = configure_remote(git_repository)
    peer = clone_peer(remote)
    remote_head = peer_commit(peer, "# Pulled\n", "Pull update")
    service = GitOperationService(git_repository)
    (git_repository / "local.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as dirty:
        service.plan("pull_ff", {"remote": "origin", "branch": "main"})
    assert dirty.value.code == "working_tree_not_clean"

    (git_repository / "local.txt").unlink()
    plan = service.plan("pull_ff", {"remote": "origin", "branch": "main"})
    assert plan.commands == ['git "pull" "--ff-only" "origin" "main"']
    service.execute(plan.id, {"approved": True})
    assert git(git_repository, "rev-parse", "HEAD").strip() == remote_head


def test_push_and_set_upstream_use_explicit_destinations(git_repository: Path) -> None:
    remote = configure_remote(git_repository)
    git(git_repository, "switch", "-c", "topic")
    (git_repository / "topic.txt").write_text("topic\n", encoding="utf-8")
    git(git_repository, "add", "topic.txt")
    git(git_repository, "commit", "-m", "Topic")
    service = GitOperationService(git_repository)

    plan = service.plan(
        "push_set_upstream",
        {"remote": "origin", "branch": "topic"},
    )
    assert plan.commands == ['git "push" "--set-upstream" "origin" "HEAD:refs/heads/topic"']
    service.execute(plan.id, {"approved": True})

    remote_topic = git(remote, "rev-parse", "refs/heads/topic").strip()
    assert remote_topic == git(git_repository, "rev-parse", "HEAD").strip()
    assert git(git_repository, "rev-parse", "--abbrev-ref", "@{upstream}").strip() == (
        "origin/topic"
    )


def test_force_push_uses_exact_lease_and_refuses_remote_race(
    git_repository: Path,
) -> None:
    remote = configure_remote(git_repository)
    peer = clone_peer(remote)
    (git_repository / "local.txt").write_text("local\n", encoding="utf-8")
    git(git_repository, "add", "local.txt")
    git(git_repository, "commit", "-m", "Local rewrite")
    service = GitOperationService(git_repository)
    plan = service.plan("force_push", {"remote": "origin", "branch": "main"})

    assert "--force-with-lease=refs/heads/main:" in plan.commands[0]
    with pytest.raises(CodePreflightError) as confirmation:
        service.execute(plan.id, {"approved": True})
    assert confirmation.value.code == "git_typed_confirmation_required"

    peer_commit(peer, "# Remote won\n", "Remote race")
    result = service.execute(
        plan.id,
        {"approved": True, "confirmation": "FORCE PUSH"},
    )
    assert result.status == "failed"
    assert git(remote, "show", "main:README.md") == "# Remote won\n"


def test_remote_configuration_change_invalidates_network_plan(
    git_repository: Path,
) -> None:
    remote = configure_remote(git_repository)
    service = GitOperationService(git_repository)
    plan = service.plan("fetch_remote", {"remote": "origin"})
    git(git_repository, "remote", "set-url", "origin", f"{remote}-replacement")

    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"


def test_merge_cherry_pick_and_revert_use_immutable_commits(
    git_repository: Path,
) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "feature.txt").write_text("feature\n", encoding="utf-8")
    git(git_repository, "add", "feature.txt")
    git(git_repository, "commit", "-m", "Feature")
    feature_oid = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "switch", "main")
    service = GitOperationService(git_repository)

    merge = service.plan("merge", {"revision": "feature"})
    assert feature_oid in merge.commands[0]
    service.execute(merge.id, {"approved": True})
    assert (git_repository / "feature.txt").exists()

    git(git_repository, "reset", "--hard", "HEAD^")
    cherry = service.plan("cherry_pick", {"revision": feature_oid})
    service.execute(cherry.id, {"approved": True})
    assert (git_repository / "feature.txt").exists()

    revert = service.plan("revert", {"revision": feature_oid})
    service.execute(revert.id, {"approved": True})
    assert not (git_repository / "feature.txt").exists()


def test_rebase_replays_current_branch_onto_bound_target(git_repository: Path) -> None:
    initial = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "switch", "-c", "topic")
    (git_repository / "topic.txt").write_text("topic\n", encoding="utf-8")
    git(git_repository, "add", "topic.txt")
    git(git_repository, "commit", "-m", "Topic")
    git(git_repository, "switch", "main")
    (git_repository / "main.txt").write_text("main\n", encoding="utf-8")
    git(git_repository, "add", "main.txt")
    git(git_repository, "commit", "-m", "Main")
    main_oid = git(git_repository, "rev-parse", "HEAD").strip()
    git(git_repository, "switch", "topic")
    assert git(git_repository, "merge-base", "HEAD", "main").strip() == initial
    service = GitOperationService(git_repository)

    rebase = service.plan("rebase", {"revision": "main"})
    assert main_oid in rebase.commands[0]
    service.execute(rebase.id, {"approved": True})

    assert git(git_repository, "merge-base", "HEAD", "main").strip() == main_oid
    assert (git_repository / "topic.txt").exists()


def test_history_conflict_is_reported_without_recovery_mutation(
    git_repository: Path,
) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "README.md").write_text("feature\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    git(git_repository, "commit", "-m", "Feature edit")
    git(git_repository, "switch", "main")
    (git_repository / "README.md").write_text("main\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    git(git_repository, "commit", "-m", "Main edit")
    service = GitOperationService(git_repository)

    plan = service.plan("merge", {"revision": "feature"})
    result = service.execute(plan.id, {"approved": True})

    assert result.status == "conflicted"
    assert result.conflict is not None
    assert result.conflict.operation == "merge"
    assert result.conflict.can_abort is True
    assert result.conflict.files == ["README.md"]


def test_hard_reset_requires_typed_confirmation_and_preserves_untracked(
    git_repository: Path,
) -> None:
    initial = git(git_repository, "rev-parse", "HEAD").strip()
    (git_repository / "README.md").write_text("committed\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    git(git_repository, "commit", "-m", "Second")
    (git_repository / "README.md").write_text("dirty\n", encoding="utf-8")
    (git_repository / "keep.txt").write_text("untracked\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan("reset", {"mode": "hard", "revision": initial})

    with pytest.raises(CodePreflightError) as confirmation:
        service.execute(plan.id, {"approved": True})
    assert confirmation.value.code == "git_typed_confirmation_required"

    service.execute(plan.id, {"approved": True, "confirmation": "RESET"})
    assert git(git_repository, "rev-parse", "HEAD").strip() == initial
    assert (git_repository / "README.md").read_text(encoding="utf-8") == "# Fixture\n"
    assert (git_repository / "keep.txt").read_text(encoding="utf-8") == "untracked\n"


def test_clean_removes_only_previewed_files_and_preserves_later_ignored_file(
    git_repository: Path,
) -> None:
    (git_repository / ".gitignore").write_text("cache/\n", encoding="utf-8")
    git(git_repository, "add", ".gitignore")
    git(git_repository, "commit", "-m", "Ignore cache")
    cache = git_repository / "cache"
    cache.mkdir()
    (cache / "selected.bin").write_text("selected\n", encoding="utf-8")
    (git_repository / "selected.txt").write_text("selected\n", encoding="utf-8")
    (git_repository / "keep.txt").write_text("keep\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan("clean_paths", {"paths": ["cache/", "selected.txt"]})
    (cache / "later.bin").write_text("later\n", encoding="utf-8")

    assert plan.selected_paths == ["cache/selected.bin", "selected.txt"]
    with pytest.raises(CodePreflightError) as confirmation:
        service.execute(plan.id, {"approved": True})
    assert confirmation.value.code == "git_typed_confirmation_required"
    service.execute(plan.id, {"approved": True, "confirmation": "CLEAN"})

    assert not (cache / "selected.bin").exists()
    assert (cache / "later.bin").exists()
    assert not (git_repository / "selected.txt").exists()
    assert (git_repository / "keep.txt").exists()
