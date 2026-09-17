from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .models import CheckDefinition, CheckResult, CheckStatus

MAX_OUTPUT = 12000


class CheckRunner:
    def run(self, root: Path, definitions: list[CheckDefinition]) -> list[CheckResult]:
        return [self._run_one(root, definition) for definition in definitions]

    def _run_one(self, root: Path, definition: CheckDefinition) -> CheckResult:
        started = time.monotonic()
        try:
            process = subprocess.run(
                definition.command,
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                timeout=definition.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            stdout = (
                error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
            )
            stderr = (
                error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
            )
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.TIMED_OUT,
                duration_ms=int((time.monotonic() - started) * 1000),
                output=(stdout + stderr)[-MAX_OUTPUT:],
            )
        except OSError as error:
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.SKIPPED,
                duration_ms=int((time.monotonic() - started) * 1000),
                output=str(error),
            )
        return CheckResult(
            name=definition.name,
            command=definition.command,
            status=CheckStatus.PASSED if process.returncode == 0 else CheckStatus.FAILED,
            exit_code=process.returncode,
            duration_ms=int((time.monotonic() - started) * 1000),
            output=(process.stdout + process.stderr)[-MAX_OUTPUT:],
        )
