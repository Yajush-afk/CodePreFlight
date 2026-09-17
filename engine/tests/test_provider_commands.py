from pathlib import Path

from codepreflight_engine.adapters.cli import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    OpenCodeCliAdapter,
)


def test_codex_command_is_ephemeral_and_read_only(tmp_path: Path) -> None:
    command = CodexCliAdapter.command(tmp_path / "schema.json", tmp_path / "output.json", tmp_path)

    assert command[:2] == ["codex", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in command
    assert "--output-schema" in command


def test_claude_command_disables_mutating_tools() -> None:
    command = ClaudeCliAdapter.command()

    assert command[:2] == ["claude", "-p"]
    assert "--disallowedTools" in command
    assert all(tool in command for tool in ("Bash", "Edit", "Write", "NotebookEdit"))


def test_opencode_command_uses_isolated_directory(tmp_path: Path) -> None:
    command = OpenCodeCliAdapter.command(tmp_path)

    assert command[:2] == ["opencode", "run"]
    assert command[command.index("--dir") + 1] == str(tmp_path)
