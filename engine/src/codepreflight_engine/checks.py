from __future__ import annotations

import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import BinaryIO

from .models import CheckDefinition, CheckResult, CheckStatus

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
            return list(pool.map(lambda definition: self._run_one(root, definition), definitions))

    def _run_one(self, root: Path, definition: CheckDefinition) -> CheckResult:
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
            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                process = subprocess.Popen(
                    definition.command,
                    cwd=root,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
                try:
                    exit_code = process.wait(timeout=definition.timeout_seconds)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    return CheckResult(
                        name=definition.name,
                        command=definition.command,
                        status=CheckStatus.TIMED_OUT,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        output=self._combined_tail(stdout_file, stderr_file),
                    )
                return CheckResult(
                    name=definition.name,
                    command=definition.command,
                    status=CheckStatus.PASSED if exit_code == 0 else CheckStatus.FAILED,
                    exit_code=exit_code,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    output=self._combined_tail(stdout_file, stderr_file),
                )
        except OSError as error:
            return CheckResult(
                name=definition.name,
                command=definition.command,
                status=CheckStatus.SKIPPED,
                duration_ms=int((time.monotonic() - started) * 1000),
                output=str(error),
            )

    def _combined_tail(self, stdout: BinaryIO, stderr: BinaryIO) -> str:
        return (self._tail(stdout) + self._tail(stderr))[-MAX_OUTPUT:]

    def _tail(self, stream: BinaryIO) -> str:
        size = stream.tell()
        stream.seek(max(0, size - MAX_OUTPUT))
        return stream.read(MAX_OUTPUT).decode("utf-8", errors="replace")
