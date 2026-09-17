from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from .errors import CodePreflightError

SECRET_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")


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
    return _merge(_read_toml(global_config_path()), _read_toml(repository_config_path(root)))
