from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessResult:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool = False


class _Capture:
    def __init__(self, limit: int, *, tail: bool) -> None:
        self.limit = limit
        self.tail = tail
        self.data = bytearray()
        self.truncated = False

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self.tail:
            self.data.extend(chunk)
            if len(self.data) > self.limit:
                del self.data[: len(self.data) - self.limit]
                self.truncated = True
            return
        remaining = self.limit - len(self.data)
        self.data.extend(chunk[: max(0, remaining)])
        self.truncated = self.truncated or len(chunk) > remaining

    def text(self) -> str:
        return bytes(self.data).decode("utf-8", errors="replace")


def terminate_process_group(process: subprocess.Popen[bytes], *, grace: float = 0.5) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def run_bounded_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: float,
    max_output_bytes: int,
    environment: Mapping[str, str] | None = None,
    input_text: str | None = None,
    capture_tail: bool = False,
    heartbeat_interval: float | None = None,
    on_heartbeat: Callable[[float], None] | None = None,
) -> ProcessResult:
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment) if environment is not None else None,
        start_new_session=True,
    )
    stdout = _Capture(max_output_bytes, tail=capture_tail)
    stderr = _Capture(max_output_bytes, tail=capture_tail)
    readers = [
        threading.Thread(target=_drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    writer = None
    if input_text is not None:
        writer = threading.Thread(target=_write_input, args=(process, input_text), daemon=True)
        writer.start()
    started = time.monotonic()
    interval = max(0.01, heartbeat_interval or timeout)
    try:
        while True:
            elapsed = time.monotonic() - started
            remaining = timeout - elapsed
            if remaining <= 0:
                raise subprocess.TimeoutExpired(list(command), timeout)
            try:
                returncode = process.wait(timeout=min(interval, remaining))
                break
            except subprocess.TimeoutExpired:
                if on_heartbeat is not None:
                    on_heartbeat(time.monotonic() - started)
    except BaseException:
        terminate_process_group(process)
        raise
    finally:
        if writer is not None:
            writer.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
    return ProcessResult(
        stdout=stdout.text(),
        stderr=stderr.text(),
        returncode=returncode,
        truncated=stdout.truncated or stderr.truncated,
    )


def _drain(stream: object, capture: _Capture) -> None:
    if stream is None:
        return
    while chunk := stream.read(65_536):  # type: ignore[attr-defined]
        capture.append(chunk)


def _write_input(process: subprocess.Popen[bytes], value: str) -> None:
    if process.stdin is None:
        return
    try:
        process.stdin.write(value.encode())
        process.stdin.close()
    except (BrokenPipeError, OSError):
        return
