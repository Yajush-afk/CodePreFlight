from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeIdentity:
    source_root: Path
    revision: str | None
    fingerprint: str

    @classmethod
    def capture(cls) -> RuntimeIdentity:
        package = Path(__file__).resolve().parent
        root = _git_root(package) or package
        return cls(root, _git_revision(root), _source_fingerprint(package))

    def changed(self) -> bool:
        package = Path(__file__).resolve().parent
        return _source_fingerprint(package) != self.fingerprint

    def public(self) -> dict[str, str | None]:
        return {
            "revision": self.revision,
            "sourceRoot": str(self.source_root),
            "fingerprint": self.fingerprint[:12],
        }


def _git_root(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def _git_revision(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--short=12", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _source_fingerprint(package: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        stat = path.stat()
        digest.update(str(path.relative_to(package)).encode())
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(str(stat.st_size).encode())
    return digest.hexdigest()
