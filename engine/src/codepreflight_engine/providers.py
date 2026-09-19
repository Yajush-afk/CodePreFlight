from __future__ import annotations

import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .models import (
    AuthenticationState,
    InstallationState,
    InvocationState,
    ModelState,
    ProviderAvailability,
    ProviderDescriptor,
    ProviderKind,
    ProviderState,
)

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


def discover_providers(config: dict[str, Any] | None = None) -> list[ProviderDescriptor]:
    config = config or {}
    with ThreadPoolExecutor(max_workers=len(CLI_PROVIDERS)) as executor:
        providers = list(
            executor.map(
                lambda definition: _discover_cli_provider(definition, config), CLI_PROVIDERS
            )
        )

    configured = bool(os.environ.get("OPENAI_API_KEY"))
    providers.append(
        ProviderDescriptor(
            id="openai-compatible",
            name="OpenAI-compatible API",
            kind=ProviderKind.API,
            state=ProviderState.READY if configured else ProviderState.NOT_CONFIGURED,
            installation=InstallationState.INSTALLED,
            authentication=(
                AuthenticationState.AUTHENTICATED if configured else AuthenticationState.REQUIRED
            ),
            model=ModelState.READY if configured else ModelState.SELECTION_REQUIRED,
            invocation=InvocationState.UNTESTED,
            availability=(
                ProviderAvailability.READY if configured else ProviderAvailability.DEGRADED
            ),
            model_name=str(
                config.get("providers", {})
                .get("openai-compatible", {})
                .get("model", "gpt-4.1-mini")
            ),
            variant_name=(
                str(config.get("providers", {}).get("openai-compatible", {}).get("variant"))
                if config.get("providers", {}).get("openai-compatible", {}).get("variant")
                else None
            ),
            sends_code_remotely=True,
            detail="uses OPENAI_API_KEY" if configured else "set OPENAI_API_KEY",
        )
    )
    return providers


def _discover_cli_provider(
    definition: tuple[str, str, ProviderKind, bool], config: dict[str, Any]
) -> ProviderDescriptor:
    executable, name, kind, remote = definition
    path = shutil.which(executable)
    provider_config = config.get("providers", {}).get(executable, {})
    if path:
        with ThreadPoolExecutor(max_workers=2) as executor:
            version_future = executor.submit(_version, executable)
            health_future = executor.submit(_health, executable, provider_config)
            version = version_future.result()
            capabilities = health_future.result()
    else:
        version = None
        capabilities = {
            "state": ProviderState.NOT_INSTALLED,
            "installation": InstallationState.MISSING,
            "authentication": AuthenticationState.UNKNOWN,
            "model": ModelState.NOT_APPLICABLE,
            "invocation": InvocationState.UNTESTED,
            "availability": ProviderAvailability.UNAVAILABLE,
            "model_name": provider_config.get("model"),
            "variant_name": provider_config.get("variant"),
            "detail": "executable not found on PATH",
        }
    return ProviderDescriptor(
        id=executable,
        name=name,
        kind=kind,
        **capabilities,
        executable=path,
        version=version,
        sends_code_remotely=remote,
        experimental=executable == "claude",
    )


def _version(executable: str) -> str | None:
    result = _run([executable, "--version"])
    if result is None:
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def _health(executable: str, provider_config: dict[str, Any]) -> dict[str, Any]:
    if executable == "ollama":
        model_name = str(provider_config.get("model", "qwen2.5-coder:7b"))
        result = _run(["ollama", "list"])
        if not result or result.returncode != 0:
            return {
                "state": ProviderState.INSTALLED,
                "installation": InstallationState.INSTALLED,
                "authentication": AuthenticationState.NOT_APPLICABLE,
                "model": ModelState.MISSING,
                "invocation": InvocationState.FAILED,
                "availability": ProviderAvailability.DEGRADED,
                "model_name": model_name,
                "variant_name": None,
                "detail": "Ollama is installed but its runtime is unavailable",
            }
        names = {
            line.split()[0]
            for line in result.stdout.splitlines()[1:]
            if line.strip() and line.split()
        }
        available = model_name in names
        return {
            "state": ProviderState.READY if available else ProviderState.INSTALLED,
            "installation": InstallationState.INSTALLED,
            "authentication": AuthenticationState.NOT_APPLICABLE,
            "model": ModelState.READY if available else ModelState.MISSING,
            "invocation": InvocationState.UNTESTED,
            "availability": (
                ProviderAvailability.READY if available else ProviderAvailability.DEGRADED
            ),
            "model_name": model_name,
            "variant_name": None,
            "detail": (
                f"model {model_name} is available"
                if available
                else f"model {model_name} is not installed; run `ollama pull {model_name}`"
            ),
        }

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
            return {
                "state": ProviderState.ERROR,
                "installation": InstallationState.INSTALLED,
                "authentication": AuthenticationState.UNKNOWN,
                "model": ModelState.NOT_APPLICABLE,
                "invocation": InvocationState.INCOMPATIBLE,
                "availability": ProviderAvailability.UNAVAILABLE,
                "detail": f"installed version lacks required flags: {', '.join(missing)}",
            }

    health_commands = {
        "codex": ["codex", "login", "status"],
        "opencode": ["opencode", "auth", "list"],
        "claude": ["claude", "auth", "status"],
    }
    result = _run(health_commands[executable])
    output = _strip_ansi((result.stdout + result.stderr) if result else "")
    authenticated = bool(result and result.returncode == 0)
    if executable == "opencode":
        authenticated = authenticated and bool(re.search(r"(?m)^\s*[●•]\s+\S+", output))
    configured_model = provider_config.get("model")
    model_required = executable == "opencode" and not configured_model
    ready = authenticated and not model_required
    return {
        "state": ProviderState.READY if ready else ProviderState.INSTALLED,
        "installation": InstallationState.INSTALLED,
        "authentication": (
            AuthenticationState.AUTHENTICATED if authenticated else AuthenticationState.REQUIRED
        ),
        "model": ModelState.SELECTION_REQUIRED if model_required else ModelState.NOT_APPLICABLE,
        "model_name": configured_model,
        "variant_name": provider_config.get("variant"),
        "invocation": InvocationState.VERIFIED if authenticated else InvocationState.UNTESTED,
        "availability": ProviderAvailability.READY if ready else ProviderAvailability.DEGRADED,
        "detail": (
            "authentication verified; select a standard-tier model"
            if model_required
            else (
                "authentication and required CLI capabilities verified"
                if authenticated
                else "installed; authentication is required"
            )
        ),
    }


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)


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
