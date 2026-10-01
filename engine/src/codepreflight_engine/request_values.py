from __future__ import annotations

from typing import Any

from .errors import CodePreflightError


def request_flag(payload: dict[str, Any], name: str, *, default: bool = False) -> bool:
    """Read a request boolean without accepting truthy strings or numbers."""
    value = payload.get(name, default)
    if type(value) is not bool:
        raise CodePreflightError(
            "invalid_request_flag",
            f"Request field `{name}` must be a boolean",
            recoverable=True,
            details={"field": name, "expected": "boolean"},
        )
    return value
