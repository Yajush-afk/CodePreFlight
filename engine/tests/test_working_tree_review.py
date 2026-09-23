from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator
from codepreflight_engine.working_tree import WorkingTreeContextBuilder, WorkingTreeSnapshot


def test_working_snapshot_includes_staged_unstaged_untracked_and_deletions(
    git_repository: Path,
) -> None:
    staged = git_repository / "staged.py"
    modified = git_repository / "modified.py"
    deleted = git_repository / "deleted.py"
    for path in (staged, modified, deleted):
        path.write_text("old\n", encoding="utf-8")
    git(git_repository, "add", "staged.py", "modified.py", "deleted.py")
    git(git_repository, "commit", "-m", "Add working fixtures")
    staged.write_text("staged\n", encoding="utf-8")
    git(git_repository, "add", "staged.py")
    modified.write_text("unstaged\n", encoding="utf-8")
    deleted.unlink()
    (git_repository / "new.py").write_text("untracked\n", encoding="utf-8")
    index_before = git(git_repository, "diff", "--cached", "--binary")

    snapshot = WorkingTreeSnapshot.capture(git_repository)
    package = WorkingTreeContextBuilder().build(
        snapshot,
        {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
    )

    assert snapshot.staged_paths == ["staged.py"]
    assert snapshot.unstaged_paths == ["deleted.py", "modified.py"]
    assert snapshot.untracked_paths == ["new.py"]
    assert package.target == "working"
    assert "## Staged changes" in package.content
    assert "## Unstaged changes" in package.content
    assert "## Untracked files" in package.content
    assert set(package.changed_files) == {"staged.py", "modified.py", "deleted.py", "new.py"}
    assert git(git_repository, "diff", "--cached", "--binary") == index_before


def test_working_snapshot_fingerprint_changes_with_untracked_content(
    git_repository: Path,
) -> None:
    source = git_repository / "new.py"
    source.write_text("first\n", encoding="utf-8")
    first = WorkingTreeSnapshot.capture(git_repository)

    source.write_text("second\n", encoding="utf-8")
    second = WorkingTreeSnapshot.capture(git_repository)

    assert first.fingerprint != second.fingerprint


def test_working_context_excludes_binary_and_oversized_files_and_redacts_secrets(
    git_repository: Path,
) -> None:
    (git_repository / "binary.data").write_bytes(b"text\0binary")
    (git_repository / "large.txt").write_text("x" * 500_001, encoding="utf-8")
    (git_repository / "auth.py").write_text(
        'api_key = "abcdefghijklmnopqrstuv"\n', encoding="utf-8"
    )

    snapshot = WorkingTreeSnapshot.capture(git_repository)
    package = WorkingTreeContextBuilder().build(snapshot, {"ignore": [], "checks": []})
    entries = {entry.path: entry for entry in package.manifest.entries}

    assert entries["binary.data"].status == "excluded"
    assert entries["binary.data"].reason == "binary content"
    assert entries["large.txt"].status == "excluded"
    assert "exceeds" in entries["large.txt"].reason
    assert "abcdefghijklmnopqrstuv" not in package.content
    assert package.manifest.redactions == 1


def test_working_review_rejects_result_when_snapshot_changes(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = git_repository / "feature.py"
    source.write_text("first\n", encoding="utf-8")

    class Adapter:
        descriptor = ProviderDescriptor(
            id="ollama",
            name="Ollama",
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        )

        def review(self, prompt: str, schema: dict[str, object]) -> str:
            source.write_text("changed during review\n", encoding="utf-8")
            return json.dumps({"summary": "Done", "findings": []})

    monkeypatch.setattr(
        "codepreflight_engine.review.ProviderRegistry",
        lambda config: type("Registry", (), {"adapter": lambda self, provider: Adapter()})(),
    )

    with pytest.raises(CodePreflightError) as error:
        ReviewOrchestrator().review(
            git_repository,
            {"target": "working", "provider": "ollama"},
            lambda event, payload: None,
        )

    assert error.value.code == "review_snapshot_changed"
