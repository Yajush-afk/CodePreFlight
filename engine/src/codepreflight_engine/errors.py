from __future__ import annotations

from typing import Any


class CodePreflightError(Exception):
    """Expected engine failure with a stable error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details
