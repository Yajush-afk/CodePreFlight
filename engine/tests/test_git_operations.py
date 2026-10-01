from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git_operations import GitOperationService


def test_stage_plan_is_read_only_and_execution_revalidates_state(
    git_repository: Path,
) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = 1\n", encoding="utf-8")
    service = GitOperationService(git_repository)

    plan = service.plan("stage_files", {"paths": ["feature.py"]})

    assert plan.action == "stage_files"
    assert plan.risk.value == "low"
    assert plan.preview is not None
    assert "feature.py" in plan.preview
    assert git(git_repository, "diff", "--cached", "--name-only") == ""
    assert service._plan_path(plan.id).stat().st_mode & 0o777 == 0o600  # noqa: SLF001

    source.write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})

    assert stale.value.code == "repository_state_changed"
    assert git(git_repository, "diff", "--cached", "--name-only") == ""


def test_stage_and_unstage_files_support_unusual_names_and_deletions(
    git_repository: Path,
) -> None:
    unusual = "odd\nname.txt"
    (git_repository / unusual).write_text("new\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    stage = service.plan("stage_files", {"paths": [unusual]})

    assert "\\n" in stage.commands[0]
    service.execute(stage.id, {"approved": True})
    assert unusual in git(git_repository, "diff", "--cached", "--name-only", "-z").split("\0")

    unstage = service.plan("unstage_files", {"paths": [unusual]})
    service.execute(unstage.id, {"approved": True})
    assert git(git_repository, "diff", "--cached", "--name-only") == ""

    tracked = git_repository / "README.md"
    tracked.unlink()
    deletion = service.plan("stage_files", {"paths": ["README.md"]})
    service.execute(deletion.id, {"approved": True})
    assert git(git_repository, "diff", "--cached", "--name-status").startswith("D")


def test_stage_file_supports_binary_content(git_repository: Path) -> None:
    (git_repository / "image.bin").write_bytes(b"\x00\x01\x02")
    service = GitOperationService(git_repository)

    plan = service.plan("stage_files", {"paths": ["image.bin"]})
    service.execute(plan.id, {"approved": True})

    assert git(git_repository, "diff", "--cached", "--name-only").strip() == "image.bin"


def test_stage_files_preserve_a_selected_rename(
    git_repository: Path,
) -> None:
    original = git_repository / "old-name.txt"
    original.write_text("rename me\n", encoding="utf-8")
    git(git_repository, "add", "old-name.txt")
    git(git_repository, "commit", "-m", "Add rename fixture")
    original.rename(git_repository / "new-name.txt")
    service = GitOperationService(git_repository)

    plan = service.plan("stage_files", {"paths": ["old-name.txt", "new-name.txt"]})
    service.execute(plan.id, {"approved": True})

    assert git(git_repository, "diff", "--cached", "--name-status", "-M").startswith("R100")


def test_discard_requires_typed_confirmation_and_preserves_staged_version(
    git_repository: Path,
) -> None:
    source = git_repository / "feature.py"
    source.write_text("base\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add feature")
    source.write_text("staged\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    source.write_text("working\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan("discard_worktree", {"paths": ["feature.py"]})

    assert plan.risk.value == "irreversible"
    assert "working" in (plan.preview or "")
    with pytest.raises(CodePreflightError) as approval:
        service.execute(plan.id, {"approved": "false"})
    assert approval.value.code == "invalid_request_flag"
    with pytest.raises(CodePreflightError) as confirmation:
        service.execute(plan.id, {"approved": True})
    assert confirmation.value.code == "git_typed_confirmation_required"

    service.execute(plan.id, {"approved": True, "confirmation": "DISCARD"})

    assert source.read_text(encoding="utf-8") == "staged\n"
    assert git(git_repository, "show", ":feature.py") == "staged\n"


def test_discard_refuses_untracked_paths(git_repository: Path) -> None:
    (git_repository / "untracked.txt").write_text("keep\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        GitOperationService(git_repository).plan("discard_worktree", {"paths": ["untracked.txt"]})

    assert error.value.code == "git_action_not_applicable"
    assert (git_repository / "untracked.txt").read_text(encoding="utf-8") == "keep\n"


def test_completed_mutation_reports_bookkeeping_failure_without_hiding_effect(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "README.md"
    source.write_text("changed\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan("discard_worktree", {"paths": ["README.md"]})

    def fail_refresh(*args: object, **kwargs: object) -> int:
        raise CodePreflightError("finding_ledger_error", "Ledger unavailable")

    monkeypatch.setattr(
        "codepreflight_engine.git_operations.FindingLedger.mark_paths_changed",
        fail_refresh,
    )
    result = service.execute(plan.id, {"approved": True, "confirmation": "DISCARD"})

    assert result.status == "completed"
    assert "finding lifecycle refresh failed" in result.message
    assert source.read_text(encoding="utf-8") == "# Fixture\n"


def test_stage_and_unstage_individual_hunks(git_repository: Path) -> None:
    source = git_repository / "feature.py"
    source.write_text("".join(f"line {index}\n" for index in range(1, 25)), encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add hunk fixture")
    lines = source.read_text(encoding="utf-8").splitlines()
    lines[1] = "changed near start"
    lines[21] = "changed near end"
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    hunks = service.hunks("feature.py", "unstaged")

    assert len(hunks["hunks"]) == 2
    first = hunks["hunks"][0]["id"]
    stage = service.plan("stage_hunks", {"path": "feature.py", "hunkIds": [first]})
    service.execute(stage.id, {"approved": True})

    staged = git(git_repository, "diff", "--cached")
    unstaged = git(git_repository, "diff")
    assert "changed near start" in staged
    assert "changed near end" not in staged
    assert "changed near end" in unstaged

    staged_hunks = service.hunks("feature.py", "staged")
    unstage = service.plan(
        "unstage_hunks",
        {"path": "feature.py", "hunkIds": [staged_hunks["hunks"][0]["id"]]},
    )
    service.execute(unstage.id, {"approved": True})
    assert git(git_repository, "diff", "--cached") == ""


def test_hunk_plan_rejects_stale_or_unknown_selection(git_repository: Path) -> None:
    source = git_repository / "README.md"
    source.write_text("# Changed\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    hunks = service.hunks("README.md", "unstaged")

    with pytest.raises(CodePreflightError) as missing:
        service.plan("stage_hunks", {"path": "README.md", "hunkIds": ["missing-hunk"]})
    assert missing.value.code == "hunk_not_found"

    plan = service.plan(
        "stage_hunks",
        {"path": "README.md", "hunkIds": [hunks["hunks"][0]["id"]]},
    )
    source.write_text("# Changed again\n", encoding="utf-8")
    with pytest.raises(CodePreflightError) as stale:
        service.execute(plan.id, {"approved": True})
    assert stale.value.code == "repository_state_changed"


def test_commit_plan_supports_multiline_message(git_repository: Path) -> None:
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    service = GitOperationService(git_repository)
    message = "feat: add feature\n\nExplain the repository behavior in detail."

    plan = service.plan("commit", {"message": message})

    assert message in (plan.preview or "")
    assert git(git_repository, "log", "-1", "--pretty=%s").strip() == "Initial commit"
    result = service.execute(plan.id, {"approved": True})

    assert result.status == "completed"
    assert git(git_repository, "log", "-1", "--pretty=%B").strip() == message
    assert not service._plan_path(plan.id).exists()  # noqa: SLF001


def test_rejects_unsafe_paths_and_unknown_plans(git_repository: Path) -> None:
    service = GitOperationService(git_repository)
    with pytest.raises(CodePreflightError) as path:
        service.plan("stage_files", {"paths": ["../outside"]})
    assert path.value.code == "invalid_git_path"

    with pytest.raises(CodePreflightError) as missing:
        service.execute("a" * 24, {"approved": True})
    assert missing.value.code == "git_plan_not_found"


def test_execute_rejects_a_modified_stored_plan(git_repository: Path) -> None:
    source = git_repository / "README.md"
    source.write_text("changed\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    plan = service.plan("discard_worktree", {"paths": ["README.md"]})
    plan_path = service._plan_path(plan.id)  # noqa: SLF001
    stored = json.loads(plan_path.read_text(encoding="utf-8"))
    stored["plan"]["action"] = "stage_files"
    plan_path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        service.execute(plan.id, {"approved": True})

    assert error.value.code == "invalid_git_plan"
    assert source.read_text(encoding="utf-8") == "changed\n"


def test_concurrent_mutations_serialize_and_reject_the_stale_plan(
    git_repository: Path,
) -> None:
    (git_repository / "first.py").write_text("first\n", encoding="utf-8")
    (git_repository / "second.py").write_text("second\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    first = service.plan("stage_files", {"paths": ["first.py"]})
    second = service.plan("stage_files", {"paths": ["second.py"]})

    def execute(plan_id: str) -> str:
        try:
            return service.execute(plan_id, {"approved": True}).status
        except CodePreflightError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(execute, [first.id, second.id]))

    assert sorted(outcomes) == ["completed", "repository_state_changed"]
    assert service.lock_path.stat().st_mode & 0o777 == 0o600


def test_plan_cleanup_refuses_symlinked_storage(git_repository: Path, tmp_path: Path) -> None:
    (git_repository / "feature.py").write_text("value = 1\n", encoding="utf-8")
    service = GitOperationService(git_repository)
    outside = tmp_path / "outside-plans"
    outside.mkdir()
    marker = outside / "keep.json"
    marker.write_text("{}", encoding="utf-8")
    service.state_dir.mkdir(parents=True, exist_ok=True)
    service.plans_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(CodePreflightError) as error:
        service.plan("stage_files", {"paths": ["feature.py"]})

    assert error.value.code == "unsafe_state_path"
    assert marker.exists()
