from pathlib import Path

from conftest import git

from codepreflight_engine.models import FindingCategory, FindingDraft
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


def test_normalizes_evidence_paths_and_validates_test_file_suggestions(
    git_repository: Path,
) -> None:
    (git_repository / "file.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "file.py")
    candidate = draft("./file.py").model_copy(update={"suggested_tests": ["tests/missing.py"]})

    findings, _ = FindingVerifier().verify(git_repository, [candidate])

    assert findings[0].evidence[0].path == "file.py"
    assert findings[0].verification.value == "partially_verified"
    assert "Suggested test file does not exist: tests/missing.py" in findings[0].verification_notes


def test_deduplication_keeps_different_issue_categories(git_repository: Path) -> None:
    (git_repository / "file.py").write_text("value = 1\n", encoding="utf-8")
    git(git_repository, "add", "file.py")
    first = draft("file.py").model_copy(update={"category": FindingCategory.BUG})
    second = draft("file.py").model_copy(
        update={"category": FindingCategory.SECURITY, "title": "Potential issue detected"}
    )

    findings, _ = FindingVerifier().verify(git_repository, [first, second])

    assert len(findings) == 2
