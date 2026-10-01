from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git_operations import GitOperationService


def create_merge_conflict(repository: Path) -> None:
    git(repository, "switch", "-c", "feature")
    (repository / "README.md").write_text("feature\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "Feature edit")
    git(repository, "switch", "main")
    (repository / "README.md").write_text("main\n", encoding="utf-8")
    git(repository, "add", "README.md")
    git(repository, "commit", "-m", "Main edit")
    result = subprocess.run(
        ["git", "merge", "feature"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_conflict_inspection_returns_stage_evidence(git_repository: Path) -> None:
    create_merge_conflict(git_repository)
    service = GitOperationService(git_repository)

    summary = service.conflicts()
    detail = service.conflicts("README.md")

    assert summary["operation"] == "merge"
    assert summary["files"] == ["README.md"]
    assert summary["can_continue"] is False
    assert summary["can_abort"] is True
    assert summary["details"] == []
    evidence = detail["details"][0]
    assert evidence["base"] == "# Fixture\n"
    assert evidence["ours"] == "main\n"
    assert evidence["theirs"] == "feature\n"
    assert "<<<<<<<" in evidence["working"]


def test_conflict_editor_requires_preview_and_returns_terminal_handoff(
    git_repository: Path,
) -> None:
    create_merge_conflict(git_repository)
    git(git_repository, "config", "core.editor", "true")
    service = GitOperationService(git_repository)
    plan = service.plan("launch_editor", {"path": "README.md"})

    assert plan.editor_involvement is True
    assert plan.selected_paths == ["README.md"]
    assert plan.commands[0].startswith('"true" ')
    result = service.execute(plan.id, {"approved": True})

    assert result.requires_terminal_handoff is True
    assert result.handoff_command == ["true", str(git_repository / "README.md")]
    assert "<<<<<<<" in (git_repository / "README.md").read_text(encoding="utf-8")


def test_editor_plan_is_stale_after_conflict_file_changes(git_repository: Path) -> None:
    create_merge_conflict(git_repository)
    git(git_repository, "config", "core.editor", "true")
    service = GitOperationService(git_repository)
    plan = service.plan("launch_editor", {"path": "README.md"})
    (git_repository / "README.md").write_text("manual edit\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"


def test_mergetool_handoff_is_limited_to_selected_conflicts(git_repository: Path) -> None:
    create_merge_conflict(git_repository)
    git(git_repository, "config", "merge.tool", "vimdiff")
    service = GitOperationService(git_repository)
    plan = service.plan("launch_mergetool", {"paths": ["README.md"]})
    result = service.execute(plan.id, {"approved": True})

    assert plan.selected_paths == ["README.md"]
    assert result.handoff_command == [
        "git",
        "mergetool",
        "--no-prompt",
        "--",
        "README.md",
    ]


def test_continue_requires_all_conflicts_resolved_and_staged(
    git_repository: Path,
) -> None:
    create_merge_conflict(git_repository)
    service = GitOperationService(git_repository)
    with pytest.raises(CodePreflightError) as unresolved:
        service.plan("continue_operation", {})
    assert unresolved.value.code == "conflicts_unresolved"

    (git_repository / "README.md").write_text("resolved\n", encoding="utf-8")
    git(git_repository, "add", "README.md")
    plan = service.plan("continue_operation", {})
    result = service.execute(plan.id, {"approved": True})

    assert result.status == "completed"
    assert service.conflicts()["operation"] is None
    assert git(git_repository, "show", "HEAD:README.md") == "resolved\n"


def test_abort_requires_preview_and_restores_pre_operation_state(
    git_repository: Path,
) -> None:
    create_merge_conflict(git_repository)
    before_abort = git(git_repository, "rev-parse", "HEAD").strip()
    service = GitOperationService(git_repository)
    plan = service.plan("abort_operation", {})
    result = service.execute(plan.id, {"approved": True})

    assert result.status == "completed"
    assert git(git_repository, "rev-parse", "HEAD").strip() == before_abort
    assert (git_repository / "README.md").read_text(encoding="utf-8") == "main\n"
    assert service.conflicts()["files"] == []


def test_operation_marker_change_invalidates_recovery_plan(git_repository: Path) -> None:
    create_merge_conflict(git_repository)
    service = GitOperationService(git_repository)
    plan = service.plan("abort_operation", {})
    git_dir = Path(git(git_repository, "rev-parse", "--absolute-git-dir").strip())
    original = (git_dir / "MERGE_HEAD").read_text(encoding="utf-8")
    (git_dir / "MERGE_HEAD").write_text(original + "\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"


def test_conflict_evidence_is_bounded(git_repository: Path) -> None:
    original = "x" * 210_000 + "\n"
    (git_repository / "large.txt").write_text(original, encoding="utf-8")
    git(git_repository, "add", "large.txt")
    git(git_repository, "commit", "-m", "Large base")
    git(git_repository, "switch", "-c", "feature")
    (git_repository / "large.txt").write_text("feature\n" + original, encoding="utf-8")
    git(git_repository, "add", "large.txt")
    git(git_repository, "commit", "-m", "Large feature")
    git(git_repository, "switch", "main")
    (git_repository / "large.txt").write_text("main\n" + original, encoding="utf-8")
    git(git_repository, "add", "large.txt")
    git(git_repository, "commit", "-m", "Large main")
    result = subprocess.run(
        ["git", "merge", "feature"],
        cwd=git_repository,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0

    evidence = GitOperationService(git_repository).conflicts("large.txt")["details"][0]

    assert evidence["truncated"] is True
    assert evidence["base"] is None
    assert evidence["ours"] is None
    assert evidence["theirs"] is None
    assert len(evidence["working"]) == 200_000
