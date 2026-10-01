from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .errors import CodePreflightError
from .state_files import atomic_write_bytes, reject_symlink_path

MAX_LOG_BYTES = 1_000_000
RETAIN_BYTES = 500_000


def local_log_path() -> Path:
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "codepreflight" / "events.jsonl"


def log_operation(
    *,
    event: Literal["complete", "error"],
    command: str,
    request_id: str,
    repository_path: str,
    duration_ms: int,
    error_code: str | None = None,
) -> None:
    """Write bounded operational metadata locally; never write payloads or repository content."""
    try:
        path = local_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        reject_symlink_path(path.parent)
        if path.is_symlink() or path.parent.is_symlink():
            return
        _rotate(path)
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            "command": command,
            "requestHash": hashlib.sha256(request_id.encode()).hexdigest()[:16],
            "repositoryHash": hashlib.sha256(repository_path.encode()).hexdigest()[:16],
            "durationMs": max(duration_ms, 0),
        }
        if error_code:
            record["errorCode"] = error_code
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except (OSError, CodePreflightError):
        return


def _rotate(path: Path) -> None:
    if not path.exists() or path.stat().st_size < MAX_LOG_BYTES:
        return
    with path.open("rb") as handle:
        handle.seek(-min(RETAIN_BYTES, path.stat().st_size), os.SEEK_END)
        tail = handle.read()
    first_newline = tail.find(b"\n")
    retained = tail[first_newline + 1 :] if first_newline >= 0 else b""
    atomic_write_bytes(path, retained)
