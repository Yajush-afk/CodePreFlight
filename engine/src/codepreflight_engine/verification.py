from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .activity import operation
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
        historical_files: dict[str, str] | None = None,
        historical_diff: str | None = None,
    ) -> tuple[list[Finding], int]:
        verified: list[Finding] = []
        rejected = 0
        with operation("Preflight", "finding verification") as record:
            for draft in drafts:
                finding = self._verify_one(
                    root,
                    draft,
                    target,
                    base_revision,
                    revision,
                    historical_files,
                    historical_diff,
                )
                if finding.verification == VerificationState.REJECTED:
                    rejected += 1
                    continue
                if not self._duplicates_existing(finding, verified):
                    verified.append(finding)
            record["summary"] = f"Preflight checked {len(drafts)} findings; {rejected} rejected"
        return verified, rejected

    def _verify_one(
        self,
        root: Path,
        draft: FindingDraft,
        target: str,
        base_revision: str | None,
        revision: str | None,
        historical_files: dict[str, str] | None,
        historical_diff: str | None,
    ) -> Finding:
        changed = (
            self._parse_changed_lines(historical_diff)
            if historical_diff is not None
            else self._changed_lines(root, target, base_revision, revision)
        )
        evidence: list[EvidenceLocation] = []
        notes: list[str] = []
        checks = successes = 0
        for location in draft.evidence:
            normalized, passed, total, reasons = self._location_rule(
                root, location, target, revision, changed, historical_files
            )
            checks += total
            successes += passed
            notes.extend(reasons)
            if normalized:
                evidence.append(normalized)
        passed, total, reasons = self._test_rule(root, draft.suggested_tests, historical_files)
        checks += total
        successes += passed
        notes.extend(reasons)
        state = self._verification_state(len(evidence), successes, checks)
        values = draft.model_dump()
        values["evidence"] = evidence or draft.evidence
        primary = (evidence or draft.evidence)[0]
        identity = hashlib.sha256(
            f"{draft.category}|{draft.title}|{primary.path}|{primary.start_line}".encode()
        ).hexdigest()[:12]
        return Finding(**values, id=identity, verification=state, verification_notes=notes)

    def _location_rule(
        self,
        root: Path,
        evidence: EvidenceLocation,
        target: str,
        revision: str | None,
        changed: dict[str, set[int]],
        historical_files: dict[str, str] | None,
    ) -> tuple[EvidenceLocation | None, int, int, list[str]]:
        normalized = self._normalize_path(root, evidence.path)
        try:
            (root / normalized).resolve().relative_to(root.resolve())
        except ValueError:
            return None, 0, 1, [f"Evidence path escapes the repository: {evidence.path}"]
        content = (
            historical_files.get(normalized)
            if historical_files is not None
            else self._selected_content(GitRunner(root), target, normalized, revision)
        )
        if content is None:
            return None, 0, 1, [f"Evidence file does not exist in reviewed state: {evidence.path}"]
        lines = content.splitlines()
        if not 1 <= evidence.start_line <= evidence.end_line <= len(lines):
            return None, 0, 1, [f"Evidence lines are outside {normalized}"]
        passed, total, notes = 1, 2, []
        if target == "full" or any(
            line in changed.get(normalized, set())
            for line in range(evidence.start_line, evidence.end_line + 1)
        ):
            passed += 1
        else:
            notes.append(f"Evidence is outside changed lines in {normalized}")
        if evidence.symbol:
            total += 1
            if re.search(rf"\b{re.escape(evidence.symbol)}\b", content):
                passed += 1
            else:
                notes.append(f"Referenced symbol '{evidence.symbol}' was not found in {normalized}")
        return evidence.model_copy(update={"path": normalized}), passed, total, notes

    def _test_rule(
        self,
        root: Path,
        suggestions: list[str],
        historical_files: dict[str, str] | None,
    ) -> tuple[int, int, list[str]]:
        passed = total = 0
        notes: list[str] = []
        for suggestion in suggestions:
            path = self._suggested_test_path(suggestion)
            if path is None:
                continue
            total += 1
            candidate = (root / path).resolve()
            exists = (
                path in historical_files
                if historical_files is not None
                else candidate.is_relative_to(root.resolve()) and candidate.is_file()
            )
            if exists:
                passed += 1
            else:
                notes.append(f"Suggested test file does not exist: {path}")
        return passed, total, notes

    def _verification_state(self, locations: int, successes: int, checks: int) -> VerificationState:
        if locations == 0:
            return VerificationState.REJECTED
        if successes == checks:
            return VerificationState.VERIFIED
        return VerificationState.PARTIALLY_VERIFIED if successes else VerificationState.UNVERIFIED

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
        return self._parse_changed_lines(diff)

    def _parse_changed_lines(self, diff: str | None) -> dict[str, set[int]]:
        changed: dict[str, set[int]] = {}
        current: str | None = None
        for line in (diff or "").splitlines():
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
