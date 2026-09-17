from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import CodePreflightError


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


class GitRunner:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, *args: str, check: bool = True, timeout: float = 20) -> GitResult:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=self.cwd,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise CodePreflightError("git_not_found", "Git is not installed") from error
        except subprocess.TimeoutExpired as error:
            raise CodePreflightError(
                "git_timeout", f"Git command timed out: git {' '.join(args)}"
            ) from error

        result = GitResult(completed.stdout, completed.stderr, completed.returncode)
        if check and result.returncode != 0:
            message = result.stderr.strip() or f"git {' '.join(args)} failed"
            raise CodePreflightError("git_command_failed", message)
        return result

    def root(self) -> Path:
        result = self.run("rev-parse", "--show-toplevel")
        return Path(result.stdout.strip()).resolve()
