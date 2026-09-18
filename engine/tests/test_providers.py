from __future__ import annotations

import subprocess

import pytest

from codepreflight_engine import providers
from codepreflight_engine.models import (
    AuthenticationState,
    InstallationState,
    InvocationState,
    ModelState,
    ProviderAvailability,
)


def completed(
    command: list[str], stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def test_ollama_without_configured_model_is_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda executable: f"/bin/{executable}")

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command == ["ollama", "--version"]:
            return completed(command, "ollama version 1.0\n")
        if command == ["ollama", "list"]:
            return completed(command, "NAME ID SIZE MODIFIED\n")
        return completed(command, returncode=1)

    monkeypatch.setattr(providers, "_run", run)

    descriptor = next(
        item
        for item in providers.discover_providers(
            {"providers": {"ollama": {"model": "qwen2.5-coder:7b"}}}
        )
        if item.id == "ollama"
    )

    assert descriptor.installation == InstallationState.INSTALLED
    assert descriptor.authentication == AuthenticationState.NOT_APPLICABLE
    assert descriptor.model == ModelState.MISSING
    assert descriptor.invocation == InvocationState.UNTESTED
    assert descriptor.availability == ProviderAvailability.DEGRADED
    assert "qwen2.5-coder:7b" in (descriptor.detail or "")


def test_ollama_with_configured_model_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers.shutil, "which", lambda executable: f"/bin/{executable}")

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command == ["ollama", "--version"]:
            return completed(command, "ollama version 1.0\n")
        if command == ["ollama", "list"]:
            return completed(
                command,
                "NAME ID SIZE MODIFIED\nqwen2.5-coder:7b abc 4 GB today\n",
            )
        return completed(command, returncode=1)

    monkeypatch.setattr(providers, "_run", run)

    descriptor = next(
        item
        for item in providers.discover_providers(
            {"providers": {"ollama": {"model": "qwen2.5-coder:7b"}}}
        )
        if item.id == "ollama"
    )

    assert descriptor.model == ModelState.READY
    assert descriptor.availability == ProviderAvailability.READY


def test_opencode_without_any_credentials_requires_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        providers.shutil,
        "which",
        lambda executable: "/bin/opencode" if executable == "opencode" else None,
    )

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        if command == ["opencode", "--version"]:
            return completed(command, "1.0\n")
        if command == ["opencode", "run", "--help"]:
            return completed(command, "--format --dir --pure\n")
        if command == ["opencode", "auth", "list"]:
            return completed(command, "Credentials ~/.local/share/opencode/auth.json\n")
        return completed(command, returncode=1)

    monkeypatch.setattr(providers, "_run", run)

    descriptor = next(item for item in providers.discover_providers({}) if item.id == "opencode")

    assert descriptor.authentication == AuthenticationState.REQUIRED
    assert descriptor.availability == ProviderAvailability.DEGRADED
