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


def discover_providers() -> list[ProviderDescriptor]:
    providers: list[ProviderDescriptor] = []
    for executable, name, kind, remote in CLI_PROVIDERS:
        path = shutil.which(executable)
        version = _version(executable) if path else None
        providers.append(
            ProviderDescriptor(
                id=executable,
                name=name,
                kind=kind,
                state=ProviderState.INSTALLED if path else ProviderState.NOT_INSTALLED,
                executable=path,
                version=version,
                sends_code_remotely=remote,
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
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None
