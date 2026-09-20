from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .automation import AutomationManager
from .errors import CodePreflightError
from .git import GitRunner
from .git_graph import GitGraphBuilder
from .repository import RepositoryInspector

MAX_TREE_ITEMS = 5_000
MAX_FILE_CHARACTERS = 40_000


class RepositoryWorkspace:
    """Read-only repository navigation for interactive and direct clients."""

    def run(self, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = RepositoryInspector().inspect(path)
        root = Path(snapshot.root)
        action = str(payload.get("action", "overview"))
        if action == "overview":
            return {"repository": snapshot.model_dump(mode="json")}
        if action == "graph":
            return GitGraphBuilder().build(root, snapshot)
        if action == "tree":
            return self._tree(root, snapshot)
        if action == "branches":
            return self._branches(root, snapshot.branch)
        if action == "commits":
            return self._commits(root, payload)
        if action == "file":
            return self._file(root, str(payload.get("path", "")))
        if action == "pr":
            return self._pull_request(root, snapshot)
        raise CodePreflightError(
            "invalid_workspace_action",
            "Workspace action must be overview, tree, branches, commits, file, or pr",
        )

    def _tree(self, root: Path, snapshot: Any) -> dict[str, Any]:
        git = GitRunner(root)
        tracked = {item for item in git.run("ls-files", "-z").stdout.split("\0") if item}
        untracked = {
            item
            for item in git.run("ls-files", "--others", "--exclude-standard", "-z").stdout.split(
                "\0"
            )
            if item
        }
        changes = {item.path: item for item in snapshot.files if not item.ignored}
        paths = sorted(tracked | untracked)
        items: list[dict[str, Any]] = []
        for relative in paths[:MAX_TREE_ITEMS]:
            change = changes.get(relative)
            if change is None:
                status = "clean"
            elif change.untracked:
                status = "untracked"
            elif change.staged and change.unstaged:
                status = "staged+modified"
            elif change.staged:
                status = f"staged-{change.kind.value}"
            else:
                status = change.kind.value
            items.append(
                {
                    "path": relative,
                    "status": status,
                    "tracked": relative in tracked,
                    "previousPath": change.previous_path if change else None,
                }
            )
        return {"items": items, "total": len(paths), "truncated": len(paths) > len(items)}

    def _branches(self, root: Path, current: str | None) -> dict[str, Any]:
        output = (
            GitRunner(root)
            .run(
                "for-each-ref",
                "--format=%(refname:short)%00%(objectname)%00%(upstream:short)%00%(subject)",
                "refs/heads",
            )
            .stdout
        )
        items = []
        for line in output.splitlines():
            fields = line.split("\0")
            if len(fields) != 4:
                continue
            name, oid, upstream, subject = fields
            items.append(
                {
                    "name": name,
                    "oid": oid,
                    "upstream": upstream or None,
                    "subject": subject,
                    "current": name == current,
                }
            )
        return {"current": current, "items": items}

    def _commits(self, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            limit = min(max(int(payload.get("limit", 50)), 1), 200)
        except (TypeError, ValueError) as error:
            raise CodePreflightError(
                "invalid_commit_limit", "Commit limit must be a number"
            ) from error
        output = (
            GitRunner(root)
            .run(
                "log",
                f"--max-count={limit}",
                "--date=iso-strict",
                "--format=%H%x00%h%x00%P%x00%an%x00%ad%x00%s",
            )
            .stdout
        )
        items = []
        for line in output.splitlines():
            fields = line.split("\0")
            if len(fields) != 6:
                continue
            oid, short, parents, author, authored_at, subject = fields
            parent_values = [value for value in parents.split() if value]
            items.append(
                {
                    "oid": oid,
                    "shortOid": short,
                    "parents": parent_values,
                    "merge": len(parent_values) > 1,
                    "author": author,
                    "authoredAt": authored_at,
                    "subject": subject,
                }
            )
        return {"items": items, "limit": limit}

    def _file(self, root: Path, relative: str) -> dict[str, Any]:
        candidate = (root / relative).resolve()
        try:
            normalized = candidate.relative_to(root).as_posix()
        except ValueError as error:
            raise CodePreflightError(
                "invalid_workspace_path", "File preview must remain inside the repository"
            ) from error
        if not relative or relative.startswith("/") or normalized == ".":
            raise CodePreflightError("invalid_workspace_path", "Select a repository file")
        git = GitRunner(root, max_output_bytes=MAX_FILE_CHARACTERS * 4)
        content = ""
        if candidate.is_file():
            raw = candidate.read_bytes()[: MAX_FILE_CHARACTERS + 1]
            if b"\0" in raw:
                content = "(binary file)"
            else:
                content = raw[:MAX_FILE_CHARACTERS].decode("utf-8", errors="replace")
        diff = git.run(
            "diff", "HEAD", "--no-ext-diff", "--unified=5", "--", normalized, check=False
        ).stdout[:MAX_FILE_CHARACTERS]
        return {
            "path": normalized,
            "content": content,
            "diff": diff or "(no working-tree diff)",
            "truncated": len(content) >= MAX_FILE_CHARACTERS or len(diff) >= MAX_FILE_CHARACTERS,
        }

    def _pull_request(self, root: Path, snapshot: Any) -> dict[str, Any]:
        if snapshot.github is None:
            raise CodePreflightError(
                "github_repository_required",
                "PR detection requires a GitHub remote",
                recoverable=True,
                details={"actions": [{"type": "open_configuration"}]},
            )
        if not snapshot.branch:
            raise CodePreflightError(
                "branch_required",
                "PR detection is unavailable in detached HEAD state",
                recoverable=True,
            )
        executable = shutil.which("gh")
        if not executable:
            raise CodePreflightError(
                "github_cli_missing",
                "Install GitHub CLI to detect pull requests",
                recoverable=True,
                details={"actions": [{"type": "authenticate_provider", "provider": "github"}]},
            )
        auth = subprocess.run(
            [executable, "auth", "status"], cwd=root, capture_output=True, text=True, timeout=15
        )
        if auth.returncode != 0:
            raise CodePreflightError(
                "github_authentication_required",
                "Authenticate GitHub CLI with `gh auth login` before PR detection",
                recoverable=True,
                details={"actions": [{"type": "authenticate_provider", "provider": "github"}]},
            )
        result = subprocess.run(
            [
                executable,
                "pr",
                "list",
                "--head",
                snapshot.branch,
                "--state",
                "open",
                "--limit",
                "10",
                "--json",
                "number,url,state,baseRefName,headRefOid",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            raise CodePreflightError(
                "github_pr_query_failed",
                result.stderr.strip() or "GitHub PR query failed",
                recoverable=True,
            )
        try:
            candidates = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise CodePreflightError(
                "github_pr_response_invalid", "GitHub CLI returned invalid JSON"
            ) from error
        if len(candidates) > 1:
            raise CodePreflightError(
                "github_pr_ambiguous",
                "Multiple open pull requests match this local branch",
                recoverable=True,
                details={"pullRequests": candidates},
            )
        local_head = GitRunner(root).run("rev-parse", "HEAD").stdout.strip()
        if not candidates:
            return {"found": False, "branch": snapshot.branch, "localHead": local_head}
        candidate = candidates[0]
        review_current = any(
            job.get("target") == "pull_request"
            and job.get("revision") == local_head
            and job.get("status") == "completed"
            for job in AutomationManager(root).status().get("jobs", [])
        )
        return {
            "found": True,
            "number": candidate["number"],
            "url": candidate["url"],
            "state": candidate["state"],
            "baseBranch": candidate["baseRefName"],
            "remoteHead": candidate["headRefOid"],
            "localHead": local_head,
            "localHeadMatches": candidate["headRefOid"] == local_head,
            "reviewFingerprintCurrent": review_current,
        }
