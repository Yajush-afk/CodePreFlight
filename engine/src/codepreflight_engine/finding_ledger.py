from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import CodePreflightError
from .git import GitRunner
from .models import (
    ContextPackage,
    Finding,
    FindingLifecycle,
    FindingReconciliation,
    ProviderDescriptor,
)
from .request_values import request_flag
from .state_files import reject_symlink_path

SCHEMA_VERSION = 1


class FindingLedger:
    """Branch-aware, repository-private finding history without conversations or prompts."""

    def __init__(self, root: Path) -> None:
        self.root = GitRunner(root).root()
        git_dir = Path(GitRunner(self.root).run("rev-parse", "--absolute-git-dir").stdout.strip())
        self.directory = git_dir / "codepreflight"
        self.path = self.directory / "findings.sqlite3"

    def record_review(
        self,
        *,
        branch: str,
        snapshot: str,
        commit: str,
        target: str,
        provider: ProviderDescriptor,
        findings: list[Finding],
        reconciliations: Sequence[FindingReconciliation],
        context: ContextPackage,
        historical_files: dict[str, str] | None = None,
    ) -> list[Finding]:
        review_id = self._review_id(branch, snapshot, target, provider)
        with self._transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO reviews
                (id, branch, snapshot, commit_oid, target, provider_id, provider_model, status,
                 complete_context, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                (
                    review_id,
                    branch,
                    snapshot,
                    commit,
                    target,
                    provider.id,
                    provider.model_name,
                    int(self._complete_context(context)),
                    self._now(),
                ),
            )
            recorded = [
                self._record_finding(
                    connection,
                    review_id,
                    branch,
                    snapshot,
                    commit,
                    target,
                    provider,
                    finding,
                    historical_files,
                )
                for finding in findings
            ]
            reported = {finding.id for finding in recorded}
            self._apply_reconciliations(
                connection,
                review_id,
                branch,
                snapshot,
                commit,
                context,
                reconciliations,
                reported,
                historical_files,
            )
            return recorded

    def reconciliation_candidates(self, branch: str, paths: list[str]) -> list[dict[str, Any]]:
        self.refresh_repository_changes(branch)
        normalized = sorted(set(paths))
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        with self._connection() as connection:
            rows = connection.execute(
                f"""SELECT id, category, title, explanation, impact, path, symbol, lifecycle
                FROM findings WHERE branch = ? AND path IN ({placeholders})
                AND lifecycle IN ('open', 'needs_rereview') ORDER BY updated_at DESC""",  # noqa: S608
                (branch, *normalized),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_paths_changed(
        self,
        branch: str,
        paths: list[str],
        commit: str,
        *,
        reason: str = "relevant_commit",
    ) -> int:
        changed = sorted(set(paths))
        if not changed:
            return 0
        placeholders = ",".join("?" for _ in changed)
        with self._transaction() as connection:
            rows = connection.execute(
                f"""SELECT id, lifecycle FROM findings WHERE branch = ?
                AND path IN ({placeholders}) AND lifecycle != 'dismissed'""",  # noqa: S608
                (branch, *changed),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE findings SET lifecycle = ?, last_commit = ?, updated_at = ?
                    WHERE id = ?""",
                    (
                        FindingLifecycle.NEEDS_REREVIEW.value,
                        commit,
                        self._now(),
                        str(row["id"]),
                    ),
                )
                self._transition(
                    connection,
                    str(row["id"]),
                    str(row["lifecycle"]),
                    FindingLifecycle.NEEDS_REREVIEW.value,
                    reason,
                    None,
                    commit,
                )
            return len(rows)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", "list"))
        branch = str(payload.get("branch") or self.current_branch())
        if action == "list":
            lifecycle = str(payload.get("lifecycle", "")) or None
            return {"items": self.list(branch=branch, lifecycle=lifecycle)}
        finding_id = str(payload.get("findingId", ""))
        if not finding_id:
            raise CodePreflightError("finding_id_required", "Select a finding")
        if action == "detail":
            return self.detail(finding_id)
        if action in {"dismiss", "reopen"}:
            if not request_flag(payload, "approved"):
                raise CodePreflightError(
                    "finding_action_approval_required",
                    "Finding lifecycle changes require explicit approval",
                )
            return self._manual_transition(action, finding_id, str(payload.get("reason", "")))
        raise CodePreflightError(
            "invalid_finding_action", "Finding action must be list, detail, dismiss, or reopen"
        )

    def list(self, *, branch: str, lifecycle: str | None = None) -> list[dict[str, Any]]:
        self.refresh_repository_changes(branch)
        query = "SELECT * FROM findings WHERE branch = ?"
        parameters: list[Any] = [branch]
        if lifecycle:
            if lifecycle not in {item.value for item in FindingLifecycle}:
                raise CodePreflightError("invalid_finding_lifecycle", f"Unknown state: {lifecycle}")
            query += " AND lifecycle = ?"
            parameters.append(lifecycle)
        query += (
            " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, updated_at DESC"
        )
        with self._connection() as connection:
            return [self._public(row) for row in connection.execute(query, parameters).fetchall()]

    def refresh_repository_changes(self, branch: str) -> int:
        if branch != self.current_branch():
            return 0
        head = self.current_commit()
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id, path, last_commit, lifecycle FROM findings
                WHERE branch = ? AND lifecycle != 'dismissed' AND last_commit != ?""",
                (branch, head),
            ).fetchall()
        affected = self._affected_finding_ids(rows, head)
        if not affected:
            return 0
        with self._transaction() as connection:
            for finding_id in affected:
                row = connection.execute(
                    "SELECT lifecycle FROM findings WHERE id = ?", (finding_id,)
                ).fetchone()
                if row is None:
                    continue
                current = str(row["lifecycle"])
                connection.execute(
                    """UPDATE findings SET lifecycle = ?, last_commit = ?, updated_at = ?
                    WHERE id = ?""",
                    (
                        FindingLifecycle.NEEDS_REREVIEW.value,
                        head,
                        self._now(),
                        finding_id,
                    ),
                )
                self._transition(
                    connection,
                    finding_id,
                    current,
                    FindingLifecycle.NEEDS_REREVIEW.value,
                    "repository_commit_changed_evidence",
                    None,
                    head,
                )
        return len(affected)

    def _affected_finding_ids(self, rows: Sequence[sqlite3.Row], head: str) -> Sequence[str]:
        changes: dict[str, set[str]] = {}
        unavailable: set[str] = set()
        affected = []
        git = GitRunner(self.root)
        for row in rows:
            previous = str(row["last_commit"])
            if previous not in changes:
                exists = (
                    git.run("cat-file", "-e", f"{previous}^{{commit}}", check=False).returncode == 0
                )
                output = (
                    git.run("diff", "--name-only", "-z", previous, head, "--").stdout
                    if exists
                    else ""
                )
                if not exists:
                    unavailable.add(previous)
                changes[previous] = {path for path in output.split("\0") if path}
            if previous in unavailable or str(row["path"]) in changes[previous]:
                affected.append(str(row["id"]))
        return affected

    def detail(self, finding_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            finding = connection.execute(
                "SELECT * FROM findings WHERE id = ?", (finding_id,)
            ).fetchone()
            if finding is None:
                raise CodePreflightError("finding_not_found", f"Unknown finding: {finding_id}")
            occurrences = connection.execute(
                """SELECT review_id, snapshot, commit_oid, target, severity, verification,
                evidence_json, observed_at FROM occurrences WHERE finding_id = ?
                ORDER BY observed_at DESC""",
                (finding_id,),
            ).fetchall()
            transitions = connection.execute(
                """SELECT from_state, to_state, reason, review_id, commit_oid, created_at
                FROM transitions WHERE finding_id = ? ORDER BY id DESC""",
                (finding_id,),
            ).fetchall()
        return {
            "finding": self._public(finding),
            "occurrences": [self._occurrence(row) for row in occurrences],
            "transitions": [dict(row) for row in transitions],
        }

    def current_branch(self) -> str:
        branch = (
            GitRunner(self.root)
            .run("symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            .stdout.strip()
        )
        if branch:
            return branch
        commit = GitRunner(self.root).run("rev-parse", "--short", "HEAD").stdout.strip()
        return f"detached:{commit}"

    def current_commit(self) -> str:
        return GitRunner(self.root).run("rev-parse", "HEAD").stdout.strip()

    def _record_finding(
        self,
        connection: sqlite3.Connection,
        review_id: str,
        branch: str,
        snapshot: str,
        commit: str,
        target: str,
        provider: ProviderDescriptor,
        finding: Finding,
        historical_files: dict[str, str] | None,
    ) -> Finding:
        anchor = self._anchor(finding, historical_files)
        existing = self._match(connection, branch, finding, anchor)
        finding_id = str(existing["id"]) if existing else f"cpf-{uuid4().hex[:20]}"
        previous = str(existing["lifecycle"]) if existing else None
        lifecycle = self._observed_lifecycle(previous)
        now = self._now()
        values = (
            finding_id,
            branch,
            finding.category.value,
            anchor["key"],
            anchor["path"],
            anchor["symbol"],
            anchor["evidence_digest"],
            anchor["claim_digest"],
            finding.title,
            finding.explanation,
            finding.impact,
            finding.recommendation,
            finding.severity.value,
            finding.legacy_severity,
            finding.confidence.value,
            finding.verification.value,
            lifecycle,
            snapshot,
            snapshot,
            commit,
            target,
            provider.id,
            provider.model_name,
            now,
            now,
        )
        connection.execute(
            """INSERT INTO findings
            (id, branch, category, anchor_key, path, symbol, evidence_digest, claim_digest,
             title, explanation, impact, recommendation, severity, legacy_severity, confidence,
             verification, lifecycle, first_seen_snapshot, last_seen_snapshot, last_commit,
             target, provider_id, provider_model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET anchor_key=excluded.anchor_key, path=excluded.path,
             symbol=excluded.symbol, evidence_digest=excluded.evidence_digest,
             claim_digest=excluded.claim_digest, title=excluded.title,
             explanation=excluded.explanation, impact=excluded.impact,
             recommendation=excluded.recommendation, severity=excluded.severity,
             confidence=excluded.confidence, verification=excluded.verification,
             lifecycle=excluded.lifecycle, last_seen_snapshot=excluded.last_seen_snapshot,
             last_commit=excluded.last_commit, target=excluded.target,
             provider_id=excluded.provider_id, provider_model=excluded.provider_model,
             updated_at=excluded.updated_at""",
            values,
        )
        connection.execute(
            """INSERT OR IGNORE INTO occurrences
            (finding_id, review_id, snapshot, commit_oid, target, severity, verification,
             evidence_json, observed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding_id,
                review_id,
                snapshot,
                commit,
                target,
                finding.severity.value,
                finding.verification.value,
                json.dumps([item.model_dump(mode="json") for item in finding.evidence]),
                now,
            ),
        )
        if previous and previous != lifecycle:
            self._transition(
                connection,
                finding_id,
                previous,
                lifecycle,
                "finding_reappeared",
                review_id,
                commit,
            )
        return finding.model_copy(
            update={"id": finding_id, "lifecycle": FindingLifecycle(lifecycle)}
        )

    def _apply_reconciliations(
        self,
        connection: sqlite3.Connection,
        review_id: str,
        branch: str,
        snapshot: str,
        commit: str,
        context: ContextPackage,
        reconciliations: Sequence[FindingReconciliation],
        reported: set[str],
        historical_files: dict[str, str] | None,
    ) -> None:
        for evaluation in reconciliations:
            row = connection.execute(
                "SELECT id, lifecycle, path FROM findings WHERE id = ? AND branch = ?",
                (evaluation.finding_id, branch),
            ).fetchone()
            if row is None or evaluation.finding_id in reported:
                continue
            if not self._path_in_context(str(row["path"]), context):
                continue
            current = str(row["lifecycle"])
            destination = self._evaluated_lifecycle(
                evaluation, context, str(row["path"]), historical_files
            )
            if current == FindingLifecycle.DISMISSED.value or current == destination:
                continue
            connection.execute(
                """UPDATE findings SET lifecycle = ?, last_evaluated_snapshot = ?,
                last_commit = ?, updated_at = ? WHERE id = ?""",
                (destination, snapshot, commit, self._now(), evaluation.finding_id),
            )
            self._transition(
                connection,
                evaluation.finding_id,
                current,
                destination,
                f"provider_{evaluation.outcome}:{evaluation.explanation[:300]}",
                review_id,
                commit,
            )

    def _evaluated_lifecycle(
        self,
        evaluation: FindingReconciliation,
        context: ContextPackage,
        prior_path: str,
        historical_files: dict[str, str] | None,
    ) -> str:
        if evaluation.outcome == "present":
            return FindingLifecycle.OPEN.value
        if evaluation.outcome != "resolved":
            return FindingLifecycle.NEEDS_REREVIEW.value
        if not self._resolution_confirmed(evaluation, context, prior_path, historical_files):
            return FindingLifecycle.NEEDS_REREVIEW.value
        return FindingLifecycle.RESOLVED.value

    def _resolution_confirmed(
        self,
        evaluation: FindingReconciliation,
        context: ContextPackage,
        prior_path: str,
        historical_files: dict[str, str] | None,
    ) -> bool:
        included = self._included_paths(context)
        if prior_path not in included or not evaluation.evidence:
            return False
        return all(
            evidence.path in included
            and self._evidence_exists(evidence.path, evidence.start_line, historical_files)
            for evidence in evaluation.evidence
        )

    def _path_in_context(self, path: str, context: ContextPackage) -> bool:
        return path in self._included_paths(context)

    def _included_paths(self, context: ContextPackage) -> set[str]:
        manifest_paths = {entry.path for entry in context.manifest.entries}
        included = {
            entry.path
            for entry in context.manifest.entries
            if entry.status in {"included", "redacted"}
        }
        return included | {path for path in context.changed_files if path not in manifest_paths}

    def _evidence_exists(
        self, path: str, line: int, historical_files: dict[str, str] | None
    ) -> bool:
        if historical_files is not None:
            content = historical_files.get(path)
            return content is not None and line <= len(content.splitlines())
        candidate = (self.root / path).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            return False
        with candidate.open("r", encoding="utf-8", errors="replace") as handle:
            return any(index >= line for index, _ in enumerate(handle, start=1))

    def _match(
        self,
        connection: sqlite3.Connection,
        branch: str,
        finding: Finding,
        anchor: dict[str, str],
    ) -> sqlite3.Row | None:
        rows = connection.execute(
            """SELECT id, lifecycle, anchor_key, path, symbol, evidence_digest, claim_digest
            FROM findings WHERE branch = ? AND category = ?""",
            (branch, finding.category.value),
        ).fetchall()
        exact = [row for row in rows if row["anchor_key"] == anchor["key"]]
        if len(exact) == 1:
            return exact[0]
        relaxed = [row for row in rows if self._relaxed_match(row, anchor)]
        return relaxed[0] if len(relaxed) == 1 else None

    def _relaxed_match(self, row: sqlite3.Row, anchor: dict[str, str]) -> bool:
        if not anchor["evidence_digest"] or row["evidence_digest"] != anchor["evidence_digest"]:
            return False
        if row["claim_digest"] != anchor["claim_digest"]:
            return False
        return not anchor["symbol"] or row["symbol"] == anchor["symbol"]

    def _anchor(self, finding: Finding, historical_files: dict[str, str] | None) -> dict[str, str]:
        primary = finding.evidence[0]
        path = primary.path
        symbol = self._normalize(primary.symbol or "")
        evidence = self._evidence_text(finding, historical_files)
        evidence_digest = hashlib.sha256(evidence.encode()).hexdigest() if evidence else ""
        claim = self._normalize(f"{finding.explanation} {finding.impact} {finding.recommendation}")
        claim_digest = hashlib.sha256(claim.encode()).hexdigest()
        material = "|".join((finding.category.value, path, symbol, evidence_digest, claim_digest))
        return {
            "key": hashlib.sha256(material.encode()).hexdigest(),
            "path": path,
            "symbol": symbol,
            "evidence_digest": evidence_digest,
            "claim_digest": claim_digest,
        }

    def _evidence_text(self, finding: Finding, historical_files: dict[str, str] | None) -> str:
        sections: list[str] = []
        for location in finding.evidence:
            content = (
                historical_files.get(location.path)
                if historical_files is not None
                else self._read_worktree_file(location.path)
            )
            if content is None:
                continue
            lines = content.splitlines()
            selected = lines[location.start_line - 1 : location.end_line]
            sections.append(self._normalize("\n".join(selected)))
        return "\n".join(sections)

    def _read_worktree_file(self, relative: str) -> str | None:
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            return None
        with candidate.open("rb") as handle:
            content = handle.read(1_000_001)
        if len(content) > 1_000_000 or b"\0" in content:
            return None
        return content.decode("utf-8", errors="replace")

    def _manual_transition(self, action: str, finding_id: str, reason: str) -> dict[str, Any]:
        destination = (
            FindingLifecycle.DISMISSED.value if action == "dismiss" else FindingLifecycle.OPEN.value
        )
        if action == "dismiss" and not reason.strip():
            raise CodePreflightError("dismissal_reason_required", "Explain why this is dismissed")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT lifecycle FROM findings WHERE id = ?", (finding_id,)
            ).fetchone()
            if row is None:
                raise CodePreflightError("finding_not_found", f"Unknown finding: {finding_id}")
            current = str(row["lifecycle"])
            connection.execute(
                """UPDATE findings SET lifecycle = ?, dismissal_reason = ?, updated_at = ?
                WHERE id = ?""",
                (
                    destination,
                    reason.strip() if action == "dismiss" else None,
                    self._now(),
                    finding_id,
                ),
            )
            self._transition(
                connection,
                finding_id,
                current,
                destination,
                reason.strip() or "manually_reopened",
                None,
                self.current_commit(),
            )
        return self.detail(finding_id)

    def _transition(
        self,
        connection: sqlite3.Connection,
        finding_id: str,
        source: str,
        destination: str,
        reason: str,
        review_id: str | None,
        commit: str | None,
    ) -> None:
        if source == destination:
            return
        connection.execute(
            """INSERT INTO transitions
            (finding_id, from_state, to_state, reason, review_id, commit_oid, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (finding_id, source, destination, reason, review_id, commit, self._now()),
        )

    def _public(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        for key in ("anchor_key", "evidence_digest", "claim_digest"):
            value.pop(key, None)
        return value

    def _occurrence(self, row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        return value

    def _observed_lifecycle(self, previous: str | None) -> str:
        if previous == FindingLifecycle.DISMISSED.value:
            return previous
        return FindingLifecycle.OPEN.value

    def _complete_context(self, context: ContextPackage) -> bool:
        relevant = set(context.changed_files)
        incomplete = {
            entry.path
            for entry in context.manifest.entries
            if entry.status in {"excluded", "truncated"}
        }
        return not bool(relevant & incomplete)

    def _review_id(
        self, branch: str, snapshot: str, target: str, provider: ProviderDescriptor
    ) -> str:
        material = f"{branch}|{snapshot}|{target}|{provider.id}|{provider.model_name}"
        return hashlib.sha256(material.encode()).hexdigest()

    def _normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._open()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _open(self) -> sqlite3.Connection:
        self.directory.mkdir(parents=True, exist_ok=True)
        reject_symlink_path(self.directory)
        if self.path.is_symlink():
            raise CodePreflightError(
                "unsafe_state_path", f"Refusing finding DB symlink: {self.path}"
            )
        try:
            connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            self._migrate(connection)
            os.chmod(self.path, 0o600)
            return connection
        except sqlite3.Error as error:
            raise CodePreflightError(
                "finding_ledger_error", "Cannot open the private finding ledger"
            ) from error

    def _migrate(self, connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise CodePreflightError(
                "finding_ledger_newer_version", "Finding ledger was created by a newer Preflight"
            )
        if version == SCHEMA_VERSION:
            return
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, branch TEXT NOT NULL, snapshot TEXT NOT NULL, commit_oid TEXT NOT NULL,
  target TEXT NOT NULL, provider_id TEXT NOT NULL, provider_model TEXT, status TEXT NOT NULL,
  complete_context INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY, branch TEXT NOT NULL, category TEXT NOT NULL, anchor_key TEXT NOT NULL,
  path TEXT NOT NULL, symbol TEXT NOT NULL, evidence_digest TEXT NOT NULL,
  claim_digest TEXT NOT NULL, title TEXT NOT NULL, explanation TEXT NOT NULL,
  impact TEXT NOT NULL, recommendation TEXT NOT NULL, severity TEXT NOT NULL,
  legacy_severity TEXT, confidence TEXT NOT NULL, verification TEXT NOT NULL,
  lifecycle TEXT NOT NULL, first_seen_snapshot TEXT NOT NULL, last_seen_snapshot TEXT NOT NULL,
  last_evaluated_snapshot TEXT, last_commit TEXT NOT NULL, target TEXT NOT NULL,
  provider_id TEXT NOT NULL, provider_model TEXT, dismissal_reason TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS findings_branch_state ON findings(branch, lifecycle);
CREATE INDEX IF NOT EXISTS findings_anchor ON findings(branch, category, anchor_key);
CREATE TABLE IF NOT EXISTS occurrences (
  id INTEGER PRIMARY KEY AUTOINCREMENT, finding_id TEXT NOT NULL REFERENCES findings(id),
  review_id TEXT NOT NULL REFERENCES reviews(id), snapshot TEXT NOT NULL, commit_oid TEXT NOT NULL,
  target TEXT NOT NULL, severity TEXT NOT NULL, verification TEXT NOT NULL,
  evidence_json TEXT NOT NULL, observed_at TEXT NOT NULL,
  UNIQUE(finding_id, review_id)
);
CREATE TABLE IF NOT EXISTS transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, finding_id TEXT NOT NULL REFERENCES findings(id),
  from_state TEXT NOT NULL, to_state TEXT NOT NULL, reason TEXT NOT NULL,
  review_id TEXT REFERENCES reviews(id), commit_oid TEXT, created_at TEXT NOT NULL
);
"""
