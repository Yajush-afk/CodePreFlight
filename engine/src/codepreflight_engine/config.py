from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import CodePreflightError
from .models import CheckDefinition

SECRET_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewSettings(ConfigModel):
    provider: str | None = None
    depth: Literal["fast", "standard", "deep"] | None = None
    context_limit: int | None = Field(default=None, ge=4_000, le=1_000_000)
    policy: Literal["informational", "warning", "block"] | None = None
    block_severities: list[Literal["critical", "warning", "suggestion", "informational"]] | None = (
        None
    )


class ProviderSettings(ConfigModel):
    model: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=1800)


class HookSettings(ConfigModel):
    remote_provider_approved: bool | None = None
    fail_closed: bool | None = None


class CacheSettings(ConfigModel):
    enabled: bool | None = None


class ScanSettings(ConfigModel):
    batch_characters: int | None = Field(default=None, ge=4_000, le=500_000)
    max_file_bytes: int | None = Field(default=None, ge=1_000, le=5_000_000)


class GitSettings(ConfigModel):
    base_branch: str | None = None


class CodePreflightConfig(ConfigModel):
    version: Literal[1] | None = None
    review: ReviewSettings | None = None
    providers: dict[str, ProviderSettings] | None = None
    checks: list[CheckDefinition] | None = None
    ignore: list[str] | None = None
    rules: list[str] | None = None
    hooks: HookSettings | None = None
    cache: CacheSettings | None = None
    scan: ScanSettings | None = None
    git: GitSettings | None = None
    base_branch: str | None = None


def global_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "codepreflight" / "config.toml"


def repository_config_path(root: Path) -> Path:
    return root / ".codepreflight.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CodePreflightError(
            "invalid_config", f"Cannot read configuration at {path}: {error}"
        ) from error
    _reject_secrets(value, path)
    return value


def _reject_secrets(value: object, path: Path, prefix: str = "") -> None:
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        qualified = f"{prefix}.{key}" if prefix else str(key)
        normalized = str(key).lower().replace("-", "_")
        if any(fragment in normalized for fragment in SECRET_FRAGMENTS) and not normalized.endswith(
            "_env"
        ):
            raise CodePreflightError(
                "secret_in_config",
                f"Configuration key '{qualified}' in {path} may contain a secret; "
                "use an environment-variable reference",
            )
        _reject_secrets(child, path, qualified)


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(root: Path) -> dict[str, Any]:
    merged = _merge(_read_toml(global_config_path()), _read_toml(repository_config_path(root)))
    try:
        CodePreflightConfig.model_validate(merged)
    except ValidationError as error:
        fields = [
            {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
            for item in error.errors()
        ]
        summary = "; ".join(f"{item['field']}: {item['message']}" for item in fields)
        raise CodePreflightError(
            "invalid_config",
            f"Configuration validation failed: {summary}",
            details={"fields": fields},
        ) from error
    return merged
