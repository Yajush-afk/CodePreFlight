from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from .errors import CodePreflightError


def atomic_write_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    _atomic_write(path, content.encode("utf-8"), mode=mode)


def atomic_write_bytes(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    _atomic_write(path, content, mode=mode)


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_path(path.parent)
    if path.is_symlink():
        raise CodePreflightError("unsafe_state_path", f"Refusing to replace symlink: {path}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(handle.name, mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def safe_read_text(path: Path, *, max_bytes: int = 8_000_000) -> str:
    reject_symlink_path(path.parent)
    if path.is_symlink():
        raise CodePreflightError("unsafe_state_path", f"Refusing to read symlink: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise CodePreflightError("unsafe_state_path", f"State is not a regular file: {path}")
        content = os.read(descriptor, max_bytes + 1)
        if len(content) > max_bytes:
            raise CodePreflightError("state_file_too_large", f"State file exceeds limit: {path}")
        return content.decode("utf-8")
    finally:
        os.close(descriptor)


def reject_symlink_path(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise CodePreflightError(
                "unsafe_state_path", f"Refusing to use symlink directory: {candidate}"
            )
