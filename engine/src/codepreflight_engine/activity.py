"""Request-scoped, content-free operation screening shared by worker threads."""

from __future__ import annotations

import re
import shlex
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .secrets import redact_secrets

_sink: Callable[[str, dict[str, Any]], None] | None = None
_lock = threading.RLock()


@contextmanager
def activity_scope(sink: Callable[[str, dict[str, Any]], None]) -> Iterator[None]:
    global _sink
    previous, _sink = _sink, sink
    try:
        yield
    finally:
        _sink = previous


def publish(event: str, payload: dict[str, Any]) -> None:
    with _lock:
        if _sink:
            _sink(event, payload)


def sanitized_command(command: list[str]) -> str:
    values: list[str] = []
    sensitive = False
    for value in command:
        if sensitive:
            values.append("[REDACTED]")
            sensitive = False
            continue
        sensitive = bool(
            re.search(r"(?i)^--?(password|token|api-key|secret|authorization)$", value)
        )
        cleaned = re.sub(
            r"(?i)(password|token|api[_-]?key|secret|authorization)=\S+", r"\1=[REDACTED]", value
        )
        cleaned = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", cleaned)
        values.append(redact_secrets(cleaned).content)
    return shlex.join(values)[:2000]


@contextmanager
def operation(
    actor: str,
    category: str,
    command: list[str] | None = None,
    *,
    mutability: str = "read_only",
    approval: str = "not_required",
) -> Iterator[dict[str, Any]]:
    started = time.monotonic()
    record: dict[str, Any] = {
        "id": str(uuid4()),
        "actor": actor,
        "category": category,
        "command": sanitized_command(command) if command else None,
        "mutability": mutability,
        "approval": approval,
        "startedAt": datetime.now(UTC).isoformat(),
        "status": "running",
    }
    publish("operation_started", record.copy())
    try:
        yield record
        record.setdefault("exitCode", 0)
        record["status"] = record.get(
            "outcome", "completed" if record["exitCode"] == 0 else "failed"
        )
    except BaseException as error:
        code = str(getattr(error, "code", "operation_failed"))
        record["status"] = (
            "cancelled"
            if isinstance(error, (SystemExit, KeyboardInterrupt))
            else "timed_out"
            if "timeout" in code
            else "failed"
        )
        record["reason"] = code
        raise
    finally:
        record["endedAt"] = datetime.now(UTC).isoformat()
        record["durationMs"] = round((time.monotonic() - started) * 1000)
        publish(
            "operation_skipped"
            if record["status"] in {"skipped", "recommended"}
            else "operation_completed",
            record.copy(),
        )
