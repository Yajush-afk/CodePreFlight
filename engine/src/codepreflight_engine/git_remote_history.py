from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .errors import CodePreflightError
from .git import GitRunner
from .models import (
    ConflictState,
    GitConfirmation,
    GitOperationRisk,
)
from .repository import RepositoryInspector

REMOTE_HISTORY_ACTIONS = {
    "fetch_remote",
    "pull_ff",
    "push_branch",
    "push_set_upstream",
    "force_push",
    "merge",
    "rebase",
    "cherry_pick",
    "revert",
    "reset",
    "clean_paths",
}


@dataclass(frozen=True)
class GitPlanDraft:
    action: str
    arguments: list[str]
    parameters: dict[str, Any]
    risk: GitOperationRisk
    confirmation: GitConfirmation
    preview: str
    effects: list[str]
    limitations: list[str]
    paths: list[str] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)
    source: str | None = None
    destination: str | None = None
    hook_involvement: bool = False
    editor_involvement: bool = False
    credential_helper_involvement: bool = False


@dataclass(frozen=True)
class GitExecutionOutcome:
    status: Literal["completed", "failed", "cancelled", "conflicted"]
    message: str
    exit_code: int
    conflict: ConflictState | None = None
    changed_paths: list[str] = field(default_factory=list)


class RemoteHistoryWorkflow:
    """Plans and executes explicit network and history-changing Git actions."""

    def __init__(self, root: Path) -> None:
        self.root = GitRunner(root).root()
        self.git = GitRunner(self.root)

    def supports(self, action: str) -> bool:
        return action in REMOTE_HISTORY_ACTIONS

    def plan(self, action: str, parameters: dict[str, Any]) -> GitPlanDraft:
        if action == "fetch_remote":
            return self._plan_fetch(parameters)
        if action in {"pull_ff", "push_branch", "push_set_upstream", "force_push"}:
            return self._plan_remote_branch(action, parameters)
        if action in {"merge", "rebase", "cherry_pick", "revert"}:
            return self._plan_history(action, parameters)
        if action == "reset":
            return self._plan_reset(parameters)
        if action == "clean_paths":
            return self._plan_clean(parameters)
        raise CodePreflightError("unsupported_git_operation", "Unsupported Git operation")

    def execute(
        self,
        action: str,
        parameters: dict[str, Any],
    ) -> GitExecutionOutcome:
        arguments = self._execution_arguments(action, parameters)
        timeout = 300 if action in self._network_actions() else 180
        result = self.git.run(
            *arguments,
            check=False,
            timeout=timeout,
            mutability="network_mutating" if action in self._network_actions() else "mutating",
        )
        if result.returncode != 0:
            return self._failed_outcome(action, result.returncode, result.stderr, result.stdout)
        changed = self._changed_since(parameters.get("oldHead"))
        if action == "reset":
            affected = parameters.get("affectedPaths", [])
            if isinstance(affected, list):
                changed = list(dict.fromkeys([*changed, *affected]))
        if action == "clean_paths":
            changed = list(parameters["paths"])
        return GitExecutionOutcome(
            status="completed",
            message=f"Completed {action.replace('_', ' ')}",
            exit_code=0,
            changed_paths=changed,
        )

    def _plan_fetch(self, parameters: dict[str, Any]) -> GitPlanDraft:
        remote = self._remote(parameters.get("remote"))
        refs = self._remote_refs(remote)
        return GitPlanDraft(
            action="fetch_remote",
            arguments=["fetch", remote],
            parameters={"remote": remote},
            risk=GitOperationRisk.LOW,
            confirmation=GitConfirmation.EXPLICIT,
            preview=f"Fetch updated references from remote {remote}",
            effects=[f"Update locally known refs/remotes/{remote}/*"],
            limitations=["Fetching does not merge, rebase, switch, or edit working files"],
            refs=refs,
            source=remote,
            credential_helper_involvement=True,
        )

    def _plan_remote_branch(self, action: str, parameters: dict[str, Any]) -> GitPlanDraft:
        snapshot = RepositoryInspector().inspect(self.root)
        branch = self._branch(parameters.get("branch") or snapshot.branch)
        remote = self._remote(parameters.get("remote") or self._upstream_remote(snapshot.upstream))
        tracking_ref = f"refs/remotes/{remote}/{branch}"
        tracking_oid = self._optional_oid(tracking_ref)
        if action == "pull_ff":
            self._require_named_branch(snapshot.branch)
            self._require_clean(snapshot)
            self._require_no_active_operation(snapshot.conflicts)
            arguments = ["pull", "--ff-only", remote, branch]
            effect = f"Fast-forward {snapshot.branch} from {remote}/{branch} if possible"
            risk = GitOperationRisk.MEDIUM
        elif action == "force_push":
            self._require_named_branch(snapshot.branch)
            if not tracking_oid:
                raise CodePreflightError(
                    "force_push_lease_unavailable",
                    f"Fetch {remote}/{branch} before planning a force-push lease",
                    recoverable=True,
                )
            lease = f"refs/heads/{branch}:{tracking_oid}"
            arguments = ["push", f"--force-with-lease={lease}", remote, f"HEAD:refs/heads/{branch}"]
            effect = f"Replace {remote}/{branch} only if its OID is still {tracking_oid[:12]}"
            risk = GitOperationRisk.IRREVERSIBLE
        else:
            self._require_named_branch(snapshot.branch)
            arguments = ["push"]
            if action == "push_set_upstream":
                arguments.append("--set-upstream")
            arguments.extend([remote, f"HEAD:refs/heads/{branch}"])
            effect = f"Push local HEAD to {remote}/{branch} without force"
            risk = GitOperationRisk.MEDIUM
        confirmation = GitConfirmation.TYPED if action == "force_push" else GitConfirmation.EXPLICIT
        return GitPlanDraft(
            action=action,
            arguments=arguments,
            parameters={
                "remote": remote,
                "branch": branch,
                "trackingOid": tracking_oid,
                "oldHead": self._head(),
            },
            risk=risk,
            confirmation=confirmation,
            preview="\n".join((effect, f"Local HEAD: {self._head()[:12]}")),
            effects=[effect],
            limitations=[
                "Remote state is checked again by Git; rejected updates are never "
                "retried with force"
            ],
            refs={tracking_ref: tracking_oid or ""},
            source=snapshot.branch,
            destination=f"{remote}/{branch}",
            hook_involvement=True,
            credential_helper_involvement=True,
        )

    def _plan_history(self, action: str, parameters: dict[str, Any]) -> GitPlanDraft:
        snapshot = RepositoryInspector().inspect(self.root)
        self._require_named_branch(snapshot.branch)
        self._require_clean(snapshot)
        self._require_no_active_operation(snapshot.conflicts)
        revision = self._revision(parameters.get("revision"))
        target = self._commit_oid(revision)
        mainline = self._mainline(parameters.get("mainline"), target, action)
        arguments = self._history_arguments(action, target, mainline)
        risks = {
            "merge": GitOperationRisk.MEDIUM,
            "rebase": GitOperationRisk.HIGH,
            "cherry_pick": GitOperationRisk.MEDIUM,
            "revert": GitOperationRisk.MEDIUM,
        }
        effects = {
            "merge": f"Merge commit {target[:12]} into {snapshot.branch}",
            "rebase": f"Replay {snapshot.branch} onto commit {target[:12]}",
            "cherry_pick": f"Apply commit {target[:12]} onto {snapshot.branch}",
            "revert": f"Create a commit reverting {target[:12]}",
        }
        return GitPlanDraft(
            action=action,
            arguments=arguments,
            parameters={
                "targetOid": target,
                "mainline": mainline,
                "oldHead": self._head(),
            },
            risk=risks[action],
            confirmation=GitConfirmation.EXPLICIT,
            preview=effects[action],
            effects=[effects[action]],
            limitations=[
                "Conflicts are left for explicit inspection and recovery; "
                "Preflight never resolves them"
            ],
            source=snapshot.branch,
            destination=target,
            hook_involvement=True,
        )

    def _plan_reset(self, parameters: dict[str, Any]) -> GitPlanDraft:
        mode = str(parameters.get("mode", ""))
        if mode not in {"soft", "mixed", "hard"}:
            raise CodePreflightError(
                "invalid_reset_mode", "Reset mode must be soft, mixed, or hard"
            )
        target = self._commit_oid(self._revision(parameters.get("revision")))
        snapshot = RepositoryInspector().inspect(self.root)
        self._require_named_branch(snapshot.branch)
        self._require_no_active_operation(snapshot.conflicts)
        changed = [item.path for item in snapshot.files if not item.ignored]
        confirmation = GitConfirmation.TYPED if mode == "hard" else GitConfirmation.EXPLICIT
        risk = GitOperationRisk.IRREVERSIBLE if mode == "hard" else GitOperationRisk.HIGH
        limitations = ["Untracked and ignored files are not removed"]
        if mode == "hard":
            limitations.insert(0, "Tracked working-tree and index changes may be unrecoverable")
        return GitPlanDraft(
            action="reset",
            arguments=["reset", f"--{mode}", target],
            parameters={
                "mode": mode,
                "targetOid": target,
                "oldHead": self._head(),
                "affectedPaths": changed,
            },
            risk=risk,
            confirmation=confirmation,
            preview=(
                f"Reset {snapshot.branch} to {target[:12]} in {mode} mode\n"
                f"Current changed paths: {len(changed)}"
            ),
            effects=[f"Move {snapshot.branch} to {target[:12]} using reset --{mode}"],
            limitations=limitations,
            source=snapshot.branch,
            destination=target,
        )

    def _plan_clean(self, parameters: dict[str, Any]) -> GitPlanDraft:
        selected = self._safe_paths(parameters.get("paths"))
        snapshot = RepositoryInspector().inspect(self.root)
        available = {item.path: item for item in snapshot.files if item.untracked or item.ignored}
        missing = [path for path in selected if path not in available]
        if missing:
            raise CodePreflightError(
                "clean_paths_not_removable",
                "Clean is limited to currently untracked or ignored paths",
                details={"paths": missing},
            )
        expanded = self._expand_clean_paths(selected)
        if not expanded:
            raise CodePreflightError("clean_paths_empty", "No removable files were selected")
        return GitPlanDraft(
            action="clean_paths",
            arguments=["clean", "-f", "-x", "--", *expanded],
            parameters={"paths": expanded},
            risk=GitOperationRisk.IRREVERSIBLE,
            confirmation=GitConfirmation.TYPED,
            preview="Remove exactly these untracked or ignored files:\n" + "\n".join(expanded),
            effects=[f"Permanently remove {len(expanded)} selected untracked or ignored files"],
            limitations=[
                "Removed files may not be recoverable by Git",
                "Empty directories may remain",
            ],
            paths=expanded,
        )

    def _execution_arguments(self, action: str, parameters: dict[str, Any]) -> list[str]:
        if action == "fetch_remote":
            return ["fetch", str(parameters["remote"])]
        if action == "pull_ff":
            return ["pull", "--ff-only", str(parameters["remote"]), str(parameters["branch"])]
        if action in {"push_branch", "push_set_upstream", "force_push"}:
            return self._push_arguments(action, parameters)
        if action in {"merge", "rebase", "cherry_pick", "revert"}:
            return self._history_arguments(
                action,
                str(parameters["targetOid"]),
                parameters.get("mainline"),
            )
        if action == "reset":
            return ["reset", f"--{parameters['mode']}", str(parameters["targetOid"])]
        return ["clean", "-f", "-x", "--", *parameters["paths"]]

    def _push_arguments(self, action: str, parameters: dict[str, Any]) -> list[str]:
        remote = str(parameters["remote"])
        branch = str(parameters["branch"])
        arguments = ["push"]
        if action == "push_set_upstream":
            arguments.append("--set-upstream")
        if action == "force_push":
            lease = f"refs/heads/{branch}:{parameters['trackingOid']}"
            arguments.append(f"--force-with-lease={lease}")
        return [*arguments, remote, f"HEAD:refs/heads/{branch}"]

    def _history_arguments(self, action: str, target: str, mainline: object) -> list[str]:
        if action == "merge":
            return ["merge", "--no-edit", target]
        if action == "rebase":
            return ["rebase", target]
        arguments = [action.replace("_", "-")]
        if mainline is not None:
            arguments.extend(["-m", str(mainline)])
        if action == "revert":
            arguments.append("--no-edit")
        arguments.append(target)
        return arguments

    def _failed_outcome(
        self,
        action: str,
        exit_code: int,
        stderr: str,
        stdout: str,
    ) -> GitExecutionOutcome:
        snapshot = RepositoryInspector().inspect(self.root)
        active = self._active_operation()
        conflicted = bool(snapshot.conflicts) or active is not None
        conflict = None
        if conflicted:
            conflict = ConflictState(
                operation=active or action,
                files=snapshot.conflicts,
                can_continue=active in {"merge", "rebase", "cherry-pick", "revert"},
                can_abort=active in {"merge", "rebase", "cherry-pick", "revert"},
            )
        detail = stderr.strip() or stdout.strip() or f"Git refused {action}"
        return GitExecutionOutcome(
            status="conflicted" if conflicted else "failed",
            message=detail[-2_000:],
            exit_code=exit_code,
            conflict=conflict,
        )

    def _require_clean(self, snapshot: Any) -> None:
        changed = [item.path for item in snapshot.files if not item.ignored]
        if changed:
            raise CodePreflightError(
                "working_tree_not_clean",
                "Commit or stash working changes before this history operation",
                recoverable=True,
                details={"paths": changed},
            )

    def _require_named_branch(self, branch: str | None) -> None:
        if not branch:
            raise CodePreflightError(
                "named_branch_required", "Return to a named local branch first", recoverable=True
            )

    def _require_no_active_operation(self, conflicts: list[str]) -> None:
        active = self._active_operation()
        if active or conflicts:
            raise CodePreflightError(
                "git_operation_active",
                f"Resolve the active {active or 'conflict'} state before this Git action",
                recoverable=True,
                details={"operation": active, "conflicts": conflicts},
            )

    def _active_operation(self) -> str | None:
        git_dir = Path(self.git.run("rev-parse", "--absolute-git-dir").stdout.strip())
        for name, markers in (
            ("merge", ("MERGE_HEAD",)),
            ("rebase", ("rebase-merge", "rebase-apply")),
            ("cherry-pick", ("CHERRY_PICK_HEAD",)),
            ("revert", ("REVERT_HEAD",)),
        ):
            if any((git_dir / marker).exists() for marker in markers):
                return name
        return None

    def _remote(self, value: object) -> str:
        if not isinstance(value, str) or not value or value.startswith("-") or "\0" in value:
            raise CodePreflightError("invalid_remote", "Select a configured Git remote")
        remotes = self.git.run("remote").stdout.splitlines()
        if value not in remotes:
            raise CodePreflightError(
                "remote_not_found", f"Configured remote `{value}` was not found"
            )
        return value

    def _branch(self, value: object) -> str:
        if not isinstance(value, str) or not value or value.startswith("-"):
            raise CodePreflightError("invalid_branch", "Select a valid branch name")
        checked = self.git.run("check-ref-format", "--branch", value, check=False)
        if checked.returncode != 0:
            raise CodePreflightError("invalid_branch", f"Invalid branch name: {value}")
        return value

    def _revision(self, value: object) -> str:
        if not isinstance(value, str) or not value or value.startswith("-") or "\0" in value:
            raise CodePreflightError("invalid_revision", "Select a reachable local commit")
        return value

    def _commit_oid(self, revision: str) -> str:
        result = self.git.run(
            "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}", check=False
        )
        if result.returncode != 0:
            raise CodePreflightError("revision_not_found", f"Commit `{revision}` was not found")
        return result.stdout.strip()

    def _mainline(self, value: object, target: str, action: str) -> int | None:
        parents = self.git.run("rev-list", "--parents", "-n", "1", target).stdout.split()[1:]
        if action not in {"cherry_pick", "revert"}:
            return None
        if len(parents) <= 1:
            if value is not None:
                raise CodePreflightError(
                    "mainline_not_applicable", "Mainline is only for merge commits"
                )
            return None
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 1
            or value > len(parents)
        ):
            raise CodePreflightError(
                "mainline_required",
                f"Choose a mainline parent from 1 to {len(parents)} for this merge commit",
            )
        return value

    def _upstream_remote(self, upstream: str | None) -> str | None:
        return upstream.split("/", 1)[0] if upstream and "/" in upstream else None

    def _head(self) -> str:
        return self.git.run("rev-parse", "HEAD").stdout.strip()

    def _optional_oid(self, ref: str) -> str:
        result = self.git.run("rev-parse", "--verify", ref, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _remote_refs(self, remote: str) -> dict[str, str]:
        output = self.git.run(
            "for-each-ref", "--format=%(refname)%00%(objectname)", f"refs/remotes/{remote}/"
        ).stdout
        refs: dict[str, str] = {}
        for line in output.splitlines():
            name, separator, oid = line.partition("\0")
            if separator:
                refs[name] = oid
        return refs

    def _network_actions(self) -> set[str]:
        return {"fetch_remote", "pull_ff", "push_branch", "push_set_upstream", "force_push"}

    def _changed_since(self, old_head: object) -> list[str]:
        if not isinstance(old_head, str) or not old_head:
            return []
        current = self._head()
        if current == old_head:
            return []
        output = self.git.run("diff", "--name-only", "-z", old_head, current).stdout
        return [path for path in output.split("\0") if path]

    def _safe_paths(self, value: object) -> list[str]:
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) for item in value)
        ):
            raise CodePreflightError("git_paths_required", "Select at least one repository path")
        result: list[str] = []
        for path in value:
            if not path or path.startswith("/") or "\0" in path or ".." in Path(path).parts:
                raise CodePreflightError("invalid_git_path", f"Unsafe repository path: {path}")
            result.append(path)
        return list(dict.fromkeys(result))

    def _expand_clean_paths(self, selected: list[str]) -> list[str]:
        expanded: list[str] = []
        for path in selected:
            output = self.git.run(
                "ls-files",
                "--others",
                "--ignored",
                "--exclude-standard",
                "-z",
                "--",
                path,
            ).stdout
            output += self.git.run(
                "ls-files", "--others", "--exclude-standard", "-z", "--", path
            ).stdout
            matches = [item for item in output.split("\0") if item]
            expanded.extend(matches or [path])
        unique = list(dict.fromkeys(expanded))
        if len(unique) > 500:
            raise CodePreflightError("too_many_clean_paths", "Select at most 500 files at once")
        return unique

    def command(self, arguments: list[str]) -> str:
        return "git " + " ".join(json.dumps(value, ensure_ascii=True) for value in arguments)
