from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from codepreflight_engine.activity import operation, publish
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.processes import run_bounded_process
from codepreflight_engine.secrets import redact_secrets

MAX_PROVIDER_OUTPUT = 8_000_000

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
            bounded = run_bounded_process(
                command,
                cwd=cwd,
                timeout=timeout,
                max_output_bytes=MAX_PROVIDER_OUTPUT,
                environment=environment or sanitized_environment(),
                input_text=prompt,
                heartbeat_interval=heartbeat_interval,
                on_heartbeat=_publish_heartbeat,
            )
            if bounded.truncated:
                raise CodePreflightError(
                    "provider_output_limit",
                    "Provider output exceeded Preflight's bounded capture limit",
                    recoverable=True,
                )
            result = subprocess.CompletedProcess(
                command, bounded.returncode, bounded.stdout, bounded.stderr
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
        detail = _safe_provider_error(result.stderr)
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


def _publish_heartbeat(elapsed: float) -> None:
    publish(
        "progress",
        {
            "kind": "provider_heartbeat",
            "actor": "Provider",
            "elapsedMs": round(elapsed * 1000),
            "message": "Provider process is still running",
        },
    )


def _safe_provider_error(value: str) -> str:
    if not value.strip():
        return "provider command failed"
    redacted = redact_secrets(value).content
    redacted = redacted.replace("\x1b", "").replace("\x00", "")
    return redacted.strip()[-2000:] or "provider command failed"


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
