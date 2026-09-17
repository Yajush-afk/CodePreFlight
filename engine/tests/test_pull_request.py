from pathlib import Path

import pytest

from codepreflight_engine.models import (
    CheckResult,
    CheckStatus,
    ContextManifest,
    ContextPackage,
    ProviderDescriptor,
    ProviderKind,
    ProviderState,
    ReviewResult,
)
from codepreflight_engine.pull_request import prepare_pull_request


def test_pr_draft_reports_checks_that_actually_ran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = ReviewResult(
        provider=ProviderDescriptor(
            id="fake",
            name="Fake",
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        ),
        summary="Add repository status support.",
        findings=[],
        rejected_findings=0,
        context=ContextPackage(
            content="context",
            manifest=ContextManifest(
                entries=[], total_characters=7, limit_characters=100, redactions=0
            ),
            changed_files=["status.py"],
            checks=[
                CheckResult(
                    name="tests",
                    command=["pytest"],
                    status=CheckStatus.PASSED,
                    exit_code=0,
                    duration_ms=10,
                )
            ],
            target="pull_request",
            base_revision="abc",
        ),
        blocking=False,
        fingerprint="fingerprint",
    )
    monkeypatch.setattr(
        "codepreflight_engine.pull_request.ReviewOrchestrator.review",
        lambda self, root, payload, emit: review,
    )

    draft = prepare_pull_request(tmp_path, {}, lambda event, payload: None)

    assert draft.title == "Add repository status support"
    assert "tests: **passed**" in draft.description
    assert "No automated checks were run" not in draft.description
