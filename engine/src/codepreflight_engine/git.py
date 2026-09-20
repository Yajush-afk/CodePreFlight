from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .activity import operation
from .errors import CodePreflightError


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

    def run(self, *args: str, check: bool = True, timeout: float = 20) -> GitResult:
        mutating = args and args[0] in {"commit", "switch", "config", "update-ref"}
        with operation(
            "Git", "repository", ["git", *args], mutability="mutating" if mutating else "read_only"
        ) as record:
            result = self._run(*args, check=check, timeout=timeout)
            record["exitCode"] = result.returncode
            return result

    def _run(self, *args: str, check: bool = True, timeout: float = 20) -> GitResult:
        try:
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = subprocess.Popen(
                    ["git", *args],
                    cwd=self.cwd,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise
                stdout, stdout_truncated = self._read(stdout_file)
                stderr, stderr_truncated = self._read(stderr_file)
        except FileNotFoundError as error:
            raise CodePreflightError("git_not_found", "Git is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise CodePreflightError(
                "git_timeout", f"Git command timed out: git {' '.join(args)}"
            ) from error

        result = GitResult(
            stdout,
            stderr,
            returncode,
            truncated=stdout_truncated or stderr_truncated,
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

    def _read(self, handle: BinaryIO) -> tuple[str, bool]:
        handle.seek(0)
        content = handle.read(self.max_output_bytes + 1)
        truncated = len(content) > self.max_output_bytes
        return content[: self.max_output_bytes].decode("utf-8", errors="replace"), truncated
