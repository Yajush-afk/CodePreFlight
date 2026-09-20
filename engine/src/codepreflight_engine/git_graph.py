from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .git import GitRunner


class GitGraphBuilder:
    """Bounded two-ref graph data; no colored log parsing or remote operations."""

    def build(self, root: Path, snapshot: Any) -> dict[str, Any]:
        git = GitRunner(root)
        current = snapshot.branch or "detached HEAD"
        head = git.run("rev-parse", "--verify", "HEAD", check=False).stdout.strip()
        base = snapshot.base_branch
        base_oid = self._resolve(git, base)
        dual = bool(base_oid and base != current)
        merge = (
            git.run("merge-base", head, base_oid, check=False).stdout.strip()
            if dual and head
            else ""
        )
        lanes = [{"id": "base" if base == current else "current", "label": current}]
        if dual:
            lanes = [{"id": "base", "label": base}, {"id": "current", "label": current}]
        commits = self._commits(git, head, base_oid, dual, lanes[0]["id"])
        if merge and not any(item["oid"] == merge for item in commits):
            parents, subject = (
                git.run("show", "-s", "--format=%P%x00%s", merge).stdout.strip().split("\0", 1)
            )
            commits.append(
                {"oid": merge, "parents": parents.split(), "subject": subject, "lane": "shared"}
            )
        result = {
            "lanes": lanes,
            "commits": commits,
            "mergeBase": merge or None,
            "head": head or None,
            "base": base,
            "current": current,
            "workingTree": {
                "staged": sum(item.staged for item in snapshot.files),
                "unstaged": sum(item.unstaged for item in snapshot.files),
                "untracked": sum(item.untracked for item in snapshot.files),
            },
            "note": None
            if base_oid
            else "Base not detected; configure git.base_branch, then /status",
            "localOnly": True,
        }
        result["fingerprint"] = hashlib.sha256(
            json.dumps(result, sort_keys=True).encode()
        ).hexdigest()
        return result

    def _resolve(self, git: GitRunner, branch: str | None) -> str:
        if not branch:
            return ""
        result = git.run(
            "rev-parse", "--verify", "--end-of-options", f"{branch}^{{commit}}", check=False
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def _commits(
        self, git: GitRunner, head: str, base: str, dual: bool, lane: str
    ) -> list[dict[str, Any]]:
        if not head:
            return []
        arguments = ["log", "--topo-order", "--max-count=20", "--format=%m%x00%H%x00%P%x00%s"]
        arguments.extend(["--left-right", "--boundary", f"{base}...{head}"] if dual else [head])
        output = git.run(*arguments, "--").stdout
        commits = []
        for line in output.splitlines():
            parts = line.split("\0", 3)
            if len(parts) != 4:
                continue
            marker, oid, parents, subject = parts
            assigned = (
                {"<": "base", ">": "current", "-": "shared"}.get(marker, lane) if dual else lane
            )
            commits.append(
                {"oid": oid, "parents": parents.split(), "subject": subject, "lane": assigned}
            )
        return commits
