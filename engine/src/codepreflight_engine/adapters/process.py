from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from codepreflight_engine.activity import operation, publish
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
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
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
    timeout: float,
    environment: dict[str, str] | None = None,
    heartbeat_interval: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    try:
        with operation("Provider", "review", command, approval="approved") as record:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment or sanitized_environment(),
            )
            result = _communicate_with_heartbeats(
                process,
                command,
                prompt,
                timeout=timeout,
                heartbeat_interval=heartbeat_interval,
            )
            record["exitCode"] = result.returncode
    except subprocess.TimeoutExpired as error:
        raise CodePreflightError(
            "provider_timeout",
            f"Provider timed out after {timeout} seconds",
            recoverable=True,
        ) from error
    except OSError as error:
        raise CodePreflightError("provider_process_error", str(error)) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "provider command failed"
        lowered = detail.lower()
        if "invalid_json_schema" in lowered or "invalid schema for response_format" in lowered:
            code = "provider_schema_rejected"
            detail = (
                "The provider rejected Preflight's structured response format. "
                "No answer was produced; update Preflight and retry."
            )
        elif any(marker in lowered for marker in ("unauthorized", "authentication", "log in")):
            code = "provider_authentication_failed"
        elif any(marker in lowered for marker in ("rate limit", "too many requests", "quota")):
            code = "provider_rate_limited"
        else:
            code = "provider_error"
        raise CodePreflightError(code, detail[-2000:], recoverable=True)
    return result


def _communicate_with_heartbeats(
    process: subprocess.Popen[str],
    command: list[str],
    prompt: str,
    *,
    timeout: float,
    heartbeat_interval: float,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    pending_input: str | None = prompt
    while True:
        elapsed = time.monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            process.kill()
            process.communicate()
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            stdout, stderr = process.communicate(
                input=pending_input,
                timeout=min(max(heartbeat_interval, 0.01), remaining),
            )
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired as error:
            pending_input = None
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                process.kill()
                process.communicate()
                raise subprocess.TimeoutExpired(command, timeout) from error
            publish(
                "progress",
                {
                    "kind": "provider_heartbeat",
                    "actor": "Provider",
                    "elapsedMs": round(elapsed * 1000),
                    "message": "Provider process is still running",
                },
            )


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
