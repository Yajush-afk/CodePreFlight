from pathlib import Path

from conftest import git

from codepreflight_engine.models import FindingDraft
from codepreflight_engine.verification import FindingVerifier


def draft(path: str, line: int = 1) -> FindingDraft:
    return FindingDraft.model_validate(
        {
            "severity": "warning",
            "title": "Potential issue",
            "explanation": "The value may be incorrect.",
            "impact": "Behavior may regress.",
            "confidence": "medium",
            "evidence": [{"path": path, "start_line": line, "end_line": line}],
            "recommendation": "Inspect the value.",
            "suggested_tests": [],
        }
    )


def test_rejects_findings_for_missing_files(git_repository: Path) -> None:
    findings, rejected = FindingVerifier().verify(git_repository, [draft("invented.py")])

    assert findings == []
    assert rejected == 1


def test_deduplicates_same_title_and_location(git_repository: Path) -> None:
    (git_repository / "file.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "file.py")

    findings, rejected = FindingVerifier().verify(
        git_repository, [draft("file.py"), draft("file.py")]
    )

    assert len(findings) == 1
    assert rejected == 0
