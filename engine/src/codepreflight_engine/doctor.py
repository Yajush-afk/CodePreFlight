from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from .config import global_config_path, repository_config_path


def doctor_report(repository_path: Path) -> dict[str, Any]:
    tools = {}
    for name in ("git", "node", "npm", "uv", "ollama", "codex", "opencode", "claude"):
        tools[name] = {"available": shutil.which(name) is not None, "path": shutil.which(name)}
    return {
        "engineVersion": "0.1.0",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tools": tools,
        "configuration": {
            "global": str(global_config_path()),
            "repository": str(repository_config_path(repository_path)),
        },
    }
