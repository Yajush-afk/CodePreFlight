from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from .errors import CodePreflightError

PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)


@dataclass(frozen=True)
class RedactionResult:
    content: str
    count: int
    safe: bool = True


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
    safe = "-----BEGIN " not in redacted or "PRIVATE KEY-----" not in redacted
    return RedactionResult(redacted, count, safe)


def verify_with_external_scanner(content: str) -> str:
    executable = shutil.which("gitleaks")
    if not executable:
        return "built-in"
    try:
        result = subprocess.run(
            [
                executable,
                "stdin",
                "--no-banner",
                "--no-color",
                "--redact=100",
                "--report-format",
                "json",
            ],
            input=content,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CodePreflightError(
            "secret_scanner_failed",
            f"Installed gitleaks scanner could not complete: {error}",
            recoverable=True,
        ) from error
    if result.returncode == 1:
        raise CodePreflightError(
            "unsafe_secret_content",
            "Gitleaks found a credential that CodePreFlight could not safely redact",
            recoverable=True,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown scanner failure"
        raise CodePreflightError(
            "secret_scanner_failed",
            f"Installed gitleaks scanner failed: {detail[-1000:]}",
            recoverable=True,
        )
    return "built-in+gitleaks"
