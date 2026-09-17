from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import pathspec

from .checks import CheckRunner
from .errors import CodePreflightError
from .git import GitRunner
from .models import (
    CheckDefinition,
    ContextEntry,
    ContextManifest,
    ContextPackage,
)
from .secrets import redact_secrets

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".woff",
    ".woff2",
}


class ContextBuilder:
    def build(
        self,
        root: Path,
        config: dict[str, Any],
        *,
        target: Literal["staged", "branch", "pull_request"] = "staged",
        base_revision: str | None = None,
    ) -> ContextPackage:
        git = GitRunner(root)
        diff_args = self._diff_args(target, base_revision)
        changed_files = [
            path for path in git.run(*diff_args, "--name-only", "-z").stdout.split("\0") if path
        ]
        if not changed_files:
            raise CodePreflightError(
                "empty_change_set", f"There are no {target.replace('_', ' ')} changes to review"
            )

        limit = int(config.get("review", {}).get("context_limit", 60000))
        ignore = config.get("ignore", [])
        matcher = pathspec.GitIgnoreSpec.from_lines(ignore if isinstance(ignore, list) else [])
        definitions = [CheckDefinition.model_validate(item) for item in config.get("checks", [])]
        checks = CheckRunner().run(root, definitions)
        entries: list[ContextEntry] = []
        sections: list[str] = []

        review_files: list[str] = []
        for relative in changed_files:
            if matcher.match_file(relative):
                entries.append(ContextEntry(path=relative, reason="ignore rule", status="excluded"))
            elif Path(relative).suffix.lower() in BINARY_SUFFIXES:
                entries.append(ContextEntry(path=relative, reason="binary file", status="excluded"))
            else:
                review_files.append(relative)

        diff = (
            git.run(*diff_args, "--no-ext-diff", "--unified=5", "--", *review_files).stdout
            if review_files
            else ""
        )
        sections.append(f"## {target.replace('_', ' ').title()} diff\n" + diff)

        for relative in review_files:
            path = root / relative
            if not path.exists():
                entries.append(
                    ContextEntry(
                        path=relative,
                        reason="deleted file represented by staged diff",
                        status="included",
                    )
                )
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                entries.append(
                    ContextEntry(path=relative, reason="not readable as text", status="excluded")
                )
                continue
            excerpt = self._relevant_excerpt(diff, relative, content)
            status: Literal["included", "truncated"] = "included"
            if len(excerpt) > 12000:
                excerpt = excerpt[:12000]
                status = "truncated"
            sections.append(f"## Current file context: {relative}\n{excerpt}")
            entries.append(
                ContextEntry(
                    path=relative,
                    reason=f"{target.replace('_', ' ')} file context",
                    included_characters=len(excerpt),
                    status=status,
                )
            )

        rules = config.get("rules", [])
        if rules:
            sections.append("## Repository rules\n" + "\n".join(f"- {rule}" for rule in rules))
        if checks:
            check_text = "\n\n".join(
                f"### {result.name}: {result.status.value}\n{result.output}" for result in checks
            )
            sections.append("## Deterministic checks\n" + check_text)
        if target == "pull_request" and base_revision:
            history = git.run(
                "log", "--format=%h %s", f"{base_revision}..HEAD", check=False
            ).stdout.strip()
            if history:
                sections.append("## Branch commits\n" + history)

        content = "\n\n".join(sections)
        redacted = redact_secrets(content)
        combined_status: Literal["included", "redacted"] = (
            "redacted" if redacted.count else "included"
        )
        entries.append(
            ContextEntry(
                path="<combined-context>",
                reason="secret scan",
                included_characters=len(redacted.content),
                status=combined_status,
            )
        )
        if len(redacted.content) > limit:
            redacted = type(redacted)(redacted.content[:limit], redacted.count)
            entries.append(
                ContextEntry(
                    path="<context-budget>",
                    reason="configured context limit",
                    included_characters=limit,
                    status="truncated",
                )
            )
        return ContextPackage(
            content=redacted.content,
            manifest=ContextManifest(
                entries=entries,
                total_characters=len(redacted.content),
                limit_characters=limit,
                redactions=redacted.count,
            ),
            changed_files=changed_files,
            checks=checks,
            target=target,
            base_revision=base_revision,
        )

    def _diff_args(
        self,
        target: Literal["staged", "branch", "pull_request"],
        base_revision: str | None,
    ) -> tuple[str, ...]:
        if target == "staged":
            return ("diff", "--cached")
        if not base_revision:
            raise CodePreflightError(
                "base_branch_required", f"A base revision is required for {target} review"
            )
        return ("diff", f"{base_revision}..HEAD")

    def _relevant_excerpt(self, diff: str, relative: str, content: str) -> str:
        marker = f"+++ b/{relative}"
        section_start = diff.find(marker)
        if section_start < 0:
            return content[:12000]
        next_file = diff.find("\ndiff --git ", section_start)
        file_diff = diff[section_start : next_file if next_file >= 0 else None]
        line_numbers = [
            int(match.group(1)) for match in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)", file_diff)
        ]
        if not line_numbers:
            return content[:12000]
        lines = content.splitlines()
        excerpts = []
        for line_number in line_numbers[:8]:
            start = max(0, line_number - 16)
            end = min(len(lines), line_number + 15)
            excerpts.append(
                "\n".join(f"{index + 1:>6} {lines[index]}" for index in range(start, end))
            )
        return "\n...\n".join(excerpts)
