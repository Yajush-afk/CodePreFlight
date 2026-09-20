from __future__ import annotations

import json
import os
import subprocess
import tomllib
from difflib import unified_diff
from pathlib import Path
from typing import Any

import tomli_w

from .config import (
    CodePreflightConfig,
    PersonalConfig,
    global_config_path,
    personal_config_path,
    repository_config_path,
)
from .errors import CodePreflightError

PROVIDER_IDS = {"ollama", "codex", "opencode", "claude", "openai-compatible"}


def configure_provider(
    root: Path,
    *,
    provider_id: str,
    model: str | None,
    scope: str,
    write: bool,
    variant: str | None = None,
) -> dict[str, object]:
    if provider_id not in PROVIDER_IDS:
        raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
    paths = {
        "personal": personal_config_path(root),
        "global": global_config_path(),
        "team": repository_config_path(root),
    }
    try:
        path = paths[scope]
    except KeyError as error:
        raise CodePreflightError(
            "invalid_config_scope",
            f"Unknown configuration scope: {scope}",
        ) from error
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        config: dict[str, Any] = tomllib.loads(current) if current else {}
    except tomllib.TOMLDecodeError as error:
        raise CodePreflightError(
            "invalid_config", f"Cannot read configuration at {path}: {error}"
        ) from error

    review = config.setdefault("review", {})
    if not isinstance(review, dict):
        raise CodePreflightError("invalid_config", "The review configuration must be a table")
    review["provider"] = provider_id
    if model:
        if _is_speed_model(model):
            raise CodePreflightError(
                "provider_speed_model_unsupported",
                "CodePreFlight uses the standard service tier only; select the non-fast model.",
                recoverable=True,
            )
        provider_settings = config.setdefault("providers", {})
        if not isinstance(provider_settings, dict):
            raise CodePreflightError(
                "invalid_config", "The providers configuration must be a table"
            )
        selected = provider_settings.setdefault(provider_id, {})
        if not isinstance(selected, dict):
            raise CodePreflightError(
                "invalid_config", f"Provider configuration for {provider_id} must be a table"
            )
        selected["model"] = model
        if variant is None:
            selected.pop("variant", None)
    if variant:
        provider_settings = config.setdefault("providers", {})
        if not isinstance(provider_settings, dict):
            raise CodePreflightError(
                "invalid_config", "The providers configuration must be a table"
            )
        selected = provider_settings.setdefault(provider_id, {})
        if not isinstance(selected, dict):
            raise CodePreflightError(
                "invalid_config", f"Provider configuration for {provider_id} must be a table"
            )
        selected["variant"] = variant

    if scope == "personal":
        PersonalConfig.model_validate(config)
    else:
        CodePreflightConfig.model_validate(config)
    rendered = tomli_w.dumps(config)
    diff = "".join(
        unified_diff(
            current.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(path) if current else "/dev/null",
            tofile=str(path),
        )
    )
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.codepreflight")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(path)
    return {
        "provider": provider_id,
        "model": model,
        "variant": variant,
        "scope": scope,
        "path": str(path),
        "written": write,
        "preview": rendered,
        "diff": diff,
    }


def provider_models(provider_id: str) -> dict[str, object]:
    if provider_id == "ollama":
        code, stdout, stderr = _run(["ollama", "list"])
        if code != 0:
            raise CodePreflightError(
                "provider_runtime_unavailable",
                stderr.strip() or "Ollama is unavailable",
                recoverable=True,
            )
        models = [
            line.split()[0] for line in stdout.splitlines()[1:] if line.strip() and line.split()
        ]
        return {
            "provider": provider_id,
            "models": models,
            "details": [
                {"id": model, "label": model, "description": "Local model"} for model in models
            ],
            "serviceTier": "standard",
        }
    if provider_id == "codex":
        entries = _codex_model_entries()
        details = [
            {
                "id": str(entry["slug"]),
                "label": str(entry.get("display_name") or entry["slug"]),
                "description": str(entry.get("description") or ""),
            }
            for entry in entries
        ]
        return {
            "provider": provider_id,
            "models": [item["id"] for item in details],
            "details": details,
            "serviceTier": "standard",
        }
    if provider_id == "opencode":
        code, stdout, stderr = _run(["opencode", "models"])
        if code != 0:
            raise CodePreflightError(
                "provider_models_unavailable",
                stderr.strip() or "OpenCode models are unavailable",
                recoverable=True,
            )
        models = [
            line.strip()
            for line in stdout.splitlines()
            if "/" in line and line.strip() and not _is_speed_model(line.strip())
        ]
        return {
            "provider": provider_id,
            "models": models,
            "details": [{"id": model, "label": model, "description": ""} for model in models],
            "serviceTier": "standard",
        }
    if provider_id not in PROVIDER_IDS:
        raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
    return {"provider": provider_id, "models": [], "details": [], "serviceTier": "standard"}


def provider_variants(provider_id: str, model: str) -> dict[str, object]:
    if not model:
        raise CodePreflightError(
            "provider_model_required",
            "Select a model before selecting a variant.",
            recoverable=True,
        )
    variants: list[str] = []
    default_variant: str | None = None
    if provider_id == "codex":
        entry = next((item for item in _codex_model_entries() if item.get("slug") == model), None)
        if entry:
            variants = [
                str(item["effort"])
                for item in entry.get("supported_reasoning_levels", [])
                if isinstance(item, dict) and item.get("effort")
            ]
            default_variant = str(entry.get("default_reasoning_level") or "") or None
    elif provider_id == "opencode":
        provider_name = model.split("/", 1)[0]
        code, stdout, stderr = _run(["opencode", "models", provider_name, "--verbose"])
        if code != 0:
            raise CodePreflightError(
                "provider_variants_unavailable",
                stderr.strip() or "OpenCode model variants are unavailable",
                recoverable=True,
            )
        marker = f"{model}\n"
        marker_index = stdout.find(marker)
        object_index = stdout.find("{", marker_index + len(marker)) if marker_index >= 0 else -1
        if object_index >= 0:
            try:
                metadata, _ = json.JSONDecoder().raw_decode(stdout[object_index:])
            except json.JSONDecodeError:
                metadata = {}
            raw_variants = metadata.get("variants", {}) if isinstance(metadata, dict) else {}
            if isinstance(raw_variants, dict):
                variants = [str(value) for value in raw_variants]
    elif provider_id not in PROVIDER_IDS:
        raise CodePreflightError("unknown_provider", f"Unknown provider: {provider_id}")
    return {
        "provider": provider_id,
        "model": model,
        "variants": variants,
        "defaultVariant": default_variant,
        "serviceTier": "standard",
    }


def _codex_model_entries() -> list[dict[str, Any]]:
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    path = root / "models_cache.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = value.get("models", []) if isinstance(value, dict) else []
    return [
        item
        for item in raw
        if isinstance(item, dict)
        and item.get("slug")
        and item.get("visibility", "list") != "hide"
        and not _is_speed_model(str(item["slug"]))
    ]


def _is_speed_model(model: str) -> bool:
    name = model.lower().rsplit("/", 1)[-1]
    return name.endswith("-fast") or name.endswith(":fast")


def _run(command: list[str]) -> tuple[int, str, str]:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CodePreflightError(
            "provider_command_failed",
            f"Could not run {' '.join(command)}: {error}",
            recoverable=True,
        ) from error
    return result.returncode, result.stdout, result.stderr
