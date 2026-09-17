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
