from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=True, capture_output=True, text=True)
    return result.stdout


@pytest.fixture
def git_repository(tmp_path: Path) -> Iterator[Path]:
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "CodePreFlight Tests")
    git(tmp_path, "config", "user.email", "tests@codepreflight.local")
    (tmp_path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    git(tmp_path, "add", "README.md")
    git(tmp_path, "commit", "-m", "Initial commit")
    yield tmp_path
