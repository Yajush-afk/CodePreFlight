from pathlib import Path

from codepreflight_engine.adapters.cli import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    OpenCodeCliAdapter,
)
from codepreflight_engine.adapters.fake import FakeProviderAdapter
from codepreflight_engine.adapters.registry import ProviderRegistry


def test_codex_command_is_ephemeral_and_read_only(tmp_path: Path) -> None:
    command = CodexCliAdapter.command(
        tmp_path / "schema.json",
        tmp_path / "output.json",
        tmp_path,
        model="gpt-economy",
        variant="high",
    )

    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--output-schema" in command
    assert command[command.index("--model") + 1] == "gpt-economy"
    assert 'model_reasoning_effort="high"' in command
    assert "priority" not in " ".join(command)


def test_claude_command_disables_mutating_tools() -> None:
    command = ClaudeCliAdapter.command()

    assert command[:2] == ["claude", "-p"]
    assert "--disallowedTools" in command
    assert all(tool in command for tool in ("Bash", "Edit", "Write", "NotebookEdit"))


def test_opencode_command_uses_isolated_directory(tmp_path: Path) -> None:
    command = OpenCodeCliAdapter.command(tmp_path, model="openai/gpt-economy", variant="high")

    assert command[:2] == ["opencode", "run"]
    assert command[command.index("--dir") + 1] == str(tmp_path)
    assert command[command.index("--model") + 1] == "openai/gpt-economy"
    assert command[command.index("--variant") + 1] == "high"


def test_provider_smoke_test_uses_only_synthetic_content(monkeypatch) -> None:
    fake = FakeProviderAdapter('{"summary":"Provider ready.","findings":[]}')
    registry = ProviderRegistry({})
    monkeypatch.setattr(registry, "adapter", lambda provider_id: fake)

    result = registry.smoke_test("fake")

    assert result == {
        "provider": "fake",
        "ready": True,
        "summary": "Provider ready.",
    }
    assert "synthetic" in fake.requests[0][0].lower()
    assert "repository" not in fake.requests[0][0].lower()
