from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import pathspec

from .checks import CheckRunner
from .errors import CodePreflightError
from .git import GitRunner
from .models import CheckDefinition, ContextEntry, ContextManifest, ContextPackage
from .secrets import redact_secrets, verify_with_external_scanner

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
DEFAULT_IGNORES = (
    ".git/",
    ".venv/",
    "node_modules/",
    "vendor/",
    "dist/",
    "build/",
    "coverage/",
    "*.min.js",
    "*.map",
)
MAX_CONTEXT_FILE_BYTES = 500_000
MAX_CHANGED_EXCERPT = 12_000
MAX_RELATED_EXCERPT = 4_000
MAX_RELATED_FILES = 12


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
        configured_ignore = config.get("ignore", [])
        ignore = [
            *DEFAULT_IGNORES,
            *(configured_ignore if isinstance(configured_ignore, list) else []),
        ]
        matcher = pathspec.GitIgnoreSpec.from_lines(ignore)
        definitions = [CheckDefinition.model_validate(item) for item in config.get("checks", [])]
        checks = CheckRunner().run(root, definitions)
        entries: list[ContextEntry] = []
        sections: list[str] = []

        selected: dict[str, str] = {}
        review_files: list[str] = []
        for relative in changed_files:
            exclusion = self._exclusion(git, target, relative, matcher)
            if exclusion:
                entries.append(ContextEntry(path=relative, reason=exclusion, status="excluded"))
                continue
            review_files.append(relative)
            content = self._selected_content(git, target, relative)
            if content is None:
                entries.append(
                    ContextEntry(
                        path=relative,
                        reason="deleted file represented by selected diff",
                        status="included",
                    )
                )
                continue
            if "\x00" in content:
                entries.append(
                    ContextEntry(path=relative, reason="binary content", status="excluded")
                )
                continue
            selected[relative] = content

        diff = (
            git.run(*diff_args, "--no-ext-diff", "--unified=5", "--", *review_files).stdout
            if review_files
            else "(all changed files were excluded or deleted)"
        )
        sections.append(f"## {target.replace('_', ' ').title()} diff\n{diff}")
        entries.append(
            ContextEntry(
                path="<selected-diff>",
                reason=f"{target.replace('_', ' ')} unified diff",
                included_characters=len(diff),
                status="included",
            )
        )

        for relative, content in selected.items():
            excerpt = self._relevant_excerpt(diff, relative, content)
            status: Literal["included", "truncated"] = "included"
            if len(excerpt) > MAX_CHANGED_EXCERPT:
                excerpt = excerpt[:MAX_CHANGED_EXCERPT]
                status = "truncated"
            sections.append(f"## Reviewed file context: {relative}\n{excerpt}")
            entries.append(
                ContextEntry(
                    path=relative,
                    reason=f"{target.replace('_', ' ')} file context",
                    included_characters=len(excerpt),
                    status=status,
                )
            )

        for relative, relationship, content in self._related_context(
            git, target, changed_files, matcher
        ):
            excerpt = content[:MAX_RELATED_EXCERPT]
            related_status: Literal["included", "truncated"] = (
                "truncated" if len(content) > len(excerpt) else "included"
            )
            sections.append(f"## Related context: {relative} ({relationship})\n{excerpt}")
            entries.append(
                ContextEntry(
                    path=relative,
                    reason=relationship,
                    included_characters=len(excerpt),
                    status=related_status,
                )
            )

        rules = config.get("rules", [])
        if rules:
            rule_text = "\n".join(f"- {rule}" for rule in rules)
            sections.append("## Repository rules\n" + rule_text)
            entries.append(
                ContextEntry(
                    path="<repository-rules>",
                    reason="trusted repository review rules",
                    included_characters=len(rule_text),
                    status="included",
                )
            )
        if checks:
            check_text = "\n\n".join(
                f"### {result.name}: {result.status.value}\n{result.output}" for result in checks
            )
            sections.append("## Deterministic checks (working tree)\n" + check_text)
            entries.extend(
                ContextEntry(
                    path=f"<check:{result.name}>",
                    reason=f"working-tree check result: {result.status.value}",
                    included_characters=len(result.output),
                    status="included",
                )
                for result in checks
            )
        if target == "pull_request" and base_revision:
            history = git.run(
                "log", "--format=%h %s", f"{base_revision}..HEAD", check=False
            ).stdout.strip()
            if history:
                sections.append("## Branch commits\n" + history)
                entries.append(
                    ContextEntry(
                        path="<branch-history>",
                        reason="pull-request commit history",
                        included_characters=len(history),
                        status="included",
                    )
                )

        content = "\n\n".join(sections)
        redacted = redact_secrets(content)
        if not redacted.safe:
            raise CodePreflightError(
                "unsafe_secret_content",
                "Selected context contains a private-key marker that could not be safely redacted",
                recoverable=True,
            )
        scanner = verify_with_external_scanner(redacted.content)
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
        final_content = redacted.content
        if len(final_content) > limit:
            final_content = final_content[:limit]
            entries.append(
                ContextEntry(
                    path="<context-budget>",
                    reason="configured context limit",
                    included_characters=limit,
                    status="truncated",
                )
            )
        return ContextPackage(
            content=final_content,
            manifest=ContextManifest(
                entries=entries,
                total_characters=len(final_content),
                limit_characters=limit,
                redactions=redacted.count,
                secret_scanner=scanner,
            ),
            changed_files=changed_files,
            checks=checks,
            target=target,
            base_revision=base_revision,
        )

    def _exclusion(
        self,
        git: GitRunner,
        target: Literal["staged", "branch", "pull_request"],
        relative: str,
        matcher: pathspec.GitIgnoreSpec,
    ) -> str | None:
        if matcher.match_file(relative):
            return "ignore rule"
        if Path(relative).suffix.lower() in BINARY_SUFFIXES:
            return "binary file type"
        size = self._selected_size(git, target, relative)
        if size is not None and size > MAX_CONTEXT_FILE_BYTES:
            return f"file exceeds {MAX_CONTEXT_FILE_BYTES}-byte context limit"
        return None

    def _related_context(
        self,
        git: GitRunner,
        target: Literal["staged", "branch", "pull_request"],
        changed_files: list[str],
        matcher: pathspec.GitIgnoreSpec,
    ) -> list[tuple[str, str, str]]:
        tokens = sorted(
            {Path(path).stem.lower() for path in changed_files if len(Path(path).stem) >= 3}
        )
        if not tokens:
            return []
        candidates: list[tuple[int, str, str, str]] = []
        tracked = sorted(filter(None, git.run("ls-files", "-z").stdout.split("\0")))
        for relative in tracked:
            if relative in changed_files or self._exclusion(git, target, relative, matcher):
                continue
            content = self._selected_content(git, target, relative)
            if content is None or "\x00" in content:
                continue
            relationship = self._relationship(relative, content, tokens)
            if relationship:
                candidates.append((*relationship, relative, content))
        candidates.sort(key=lambda item: (item[0], item[2]))
        return [
            (relative, relationship, content)
            for _, relationship, relative, content in candidates[:MAX_RELATED_FILES]
        ]

    def _relationship(self, path: str, content: str, tokens: list[str]) -> tuple[int, str] | None:
        lowered_path = path.lower()
        lowered_content = content.lower()
        path_stem = Path(path).stem.lower()
        referenced = next((token for token in tokens if token == path_stem), None) or next(
            (token for token in tokens if re.search(rf"\b{re.escape(token)}\b", lowered_content)),
            None,
        )
        if not referenced:
            return None
        if "test" in lowered_path or "spec" in lowered_path:
            return (0, f"related test referencing {referenced}")
        if (
            Path(path).suffix == ".pyi"
            or path.endswith(".d.ts")
            or re.search(r"\b(?:interface|protocol|type)\b", lowered_content)
        ):
            return (1, f"related interface referencing {referenced}")
        if any(part in lowered_path for part in ("route", "api", "controller")):
            return (2, f"related route referencing {referenced}")
        if re.search(
            rf"(?m)^\s*(?:from|import|export).*\b{re.escape(referenced)}\b",
            lowered_content,
        ):
            return (3, f"direct importer referencing {referenced}")
        return (4, f"symbol reference to {referenced}")

    def _selected_size(
        self,
        git: GitRunner,
        target: Literal["staged", "branch", "pull_request"],
        relative: str,
    ) -> int | None:
        revision = f":{relative}" if target == "staged" else f"HEAD:{relative}"
        result = git.run("cat-file", "-s", revision, check=False)
        if result.returncode != 0:
            return None
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None

    def _selected_content(
        self,
        git: GitRunner,
        target: Literal["staged", "branch", "pull_request"],
        relative: str,
    ) -> str | None:
        revision = f":{relative}" if target == "staged" else f"HEAD:{relative}"
        result = git.run("show", revision, check=False)
        return result.stdout if result.returncode == 0 else None

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
            return content[:MAX_CHANGED_EXCERPT]
        next_file = diff.find("\ndiff --git ", section_start)
        file_diff = diff[section_start : next_file if next_file >= 0 else None]
        line_numbers = [
            int(match.group(1)) for match in re.finditer(r"@@ -\d+(?:,\d+)? \+(\d+)", file_diff)
        ]
        if not line_numbers:
            return content[:MAX_CHANGED_EXCERPT]
        lines = content.splitlines()
        excerpts = []
        for line_number in line_numbers[:8]:
            start = max(0, line_number - 16)
            end = min(len(lines), line_number + 15)
            excerpts.append(
                "\n".join(f"{index + 1:>6} {lines[index]}" for index in range(start, end))
            )
        return "\n...\n".join(excerpts)
