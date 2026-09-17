from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .git import GitRunner
from .models import (
    Finding,
    FindingDraft,
    VerificationState,
)


class FindingVerifier:
    def verify(self, root: Path, drafts: list[FindingDraft]) -> tuple[list[Finding], int]:
        verified: list[Finding] = []
        rejected = 0
        for draft in drafts:
            finding = self._verify_one(root, draft)
            if finding.verification == VerificationState.REJECTED:
                rejected += 1
                continue
            if not self._duplicates_existing(finding, verified):
                verified.append(finding)
        return verified, rejected

    def _verify_one(self, root: Path, draft: FindingDraft) -> Finding:
        changed_lines = self._changed_lines(root)
        checks = 0
        successes = 0
        notes: list[str] = []
        valid_locations = 0
        for evidence in draft.evidence:
            checks += 1
            candidate = (root / evidence.path).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                notes.append(f"Evidence path escapes the repository: {evidence.path}")
                continue
            if not candidate.exists() or not candidate.is_file():
                notes.append(f"Evidence file does not exist: {evidence.path}")
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                notes.append(f"Evidence file is not readable text: {evidence.path}")
                continue
            if (
                evidence.end_line < evidence.start_line
                or evidence.start_line > len(lines)
                or evidence.end_line > len(lines)
            ):
                notes.append(f"Evidence lines are outside {evidence.path}")
                continue
            valid_locations += 1
            successes += 1
            checks += 1
            staged_lines = changed_lines.get(evidence.path, set())
            if any(
                line in staged_lines for line in range(evidence.start_line, evidence.end_line + 1)
            ):
                successes += 1
            else:
                notes.append(f"Evidence is outside changed lines in {evidence.path}")
            if evidence.symbol:
                checks += 1
                if re.search(rf"\b{re.escape(evidence.symbol)}\b", "\n".join(lines)):
                    successes += 1
                else:
                    notes.append(
                        f"Referenced symbol '{evidence.symbol}' was not found in {evidence.path}"
                    )

        if valid_locations == 0:
            state = VerificationState.REJECTED
        elif successes == checks:
            state = VerificationState.VERIFIED
        elif successes > 0:
            state = VerificationState.PARTIALLY_VERIFIED
        else:
            state = VerificationState.UNVERIFIED
        identity = hashlib.sha256(
            f"{draft.title}|{draft.evidence[0].path}|{draft.evidence[0].start_line}".encode()
        ).hexdigest()[:12]
        return Finding(
            **draft.model_dump(),
            id=identity,
            verification=state,
            verification_notes=notes,
        )

    def _changed_lines(self, root: Path) -> dict[str, set[int]]:
        diff = GitRunner(root).run("diff", "--cached", "--unified=0", "--no-ext-diff").stdout
        changed: dict[str, set[int]] = {}
        current: str | None = None
        for line in diff.splitlines():
            if line.startswith("+++ b/"):
                current = line[6:]
                changed.setdefault(current, set())
                continue
            if current and line.startswith("@@"):
                match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if match:
                    start = int(match.group(1))
                    count = int(match.group(2) or "1")
                    changed[current].update(range(start, start + count))
        return changed

    def _duplicates_existing(self, finding: Finding, existing: list[Finding]) -> bool:
        title = self._normalize(finding.title)
        location = finding.evidence[0]
        for other in existing:
            other_location = other.evidence[0]
            same_path = location.path == other_location.path
            overlaps = not (
                location.end_line < other_location.start_line
                or other_location.end_line < location.start_line
            )
            if same_path and overlaps and self._normalize(other.title) == title:
                return True
        return False

    def _normalize(self, title: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9 ]", "", title.lower()).split())
