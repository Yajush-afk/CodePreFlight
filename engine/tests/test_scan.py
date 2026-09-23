import json
import time
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest
from conftest import git

from codepreflight_engine.adapters.fake import FakeProviderAdapter
from codepreflight_engine.config import load_config
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.readiness import ProviderHealth
from codepreflight_engine.scan import FullScanOrchestrator, ScanExecutor, ScanPlanner


def test_long_source_lines_are_excluded_with_manifest_reason(git_repository: Path) -> None:
    (git_repository / "long.py").write_text("a" * 1000)
    git(git_repository, "add", "long.py")
    inventory = ScanPlanner()._inventory(git_repository, {}, 120)
    assert "long.py" not in inventory["selected"]
    assert any(
        item["path"] == "long.py" and "batch budget" in item["reason"]
        for item in inventory["files"]
    )


def test_lockfiles_are_excluded_and_source_is_grouped_with_its_tests(
    git_repository: Path,
) -> None:
    for directory in ("engine/src/codepreflight_engine", "engine/tests"):
        (git_repository / directory).mkdir(parents=True)
    files = {
        "engine/src/codepreflight_engine/alpha.py": "def alpha():\n    return True\n",
        "engine/tests/test_alpha.py": "def test_alpha():\n    assert True\n",
        "engine/src/codepreflight_engine/zeta.py": "def zeta():\n    return False\n",
        "engine/tests/test_zeta.py": "def test_zeta():\n    assert True\n",
        "engine/uv.lock": "[[package]]\nname = 'demo'\n" * 300,
    }
    for relative, content in files.items():
        (git_repository / relative).write_text(content, encoding="utf-8")
    git(git_repository, "add", ".")
    planner = ScanPlanner()
    inventory = planner._inventory(git_repository, {}, 120)
    assert "engine/uv.lock" not in inventory["selected"]
    assert any(
        item["path"] == "engine/uv.lock" and "lockfile" in item["reason"]
        for item in inventory["files"]
    )
    batches = planner._batches(inventory["selected"], 120)
    combined = "\n".join(batches)
    assert combined.index("alpha.py") < combined.index("test_alpha.py") < combined.index("zeta.py")


def test_verified_scan_uses_one_provider_call_per_uncached_batch(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "one batch", "findings": []}))
    install_adapter(monkeypatch, adapter, git_repository)
    preview = ScanPlanner().plan(git_repository, {"provider": "fake"})
    result = ScanExecutor().execute(
        git_repository,
        {"provider": "fake"},
        preview["fingerprint"],
        approved=True,
        emit=lambda *args: None,
    )
    assert len(adapter.requests) == result["manifest"]["batches"]
    assert result["manifest"]["providerRequests"] == result["manifest"]["batches"]
    assert "Full repository scan" in result["summary"]


def test_scan_limits_parallel_requests_and_reports_both_active_batches(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / ".codepreflight.toml").write_text(
        "[scan]\nmax_parallel_requests = 2\n", encoding="utf-8"
    )
    for index in range(8):
        (git_repository / f"module_{index}.py").write_text(
            f"def module_{index}():\n    return '{'a' * 35}'\n", encoding="utf-8"
        )
    git(git_repository, "add", ".")
    git(git_repository, "commit", "-m", "Add parallel scan fixture")
    synchronized_repository(git_repository, tmp_path)
    lock = Lock()
    active = maximum = 0

    def respond(prompt: str, schema: dict[str, object]) -> str:
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return json.dumps({"summary": "batch checked", "findings": []})

    adapter = FakeProviderAdapter(respond)
    install_adapter(monkeypatch, adapter, git_repository)
    preview = ScanPlanner().plan(git_repository, {"provider": "fake", "batchCharacters": 120})
    assert preview["parallel"] == 2
    assert len(preview["batches"]) > 1
    events: list[tuple[str, dict[str, object]]] = []
    result = ScanExecutor().execute(
        git_repository,
        {"provider": "fake", "batchCharacters": 120},
        preview["fingerprint"],
        approved=True,
        emit=lambda event, payload: events.append((event, payload)),
    )
    assert maximum == 2
    assert result["manifest"]["parallelRequests"] == 2
    assert len(adapter.requests) == result["manifest"]["batches"]
    assert any(
        len(payload.get("activeBatches", [])) == 2
        for event, payload in events
        if event == "scan_progress"
    )


def test_rate_limit_downgrades_remaining_scan_work_to_one_request(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / ".codepreflight.toml").write_text(
        "[scan]\nmax_parallel_requests = 2\n", encoding="utf-8"
    )
    for index in range(4):
        (git_repository / f"module_{index}.py").write_text(
            f"def module_{index}():\n    return True\n", encoding="utf-8"
        )
    git(git_repository, "add", ".")
    git(git_repository, "commit", "-m", "Add rate limit fixture")
    synchronized_repository(git_repository, tmp_path)
    first = True

    def respond(prompt: str, schema: dict[str, object]) -> str:
        nonlocal first
        if first:
            first = False
            raise CodePreflightError("provider_rate_limited", "synthetic concurrency limit")
        return json.dumps({"summary": "batch checked", "findings": []})

    adapter = FakeProviderAdapter(respond)
    install_adapter(monkeypatch, adapter, git_repository)
    preview = ScanPlanner().plan(git_repository, {"provider": "fake", "batchCharacters": 120})
    assert len(preview["batches"]) > 1
    result = ScanExecutor().execute(
        git_repository,
        {"provider": "fake", "batchCharacters": 120},
        preview["fingerprint"],
        approved=True,
        emit=lambda *args: None,
    )
    assert result["status"] == "completed"
    assert len(adapter.requests) == len(preview["batches"]) + 1


def test_executor_requires_explicit_approval(git_repository: Path) -> None:
    with pytest.raises(CodePreflightError) as error:
        ScanExecutor().execute(
            git_repository, {}, "anything", approved=False, emit=lambda *args: None
        )
    assert error.value.code == "full_scan_confirmation_required"


def test_dirty_after_preview_is_stale_and_checks_cannot_change_approved_content(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "ok", "findings": []}))
    install_adapter(monkeypatch, adapter, git_repository)
    preview = FullScanOrchestrator().scan(
        git_repository, {"action": "plan", "provider": "fake"}, lambda *args: None
    )
    payload = {
        "provider": "fake",
        "fullScanApproved": True,
        "planFingerprint": preview["planFingerprint"],
    }
    dirty = git_repository / "dirty.py"
    dirty.write_text("value = 1\n")
    with pytest.raises(CodePreflightError) as error:
        FullScanOrchestrator().scan(git_repository, payload, lambda *args: None)
    assert error.value.code == "scan_plan_stale"
    dirty.unlink()

    def modifying_check(*args: object) -> list[object]:
        dirty.write_text("value = 2\n")
        return []

    monkeypatch.setattr("codepreflight_engine.scan.CheckRunner.run", modifying_check)
    with pytest.raises(CodePreflightError) as error:
        FullScanOrchestrator().scan(git_repository, payload, lambda *args: None)
    assert error.value.code == "scan_plan_stale"
    assert adapter.requests == []


def synchronized_repository(git_repository: Path, tmp_path: Path) -> Path:
    remote = git_repository.parent / f"{git_repository.name}-remote.git"
    git(git_repository.parent, "init", "--bare", str(remote))
    git(git_repository, "remote", "add", "origin", str(remote))
    git(git_repository, "push", "-u", "origin", "main")
    return git_repository


def install_adapter(
    monkeypatch: pytest.MonkeyPatch, adapter: FakeProviderAdapter, root: Path
) -> None:
    monkeypatch.setattr(
        "codepreflight_engine.scan.ProviderRegistry",
        lambda config: SimpleNamespace(adapter=lambda provider_id: adapter),
    )
    ProviderHealth(root).record(adapter.descriptor, load_config(root))


def test_full_scan_rejects_dirty_or_unsynchronized_repository(
    git_repository: Path, tmp_path: Path
) -> None:
    synchronized_repository(git_repository, tmp_path)
    (git_repository / "dirty.py").write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        FullScanOrchestrator().scan(git_repository, {}, lambda event, payload: None)

    assert error.value.code == "scan_blocked"
    assert any(
        item["code"] == "full_scan_worktree_dirty" for item in error.value.details["blockers"]
    )
    assert error.value.recoverable is True


def test_full_scan_shows_manifest_before_dedicated_confirmation(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "ok", "findings": []}))
    install_adapter(monkeypatch, adapter, git_repository)
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
    install_adapter(monkeypatch, adapter, git_repository)
    preview = FullScanOrchestrator().scan(
        git_repository,
        {"provider": "fake", "action": "plan", "batchCharacters": 120},
        lambda *args: None,
    )
    events: list[tuple[str, dict[str, object]]] = []

    first = FullScanOrchestrator().scan(
        git_repository,
        {
            "provider": "fake",
            "fullScanApproved": True,
            "batchCharacters": 120,
            "planFingerprint": preview["planFingerprint"],
        },
        lambda event, payload: events.append((event, payload)),
    )
    calls = len(adapter.requests)
    second = FullScanOrchestrator().scan(
        git_repository,
        {
            "provider": "fake",
            "fullScanApproved": True,
            "batchCharacters": 120,
            "planFingerprint": preview["planFingerprint"],
        },
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
    review_events = [
        payload
        for event, payload in events
        if event == "scan_progress" and payload.get("stage") == "review"
    ]
    assert review_events[0]["status"] == "started"
    assert review_events[0]["sources"]
    assert review_events[-1]["completedBatches"] == first["manifest"]["batches"]
    assert second["cacheHit"] is True
    assert len(adapter.requests) == calls

    with pytest.raises(CodePreflightError, match="approve") as error:
        FullScanOrchestrator().scan(
            git_repository, {"provider": "fake", "batchCharacters": 120}, lambda *args: None
        )
    assert error.value.code == "full_scan_confirmation_required"


def test_planning_runs_no_checks_and_execution_runs_once(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "ok", "findings": []}))
    install_adapter(monkeypatch, adapter, git_repository)
    calls = []
    monkeypatch.setattr(
        "codepreflight_engine.scan.CheckRunner.run", lambda *args: calls.append(True) or []
    )
    scanner = FullScanOrchestrator()
    preview = scanner.scan(
        git_repository, {"action": "plan", "provider": "fake"}, lambda *args: None
    )
    assert calls == []
    assert adapter.requests == []
    scanner.scan(
        git_repository,
        {
            "provider": "fake",
            "fullScanApproved": True,
            "planFingerprint": preview["planFingerprint"],
        },
        lambda *args: None,
    )
    assert calls == [True]


def test_stale_approval_does_not_execute(
    git_repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized_repository(git_repository, tmp_path)
    adapter = FakeProviderAdapter(json.dumps({"summary": "ok", "findings": []}))
    install_adapter(monkeypatch, adapter, git_repository)
    scanner = FullScanOrchestrator()
    preview = scanner.scan(
        git_repository, {"action": "plan", "provider": "fake"}, lambda *args: None
    )
    calls = []
    monkeypatch.setattr(
        "codepreflight_engine.scan.CheckRunner.run", lambda *args: calls.append(True) or []
    )
    with pytest.raises(CodePreflightError) as error:
        scanner.scan(
            git_repository,
            {
                "provider": "fake",
                "fullScanApproved": True,
                "planFingerprint": preview["planFingerprint"],
                "batchCharacters": 100,
            },
            lambda *args: None,
        )
    assert error.value.code == "scan_plan_stale"
    assert calls == []
    assert adapter.requests == []
