from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import ValidationError

from .errors import CodePreflightError
from .finding_ledger import FindingLedger
from .git import GitRunner
from .models import (
    GitConfirmation,
    GitOperationPlan,
    GitOperationResult,
    GitOperationRisk,
)
from .repository import RepositoryInspector
from .request_values import request_flag
from .state_files import atomic_write_json, reject_symlink_path, safe_read_text

PLAN_LIFETIME = timedelta(minutes=30)
PLAN_ID = re.compile(r"^[a-f0-9]{24}$")
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?P<context>.*)$")

FileAction = Literal["stage_files", "unstage_files", "discard_worktree"]
HunkAction = Literal["stage_hunks", "unstage_hunks"]


class GitOperationService:
    """Preview, persist, revalidate, and execute bounded Git mutations."""

    def __init__(self, root: Path) -> None:
        self.root = GitRunner(root).root()
        git_dir = Path(GitRunner(self.root).run("rev-parse", "--absolute-git-dir").stdout.strip())
        self.state_dir = git_dir / "codepreflight"
        self.plans_dir = self.state_dir / "git-plans"
        self.lock_path = self.state_dir / "git-operation.lock"

    def plan(self, action: str, parameters: dict[str, Any]) -> GitOperationPlan:
        self._cleanup_plans()
        if action in {"stage_files", "unstage_files", "discard_worktree"}:
            return self._plan_files(action, parameters)  # type: ignore[arg-type]
        if action in {"stage_hunks", "unstage_hunks"}:
            return self._plan_hunks(action, parameters)  # type: ignore[arg-type]
        if action == "commit":
            return self._plan_commit(parameters)
        raise CodePreflightError(
            "unsupported_git_operation",
            "This release can plan stage, unstage, discard-worktree, hunk, and commit actions",
        )

    def execute(self, plan_id: str, payload: dict[str, Any]) -> GitOperationResult:
        if not request_flag(payload, "approved"):
            raise CodePreflightError(
                "git_action_approval_required", "Git mutations require explicit approval"
            )
        with self._mutation_lock():
            stored = self._load_plan(plan_id)
            try:
                plan = GitOperationPlan.model_validate(stored["plan"])
            except (KeyError, ValidationError) as error:
                raise CodePreflightError(
                    "invalid_git_plan", "Stored Git preview is invalid"
                ) from error
            self._validate_stored_plan(plan_id, stored, plan)
            self._require_confirmation(plan, payload)
            self._require_fresh_plan(stored, plan)
            result = self._execute_stored(stored, plan)
            self._plan_path(plan_id).unlink(missing_ok=True)
            return result

    def hunks(self, path: str, area: str) -> dict[str, Any]:
        relative = self._paths([path])[0]
        if area not in {"unstaged", "staged"}:
            raise CodePreflightError("invalid_hunk_area", "Hunk area must be unstaged or staged")
        internal = self._read_hunks(relative, area)
        return {
            "path": relative,
            "area": area,
            "binary": internal["binary"],
            "hunks": [self._public_hunk(item) for item in internal["hunks"]],
        }

    def _plan_files(self, action: FileAction, parameters: dict[str, Any]) -> GitOperationPlan:
        paths = self._paths(parameters.get("paths"))
        self._validate_file_action(action, paths)
        paths = self._expand_renames(action, paths)
        command, risk, confirmation = self._file_action_metadata(action, paths)
        preview = self._file_preview(action, paths)
        effects = {
            "stage_files": ["Add the selected working-tree changes to the index"],
            "unstage_files": ["Remove the selected changes from the index only"],
            "discard_worktree": ["Replace selected working files with their index versions"],
        }[action]
        limitations = (
            ["Discarded working-tree content may not be recoverable by Git"]
            if action == "discard_worktree"
            else []
        )
        return self._save_plan(
            action=action,
            command=command,
            paths=paths,
            hunks=[],
            parameters={"paths": paths},
            patch=None,
            risk=risk,
            confirmation=confirmation,
            preview=preview,
            effects=effects,
            limitations=limitations,
        )

    def _expand_renames(self, action: FileAction, paths: list[str]) -> list[str]:
        if action == "discard_worktree":
            return paths
        changes = {item.path: item for item in RepositoryInspector().inspect(self.root).files}
        expanded = list(paths)
        for path in paths:
            previous = changes[path].previous_path if path in changes else None
            if previous:
                expanded.append(previous)
        return self._paths(expanded)

    def _plan_hunks(self, action: HunkAction, parameters: dict[str, Any]) -> GitOperationPlan:
        path = self._paths([parameters.get("path")])[0]
        identifiers = self._string_list(parameters.get("hunkIds"), "hunkIds")
        if not identifiers:
            raise CodePreflightError("hunks_required", "Select at least one diff hunk")
        area = "unstaged" if action == "stage_hunks" else "staged"
        available = self._read_hunks(path, area)
        if available["binary"]:
            raise CodePreflightError(
                "binary_hunks_unsupported", "Stage or unstage this binary file as a whole"
            )
        by_id = {str(item["id"]): item for item in available["hunks"]}
        missing = [identifier for identifier in identifiers if identifier not in by_id]
        if missing:
            raise CodePreflightError(
                "hunk_not_found",
                "The selected hunk is no longer present; refresh the diff",
                recoverable=True,
                details={"missing": missing},
            )
        selected = [item for item in available["hunks"] if item["id"] in identifiers]
        patch = str(available["header"]) + "".join(str(item["patch"]) for item in selected)
        reverse = action == "unstage_hunks"
        args = ["apply", "--cached", "--whitespace=nowarn"]
        if reverse:
            args.append("--reverse")
        args.append("-")
        return self._save_plan(
            action=action,
            command=self._command(args),
            paths=[path],
            hunks=identifiers,
            parameters={"path": path, "hunkIds": identifiers},
            patch=patch,
            risk=GitOperationRisk.MEDIUM,
            confirmation=GitConfirmation.EXPLICIT,
            preview=patch,
            effects=[
                (
                    "Apply the selected hunks to the index"
                    if not reverse
                    else "Remove the selected hunks from the index"
                )
            ],
            limitations=[],
        )

    def _plan_commit(self, parameters: dict[str, Any]) -> GitOperationPlan:
        message = self._commit_message(parameters.get("message"))
        paths = self._nul_paths(
            GitRunner(self.root).run("diff", "--cached", "--name-only", "-z").stdout
        )
        if not paths:
            raise CodePreflightError("empty_change_set", "There are no staged changes to commit")
        preview = GitRunner(self.root).run("diff", "--cached", "--stat", "--", *paths).stdout
        return self._save_plan(
            action="commit",
            command=self._command(["commit", "-m", message]),
            paths=paths,
            hunks=[],
            parameters={"message": message, "paths": paths},
            patch=None,
            risk=GitOperationRisk.MEDIUM,
            confirmation=GitConfirmation.EXPLICIT,
            preview=f"Commit message:\n{message}\n\n{preview}",
            effects=[f"Create one commit containing {len(paths)} staged path(s)"],
            limitations=["Commit hooks may reject or modify the operation"],
            hook_involvement=True,
        )

    def _save_plan(
        self,
        *,
        action: str,
        command: str,
        paths: list[str],
        hunks: list[str],
        parameters: dict[str, Any],
        patch: str | None,
        risk: GitOperationRisk,
        confirmation: GitConfirmation,
        preview: str,
        effects: list[str],
        limitations: list[str],
        hook_involvement: bool = False,
    ) -> GitOperationPlan:
        state = self._state(paths)
        fingerprint = self._fingerprint(action, parameters, patch, state)
        plan_id = uuid4().hex[:24]
        expires = datetime.now(UTC) + PLAN_LIFETIME
        plan = GitOperationPlan(
            id=plan_id,
            action=action,
            commands=[command],
            fingerprint=fingerprint,
            risk=risk,
            confirmation=confirmation,
            head_oid=state["head"] or None,
            index_fingerprint=state["index"],
            worktree_fingerprint=state["worktree"],
            selected_paths=paths,
            selected_hunks=hunks,
            expected_effects=effects,
            hook_involvement=hook_involvement,
            recovery_limitations=limitations,
            preview=preview,
            expires_at=expires.isoformat(),
        )
        atomic_write_json(
            self._plan_path(plan_id),
            {
                "plan": plan.model_dump(mode="json"),
                "state": state,
                "parameters": parameters,
                "patch": patch,
            },
        )
        return plan

    def _execute_stored(self, stored: dict[str, Any], plan: GitOperationPlan) -> GitOperationResult:
        parameters = self._dict(stored.get("parameters"), "parameters")
        git = GitRunner(self.root)
        warning: str | None = None
        if plan.action == "stage_files":
            git.run("add", "--", *plan.selected_paths, mutability="mutating")
        elif plan.action == "unstage_files":
            self._unstage_files(git, plan.selected_paths)
        elif plan.action == "discard_worktree":
            git.run("restore", "--worktree", "--", *plan.selected_paths, mutability="mutating")
            warning = self._mark_findings_changed(plan.selected_paths, "working_tree_discarded")
        elif plan.action in {"stage_hunks", "unstage_hunks"}:
            self._apply_hunks(git, plan.action, stored.get("patch"))
        elif plan.action == "commit":
            warning = self._commit(git, plan.selected_paths, parameters)
        else:
            raise CodePreflightError(
                "unsupported_git_operation", f"Cannot execute action: {plan.action}"
            )
        try:
            snapshot = RepositoryInspector().inspect(self.root)
        except CodePreflightError as error:
            snapshot = None
            warning = warning or f"repository refresh failed ({error.code})"
        message = f"Completed {plan.action.replace('_', ' ')}"
        if warning:
            message += f"; {warning}"
        return GitOperationResult(
            plan_id=plan.id,
            action=plan.action,
            status="completed",
            message=message,
            exit_code=0,
            repository=snapshot,
        )

    def _unstage_files(self, git: GitRunner, paths: list[str]) -> None:
        head = git.run("rev-parse", "--verify", "HEAD", check=False)
        if head.returncode == 0:
            git.run("restore", "--staged", "--", *paths, mutability="mutating")
            return
        git.run("rm", "--cached", "--", *paths, mutability="mutating")

    def _apply_hunks(self, git: GitRunner, action: str, patch: object) -> None:
        if not isinstance(patch, str) or not patch:
            raise CodePreflightError("invalid_git_plan", "Stored hunk patch is missing")
        args = ["apply", "--cached", "--whitespace=nowarn"]
        if action == "unstage_hunks":
            args.append("--reverse")
        args.append("-")
        git.run(*args, mutability="mutating", input_text=patch)

    def _commit(self, git: GitRunner, paths: list[str], parameters: dict[str, Any]) -> str | None:
        message = self._commit_message(parameters.get("message"))
        git.run("commit", "-m", message, mutability="mutating", timeout=300)
        return self._mark_findings_changed(paths, "relevant_commit")

    def _mark_findings_changed(self, paths: list[str], reason: str) -> str | None:
        try:
            ledger = FindingLedger(self.root)
            ledger.mark_paths_changed(
                ledger.current_branch(), paths, ledger.current_commit(), reason=reason
            )
        except CodePreflightError as error:
            return f"finding lifecycle refresh failed ({error.code})"
        return None

    def _require_fresh_plan(self, stored: dict[str, Any], plan: GitOperationPlan) -> None:
        try:
            expires = datetime.fromisoformat(plan.expires_at or "")
        except ValueError as error:
            raise CodePreflightError(
                "invalid_git_plan", "Stored Git preview expiry is invalid"
            ) from error
        if expires.tzinfo is None or expires < datetime.now(UTC):
            raise CodePreflightError(
                "git_plan_expired",
                "This Git preview expired; create a fresh plan",
                recoverable=True,
            )
        expected = self._dict(stored.get("state"), "state")
        current = self._state(plan.selected_paths)
        if expected != current:
            raise CodePreflightError(
                "repository_state_changed",
                "Repository state changed after the Git preview; create a fresh plan",
                recoverable=True,
                details={"planId": plan.id},
            )

    def _validate_stored_plan(
        self, plan_id: str, stored: dict[str, Any], plan: GitOperationPlan
    ) -> None:
        if plan.id != plan_id or self._paths(plan.selected_paths) != plan.selected_paths:
            raise CodePreflightError("invalid_git_plan", "Stored Git preview identity is invalid")
        state = self._dict(stored.get("state"), "state")
        parameters = self._dict(stored.get("parameters"), "parameters")
        patch = stored.get("patch")
        if patch is not None and not isinstance(patch, str):
            raise CodePreflightError("invalid_git_plan", "Stored Git patch is invalid")
        expected = self._fingerprint(plan.action, parameters, patch, state)
        if plan.fingerprint != expected:
            raise CodePreflightError("invalid_git_plan", "Stored Git preview was modified")

    def _require_confirmation(self, plan: GitOperationPlan, payload: dict[str, Any]) -> None:
        if plan.confirmation != GitConfirmation.TYPED:
            return
        expected = "DISCARD" if plan.action == "discard_worktree" else plan.action.upper()
        if payload.get("confirmation") != expected:
            raise CodePreflightError(
                "git_typed_confirmation_required",
                f"Type {expected} to approve this irreversible action",
                recoverable=True,
                details={"confirmation": expected},
            )

    def _validate_file_action(self, action: FileAction, paths: list[str]) -> None:
        snapshot = RepositoryInspector().inspect(self.root)
        changes = {item.path: item for item in snapshot.files if not item.ignored}
        missing = [path for path in paths if path not in changes]
        if missing:
            raise CodePreflightError(
                "git_paths_unchanged",
                "Every selected path must have a current repository change",
                details={"paths": missing},
            )
        if action == "unstage_files":
            invalid = [path for path in paths if not changes[path].staged]
        elif action == "discard_worktree":
            invalid = [
                path for path in paths if changes[path].untracked or not changes[path].unstaged
            ]
        else:
            invalid = [
                path for path in paths if not changes[path].unstaged and not changes[path].untracked
            ]
        if invalid:
            raise CodePreflightError(
                "git_action_not_applicable",
                f"The selected paths cannot be used for {action.replace('_', ' ')}",
                details={"paths": invalid},
            )

    def _file_action_metadata(
        self, action: FileAction, paths: list[str]
    ) -> tuple[str, GitOperationRisk, GitConfirmation]:
        if action == "stage_files":
            return (
                self._command(["add", "--", *paths]),
                GitOperationRisk.LOW,
                GitConfirmation.EXPLICIT,
            )
        if action == "unstage_files":
            has_head = (
                GitRunner(self.root).run("rev-parse", "--verify", "HEAD", check=False).returncode
                == 0
            )
            arguments = (
                ["restore", "--staged", "--", *paths]
                if has_head
                else ["rm", "--cached", "--", *paths]
            )
            return (
                self._command(arguments),
                GitOperationRisk.LOW,
                GitConfirmation.EXPLICIT,
            )
        return (
            self._command(["restore", "--worktree", "--", *paths]),
            GitOperationRisk.IRREVERSIBLE,
            GitConfirmation.TYPED,
        )

    def _file_preview(self, action: FileAction, paths: list[str]) -> str:
        git = GitRunner(self.root)
        args = ["diff", "--binary", "--no-ext-diff"]
        if action == "unstage_files":
            args.append("--cached")
        preview = git.run(*args, "--", *paths).stdout
        if action == "stage_files":
            snapshot = RepositoryInspector().inspect(self.root)
            untracked = [
                item.path for item in snapshot.files if item.untracked and item.path in paths
            ]
            if untracked:
                preview += "\nUntracked files selected:\n" + "\n".join(untracked) + "\n"
        return preview or "No textual diff is available for the selected path(s)."

    def _read_hunks(self, path: str, area: str) -> dict[str, Any]:
        args = ["diff", "--patch", "--binary", "--no-ext-diff"]
        if area == "staged":
            args.append("--cached")
        output = GitRunner(self.root).run(*args, "--", path).stdout
        lines = output.splitlines(keepends=True)
        starts = [index for index, line in enumerate(lines) if line.startswith("@@ ")]
        binary = "GIT binary patch" in output or "Binary files " in output
        if not starts:
            return {"header": output, "hunks": [], "binary": binary}
        header = "".join(lines[: starts[0]])
        hunks = []
        for position, start in enumerate(starts):
            end = starts[position + 1] if position + 1 < len(starts) else len(lines)
            patch = "".join(lines[start:end])
            match = HUNK_HEADER.match(lines[start].rstrip("\n"))
            if match is None:
                continue
            identifier = hashlib.sha256(f"{area}|{path}|{patch}".encode()).hexdigest()[:16]
            hunks.append(
                {
                    "id": identifier,
                    "header": lines[start].rstrip("\n"),
                    "oldStart": int(match.group(1)),
                    "oldLines": int(match.group(2) or "1"),
                    "newStart": int(match.group(3)),
                    "newLines": int(match.group(4) or "1"),
                    "context": match.group("context").strip(),
                    "patch": patch,
                }
            )
        return {"header": header, "hunks": hunks, "binary": binary}

    def _public_hunk(self, hunk: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in hunk.items() if key != "patch"} | {
            "diff": hunk["patch"]
        }

    def _state(self, paths: list[str]) -> dict[str, str]:
        git = GitRunner(self.root)
        head = git.run("rev-parse", "--verify", "HEAD", check=False).stdout.strip()
        index = git.run("ls-files", "-s", "-z").stdout
        status = git.run("status", "--porcelain=v2", "-z", "--untracked-files=all").stdout
        worktree = git.run("diff", "--binary", "--no-ext-diff").stdout
        selected = {path: self._path_digest(path) for path in paths}
        return {
            "head": head,
            "index": self._digest(index),
            "worktree": self._digest(worktree + "\0" + status),
            "selected": self._digest(json.dumps(selected, sort_keys=True)),
        }

    def _path_digest(self, relative: str) -> str:
        path = self.root / relative
        if path.is_symlink():
            return self._digest("symlink:" + os.readlink(path))
        if not path.exists():
            return "missing"
        if not path.is_file():
            return "non-file"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1_048_576):
                digest.update(chunk)
        return digest.hexdigest()

    def _fingerprint(
        self,
        action: str,
        parameters: dict[str, Any],
        patch: str | None,
        state: dict[str, str],
    ) -> str:
        value = {"action": action, "parameters": parameters, "patch": patch, "state": state}
        return self._digest(json.dumps(value, sort_keys=True))

    def _paths(self, value: object) -> list[str]:
        paths = self._string_list(value, "paths")
        if not paths:
            raise CodePreflightError("git_paths_required", "Select at least one repository path")
        if len(paths) > 500:
            raise CodePreflightError("too_many_git_paths", "Select at most 500 paths at once")
        normalized: list[str] = []
        for path in paths:
            if "\0" in path:
                raise CodePreflightError("invalid_git_path", "Git paths cannot contain NUL")
            pure = PurePosixPath(path)
            if pure.is_absolute() or not pure.parts or ".." in pure.parts or path in {"", "."}:
                raise CodePreflightError("invalid_git_path", f"Unsafe repository path: {path}")
            parent = (self.root / pure.parent).resolve()
            if not parent.is_relative_to(self.root):
                raise CodePreflightError("invalid_git_path", f"Path leaves repository: {path}")
            normalized.append(pure.as_posix())
        return list(dict.fromkeys(normalized))

    def _string_list(self, value: object, field: str) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise CodePreflightError(
                "invalid_git_parameters", f"Git field `{field}` must be a string array"
            )
        return list(dict.fromkeys(value))

    def _commit_message(self, value: object) -> str:
        if not isinstance(value, str):
            raise CodePreflightError("invalid_commit_message", "Enter a commit message")
        message = value.replace("\r\n", "\n").strip()
        if not message or not message.splitlines()[0].strip():
            raise CodePreflightError("invalid_commit_message", "Enter a non-empty commit subject")
        if "\0" in message or len(message) > 20_000:
            raise CodePreflightError(
                "invalid_commit_message", "Commit message must be under 20,000 characters"
            )
        return message

    def _nul_paths(self, value: str) -> list[str]:
        return [path for path in value.split("\0") if path]

    def _command(self, arguments: list[str]) -> str:
        return "git " + " ".join(json.dumps(value, ensure_ascii=True) for value in arguments)

    def _digest(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _dict(self, value: object, name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CodePreflightError("invalid_git_plan", f"Stored plan {name} is invalid")
        return value

    def _plan_path(self, plan_id: str) -> Path:
        if not PLAN_ID.fullmatch(plan_id):
            raise CodePreflightError("invalid_git_plan", "Git plan identifier is invalid")
        return self.plans_dir / f"{plan_id}.json"

    def _load_plan(self, plan_id: str) -> dict[str, Any]:
        path = self._plan_path(plan_id)
        try:
            value = json.loads(safe_read_text(path, max_bytes=32_000_000))
        except FileNotFoundError as error:
            raise CodePreflightError(
                "git_plan_not_found", "Git preview was not found; create it again", recoverable=True
            ) from error
        except (OSError, ValueError) as error:
            raise CodePreflightError("invalid_git_plan", "Stored Git preview is invalid") from error
        return self._dict(value, "root")

    def _cleanup_plans(self) -> None:
        reject_symlink_path(self.plans_dir.parent)
        if self.plans_dir.is_symlink():
            raise CodePreflightError(
                "unsafe_state_path", f"Refusing Git plan symlink: {self.plans_dir}"
            )
        if not self.plans_dir.exists():
            return
        cutoff = datetime.now(UTC).timestamp() - 3600
        for path in self.plans_dir.glob("*.json"):
            if not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)

    @contextmanager
    def _mutation_lock(self) -> Iterator[None]:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        reject_symlink_path(self.state_dir)
        if self.lock_path.is_symlink():
            raise CodePreflightError(
                "unsafe_state_path", f"Refusing Git operation lock symlink: {self.lock_path}"
            )
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        with os.fdopen(descriptor, "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
