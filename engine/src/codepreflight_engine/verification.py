from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .git import GitRunner
from .models import (
    EvidenceLocation,
    Finding,
    FindingDraft,
    VerificationState,
)


class FindingVerifier:
    def verify(
        self,
        root: Path,
        drafts: list[FindingDraft],
        *,
        target: str = "staged",
        base_revision: str | None = None,
        revision: str | None = None,
    ) -> tuple[list[Finding], int]:
        verified: list[Finding] = []
        rejected = 0
        for draft in drafts:
            finding = self._verify_one(root, draft, target, base_revision, revision)
            if finding.verification == VerificationState.REJECTED:
                rejected += 1
                continue
            if not self._duplicates_existing(finding, verified):
                verified.append(finding)
        return verified, rejected

    def _verify_one(
        self,
        root: Path,
        draft: FindingDraft,
        target: str,
        base_revision: str | None,
        revision: str | None,
    ) -> Finding:
        changed_lines = self._changed_lines(root, target, base_revision, revision)
        checks = 0
        successes = 0
        notes: list[str] = []
        valid_locations = 0
        normalized_evidence: list[EvidenceLocation] = []
        git = GitRunner(root)
        for evidence in draft.evidence:
            checks += 1
            normalized_path = self._normalize_path(root, evidence.path)
            candidate = (root / normalized_path).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                notes.append(f"Evidence path escapes the repository: {evidence.path}")
                continue
            content = self._selected_content(git, target, normalized_path, revision)
            if content is None:
                notes.append(f"Evidence file does not exist in reviewed state: {evidence.path}")
                continue
            lines = content.splitlines()
            if (
                evidence.end_line < evidence.start_line
                or evidence.start_line > len(lines)
                or evidence.end_line > len(lines)
            ):
                notes.append(f"Evidence lines are outside {normalized_path}")
                continue
            normalized_evidence.append(evidence.model_copy(update={"path": normalized_path}))
            valid_locations += 1
            successes += 1
            checks += 1
            staged_lines = changed_lines.get(normalized_path, set())
            if target == "full" or any(
                line in staged_lines for line in range(evidence.start_line, evidence.end_line + 1)
            ):
                successes += 1
            else:
                notes.append(f"Evidence is outside changed lines in {normalized_path}")
            if evidence.symbol:
                checks += 1
                if re.search(rf"\b{re.escape(evidence.symbol)}\b", "\n".join(lines)):
                    successes += 1
                else:
                    notes.append(
                        f"Referenced symbol '{evidence.symbol}' was not found in {normalized_path}"
                    )

        for suggestion in draft.suggested_tests:
            path = self._suggested_test_path(suggestion)
            if path is None:
                continue
            checks += 1
            if (root / path).is_file():
                successes += 1
            else:
                notes.append(f"Suggested test file does not exist: {path}")

        if valid_locations == 0:
            state = VerificationState.REJECTED
        elif successes == checks:
            state = VerificationState.VERIFIED
        elif successes > 0:
            state = VerificationState.PARTIALLY_VERIFIED
        else:
            state = VerificationState.UNVERIFIED
        values = draft.model_dump()
        values["evidence"] = normalized_evidence or draft.evidence
        primary = (normalized_evidence or draft.evidence)[0]
        identity = hashlib.sha256(
            f"{draft.category}|{draft.title}|{primary.path}|{primary.start_line}".encode()
        ).hexdigest()[:12]
        return Finding(
            **values,
            id=identity,
            verification=state,
            verification_notes=notes,
        )

    def _selected_content(
        self, git: GitRunner, target: str, path: str, revision: str | None
    ) -> str | None:
        selected = f":{path}" if target == "staged" else f"{revision or 'HEAD'}:{path}"
        result = git.run("show", selected, check=False)
        return result.stdout if result.returncode == 0 else None

    def _changed_lines(
        self, root: Path, target: str, base_revision: str | None, revision: str | None
    ) -> dict[str, set[int]]:
        if target == "full":
            return {}
        if target == "staged":
            args = ["diff", "--cached"]
        elif target == "commit" and base_revision == "<root>":
            args = ["diff-tree", "--root", "--no-commit-id", "-r", revision or "HEAD"]
        else:
            args = ["diff", f"{base_revision}..{revision or 'HEAD'}"]
        diff = GitRunner(root).run(*args, "--unified=0", "--no-ext-diff").stdout
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
        title_tokens = self._tokens(finding.title)
        location = finding.evidence[0]
        for other in existing:
            other_location = other.evidence[0]
            same_path = location.path == other_location.path
            overlaps = not (
                location.end_line < other_location.start_line
                or other_location.end_line < location.start_line
            )
            other_tokens = self._tokens(other.title)
            union = title_tokens | other_tokens
            similarity = len(title_tokens & other_tokens) / len(union) if union else 1.0
            if finding.category == other.category and same_path and overlaps and similarity >= 0.6:
                return True
        return False

    def _tokens(self, title: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9 ]", "", title.lower()).split())

    def _normalize_path(self, root: Path, path: str) -> str:
        candidate = (root / path).resolve()
        try:
            return candidate.relative_to(root.resolve()).as_posix()
        except ValueError:
            return path

    def _suggested_test_path(self, suggestion: str) -> str | None:
        candidate = suggestion.strip().strip("`'\"")
        if " " in candidate or not Path(candidate).suffix:
            return None
        return candidate.removeprefix("./")
