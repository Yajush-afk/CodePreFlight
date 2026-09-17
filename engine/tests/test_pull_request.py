import pytest
from conftest import git

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
    git_repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = git(git_repository, "rev-parse", "HEAD").strip()
    (git_repository / "status.py").write_text("value = True\n", encoding="utf-8")
    git(git_repository, "add", "status.py")
    git(git_repository, "commit", "-m", "Add repository status support")
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
                ),
                CheckResult(
                    name="integration",
                    command=["pytest", "tests/integration"],
                    status=CheckStatus.RECOMMENDED,
                    duration_ms=0,
                ),
                CheckResult(
                    name="browser",
                    command=["npm", "run", "test:e2e"],
                    status=CheckStatus.SKIPPED,
                    duration_ms=0,
                ),
            ],
            target="pull_request",
            base_revision=base,
        ),
        blocking=False,
        fingerprint="fingerprint",
    )
    monkeypatch.setattr(
        "codepreflight_engine.pull_request.ReviewOrchestrator.review",
        lambda self, root, payload, emit: review,
    )

    draft = prepare_pull_request(git_repository, {}, lambda event, payload: None)

    assert draft.title == "Add repository status support"
    assert "tests: **passed**" in draft.description
    assert "No automated checks were run" not in draft.description
    assert "integration: **recommended**" not in draft.description
    assert "pytest tests/integration" in draft.description
    assert "browser" in draft.description
    assert "Add repository status support" in draft.description
