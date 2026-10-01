import pytest
from pydantic import ValidationError

from codepreflight_engine.models import (
    ConflictFileDetail,
    ConflictInspection,
    ConflictState,
    FindingDraft,
    GitConfirmation,
    GitOperationPlan,
    GitOperationRisk,
    Severity,
)
from codepreflight_engine.protocol_generated import PROTOCOL_VERSION


def test_protocol_v4_contract_vocabularies() -> None:
    assert PROTOCOL_VERSION == 4
    assert [item.value for item in Severity] == ["critical", "high", "medium", "low"]
    plan = GitOperationPlan(
        id="plan-1",
        action="stage_file",
        commands=["git add -- feature.py"],
        fingerprint="snapshot",
        risk=GitOperationRisk.LOW,
        confirmation=GitConfirmation.EXPLICIT,
        selected_paths=["feature.py"],
    )
    conflict = ConflictState(
        operation="merge", files=["feature.py"], can_continue=True, can_abort=True
    )
    assert plan.selected_paths == ["feature.py"]
    assert conflict.can_abort is True

    inspection = ConflictInspection(
        operation="merge",
        files=["feature.py"],
        details=[
            ConflictFileDetail(
                path="feature.py",
                base="old\n",
                ours="ours\n",
                theirs="theirs\n",
                working="conflict\n",
            )
        ],
        can_abort=True,
    )
    assert inspection.details[0].theirs == "theirs\n"


def test_provider_contract_rejects_legacy_severity() -> None:
    with pytest.raises(ValidationError):
        FindingDraft.model_validate(
            {
                "severity": "warning",
                "title": "Legacy severity",
                "explanation": "Old output.",
                "impact": "Cannot use the v4 contract.",
                "confidence": "medium",
                "evidence": [{"path": "file.py", "start_line": 1, "end_line": 1}],
                "recommendation": "Review again.",
            }
        )
