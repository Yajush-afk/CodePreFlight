from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from codepreflight_engine.errors import CodePreflightError

ALLOWED_ENVIRONMENT = {
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TERM",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_STATE_HOME",
    "CODEX_HOME",
    "CODEX_ACCESS_TOKEN",
    "CODEX_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CONFIG_DIR",
    "OPENCODE_CONFIG",
    "OPENCODE_CONFIG_DIR",
}


def sanitized_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key in ALLOWED_ENVIRONMENT}
    if extra:
        environment.update(extra)
    return environment


def run_provider_process(
    command: list[str],
    *,
    prompt: str,
    cwd: Path,
    timeout: int,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            env=environment or sanitized_environment(),
        )
    except subprocess.TimeoutExpired as error:
        raise CodePreflightError(
            "provider_timeout", f"Provider timed out after {timeout} seconds"
        ) from error
    except OSError as error:
        raise CodePreflightError("provider_process_error", str(error)) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "provider command failed"
        raise CodePreflightError("provider_error", detail[-2000:])
    return result


def extract_json_event_text(output: str) -> str:
    text_parts: list[str] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        for candidate in (
            value.get("text"),
            value.get("content"),
            value.get("result"),
            value.get("message"),
        ):
            if isinstance(candidate, str) and candidate.strip():
                text_parts.append(candidate)
        part = value.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    return "".join(text_parts).strip()
