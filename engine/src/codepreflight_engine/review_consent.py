from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import CodePreflightError
from .models import ContextPackage, ProviderDescriptor
from .readiness import consent_fingerprint, provider_destination, remote_approval_matches


def require_review_consent(
    provider: ProviderDescriptor,
    context: ContextPackage,
    config: dict[str, Any],
    payload: dict[str, Any],
    emit: Callable[[str, dict[str, Any]], None],
) -> None:
    emit(
        "consent_required",
        {
            "provider": provider.model_dump(mode="json"),
            "consentScope": consent_fingerprint(provider, config),
            "contextCharacters": context.manifest.total_characters,
            "redactions": context.manifest.redactions,
            "manifest": context.manifest.model_dump(mode="json"),
            "destination": {
                "kind": provider.kind.value,
                "remote": provider.sends_code_remotely,
                "address": provider_destination(provider, config),
            },
        },
    )
    hook_approval = bool(payload.get("hook")) and bool(
        config.get("hooks", {}).get("remote_provider_approved", False)
    )
    if provider.sends_code_remotely and not (
        remote_approval_matches(provider, config, payload) or hook_approval
    ):
        raise CodePreflightError(
            "provider_consent_required",
            f"{provider.name} may send code remotely; review the disclosure before approving",
            recoverable=True,
        )
