from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import personal_config_path
from .errors import CodePreflightError
from .models import ProviderDescriptor


class ProviderHealth:
    """Repository-private evidence from actual successful provider invocations."""

    def __init__(self, root: Path) -> None:
        self.path = personal_config_path(root).with_name("provider-health.json")

    def fingerprint(self, provider: ProviderDescriptor, config: dict[str, Any]) -> str:
        settings = config.get("providers", {}).get(provider.id, {})
        identity = {
            "id": provider.id,
            "kind": provider.kind.value,
            "executable": provider.executable,
            "version": provider.version,
            "model": provider.model_name,
            "variant": provider.variant_name,
            "destination": settings.get("base_url", provider.kind.value),
            "credentialSource": settings.get("api_key_env"),
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def verified(self, provider: ProviderDescriptor, config: dict[str, Any]) -> bool:
        record = self._read().get(provider.id)
        return isinstance(record, dict) and record.get("fingerprint") == self.fingerprint(
            provider, config
        )

    def record(self, provider: ProviderDescriptor, config: dict[str, Any]) -> None:
        records = self._read()
        records[provider.id] = {
            "fingerprint": self.fingerprint(provider, config),
            "verifiedAt": datetime.now(UTC).isoformat(),
        }
        self._write(records)

    def invalidate(self, provider: ProviderDescriptor) -> None:
        records = self._read()
        if records.pop(provider.id, None) is not None:
            self._write(records)

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, records: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(records, sort_keys=True) + "\n")
        try:
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


def require_review_ready(
    root: Path, provider: ProviderDescriptor, config: dict[str, Any], *, evidence: bool = False
) -> None:
    readiness = review_readiness(
        provider,
        verified=ProviderHealth(root).verified(provider, config),
        require_verified=evidence,
    )
    if readiness["state"] != "ready":
        raise CodePreflightError(
            "provider_unavailable",
            "; ".join(item["message"] for item in readiness["blockers"]),
            recoverable=True,
            details={
                "readiness": readiness,
                "actions": [item["action"] for item in readiness["blockers"]],
            },
        )


def review_readiness(
    provider: ProviderDescriptor, *, verified: bool = False, require_verified: bool = False
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    requirements = [
        (
            provider.installation == "missing",
            "installation",
            "Install this provider CLI",
            "install_provider",
        ),
        (
            provider.authentication in {"required", "unknown"},
            "authentication",
            "Sign in to this provider",
            "authenticate_provider",
        ),
        (
            provider.model in {"missing", "selection_required"},
            "model",
            "Select an available model",
            "select_model",
        ),
        (
            provider.invocation == "incompatible",
            "compatibility",
            "Update the provider CLI",
            "update_provider",
        ),
        (
            require_verified and not verified,
            "invocation",
            "Test the provider connection first",
            "test_provider",
        ),
    ]
    for missing, capability, message, action in requirements:
        if missing:
            blockers.append(
                {
                    "code": f"provider_{capability}_required",
                    "message": message,
                    "capability": capability,
                    "action": {"type": action, "provider": provider.id},
                    "interactive": True,
                    "affectsGlobalAuthentication": action == "authenticate_provider",
                }
            )
    if not blockers and provider.availability != "ready":
        blockers.append(
            {
                "code": "provider_unavailable",
                "message": provider.detail or "Provider unavailable",
                "capability": "runtime",
                "action": {"type": "select_provider"},
                "interactive": True,
                "affectsGlobalAuthentication": False,
            }
        )
    unavailable = provider.installation == "missing" or provider.invocation == "incompatible"
    return {
        "state": "unavailable" if unavailable else "action_required" if blockers else "ready",
        "blockers": blockers,
        "invocationVerified": verified,
    }
