from __future__ import annotations

import re
from dataclasses import dataclass

PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


@dataclass(frozen=True)
class RedactionResult:
    content: str
    count: int


def redact_secrets(content: str) -> RedactionResult:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        if match.lastindex and match.lastindex >= 2:
            return match.group(0).replace(match.group(2), "[REDACTED]")
        return "[REDACTED SECRET]"

    redacted = content
    for pattern in PATTERNS:
        redacted = pattern.sub(replace, redacted)
    return RedactionResult(redacted, count)
