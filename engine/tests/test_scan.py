import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.adapters.fake import FakeProviderAdapter
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.scan import FullScanOrchestrator


def synchronized_repository(git_repository: Path, tmp_path: Path) -> Path:
    remote = git_repository.parent / f"{git_repository.name}-remote.git"
    git(git_repository.parent, "init", "--bare", str(remote))
    git(git_repository, "remote", "add", "origin", str(remote))
    git(git_repository, "push", "-u", "origin", "main")
    return git_repository


def install_adapter(monkeypatch: pytest.MonkeyPatch, adapter: FakeProviderAdapter) -> None:
    monkeypatch.setattr(
        "codepreflight_engine.scan.ProviderRegistry",
        lambda config: SimpleNamespace(adapter=lambda provider_id: adapter),
    )


def test_full_scan_rejects_dirty_or_unsynchronized_repository(
    git_repository: Path, tmp_path: Path
) -> None:
    synchronized_repository(git_repository, tmp_path)
    (git_repository / "dirty.py").write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        FullScanOrchestrator().scan(git_repository, {}, lambda event, payload: None)

    assert error.value.code == "full_scan_worktree_dirty"
    assert error.value.recoverable is True


def test_full_scan_shows_manifest_before_dedicated_confirmation(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "ok", "findings": []}))
    install_adapter(monkeypatch, adapter)
    events: list[tuple[str, dict[str, object]]] = []

    with pytest.raises(CodePreflightError) as error:
        FullScanOrchestrator().scan(
            git_repository,
            {"provider": "fake"},
            lambda event, payload: events.append((event, payload)),
        )

    assert error.value.code == "full_scan_confirmation_required"
    manifest = next(payload for event, payload in events if event == "consent_required")
    assert manifest["fullScan"] is True
    assert manifest["manifest"]["eligibleFiles"] >= 1  # type: ignore[index]
    assert adapter.requests == []


def test_full_scan_batches_filters_caches_and_resumes(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "src").mkdir()
    (git_repository / "src" / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (git_repository / "src" / "two.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    (git_repository / "generated.min.js").write_text("generated", encoding="utf-8")
    (git_repository / "image.png").write_bytes(b"\x89PNG\x00data")
    git(git_repository, "add", ".")
    git(git_repository, "commit", "-m", "Add scan fixtures")
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "No verified issues.", "findings": []}))
    install_adapter(monkeypatch, adapter)

    first = FullScanOrchestrator().scan(
        git_repository,
        {"provider": "fake", "fullScanApproved": True, "batchCharacters": 120},
        lambda event, payload: None,
    )
    calls = len(adapter.requests)
    second = FullScanOrchestrator().scan(
        git_repository,
        {"provider": "fake", "fullScanApproved": True, "batchCharacters": 120},
        lambda event, payload: None,
    )

    excluded = {
        item["path"]: item["reason"]
        for item in first["manifest"]["files"]
        if item["status"] == "excluded"
    }
    assert excluded["generated.min.js"] == "generated file"
    assert excluded["image.png"] == "binary file"
    assert first["manifest"]["providerRequests"] > 1
    assert second["cacheHit"] is True
    assert len(adapter.requests) == calls
