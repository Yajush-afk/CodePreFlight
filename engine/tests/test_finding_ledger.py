from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.finding_ledger import FindingLedger
from codepreflight_engine.models import (
    ContextEntry,
    ContextManifest,
    ContextPackage,
    Finding,
    FindingReconciliation,
    ProviderDescriptor,
    ProviderKind,
)


def provider() -> ProviderDescriptor:
    return ProviderDescriptor(
        id="fake",
        name="Fake",
        kind=ProviderKind.LOCAL,
        sends_code_remotely=False,
        model_name="review-model",
    )


def finding(
    path: str,
    line: int,
    *,
    title: str = "Incorrect result",
    explanation: str = "The calculation returns the wrong value.",
    symbol: str | None = "calculate",
) -> Finding:
    return Finding.model_validate(
        {
            "id": "temporary-provider-id",
            "severity": "high",
            "category": "bug",
            "title": title,
            "explanation": explanation,
            "impact": "Callers receive an invalid result.",
            "confidence": "high",
            "evidence": [
                {
                    "path": path,
                    "start_line": line,
                    "end_line": line,
                    "symbol": symbol,
                }
            ],
            "recommendation": "Correct the calculation.",
            "suggested_tests": ["Exercise the failing input."],
            "verification": "verified",
        }
    )


def context(
    path: str,
    *,
    status: Literal["included", "excluded", "redacted", "truncated"] = "included",
) -> ContextPackage:
    return ContextPackage(
        content=f"## {path}\nselected repository context",
        manifest=ContextManifest(
            entries=[
                ContextEntry(
                    path=path,
                    reason="changed file",
                    included_characters=24,
                    status=status,
                )
            ],
            total_characters=24,
            limit_characters=10_000,
            redactions=0,
        ),
        changed_files=[path],
        checks=[],
    )


def record(
    ledger: FindingLedger,
    item: Finding,
    package: ContextPackage,
    snapshot: str,
    *,
    branch: str = "main",
    reconciliations: list[FindingReconciliation] | None = None,
) -> Finding:
    recorded = ledger.record_review(
        branch=branch,
        snapshot=snapshot,
        commit=ledger.current_commit(),
        target="working",
        provider=provider(),
        findings=[item],
        reconciliations=reconciliations or [],
        context=package,
    )
    return recorded[0]


def reconcile(
    ledger: FindingLedger,
    finding_id: str,
    package: ContextPackage,
    snapshot: str,
    outcome: Literal["present", "resolved", "uncertain"],
) -> None:
    evidence = []
    if outcome == "resolved":
        evidence = [
            {
                "path": package.changed_files[0],
                "start_line": 1,
                "end_line": 1,
                "symbol": "calculate",
            }
        ]
    ledger.record_review(
        branch="main",
        snapshot=snapshot,
        commit=ledger.current_commit(),
        target="working",
        provider=provider(),
        findings=[],
        reconciliations=[
            FindingReconciliation.model_validate(
                {
                    "finding_id": finding_id,
                    "outcome": outcome,
                    "explanation": "The prior failure condition was evaluated directly.",
                    "evidence": evidence,
                }
            )
        ],
        context=package,
    )


def test_stable_identity_survives_line_movement_and_rename(
    git_repository: Path,
) -> None:
    original = git_repository / "old.py"
    original.write_text("before\nreturn broken\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)

    first = record(ledger, finding("old.py", 2), context("old.py"), "snapshot-1")
    original.rename(git_repository / "new.py")
    (git_repository / "new.py").write_text("inserted\nbefore\nreturn broken\n", encoding="utf-8")
    second = record(ledger, finding("new.py", 3), context("new.py"), "snapshot-2")

    assert second.id == first.id
    assert ledger.detail(first.id)["finding"]["path"] == "new.py"


def test_distinct_claims_on_the_same_evidence_remain_separate(
    git_repository: Path,
) -> None:
    (git_repository / "feature.py").write_text("return broken\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)

    first = record(
        ledger,
        finding("feature.py", 1, explanation="The result is incorrect."),
        context("feature.py"),
        "snapshot-1",
    )
    second = record(
        ledger,
        finding("feature.py", 1, explanation="The result leaks private state."),
        context("feature.py"),
        "snapshot-2",
    )

    assert second.id != first.id
    assert len(ledger.list(branch="main")) == 2


def test_findings_are_branch_scoped(git_repository: Path) -> None:
    (git_repository / "feature.py").write_text("return broken\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)
    item = finding("feature.py", 1)
    package = context("feature.py")

    main = record(ledger, item, package, "main-snapshot")
    feature = record(ledger, item, package, "feature-snapshot", branch="feature/ledger")

    assert main.id != feature.id
    assert [row["id"] for row in ledger.list(branch="main")] == [main.id]
    assert [row["id"] for row in ledger.list(branch="feature/ledger")] == [feature.id]


def test_relevant_commit_requires_rereview_and_omission_does_not_resolve(
    git_repository: Path,
) -> None:
    (git_repository / "feature.py").write_text("return fixed\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)
    recorded = record(ledger, finding("feature.py", 1), context("feature.py"), "snapshot-1")

    changed = ledger.mark_paths_changed("main", ["feature.py"], ledger.current_commit())
    ledger.record_review(
        branch="main",
        snapshot="snapshot-2",
        commit=ledger.current_commit(),
        target="working",
        provider=provider(),
        findings=[],
        reconciliations=[],
        context=context("feature.py"),
    )

    assert changed == 1
    assert ledger.detail(recorded.id)["finding"]["lifecycle"] == "needs_rereview"


def test_listing_detects_a_new_commit_that_changed_finding_evidence(
    git_repository: Path,
) -> None:
    source = git_repository / "feature.py"
    source.write_text("return broken\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Add broken feature")
    ledger = FindingLedger(git_repository)
    recorded = record(ledger, finding("feature.py", 1), context("feature.py"), "snapshot-1")
    source.write_text("return maybe_fixed\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    git(git_repository, "commit", "-m", "Change finding evidence")

    items = ledger.list(branch="main")

    assert items[0]["id"] == recorded.id
    assert items[0]["lifecycle"] == "needs_rereview"


def test_resolution_requires_explicit_evaluation_and_complete_evidence(
    git_repository: Path,
) -> None:
    (git_repository / "feature.py").write_text("return fixed\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)
    recorded = record(ledger, finding("feature.py", 1), context("feature.py"), "snapshot-1")
    ledger.mark_paths_changed("main", ["feature.py"], ledger.current_commit())

    reconcile(
        ledger,
        recorded.id,
        context("feature.py", status="truncated"),
        "snapshot-2",
        "resolved",
    )
    assert ledger.detail(recorded.id)["finding"]["lifecycle"] == "needs_rereview"

    reconcile(ledger, recorded.id, context("feature.py"), "snapshot-3", "resolved")
    detail = ledger.detail(recorded.id)
    assert detail["finding"]["lifecycle"] == "resolved"
    assert detail["transitions"][0]["to_state"] == "resolved"


def test_dismissal_requires_strict_approval_and_survives_recurrence(
    git_repository: Path,
) -> None:
    (git_repository / "feature.py").write_text("return broken\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)
    item = finding("feature.py", 1)
    recorded = record(ledger, item, context("feature.py"), "snapshot-1")

    with pytest.raises(CodePreflightError) as error:
        ledger.run(
            {
                "action": "dismiss",
                "findingId": recorded.id,
                "reason": "Accepted risk",
                "approved": "false",
            }
        )
    assert error.value.code == "invalid_request_flag"

    with pytest.raises(CodePreflightError) as missing:
        ledger.run(
            {
                "action": "dismiss",
                "findingId": recorded.id,
                "reason": "Accepted risk",
                "approved": False,
            }
        )
    assert missing.value.code == "finding_action_approval_required"

    ledger.run(
        {
            "action": "dismiss",
            "findingId": recorded.id,
            "reason": "Accepted risk",
            "approved": True,
        }
    )
    repeated = record(ledger, item, context("feature.py"), "snapshot-2")
    assert repeated.lifecycle.value == "dismissed"

    reopened = ledger.run({"action": "reopen", "findingId": recorded.id, "approved": True})
    assert reopened["finding"]["lifecycle"] == "open"


def test_ledger_is_private_to_git_metadata_and_does_not_store_source(
    git_repository: Path,
) -> None:
    marker = "private-source-marker-that-must-not-be-persisted"
    (git_repository / "feature.py").write_text(f"{marker}\n", encoding="utf-8")
    ledger = FindingLedger(git_repository)
    record(ledger, finding("feature.py", 1), context("feature.py"), "snapshot-1")

    git_dir = Path(git(git_repository, "rev-parse", "--absolute-git-dir").strip())
    assert ledger.path.parent == git_dir / "codepreflight"
    assert ledger.path.stat().st_mode & 0o777 == 0o600
    stored = b"".join(
        path.read_bytes()
        for path in ledger.path.parent.iterdir()
        if path.name.startswith("findings.sqlite3")
    )
    assert marker.encode() not in stored


def test_concurrent_reviews_do_not_lose_findings(git_repository: Path) -> None:
    ledger = FindingLedger(git_repository)
    ledger.list(branch="main")
    for index in range(8):
        (git_repository / f"feature-{index}.py").write_text(f"return {index}\n", encoding="utf-8")

    def write(index: int) -> str:
        path = f"feature-{index}.py"
        return record(
            ledger,
            finding(path, 1, title=f"Issue {index}"),
            context(path),
            f"snapshot-{index}",
        ).id

    with ThreadPoolExecutor(max_workers=4) as executor:
        identifiers = list(executor.map(write, range(8)))

    assert len(set(identifiers)) == 8
    assert len(ledger.list(branch="main")) == 8


def test_refuses_a_symlinked_ledger_database(git_repository: Path, tmp_path: Path) -> None:
    ledger = FindingLedger(git_repository)
    ledger.directory.mkdir(parents=True)
    ledger.path.symlink_to(tmp_path / "outside.sqlite3")

    with pytest.raises(CodePreflightError) as error:
        ledger.list(branch="main")

    assert error.value.code == "unsafe_state_path"
