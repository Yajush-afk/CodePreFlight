from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .activity import operation
from .errors import CodePreflightError
from .processes import run_bounded_process


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool = False


class GitRunner:
    def __init__(self, cwd: Path, *, max_output_bytes: int = 8_000_000) -> None:
        self.cwd = cwd
        self.max_output_bytes = max_output_bytes

    def run(
        self,
        *args: str,
        check: bool = True,
        timeout: float = 20,
        mutability: str | None = None,
        input_text: str | None = None,
    ) -> GitResult:
        command_mutability = self._mutability(args, mutability)
        with operation(
            "Git", "repository", ["git", *args], mutability=command_mutability
        ) as record:
            result = self._run(*args, check=check, timeout=timeout, input_text=input_text)
            record["exitCode"] = result.returncode
            return result

    def _run(
        self,
        *args: str,
        check: bool = True,
        timeout: float = 20,
        input_text: str | None = None,
    ) -> GitResult:
        try:
            completed = run_bounded_process(
                ["git", *args],
                cwd=self.cwd,
                timeout=timeout,
                max_output_bytes=self.max_output_bytes,
                input_text=input_text,
            )
        except FileNotFoundError as error:
            raise CodePreflightError("git_not_found", "Git is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise CodePreflightError(
                "git_timeout", f"Git command timed out: git {' '.join(args)}"
            ) from error

        result = GitResult(
            completed.stdout,
            completed.stderr,
            completed.returncode,
            truncated=completed.truncated,
        )
        if result.truncated:
            raise CodePreflightError(
                "git_output_limit",
                f"Git command exceeded the {self.max_output_bytes}-byte output limit: "
                f"git {' '.join(args)}",
            )
        if check and result.returncode != 0:
            message = result.stderr.strip() or f"git {' '.join(args)} failed"
            raise CodePreflightError("git_command_failed", message)
        return result

    def root(self) -> Path:
        result = self.run("rev-parse", "--show-toplevel")
        return Path(result.stdout.strip()).resolve()

    def _mutability(self, args: tuple[str, ...], declared: str | None) -> str:
        if not args:
            return "unknown"
        command = args[0]
        mutating = command in {
            "add",
            "am",
            "branch",
            "checkout",
            "cherry-pick",
            "clean",
            "commit",
            "fetch",
            "merge",
            "mv",
            "pull",
            "push",
            "rebase",
            "reset",
            "restore",
            "revert",
            "rm",
            "stash",
            "switch",
            "tag",
            "update-index",
            "update-ref",
        } or (
            command == "config"
            and not any(
                flag in args for flag in ("--get", "--get-all", "--get-regexp", "--list", "-l")
            )
        )
        if mutating and declared is None:
            raise CodePreflightError(
                "git_mutability_required",
                f"Git mutation `{command}` requires explicit action metadata",
            )
        if declared is not None:
            return declared
        if command in {
            "blame",
            "cat-file",
            "diff",
            "diff-tree",
            "for-each-ref",
            "log",
            "ls-files",
            "ls-tree",
            "merge-base",
            "name-rev",
            "remote",
            "rev-list",
            "rev-parse",
            "show",
            "show-ref",
            "status",
            "symbolic-ref",
        }:
            return "read_only"
        return "unknown"
