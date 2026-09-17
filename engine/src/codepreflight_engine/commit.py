from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner
from .models import CommitPreparation, ReviewResult
from .review import EventEmitter, ReviewOrchestrator


def staged_fingerprint(root: Path) -> str:
    diff = GitRunner(root).run("diff", "--cached", "--binary", "--no-ext-diff").stdout
    if not diff:
        raise CodePreflightError("empty_change_set", "There are no staged changes to commit")
    return hashlib.sha256(diff.encode()).hexdigest()


def prepare_commit(root: Path, payload: dict[str, Any], emit: EventEmitter) -> CommitPreparation:
    review = ReviewOrchestrator().review_staged(root, payload, emit)
    return CommitPreparation(
        message=generate_commit_message(review),
        fingerprint=staged_fingerprint(root),
        review=review,
    )


def create_commit(root: Path, payload: dict[str, Any]) -> dict[str, str]:
    if not bool(payload.get("approved")):
        raise CodePreflightError("commit_not_approved", "Commit requires explicit approval")
    expected = str(payload.get("fingerprint", ""))
    actual = staged_fingerprint(root)
    if not expected or expected != actual:
        raise CodePreflightError(
            "staged_changes_changed",
            "Staged changes changed after review; review the current staged change set again",
        )
    message = str(payload.get("message", "")).strip()
    if not message or "\n" in message:
        raise CodePreflightError(
            "invalid_commit_message", "Commit message must be a non-empty single line"
        )
    result = GitRunner(root).run("commit", "-m", message)
    commit_hash = GitRunner(root).run("rev-parse", "HEAD").stdout.strip()
    return {"commit": commit_hash, "message": message, "output": result.stdout.strip()}


def generate_commit_message(review: ReviewResult) -> str:
    files = review.context.staged_files
    if files and all(path.lower().endswith((".md", ".mdx")) for path in files):
        kind = "docs"
    elif files and all("test" in path.lower() or "spec" in path.lower() for path in files):
        kind = "test"
    elif files and all(
        path.endswith((".toml", ".json", ".yaml", ".yml", ".lock")) for path in files
    ):
        kind = "chore"
    else:
        kind = "feat"
    if review.status == "failed":
        noun = files[0] if len(files) == 1 else f"{len(files)} staged files"
        return f"{kind}: update {noun}"
    sentence = re.split(r"[.!?]\s|\n", review.summary.strip(), maxsplit=1)[0].strip()
    sentence = sentence[:68].rstrip(" .") or "update staged changes"
    sentence = sentence[0].lower() + sentence[1:] if sentence else sentence
    return f"{kind}: {sentence}"
