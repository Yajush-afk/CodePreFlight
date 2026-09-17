from __future__ import annotations

import os
import shutil
import subprocess

from .models import ProviderDescriptor, ProviderKind, ProviderState

CLI_PROVIDERS = (
    ("ollama", "Ollama", ProviderKind.LOCAL, False),
    ("codex", "Codex CLI", ProviderKind.SUBSCRIPTION_CLI, True),
    ("opencode", "OpenCode", ProviderKind.SUBSCRIPTION_CLI, True),
    ("claude", "Claude Code", ProviderKind.SUBSCRIPTION_CLI, True),
)

REQUIRED_FLAGS = {
    "codex": ("--output-schema", "--sandbox", "--ephemeral"),
    "opencode": ("--format", "--dir", "--pure"),
    "claude": ("--output-format", "--disallowedTools", "--permission-mode"),
}


def discover_providers() -> list[ProviderDescriptor]:
    providers: list[ProviderDescriptor] = []
    for executable, name, kind, remote in CLI_PROVIDERS:
        path = shutil.which(executable)
        version = _version(executable) if path else None
        state, detail = _health(executable) if path else (ProviderState.NOT_INSTALLED, None)
        providers.append(
            ProviderDescriptor(
                id=executable,
                name=name,
                kind=kind,
                state=state,
                executable=path,
                version=version,
                sends_code_remotely=remote,
                detail=detail,
            )
        )

    configured = bool(os.environ.get("OPENAI_API_KEY"))
    providers.append(
        ProviderDescriptor(
            id="openai-compatible",
            name="OpenAI-compatible API",
            kind=ProviderKind.API,
            state=ProviderState.READY if configured else ProviderState.NOT_CONFIGURED,
            sends_code_remotely=True,
            detail="uses OPENAI_API_KEY" if configured else "set OPENAI_API_KEY",
        )
    )
    return providers


def _version(executable: str) -> str | None:
    result = _run([executable, "--version"])
    if result is None:
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def _health(executable: str) -> tuple[ProviderState, str | None]:
    if executable in REQUIRED_FLAGS:
        help_command = (
            [executable, "exec", "--help"]
            if executable == "codex"
            else [executable, "run", "--help"]
        )
        if executable == "claude":
            help_command = [executable, "--help"]
        help_result = _run(help_command)
        help_output = (help_result.stdout + help_result.stderr) if help_result else ""
        missing = [flag for flag in REQUIRED_FLAGS[executable] if flag not in help_output]
        if missing:
            return (
                ProviderState.ERROR,
                f"installed version lacks required flags: {', '.join(missing)}",
            )

    health_commands = {
        "ollama": ["ollama", "list"],
        "codex": ["codex", "login", "status"],
        "opencode": ["opencode", "auth", "list"],
        "claude": ["claude", "auth", "status"],
    }
    result = _run(health_commands[executable])
    if result and result.returncode == 0:
        return ProviderState.READY, "authentication/runtime check passed"
    return ProviderState.INSTALLED, "installed; authentication or runtime readiness is unconfirmed"


def _run(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
