from __future__ import annotations

import subprocess
import tomllib
from difflib import unified_diff
from pathlib import Path
from typing import Any

import tomli_w

from .config import CodePreflightConfig, global_config_path, repository_config_path
from .errors import CodePreflightError

PROVIDER_IDS = {"ollama", "codex", "opencode", "claude", "openai-compatible"}


def configure_provider(
    root: Path,
    *,
    provider_id: str,
    model: str | None,
    global_scope: bool,
    write: bool,
) -> dict[str, object]:
    if provider_id not in PROVIDER_IDS:
        raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
    path = global_config_path() if global_scope else repository_config_path(root)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        config: dict[str, Any] = tomllib.loads(current) if current else {}
    except tomllib.TOMLDecodeError as error:
        raise CodePreflightError(
            "invalid_config", f"Cannot read configuration at {path}: {error}"
        ) from error

    review = config.setdefault("review", {})
    if not isinstance(review, dict):
        raise CodePreflightError("invalid_config", "The review configuration must be a table")
    review["provider"] = provider_id
    if model:
        provider_settings = config.setdefault("providers", {})
        if not isinstance(provider_settings, dict):
            raise CodePreflightError(
                "invalid_config", "The providers configuration must be a table"
            )
        selected = provider_settings.setdefault(provider_id, {})
        if not isinstance(selected, dict):
            raise CodePreflightError(
                "invalid_config", f"Provider configuration for {provider_id} must be a table"
            )
        selected["model"] = model

    CodePreflightConfig.model_validate(config)
    rendered = tomli_w.dumps(config)
    diff = "".join(
        unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(path) if current else "/dev/null",
            tofile=str(path),
        )
    )
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.codepreflight")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    return {
        "provider": provider_id,
        "model": model,
        "scope": "global" if global_scope else "repository",
        "path": str(path),
        "written": write,
        "preview": rendered,
        "diff": diff,
    }


def provider_models(provider_id: str) -> dict[str, object]:
    if provider_id == "ollama":
        code, stdout, stderr = _run(["ollama", "list"])
        if code != 0:
            raise CodePreflightError(
                "provider_runtime_unavailable",
                stderr.strip() or "Ollama is unavailable",
                recoverable=True,
            )
        models = [
            line.split()[0] for line in stdout.splitlines()[1:] if line.strip() and line.split()
        ]
        return {"provider": provider_id, "models": models}
    if provider_id == "opencode":
        code, stdout, stderr = _run(["opencode", "models"])
        if code != 0:
            raise CodePreflightError(
                "provider_models_unavailable",
                stderr.strip() or "OpenCode models are unavailable",
                recoverable=True,
            )
        models = [line.strip() for line in stdout.splitlines() if "/" in line and line.strip()]
        return {"provider": provider_id, "models": models}
    if provider_id not in PROVIDER_IDS:
        raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
    return {"provider": provider_id, "models": []}


def _run(command: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CodePreflightError(
            "provider_command_failed",
            f"Could not run {' '.join(command)}: {error}",
            recoverable=True,
        ) from error
    return result.returncode, result.stdout, result.stderr
