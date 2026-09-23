"""Bounded, locally verified evidence for repository and review conversations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner
from .repository import RepositoryInspector
from .secrets import redact_secrets, verify_with_external_scanner


@dataclass(frozen=True)
class ConversationEvidence:
    text: str
    redactions: int
    paths: list[str]
    scanner: str


class ConversationContext:
    def build(self, root: Path, payload: dict[str, Any]) -> ConversationEvidence:
        sections = self._git_sections(root)
        review = payload.get("reviewContext")
        if review is None:
            return self._finish(sections, 0, [])
        if not isinstance(review, dict) or review.get("target") not in {
            "full",
            "staged",
            "commit",
            "branch",
            "pull_request",
        }:
            raise CodePreflightError("invalid_review_context", "Review context is malformed")
        findings = review.get("findings", [])
        if not isinstance(findings, list) or len(findings) > 10:
            raise CodePreflightError("invalid_review_context", "Too many review findings selected")
        sections.append(
            f"## Active {review['target']} review\n"
            f"Summary: {str(review.get('summary', ''))[:4_000]}"
        )
        paths: list[str] = []
        redactions = 0
        for index, finding in enumerate(findings, 1):
            if not isinstance(finding, dict):
                continue
            sections.append(self._finding_summary(index, finding))
            locations = finding.get("evidence", [])
            if not isinstance(locations, list):
                continue
            for evidence in locations[:3]:
                excerpt = self._excerpt(root, evidence)
                if excerpt is None:
                    continue
                text, count, path = excerpt
                sections.append(text)
                redactions += count
                paths.append(path)
        return self._finish(sections, redactions, paths)

    def _git_sections(self, root: Path) -> list[str]:
        git = GitRunner(root)
        status = git.run("status", "--short", "--branch", check=False).stdout[:4_000]
        history = git.run("log", "-n", "8", "--format=%h %s", check=False).stdout[:4_000]
        sections = [
            f"## Local Git status\n{status or 'clean'}",
            f"## Relevant Git history (recent commits)\n{history}",
        ]
        snapshot = RepositoryInspector().inspect(root)
        if snapshot.merge_base:
            branch_changes = git.run(
                "diff", "--stat", f"{snapshot.merge_base}..HEAD", check=False
            ).stdout[:8_000]
            sections.append(
                f"## Current branch change summary\n{branch_changes or 'No committed changes'}"
            )
        working_changes = git.run("diff", "--stat", "HEAD", check=False).stdout[:4_000]
        if working_changes:
            sections.append(f"## Uncommitted change summary\n{working_changes}")
        return sections

    def _finish(self, sections: list[str], count: int, paths: list[str]) -> ConversationEvidence:
        redacted = redact_secrets("\n\n".join(sections)[:80_000])
        if not redacted.safe:
            raise CodePreflightError(
                "unsafe_conversation_context",
                "A repository question contains sensitive content that cannot be safely redacted",
            )
        scanner = verify_with_external_scanner(redacted.content)
        return ConversationEvidence(redacted.content, count + redacted.count, paths, scanner)

    def _finding_summary(self, index: int, finding: dict[str, Any]) -> str:
        fields = (
            "id",
            "severity",
            "title",
            "explanation",
            "impact",
            "recommendation",
            "verification",
        )
        lines = [f"## Selected finding {finding.get('index', index)}"]
        lines.extend(f"{field}: {str(finding.get(field, ''))[:2_000]}" for field in fields)
        return "\n".join(lines)

    def _excerpt(self, root: Path, evidence: Any) -> tuple[str, int, str] | None:
        if not isinstance(evidence, dict):
            return None
        relative = evidence.get("path")
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            return None
        path = root / relative
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(root.resolve()) or not path.is_file():
            return None
        if path.stat().st_size > 500_000:
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return None
        try:
            raw_line = evidence.get("start_line", evidence.get("line", 1))
            if not isinstance(raw_line, (int, str)):
                return None
            line = int(raw_line)
        except (TypeError, ValueError):
            return None
        if line < 1 or line > len(lines):
            return None
        start, end = max(1, line - 8), min(len(lines), line + 8)
        numbered = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
        redacted = redact_secrets(numbered)
        if not redacted.safe:
            return None
        return (
            f"## Current file {relative} lines {start}-{end}\n{redacted.content}",
            redacted.count,
            relative,
        )
