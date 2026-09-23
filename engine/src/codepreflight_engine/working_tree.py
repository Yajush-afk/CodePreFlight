from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pathspec

from .context import (
    BINARY_SUFFIXES,
    DEFAULT_IGNORES,
    MAX_CHANGED_EXCERPT,
    MAX_CONTEXT_FILE_BYTES,
)
from .errors import CodePreflightError
from .git import GitRunner
from .models import CheckResult, ContextEntry, ContextManifest, ContextPackage
from .secrets import redact_secrets, verify_with_external_scanner


@dataclass(frozen=True)
class WorkingTreeSnapshot:
    staged_paths: list[str]
    unstaged_paths: list[str]
    untracked_paths: list[str]
    files: dict[str, str]
    unavailable: dict[str, str]
    staged_diff: str
    unstaged_diff: str
    verification_diff: str
    fingerprint: str

    @property
    def changed_files(self) -> list[str]:
        return sorted(set(self.staged_paths + self.unstaged_paths + self.untracked_paths))

    @classmethod
    def capture(cls, root: Path) -> WorkingTreeSnapshot:
        git = GitRunner(root)
        staged_paths = cls._paths(git.run("diff", "--cached", "--name-only", "-z").stdout)
        unstaged_paths = cls._paths(git.run("diff", "--name-only", "-z").stdout)
        untracked_paths = cls._paths(
            git.run("ls-files", "--others", "--exclude-standard", "-z").stdout
        )
        changed = sorted(set(staged_paths + unstaged_paths + untracked_paths))
        if not changed:
            raise CodePreflightError(
                "empty_change_set", "There are no working tree changes to review"
            )
        staged_diff = git.run("diff", "--cached", "--binary", "--no-ext-diff", "--unified=5").stdout
        unstaged_diff = git.run("diff", "--binary", "--no-ext-diff", "--unified=5").stdout
        files, unavailable = cls._read_files(root, changed)
        untracked_diff = cls._untracked_diff(untracked_paths, files)
        verification_diff = staged_diff + "\n" + unstaged_diff + "\n" + untracked_diff
        material = json.dumps(
            {
                "staged": staged_diff,
                "unstaged": unstaged_diff,
                "untracked": [[path, cls._file_identity(root / path)] for path in untracked_paths],
            },
            sort_keys=True,
        )
        return cls(
            staged_paths=staged_paths,
            unstaged_paths=unstaged_paths,
            untracked_paths=untracked_paths,
            files=files,
            unavailable=unavailable,
            staged_diff=staged_diff,
            unstaged_diff=unstaged_diff,
            verification_diff=verification_diff,
            fingerprint=hashlib.sha256(material.encode()).hexdigest(),
        )

    @staticmethod
    def _paths(value: str) -> list[str]:
        return sorted(path for path in value.split("\0") if path)

    @staticmethod
    def _read_files(root: Path, paths: list[str]) -> tuple[dict[str, str], dict[str, str]]:
        files: dict[str, str] = {}
        unavailable: dict[str, str] = {}
        for relative in paths:
            candidate = root / relative
            if candidate.is_symlink():
                unavailable[relative] = "symlink content"
                continue
            if not candidate.exists():
                unavailable[relative] = "deleted file represented by diff"
                continue
            if not candidate.is_file():
                unavailable[relative] = "non-regular file"
                continue
            raw = candidate.read_bytes()[: MAX_CONTEXT_FILE_BYTES + 1]
            if len(raw) > MAX_CONTEXT_FILE_BYTES:
                unavailable[relative] = f"file exceeds {MAX_CONTEXT_FILE_BYTES}-byte context limit"
            elif b"\0" in raw:
                unavailable[relative] = "binary content"
            else:
                files[relative] = raw.decode("utf-8", errors="replace")
        return files, unavailable

    @staticmethod
    def _file_identity(path: Path) -> str:
        if path.is_symlink():
            return f"symlink:{path.readlink()}"
        if not path.is_file():
            return "missing"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _untracked_diff(paths: list[str], files: dict[str, str]) -> str:
        sections = []
        for path in paths:
            content = files.get(path)
            if content is None:
                continue
            lines = content.splitlines()
            body = "\n".join(f"+{line}" for line in lines)
            sections.append(
                f"diff --git a/{path} b/{path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{path}\n"
                f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
            )
        return "\n".join(sections)


class WorkingTreeContextBuilder:
    """Build review context for the exact captured index and working tree."""

    def build(
        self,
        snapshot: WorkingTreeSnapshot,
        config: dict[str, Any],
        checks: list[CheckResult] | None = None,
    ) -> ContextPackage:
        configured = config.get("ignore", [])
        matcher = pathspec.GitIgnoreSpec.from_lines(
            [
                *DEFAULT_IGNORES,
                *(configured if isinstance(configured, list) else []),
            ]
        )
        entries: list[ContextEntry] = []
        eligible = [
            path
            for path in snapshot.changed_files
            if not self._exclude(path, snapshot.unavailable.get(path), matcher, entries)
        ]
        eligible_set = set(eligible)
        staged_diff = self._selected_patch(snapshot.staged_diff, eligible_set)
        unstaged_diff = self._selected_patch(snapshot.unstaged_diff, eligible_set)
        sections = [
            "## Working tree review semantics\n"
            "This snapshot combines staged, unstaged, deleted, renamed, and eligible untracked "
            "work without modifying the index or files.",
            "## Staged changes\n" + (staged_diff or "(none)"),
            "## Unstaged changes\n" + (unstaged_diff or "(none)"),
            "## Untracked files\n"
            + (
                "\n".join(path for path in snapshot.untracked_paths if path in eligible_set)
                or "(none)"
            ),
        ]
        self._record_categories(snapshot, eligible_set, entries)
        for path in eligible:
            content = snapshot.files.get(path)
            if content is None:
                continue
            excerpt = content[:MAX_CHANGED_EXCERPT]
            sections.append(f"## Current working file context: {path}\n{excerpt}")
            entries.append(
                ContextEntry(
                    path=path,
                    reason="current working file content",
                    included_characters=len(excerpt),
                    status="truncated" if len(content) > len(excerpt) else "included",
                )
            )
        rules = config.get("rules", [])
        if rules:
            rule_text = "\n".join(f"- {rule}" for rule in rules)
            sections.append("## Repository rules\n" + rule_text)
        actual_checks = checks or []
        if actual_checks:
            sections.append(
                "## Deterministic checks (working tree)\n"
                + "\n\n".join(
                    f"### {result.name}: {result.status.value}\n{result.output}"
                    for result in actual_checks
                )
            )
        return self._package(snapshot, eligible, actual_checks, sections, entries, config)

    def _package(
        self,
        snapshot: WorkingTreeSnapshot,
        eligible: list[str],
        checks: list[CheckResult],
        sections: list[str],
        entries: list[ContextEntry],
        config: dict[str, Any],
    ) -> ContextPackage:
        limit = int(config.get("review", {}).get("context_limit", 60000))
        redacted = redact_secrets("\n\n".join(sections))
        if not redacted.safe:
            raise CodePreflightError(
                "unsafe_secret_content",
                "Working tree context contains a private-key marker that cannot be sent",
                recoverable=True,
            )
        content = redacted.content[:limit]
        if len(redacted.content) > limit:
            entries.append(
                ContextEntry(
                    path="<context-budget>",
                    reason="configured context limit",
                    included_characters=limit,
                    status="truncated",
                )
            )
        return ContextPackage(
            content=content,
            manifest=ContextManifest(
                entries=entries,
                total_characters=len(content),
                limit_characters=limit,
                redactions=redacted.count,
                secret_scanner=verify_with_external_scanner(content),
            ),
            changed_files=eligible,
            checks=checks,
            target="working",
            comparison_note=f"Working snapshot {snapshot.fingerprint}",
        )

    def _record_categories(
        self,
        snapshot: WorkingTreeSnapshot,
        eligible: set[str],
        entries: list[ContextEntry],
    ) -> None:
        categories = (
            ("staged", snapshot.staged_paths),
            ("unstaged", snapshot.unstaged_paths),
            ("untracked", snapshot.untracked_paths),
        )
        for category, paths in categories:
            entries.extend(
                ContextEntry(path=path, reason=f"{category} change", status="included")
                for path in paths
                if path in eligible
            )

    def _exclude(
        self,
        path: str,
        unavailable: str | None,
        matcher: pathspec.GitIgnoreSpec,
        entries: list[ContextEntry],
    ) -> bool:
        reason = None
        if matcher.match_file(path):
            reason = "ignore rule"
        elif Path(path).suffix.lower() in BINARY_SUFFIXES:
            reason = "binary file type"
        elif unavailable and not unavailable.startswith("deleted file"):
            reason = unavailable
        if reason:
            entries.append(ContextEntry(path=path, reason=reason, status="excluded"))
            return True
        if unavailable:
            entries.append(ContextEntry(path=path, reason=unavailable, status="included"))
        return False

    def _selected_patch(self, patch: str, eligible: set[str]) -> str:
        sections = re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE)
        selected = []
        for section in sections:
            match = re.match(r"diff --git a/.+ b/(.+)\n", section)
            if match and match.group(1) in eligible:
                selected.append(section)
        return "".join(selected)
