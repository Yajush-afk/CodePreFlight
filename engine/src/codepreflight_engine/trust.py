from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import repository_config_path
from .git import GitRunner


def config_digest(root: Path) -> str:
    path = repository_config_path(root)
    content = path.read_bytes() if path.exists() else b""
    return hashlib.sha256(content).hexdigest()


def trust_path(root: Path) -> Path:
    value = GitRunner(root).run("rev-parse", "--git-dir").stdout.strip()
    git_dir = Path(value) if Path(value).is_absolute() else (root / value).resolve()
    return git_dir / "codepreflight" / "trust.json"


def remote_identity(root: Path) -> str | None:
    result = GitRunner(root).run("remote", "get-url", "origin", check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def is_trusted(root: Path) -> bool:
    path = trust_path(root)
    if not path.exists():
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        value.get("repository") == str(root.resolve())
        and value.get("remote") == remote_identity(root)
        and value.get("configDigest") == config_digest(root)
    )


def trust_repository(root: Path) -> None:
    path = trust_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "repository": str(root.resolve()),
                "remote": remote_identity(root),
                "configDigest": config_digest(root),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
