from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .git import GitRunner
from .models import ContextPackage, ReviewResult


class ReviewCache:
    def __init__(self, root: Path) -> None:
        git_dir = GitRunner(root).run("rev-parse", "--git-dir").stdout.strip()
        resolved = (root / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir)
        self.directory = resolved / "codepreflight" / "cache"

    def get(self, fingerprint: str, context: ContextPackage) -> ReviewResult | None:
        path = self.directory / f"{fingerprint}.json"
        if not path.exists():
            return None
        try:
            value = ReviewResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            path.unlink(missing_ok=True)
            return None
        return value.model_copy(update={"context": context, "cache_hit": True})

    def put(self, review: ReviewResult) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        safe_context = review.context.model_copy(update={"content": ""})
        safe_review = review.model_copy(update={"context": safe_context, "cache_hit": False})
        path = self.directory / f"{review.fingerprint}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(safe_review.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def status(self) -> dict[str, Any]:
        files = list(self.directory.glob("*.json")) if self.directory.exists() else []
        return {
            "path": str(self.directory),
            "entries": len(files),
            "bytes": sum(path.stat().st_size for path in files),
        }

    def clear(self) -> dict[str, Any]:
        files = list(self.directory.glob("*.json")) if self.directory.exists() else []
        for path in files:
            path.unlink()
        return {"path": str(self.directory), "removed": len(files)}
