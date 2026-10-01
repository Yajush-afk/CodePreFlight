from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner
from .git_operations import GitOperationService
from .repository import RepositoryInspector
from .request_values import request_flag


class GitActions:
    """Conservative, confirmation-gated Git mutations."""

    def run(self, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        root = GitRunner(path).root()
        action = str(payload.get("action", ""))
        branch = str(payload.get("branch", ""))
        service = GitOperationService(root)
        if action == "plan":
            plan = service.plan(str(payload.get("operation", "")), payload)
            return plan.model_dump(mode="json")
        if action == "execute":
            result = service.execute(str(payload.get("planId", "")), payload)
            return result.model_dump(mode="json")
        if action == "hunks":
            return service.hunks(str(payload.get("path", "")), str(payload.get("area", "")))
        if action == "switch_preview":
            return self._preview(root, branch)
        if action == "switch_execute":
            if not request_flag(payload, "approved"):
                raise CodePreflightError(
                    "git_action_approval_required", "Branch switching requires explicit approval"
                )
            expected_head = str(payload.get("expectedHead", ""))
            current_head = GitRunner(root).run("rev-parse", "HEAD").stdout.strip()
            if not expected_head or current_head != expected_head:
                raise CodePreflightError(
                    "repository_state_changed",
                    "Repository HEAD changed after the branch-switch preview; preview it again",
                    recoverable=True,
                )
            expected_target = str(payload.get("targetOid", ""))
            current_target = GitRunner(root).run("rev-parse", f"refs/heads/{branch}").stdout.strip()
            if not expected_target or current_target != expected_target:
                raise CodePreflightError(
                    "repository_state_changed",
                    "The destination branch changed after preview; preview it again",
                    recoverable=True,
                )
            preview = self._preview(root, branch)
            if not preview["allowed"]:
                raise CodePreflightError(
                    "branch_switch_unsafe",
                    "Branch switch would overwrite local paths",
                    recoverable=True,
                    details=preview,
                )
            GitRunner(root).run("switch", "--no-guess", branch, mutability="mutating")
            snapshot = RepositoryInspector().inspect(root)
            return {
                "branch": snapshot.branch,
                "previousBranch": preview["currentBranch"],
                "repository": snapshot.model_dump(mode="json"),
            }
        raise CodePreflightError(
            "invalid_git_action",
            "Git action must be plan, execute, hunks, switch_preview, or switch_execute",
        )

    def _preview(self, root: Path, branch: str) -> dict[str, Any]:
        if not branch or branch.startswith("-"):
            raise CodePreflightError("invalid_branch", "Select an existing local branch")
        git = GitRunner(root)
        exists = git.run("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
        if exists.returncode != 0:
            raise CodePreflightError(
                "local_branch_not_found",
                f"Local branch `{branch}` does not exist; "
                "CodePreflight will not create or fetch it",
                recoverable=True,
            )
        snapshot = RepositoryInspector().inspect(root)
        if not snapshot.branch:
            raise CodePreflightError(
                "branch_switch_detached_head",
                "Return to a named local branch before switching through CodePreflight",
                recoverable=True,
            )
        active = self._active_operation(git)
        if active or snapshot.conflicts:
            raise CodePreflightError(
                "git_operation_active",
                f"Resolve the active {active or 'conflict'} state before switching branches",
                recoverable=True,
                details={"operation": active, "conflicts": snapshot.conflicts},
            )
        expected_head = git.run("rev-parse", "HEAD").stdout.strip()
        target_oid = git.run("rev-parse", f"refs/heads/{branch}").stdout.strip()
        differing = set(
            filter(
                None,
                git.run("diff", "--name-only", "-z", "HEAD", target_oid).stdout.split("\0"),
            )
        )
        dirty = {item.path for item in snapshot.files if not item.untracked and not item.ignored}
        untracked = {item.path for item in snapshot.files if item.untracked}
        target_paths = set(
            filter(
                None,
                git.run("ls-tree", "-r", "-z", "--name-only", target_oid).stdout.split("\0"),
            )
        )
        collisions = sorted((dirty & differing) | (untracked & target_paths))
        preserved = sorted((dirty | untracked) - set(collisions))
        return {
            "allowed": not collisions,
            "currentBranch": snapshot.branch,
            "targetBranch": branch,
            "expectedHead": expected_head,
            "targetOid": target_oid,
            "preservedPaths": preserved,
            "collisions": collisions,
        }

    def _active_operation(self, git: GitRunner) -> str | None:
        git_dir = Path(git.run("rev-parse", "--git-dir").stdout.strip())
        if not git_dir.is_absolute():
            git_dir = (git.cwd / git_dir).resolve()
        for name, markers in (
            ("merge", ("MERGE_HEAD",)),
            ("rebase", ("rebase-merge", "rebase-apply")),
            ("cherry-pick", ("CHERRY_PICK_HEAD",)),
            ("revert", ("REVERT_HEAD",)),
        ):
            if any((git_dir / marker).exists() for marker in markers):
                return name
        return None
