from pathlib import Path

import pytest

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import (
    Confidence,
    ContextManifest,
    ContextPackage,
    EvidenceLocation,
    Finding,
    PanelProviderResult,
    ProviderDescriptor,
    ProviderKind,
    ProviderState,
    ReviewResult,
    Severity,
    VerificationState,
)
from codepreflight_engine.panel import PanelReviewer


def review(provider: str, severity: Severity, title: str) -> ReviewResult:
    return ReviewResult(
        provider=ProviderDescriptor(
            id=provider,
            name=provider,
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        ),
        summary="Review complete.",
        findings=[
            Finding(
                id=f"{provider}-1",
                severity=severity,
                title=title,
                explanation="The return value can be missing.",
                impact="A caller may fail.",
                confidence=Confidence.HIGH,
                evidence=[EvidenceLocation(path="feature.py", start_line=2, end_line=2)],
                recommendation="Handle the missing result.",
                verification=VerificationState.VERIFIED,
            )
        ],
        rejected_findings=0,
        context=ContextPackage(
            content="",
            manifest=ContextManifest(
                entries=[], total_characters=0, limit_characters=1000, redactions=0
            ),
            changed_files=["feature.py"],
            checks=[],
        ),
        blocking=False,
        fingerprint=provider,
    )


def test_consensus_preserves_attribution_and_severity_disagreement() -> None:
    results = [
        PanelProviderResult(
            provider="alpha",
            review=review("alpha", Severity.WARNING, "Missing return value"),
        ),
        PanelProviderResult(
            provider="beta",
            review=review("beta", Severity.CRITICAL, "Return value is missing"),
        ),
    ]

    consensus = PanelReviewer()._consensus(results)

    assert consensus[0].agreement == 2
    assert consensus[0].providers == ["alpha", "beta"]
    assert consensus[0].severity_conflict is True


def test_panel_rejects_duplicate_provider_ids() -> None:
    with pytest.raises(CodePreflightError) as error:
        PanelReviewer().review(
            Path("."), {"providers": ["same", "same"]}, lambda event, payload: None
        )

    assert error.value.code == "panel_providers_duplicate"
