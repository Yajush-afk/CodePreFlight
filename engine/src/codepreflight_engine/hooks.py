from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner

SUPPORTED_HOOKS = {"pre-commit", "pre-push"}
START = "# >>> CodePreFlight managed block >>>"
END = "# <<< CodePreFlight managed block <<<"
BLOCK_PATTERN = re.compile(rf"\n?{re.escape(START)}.*?{re.escape(END)}\n?", re.DOTALL)


class HookManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        git_dir = GitRunner(root).run("rev-parse", "--git-dir").stdout.strip()
        self.git_dir = (
            (root / git_dir).resolve() if not Path(git_dir).is_absolute() else Path(git_dir)
        )
        self.state_dir = self.git_dir / "codepreflight" / "hooks"

    def apply(self, action: str, hook: str, *, write: bool = False) -> dict[str, Any]:
        self._validate_hook(hook)
        if action == "install":
            return self.install(hook, write=write)
        if action == "remove":
            return self.remove(hook, write=write)
        if action == "disable":
            return self.set_disabled(hook, disabled=True, write=write)
        if action == "enable":
            return self.set_disabled(hook, disabled=False, write=write)
        if action == "status":
            return self.status(hook)
        raise CodePreflightError("invalid_hook_action", f"Unknown hook action: {action}")

    def install(self, hook: str, *, write: bool) -> dict[str, Any]:
        path = self.git_dir / "hooks" / hook
        original = self._read(path)
        if original and not original.startswith("#!"):
            raise CodePreflightError(
                "hook_without_shebang",
                f"Existing {hook} hook has no shebang; "
                "CodePreFlight will not modify it automatically",
            )
        without_managed = BLOCK_PATTERN.sub("\n", original).rstrip()
        shebang = "#!/bin/sh"
        body = ""
        if without_managed:
            first, separator, remainder = without_managed.partition("\n")
            shebang = first
            body = remainder if separator else ""
        block = self._block(hook)
        installed = shebang + "\n" + block + ("\n" + body if body else "") + "\n"
        if write:
            self._save_metadata(hook, original, installed)
            self._atomic_write(path, installed)
            path.chmod(path.stat().st_mode | 0o111)
        return {
            "hook": hook,
            "action": "install",
            "written": write,
            "path": str(path),
            "preservedExistingContent": bool(body),
            "preview": installed,
        }

    def remove(self, hook: str, *, write: bool) -> dict[str, Any]:
        path = self.git_dir / "hooks" / hook
        current = self._read(path)
        metadata = self._metadata(hook)
        if not metadata and START not in current:
            return {"hook": hook, "action": "remove", "written": False, "installed": False}
        if metadata and self._hash(current) == metadata.get("installedHash"):
            restored = str(metadata.get("original", ""))
        else:
            restored = BLOCK_PATTERN.sub("\n", current).lstrip("\n")
            if restored == "#!/bin/sh\n":
                restored = ""
        if write:
            if restored:
                self._atomic_write(path, restored)
                path.chmod(path.stat().st_mode | 0o111)
            elif path.exists():
                path.unlink()
            self._metadata_path(hook).unlink(missing_ok=True)
            self._disabled_path(hook).unlink(missing_ok=True)
        return {
            "hook": hook,
            "action": "remove",
            "written": write,
            "path": str(path),
            "preview": restored,
        }

    def set_disabled(self, hook: str, *, disabled: bool, write: bool) -> dict[str, Any]:
        if START not in self._read(self.git_dir / "hooks" / hook):
            raise CodePreflightError("hook_not_installed", f"CodePreFlight does not manage {hook}")
        flag = self._disabled_path(hook)
        if write:
            flag.parent.mkdir(parents=True, exist_ok=True)
            if disabled:
                flag.write_text("disabled\n", encoding="utf-8")
            else:
                flag.unlink(missing_ok=True)
        return {"hook": hook, "action": "disable" if disabled else "enable", "written": write}

    def status(self, hook: str) -> dict[str, Any]:
        path = self.git_dir / "hooks" / hook
        return {
            "hook": hook,
            "path": str(path),
            "installed": START in self._read(path),
            "disabled": self._disabled_path(hook).exists(),
            "exists": path.exists(),
        }

    def _block(self, hook: str) -> str:
        review_args = "--staged" if hook == "pre-commit" else "--branch"
        return "\n".join(
            [
                START,
                f'disabled_file="$(git rev-parse --git-path codepreflight/hooks/{hook}.disabled)"',
                'if [ "${PREFLIGHT_BYPASS:-0}" != "1" ] && [ ! -f "$disabled_file" ]; then',
                "  codepreflight_status=0",
                f"  preflight review {review_args} --hook || codepreflight_status=$?",
                '  if [ "$codepreflight_status" -eq 1 ]; then exit 1; fi',
                '  if [ "$codepreflight_status" -gt 1 ]; then',
                '    echo "CodePreFlight review failed operationally; continuing (fail-open)." >&2',
                "  fi",
                "fi",
                END,
            ]
        )

    def _save_metadata(self, hook: str, original: str, installed: str) -> None:
        path = self._metadata_path(hook)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = self._metadata(hook)
            original = str(existing.get("original", original)) if existing else original
        path.write_text(
            json.dumps({"original": original, "installedHash": self._hash(installed)}, indent=2)
            + "\n",
            encoding="utf-8",
        )

    def _metadata(self, hook: str) -> dict[str, Any] | None:
        path = self._metadata_path(hook)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _metadata_path(self, hook: str) -> Path:
        return self.state_dir / f"{hook}.json"

    def _disabled_path(self, hook: str) -> Path:
        return self.state_dir / f"{hook}.disabled"

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.codepreflight-{os.getpid()}")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def _read(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CodePreflightError(
                "hook_unreadable", f"Cannot safely read hook {path}"
            ) from error

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _validate_hook(self, hook: str) -> None:
        if hook not in SUPPORTED_HOOKS:
            raise CodePreflightError(
                "unsupported_hook", f"Supported hooks: {', '.join(sorted(SUPPORTED_HOOKS))}"
            )
