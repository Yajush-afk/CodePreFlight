from __future__ import annotations

from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git_operations import GitOperationService


def test_create_switch_rename_and_delete_local_branches(
    git_repository: Path,
) -> None:
    service = GitOperationService(git_repository)
    create = service.plan("create_branch", {"branch": "feature/local"})
    assert git(git_repository, "branch", "--list", "feature/local") == ""
    service.execute(create.id, {"approved": True})

    switch = service.plan("switch_branch", {"branch": "feature/local"})
    assert switch.source == "main"
    assert switch.destination == "feature/local"
    service.execute(switch.id, {"approved": True})
    assert git(git_repository, "branch", "--show-current").strip() == "feature/local"

    rename = service.plan(
        "rename_branch",
        {"source": "feature/local", "destination": "feature/renamed"},
    )
    service.execute(rename.id, {"approved": True})
    assert git(git_repository, "branch", "--show-current").strip() == "feature/renamed"

    back = service.plan("switch_branch", {"branch": "main"})
    service.execute(back.id, {"approved": True})
    delete = service.plan("delete_branch", {"branch": "feature/renamed"})
    service.execute(delete.id, {"approved": True})
    assert git(git_repository, "branch", "--list", "feature/renamed") == ""


def test_branch_switch_plan_binds_destination_oid(git_repository: Path) -> None:
    git(git_repository, "branch", "feature")
    service = GitOperationService(git_repository)
    plan = service.plan("switch_branch", {"branch": "feature"})
    tree = git(git_repository, "rev-parse", "HEAD^{tree}").strip()
    replacement = git(
        git_repository,
        "commit-tree",
        tree,
        "-p",
        plan.refs["refs/heads/feature"],
        "-m",
        "Move destination",
    ).strip()
    git(git_repository, "branch", "-f", "feature", replacement)

    with pytest.raises(CodePreflightError) as error:
        service.execute(plan.id, {"approved": True})

    assert error.value.code == "repository_state_changed"
    assert git(git_repository, "branch", "--show-current").strip() == "main"


def test_branch_creation_plan_expires_when_destination_appears(
    git_repository: Path,
) -> None:
    service = GitOperationService(git_repository)
    plan = service.plan("create_branch", {"branch": "feature"})
    git(git_repository, "branch", "feature")

    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"


def test_branch_rename_plan_expires_when_destination_appears(
    git_repository: Path,
) -> None:
    git(git_repository, "branch", "source")
    service = GitOperationService(git_repository)
    plan = service.plan(
        "rename_branch",
        {"source": "source", "destination": "destination"},
    )
    git(git_repository, "branch", "destination")

    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"


def test_switch_rejects_untracked_collision(git_repository: Path) -> None:
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "collision.txt").write_text("branch\n", encoding="utf-8")
    git(git_repository, "add", "collision.txt")
    git(git_repository, "commit", "-m", "Add collision")
    git(git_repository, "switch", "main")
    (git_repository / "collision.txt").write_text("local\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        GitOperationService(git_repository).plan("switch_branch", {"branch": "feature"})

    assert error.value.code == "branch_switch_unsafe"
    assert error.value.details == {
        "collisions": ["collision.txt"],
        "preservedPaths": [],
    }


def test_safe_delete_rejects_current_and_unmerged_branches(
    git_repository: Path,
) -> None:
    service = GitOperationService(git_repository)
    with pytest.raises(CodePreflightError) as current:
        service.plan("delete_branch", {"branch": "main"})
    assert current.value.code == "cannot_delete_current_branch"

    git(git_repository, "switch", "-c", "unmerged")
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Unmerged feature")
    git(git_repository, "switch", "main")

    with pytest.raises(CodePreflightError) as unmerged:
        service.plan("delete_branch", {"branch": "unmerged"})
    assert unmerged.value.code == "branch_not_merged"
    assert git(git_repository, "branch", "--list", "unmerged").strip()


def test_stash_selected_paths_preserves_unselected_changes_and_is_inspectable(
    git_repository: Path,
) -> None:
    first = git_repository / "first.txt"
    second = git_repository / "second.txt"
    first.write_text("base first\n", encoding="utf-8")
    second.write_text("base second\n", encoding="utf-8")
    git(git_repository, "add", "first.txt", "second.txt")
    git(git_repository, "commit", "-m", "Add stash fixtures")
    first.write_text("changed first\n", encoding="utf-8")
    second.write_text("changed second\n", encoding="utf-8")
    (git_repository / "third.txt").write_text("untracked third\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan(
        "stash_create",
        {
            "paths": ["first.txt", "third.txt"],
            "message": "Selected work",
        },
    )

    service.execute(plan.id, {"approved": True})

    assert first.read_text(encoding="utf-8") == "base first\n"
    assert second.read_text(encoding="utf-8") == "changed second\n"
    assert not (git_repository / "third.txt").exists()
    stashes = service.stashes()
    assert len(stashes["items"]) == 1
    assert "Selected work" in stashes["items"][0]["subject"]
    shown = service.stashes("stash@{0}")
    assert "changed first" in shown["diff"]
    assert "untracked third" in shown["diff"]


def test_stash_apply_pop_and_drop_follow_explicit_lifecycle(
    git_repository: Path,
) -> None:
    source = git_repository / "README.md"
    source.write_text("stashed\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    create = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(create.id, {"approved": True})

    apply = service.plan("stash_apply", {"stash": "stash@{0}"})
    service.execute(apply.id, {"approved": True})
    assert source.read_text(encoding="utf-8") == "stashed\n"
    assert len(service.stashes()["items"]) == 1

    git(git_repository, "restore", "README.md")
    pop = service.plan("stash_pop", {"stash": "stash@{0}"})
    service.execute(pop.id, {"approved": True})
    assert source.read_text(encoding="utf-8") == "stashed\n"
    assert service.stashes()["items"] == []

    git(git_repository, "restore", "README.md")
    source.write_text("stash again\n", encoding="utf-8")
    create_again = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(create_again.id, {"approved": True})
    drop = service.plan("stash_drop", {"stash": "stash@{0}"})
    with pytest.raises(CodePreflightError) as confirmation:
        service.execute(drop.id, {"approved": True})
    assert confirmation.value.code == "git_typed_confirmation_required"
    service.execute(drop.id, {"approved": True, "confirmation": "DROP"})
    assert service.stashes()["items"] == []


def test_stash_apply_with_index_restores_staged_state(git_repository: Path) -> None:
    source = git_repository / "README.md"
    source.write_text("staged stash\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    service = GitOperationService(git_repository)
    create = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(create.id, {"approved": True})

    apply = service.plan("stash_apply", {"stash": "stash@{0}", "reinstateIndex": True})
    service.execute(apply.id, {"approved": True})

    assert git(git_repository, "diff", "--cached", "--name-only").strip() == "README.md"


def test_stash_plan_is_stale_when_reference_moves(git_repository: Path) -> None:
    source = git_repository / "README.md"
    source.write_text("first stash\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    first = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(first.id, {"approved": True})
    apply = service.plan("stash_apply", {"stash": "stash@{0}"})

    source.write_text("second stash\n", encoding="utf-8")
    second = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(second.id, {"approved": True})

    with pytest.raises(CodePreflightError) as stale:
        service.execute(apply.id, {"approved": True})
    assert stale.value.code == "repository_state_changed"


def test_conflicting_stash_apply_reports_conflicted_state(
    git_repository: Path,
) -> None:
    source = git_repository / "README.md"
    source.write_text("stashed version\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    create = service.plan("stash_create", {"paths": ["README.md"]})
    service.execute(create.id, {"approved": True})
    source.write_text("committed version\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    git(git_repository, "commit", "-m", "Conflicting change")

    apply = service.plan("stash_apply", {"stash": "stash@{0}"})
    result = service.execute(apply.id, {"approved": True})

    assert result.status == "conflicted"
    assert result.conflict is not None
    assert result.conflict.files == ["README.md"]
    assert len(service.stashes()["items"]) == 1
