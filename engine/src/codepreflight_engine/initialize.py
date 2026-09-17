from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomli_w

from .config import repository_config_path
from .errors import CodePreflightError
from .trust import trust_repository


def propose_configuration(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    package_file = root / "package.json"
    if package_file.exists():
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        for name in ("test", "check", "lint", "typecheck", "build"):
            if isinstance(scripts, dict) and name in scripts:
                checks.append(
                    {
                        "name": name,
                        "command": ["npm", "run", name],
                        "timeout_seconds": 180,
                    }
                )
    if (root / "pyproject.toml").exists():
        checks.extend(
            [
                {
                    "name": "python-tests",
                    "command": ["uv", "run", "pytest"],
                    "timeout_seconds": 180,
                },
                {
                    "name": "python-lint",
                    "command": ["uv", "run", "ruff", "check", "."],
                    "timeout_seconds": 120,
                },
            ]
        )
    return {
        "version": 1,
        "review": {"provider": "ollama", "context_limit": 60000, "policy": "warning"},
        "checks": checks,
        "ignore": [
            "node_modules/",
            ".venv/",
            "dist/",
            "build/",
            "coverage/",
            "*.lock",
        ],
        "rules": [],
        "hooks": {"remote_provider_approved": False, "fail_closed": False},
    }


def initialize_repository(root: Path, *, write: bool) -> dict[str, Any]:
    config = propose_configuration(root)
    rendered = tomli_w.dumps(config)
    path = repository_config_path(root)
    if write:
        if path.exists():
            raise CodePreflightError(
                "config_exists",
                f"Repository configuration already exists at {path}; review it before replacing it",
            )
        path.write_text(rendered, encoding="utf-8")
        trust_repository(root)
    return {
        "path": str(path),
        "written": write,
        "trusted": write,
        "configuration": config,
        "preview": rendered,
    }
