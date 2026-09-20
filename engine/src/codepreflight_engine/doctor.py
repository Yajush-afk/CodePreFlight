from __future__ import annotations

import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import global_config_path, load_config, personal_config_path, repository_config_path
from .errors import CodePreflightError
from .local_log import local_log_path
from .protocol_generated import PROTOCOL_VERSION
from .providers import discover_providers

REQUIRED_TOOLS = {
    "git": (["git", "--version"], (2, 30)),
    "node": (["node", "--version"], (22, 0)),
    "npm": (["npm", "--version"], (9, 0)),
    "uv": (["uv", "--version"], (0, 8)),
}


def doctor_report(repository_path: Path) -> dict[str, Any]:
    tools = {
        name: _tool(name, command, minimum) for name, (command, minimum) in REQUIRED_TOOLS.items()
    }
    python_healthy = sys.version_info >= (3, 12)
    global_path = global_config_path()
    repository_path_config = repository_config_path(repository_path)
    personal_path = personal_config_path(repository_path)
    config_error: str | None = None
    try:
        load_config(repository_path)
    except CodePreflightError as error:
        config_error = str(error)
    providers = [provider.model_dump(mode="json") for provider in discover_providers()]
    return {
        "healthy": python_healthy
        and all(bool(tool["healthy"]) for tool in tools.values())
        and config_error is None,
        "engineVersion": "0.1.0",
        "protocol": {
            "version": PROTOCOL_VERSION,
            "compatible": True,
        },
        "runtime": {
            "python": {
                "version": platform.python_version(),
                "minimum": "3.12",
                "healthy": python_healthy,
                "executable": sys.executable,
            },
            "platform": platform.platform(),
            "supported": sys.platform.startswith(("linux", "darwin")),
        },
        "tools": tools,
        "providers": providers,
        "privacy": {
            "telemetry": False,
            "operationalLog": str(local_log_path()),
            "logContainsRepositoryContent": False,
        },
        "configuration": {
            "valid": config_error is None,
            "error": config_error,
            "global": {
                "path": str(global_path),
                "exists": global_path.exists(),
            },
            "repository": {
                "path": str(repository_path_config),
                "exists": repository_path_config.exists(),
            },
            "personal": {
                "path": str(personal_path),
                "exists": personal_path.exists(),
            },
        },
    }


def _tool(name: str, command: list[str], minimum: tuple[int, int]) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        return {
            "available": False,
            "healthy": False,
            "path": None,
            "version": None,
            "minimum": ".".join(map(str, minimum)),
        }
    version = _version(command)
    parsed = _version_tuple(version)
    return {
        "available": True,
        "healthy": parsed is not None and parsed >= minimum,
        "path": path,
        "version": version,
        "minimum": ".".join(map(str, minimum)),
    }


def _version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def _version_tuple(value: str | None) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\.(\d+)", value or "")
    return (int(match.group(1)), int(match.group(2))) if match else None
