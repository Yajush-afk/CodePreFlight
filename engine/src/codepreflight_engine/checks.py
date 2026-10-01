from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .activity import operation, submit_with_activity
from .models import CheckDefinition, CheckResult, CheckStatus
from .processes import run_bounded_process

MAX_OUTPUT = 12000


class CheckRunner:
    def run(
        self,
        root: Path,
        definitions: list[CheckDefinition],
        *,
        concurrency: int = 4,
    ) -> list[CheckResult]:
        workers = max(1, min(concurrency, len(definitions) or 1))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="preflight-check") as pool:
            futures = [
                submit_with_activity(pool, self._run_one, root, item) for item in definitions
            ]
            return [future.result() for future in futures]

    def _run_one(self, root: Path, definition: CheckDefinition) -> CheckResult:
        with operation(
            "Check",
            "validation",
            definition.command,
            mutability="executes_repository_code",
            approval="approved" if definition.run else "not_approved",
        ) as record:
            result = self._execute(root, definition)
            record.update(exitCode=result.exit_code, outcome=result.status.value)
            return result

    def _execute(self, root: Path, definition: CheckDefinition) -> CheckResult:
        if not definition.run:
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.RECOMMENDED,
                duration_ms=0,
                output="Recommended by repository configuration; not run.",
            )
        started = time.monotonic()
        try:
            result = run_bounded_process(
                definition.command,
                cwd=root,
                timeout=definition.timeout_seconds,
                max_output_bytes=MAX_OUTPUT,
                capture_tail=True,
            )
            output = (result.stdout + result.stderr)[-MAX_OUTPUT:]
            if result.truncated:
                output = "[earlier output truncated]\n" + output
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.PASSED if result.returncode == 0 else CheckStatus.FAILED,
                exit_code=result.returncode,
                duration_ms=int((time.monotonic() - started) * 1000),
                output=output,
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.TIMED_OUT,
                duration_ms=int((time.monotonic() - started) * 1000),
                output="Check timed out; Preflight terminated its process group.",
            )
        except OSError as error:
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.SKIPPED,
                duration_ms=int((time.monotonic() - started) * 1000),
                output=str(error),
            )
