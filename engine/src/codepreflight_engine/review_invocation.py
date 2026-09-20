from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .adapters.base import ProviderAdapter
from .errors import CodePreflightError
from .finding_schema import parse_provider_response, provider_output_schema
from .models import ProviderReviewResponse, ReviewFailure
from .readiness import ProviderHealth


class ReviewInvocation:
    """Owns provider execution and the single structured-output repair budget."""

    def __init__(self, adapter: ProviderAdapter, root: Path) -> None:
        self.adapter = adapter
        self.health = ProviderHealth(root)

    def run(
        self, prompt: str, emit: Callable[[str, dict[str, Any]], None]
    ) -> ProviderReviewResponse | ReviewFailure:
        self.health.invalidate(self.adapter.descriptor)
        output = self.adapter.review(prompt, provider_output_schema())
        emit("provider_delta", {"characters": len(output)})
        try:
            return parse_provider_response(output)
        except CodePreflightError as error:
            if error.code != "provider_output_invalid":
                raise
        emit("progress", {"message": "Repairing malformed structured provider output"})
        repaired = self.adapter.review(
            "Convert the following malformed review response into JSON matching the supplied "
            "schema. Preserve only claims already present. Do not add findings, evidence, or "
            "facts. Return only the repaired JSON.\n\n" + output[-12_000:],
            provider_output_schema(),
        )
        emit("provider_delta", {"characters": len(repaired), "repair": True})
        try:
            return parse_provider_response(repaired)
        except CodePreflightError as error:
            if error.code != "provider_output_invalid":
                raise
            return ReviewFailure(
                code="provider_output_invalid",
                message=str(error),
                provider_response=repaired[-12_000:],
                attempts=2,
            )
