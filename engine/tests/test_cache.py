import json
from pathlib import Path

from codepreflight_engine.cache import ReviewCache
from codepreflight_engine.models import (
    ContextManifest,
    ContextPackage,
    ProviderDescriptor,
    ProviderKind,
    ProviderState,
    ReviewResult,
)


def test_cache_does_not_persist_repository_content(git_repository: Path) -> None:
    context = ContextPackage(
        content="private repository source",
        manifest=ContextManifest(
            entries=[], total_characters=25, limit_characters=1000, redactions=0
        ),
        changed_files=["feature.py"],
        checks=[],
    )
    review = ReviewResult(
        provider=ProviderDescriptor(
            id="fake",
            name="Fake",
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        ),
        summary="No findings.",
        findings=[],
        rejected_findings=0,
        context=context,
        blocking=False,
        fingerprint="a" * 64,
    )
    cache = ReviewCache(git_repository)

    cache.put(review)

    stored = next(cache.directory.glob("*.json")).read_text(encoding="utf-8")
    assert "private repository source" not in stored
    restored = cache.get(review.fingerprint, context)
    assert restored is not None
    assert restored.cache_hit is True
    assert restored.context.content == "private repository source"
    assert cache.clear()["removed"] == 1


def test_cache_invalidates_legacy_severity_results(git_repository: Path) -> None:
    context = ContextPackage(
        content="current source",
        manifest=ContextManifest(
            entries=[], total_characters=14, limit_characters=1000, redactions=0
        ),
        changed_files=["feature.py"],
        checks=[],
    )
    review = ReviewResult(
        provider=ProviderDescriptor(
            id="fake",
            name="Fake",
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        ),
        summary="Legacy finding.",
        findings=[],
        rejected_findings=0,
        context=context.model_copy(update={"content": ""}),
        blocking=False,
        fingerprint="b" * 64,
    )
    legacy = review.model_dump(mode="json")
    legacy["findings"] = [
        {
            "id": "legacy",
            "severity": "warning",
            "category": "bug",
            "title": "Legacy severity",
            "explanation": "Old cached result.",
            "impact": "Could mis-rank the finding.",
            "confidence": "medium",
            "evidence": [{"path": "feature.py", "start_line": 1, "end_line": 1}],
            "recommendation": "Review again.",
            "suggested_tests": [],
            "verification": "unverified",
            "verification_notes": [],
        }
    ]
    cache = ReviewCache(git_repository)
    cache.directory.mkdir(parents=True)
    path = cache.directory / f"{review.fingerprint}.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert cache.get(review.fingerprint, context) is None
    assert not path.exists()
