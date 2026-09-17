from __future__ import annotations

import json
import tempfile
from pathlib import Path

from codepreflight_engine.adapters.process import (
    extract_json_event_text,
    run_provider_process,
    sanitized_environment,
)
from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.models import ProviderDescriptor


class CodexCliAdapter:
    def __init__(self, descriptor: ProviderDescriptor, *, timeout: int = 180) -> None:
        self.descriptor = descriptor
        self.timeout = timeout

    @staticmethod
    def command(schema_path: Path, output_path: Path, cwd: Path) -> list[str]:
        return [
            "codex",
            "exec",
            "--cd",
            str(cwd),
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        with tempfile.TemporaryDirectory(prefix="codepreflight-codex-") as temporary:
            root = Path(temporary)
            schema_path = root / "review-schema.json"
            output_path = root / "review.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            run_provider_process(
                self.command(schema_path, output_path, root),
                prompt=prompt,
                cwd=root,
                timeout=self.timeout,
            )
            if not output_path.exists():
                raise CodePreflightError(
                    "provider_output_invalid", "Codex produced no final output"
                )
            return output_path.read_text(encoding="utf-8")


class ClaudeCliAdapter:
    def __init__(self, descriptor: ProviderDescriptor, *, timeout: int = 180) -> None:
        self.descriptor = descriptor
        self.timeout = timeout

    @staticmethod
    def command() -> list[str]:
        return [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "plan",
            "--disallowedTools",
            "Bash",
            "Edit",
            "Write",
            "NotebookEdit",
        ]

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        with tempfile.TemporaryDirectory(prefix="codepreflight-claude-") as temporary:
            result = run_provider_process(
                self.command(),
                prompt=prompt + "\n\nRequired JSON Schema:\n" + json.dumps(schema),
                cwd=Path(temporary),
                timeout=self.timeout,
            )
            try:
                value = json.loads(result.stdout)
            except json.JSONDecodeError as error:
                raise CodePreflightError(
                    "provider_output_invalid", "Claude Code returned invalid JSON"
                ) from error
            result_text = value.get("result") if isinstance(value, dict) else None
            if isinstance(result_text, str):
                return result_text
            raise CodePreflightError(
                "provider_output_invalid", "Claude Code response did not contain a result"
            )


class OpenCodeCliAdapter:
    def __init__(self, descriptor: ProviderDescriptor, *, timeout: int = 180) -> None:
        self.descriptor = descriptor
        self.timeout = timeout

    @staticmethod
    def command(cwd: Path) -> list[str]:
        return ["opencode", "run", "--format", "json", "--pure", "--dir", str(cwd)]

    def review(self, prompt: str, schema: dict[str, object]) -> str:
        with tempfile.TemporaryDirectory(prefix="codepreflight-opencode-") as temporary:
            root = Path(temporary)
            environment = sanitized_environment(
                {
                    "OPENCODE_CONFIG_CONTENT": json.dumps(
                        {"tools": {"write": False, "edit": False, "bash": False}}
                    )
                }
            )
            result = run_provider_process(
                self.command(root),
                prompt=prompt + "\n\nRequired JSON Schema:\n" + json.dumps(schema),
                cwd=root,
                timeout=self.timeout,
                environment=environment,
            )
            output = extract_json_event_text(result.stdout)
            if not output:
                raise CodePreflightError(
                    "provider_output_invalid", "OpenCode returned no review text"
                )
            return output
