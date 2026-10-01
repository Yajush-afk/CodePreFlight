from __future__ import annotations

import json
import os
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner
from .models import (
    ConflictFileDetail,
    ConflictInspection,
    ConflictState,
    GitOperationResult,
    GitOperationRisk,
)
from .repository import RepositoryInspector

CONFLICT_ACTIONS = {
    "launch_editor",
    "launch_mergetool",
    "continue_operation",
    "abort_operation",
}
MAX_EVIDENCE_BYTES = 200_000


@dataclass(frozen=True)
class ConflictPlanDraft:
    action: str
    command: list[str]
    parameters: dict[str, Any]
    risk: GitOperationRisk
    preview: str
    effects: list[str]
    limitations: list[str]
    paths: list[str] = field(default_factory=list)
    editor_involvement: bool = False


class ConflictWorkflow:
    """Inspects conflicts and plans explicit external or Git recovery steps."""

    def __init__(self, root: Path) -> None:
        self.root = GitRunner(root).root()
        self.git = GitRunner(self.root)

    def supports(self, action: str) -> bool:
        return action in CONFLICT_ACTIONS

    def inspect(self, selected: str | None = None) -> ConflictInspection:
        operation = self._active_operation()
        files = self._conflict_files()
        if selected is not None and selected not in files:
            raise CodePreflightError(
                "conflict_path_not_found", f"Path is not currently conflicted: {selected}"
            )
        editor = self._editor_command(required=False)
        mergetool = self._mergetool_name()
        details = [self._detail(selected)] if selected else []
        recoverable = operation in {"merge", "rebase", "cherry-pick", "revert"}
        return ConflictInspection(
            operation=operation,
            files=files,
            details=details,
            can_continue=recoverable and not files,
            can_abort=recoverable,
            editor_available=editor is not None,
            editor_name=Path(editor[0]).name if editor else None,
            mergetool_available=mergetool is not None,
            mergetool_name=mergetool,
        )

    def plan(self, action: str, parameters: dict[str, Any]) -> ConflictPlanDraft:
        inspection = self.inspect()
        if action == "launch_editor":
            return self._plan_editor(parameters, inspection)
        if action == "launch_mergetool":
            return self._plan_mergetool(parameters, inspection)
        if action in {"continue_operation", "abort_operation"}:
            return self._plan_recovery(action, inspection)
        raise CodePreflightError("unsupported_git_operation", "Unsupported conflict action")

    def execute(
        self,
        action: str,
        parameters: dict[str, Any],
        plan_id: str,
    ) -> GitOperationResult:
        if action in {"launch_editor", "launch_mergetool"}:
            command = parameters.get("command")
            if not self._command_array(command):
                raise CodePreflightError("invalid_git_plan", "Stored handoff command is invalid")
            return GitOperationResult(
                plan_id=plan_id,
                action=action,
                status="completed",
                message="Terminal control is ready to hand off to the approved tool",
                exit_code=0,
                repository=RepositoryInspector().inspect(self.root),
                requires_terminal_handoff=True,
                handoff_command=command,
            )
        operation = str(parameters.get("operation", ""))
        verb = "continue" if action == "continue_operation" else "abort"
        arguments = self._recovery_arguments(operation, verb)
        result = self.git.run(*arguments, check=False, timeout=300, mutability="mutating")
        snapshot = RepositoryInspector().inspect(self.root)
        if result.returncode == 0:
            return GitOperationResult(
                plan_id=plan_id,
                action=action,
                status="completed",
                message=f"Completed {operation} {verb}",
                exit_code=0,
                repository=snapshot,
            )
        current = self._active_operation()
        conflict = ConflictState(
            operation=current or operation,
            files=snapshot.conflicts,
            can_continue=current is not None and not snapshot.conflicts,
            can_abort=current is not None,
            editor_available=self._editor_command(required=False) is not None,
            mergetool_available=self._mergetool_name() is not None,
        )
        message = result.stderr.strip() or result.stdout.strip() or "Git refused recovery"
        return GitOperationResult(
            plan_id=plan_id,
            action=action,
            status="conflicted" if current or snapshot.conflicts else "failed",
            message=message[-2_000:],
            exit_code=result.returncode,
            repository=snapshot,
            conflict=conflict if current or snapshot.conflicts else None,
        )

    def _plan_editor(
        self,
        parameters: dict[str, Any],
        inspection: ConflictInspection,
    ) -> ConflictPlanDraft:
        path = str(parameters.get("path", ""))
        if path not in inspection.files:
            raise CodePreflightError(
                "conflict_path_not_found", f"Path is not currently conflicted: {path}"
            )
        editor = self._editor_command(required=True)
        assert editor is not None
        target = self.root / path
        if target.is_symlink():
            raise CodePreflightError(
                "conflict_editor_symlink",
                "Use a configured mergetool to resolve a conflicted symbolic link",
                recoverable=True,
            )
        command = [*editor, str(target.absolute())]
        return ConflictPlanDraft(
            action="launch_editor",
            command=command,
            parameters={"command": command, "path": path},
            risk=GitOperationRisk.MEDIUM,
            preview=f"Open conflicted path {path} in {Path(editor[0]).name}",
            effects=["Hand terminal control to the configured editor for this file"],
            limitations=["Preflight does not edit, stage, or mark the conflict resolved"],
            paths=[path],
            editor_involvement=True,
        )

    def _plan_mergetool(
        self,
        parameters: dict[str, Any],
        inspection: ConflictInspection,
    ) -> ConflictPlanDraft:
        tool = self._mergetool_name()
        if tool is None:
            raise CodePreflightError(
                "mergetool_not_configured",
                "Configure merge.tool before launching a mergetool through Preflight",
                recoverable=True,
            )
        requested = parameters.get("paths")
        paths = inspection.files if requested is None else self._path_array(requested)
        invalid = [path for path in paths if path not in inspection.files]
        if invalid or not paths:
            raise CodePreflightError(
                "conflict_path_not_found",
                "Mergetool paths must be current conflict files",
                details={"paths": invalid},
            )
        command = ["git", "mergetool", "--no-prompt", "--", *paths]
        return ConflictPlanDraft(
            action="launch_mergetool",
            command=command,
            parameters={"command": command, "paths": paths},
            risk=GitOperationRisk.MEDIUM,
            preview=f"Launch configured mergetool {tool} for {len(paths)} conflict file(s)",
            effects=["Hand terminal control to Git's configured mergetool"],
            limitations=[
                "The mergetool may edit files; Preflight does not stage or continue for it"
            ],
            paths=paths,
            editor_involvement=True,
        )

    def _plan_recovery(
        self,
        action: str,
        inspection: ConflictInspection,
    ) -> ConflictPlanDraft:
        operation = inspection.operation
        if operation not in {"merge", "rebase", "cherry-pick", "revert"}:
            raise CodePreflightError(
                "git_operation_not_active", "No supported Git operation is active"
            )
        verb = "continue" if action == "continue_operation" else "abort"
        if verb == "continue" and inspection.files:
            raise CodePreflightError(
                "conflicts_unresolved",
                "Resolve and stage every conflict before continuing",
                recoverable=True,
                details={"paths": inspection.files},
            )
        arguments = self._recovery_arguments(operation, verb)
        command = ["git", *arguments]
        effect = f"{verb.title()} the active {operation} operation"
        return ConflictPlanDraft(
            action=action,
            command=command,
            parameters={"operation": operation},
            risk=GitOperationRisk.HIGH,
            preview=effect,
            effects=[effect],
            limitations=["Git's final safety checks remain authoritative"],
            editor_involvement=verb == "continue",
        )

    def _detail(self, path: str) -> ConflictFileDetail:
        values: dict[str, str | None] = {}
        truncated = False
        binary = False
        for label, stage in (("base", 1), ("ours", 2), ("theirs", 3)):
            value, was_truncated, was_binary = self._stage_content(stage, path)
            values[label] = value
            truncated = truncated or was_truncated
            binary = binary or was_binary
        working, working_truncated, working_binary = self._working_content(path)
        return ConflictFileDetail(
            path=path,
            binary=binary or working_binary,
            base=values["base"],
            ours=values["ours"],
            theirs=values["theirs"],
            working=working,
            truncated=truncated or working_truncated,
        )

    def _stage_content(self, stage: int, path: str) -> tuple[str | None, bool, bool]:
        reference = f":{stage}:{path}"
        size = self.git.run("cat-file", "-s", reference, check=False)
        if size.returncode != 0:
            return None, False, False
        if int(size.stdout.strip()) > MAX_EVIDENCE_BYTES:
            return None, True, False
        content = self.git.run("show", reference).stdout
        binary = "\0" in content
        return (None if binary else content), False, binary

    def _working_content(self, path: str) -> tuple[str | None, bool, bool]:
        target = self.root / path
        if target.is_symlink():
            return os.readlink(target), False, False
        try:
            with target.open("rb") as handle:
                content = handle.read(MAX_EVIDENCE_BYTES + 1)
        except (FileNotFoundError, IsADirectoryError):
            return None, False, False
        truncated = len(content) > MAX_EVIDENCE_BYTES
        bounded = content[:MAX_EVIDENCE_BYTES]
        binary = b"\0" in bounded
        return (
            None if binary else bounded.decode("utf-8", errors="replace"),
            truncated,
            binary,
        )

    def _conflict_files(self) -> list[str]:
        output = self.git.run("diff", "--name-only", "--diff-filter=U", "-z").stdout
        return [path for path in output.split("\0") if path]

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

    def _editor_command(self, *, required: bool) -> list[str] | None:
        result = self.git.run("var", "GIT_EDITOR", check=False)
        value = result.stdout.strip() if result.returncode == 0 else ""
        try:
            command = shlex.split(value) if value else []
        except ValueError as error:
            raise CodePreflightError(
                "invalid_editor", "Configured Git editor is invalid"
            ) from error
        available = bool(command) and "\0" not in value and "\n" not in value
        if available and shutil.which(command[0]) is not None:
            return command
        if required:
            raise CodePreflightError(
                "editor_not_available",
                "Configure an available Git editor before requesting editor handoff",
                recoverable=True,
            )
        return None

    def _mergetool_name(self) -> str | None:
        result = self.git.run("config", "--get", "merge.tool", check=False)
        value = result.stdout.strip()
        if result.returncode != 0 or not value or "\0" in value or "\n" in value:
            return None
        return value

    def _recovery_arguments(self, operation: str, verb: str) -> list[str]:
        if operation not in {"merge", "rebase", "cherry-pick", "revert"}:
            raise CodePreflightError("git_operation_not_active", "Unsupported Git operation")
        arguments = [operation, f"--{verb}"]
        if verb == "continue":
            return ["-c", "core.editor=true", *arguments]
        return arguments

    def _path_array(self, value: object) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(path, str) for path in value):
            raise CodePreflightError("invalid_git_parameters", "Conflict paths must be strings")
        return list(dict.fromkeys(value))

    def _command_array(self, value: object) -> bool:
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, str) and item and "\0" not in item for item in value)
        )

    def command_text(self, command: list[str]) -> str:
        return " ".join(json.dumps(item, ensure_ascii=True) for item in command)
