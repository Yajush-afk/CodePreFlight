from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .models import (
    ConsensusFinding,
    Finding,
    PanelProviderResult,
    PanelReviewResult,
)
from .review import EventEmitter, ReviewOrchestrator


class PanelReviewer:
    def review(self, root: Path, payload: dict[str, Any], emit: EventEmitter) -> PanelReviewResult:
        provider_ids = payload.get("providers")
        if not isinstance(provider_ids, list) or len(provider_ids) < 2:
            raise CodePreflightError(
                "panel_providers_required", "Panel review requires at least two providers"
            )
        normalized = [str(provider_id) for provider_id in provider_ids]
        if len(set(normalized)) != len(normalized):
            raise CodePreflightError(
                "panel_providers_duplicate", "Panel providers must be distinct"
            )
        if len(normalized) > 5:
            raise CodePreflightError(
                "panel_providers_limit", "Panel review supports at most five providers"
            )
        results: list[PanelProviderResult] = []
        for provider_id in normalized:
            emit("progress", {"message": f"Running panel provider {provider_id}"})
            try:
                review = ReviewOrchestrator().review(
                    root,
                    {**payload, "provider": str(provider_id)},
                    emit,
                )
                results.append(PanelProviderResult(provider=str(provider_id), review=review))
            except CodePreflightError as error:
                results.append(PanelProviderResult(provider=str(provider_id), error=str(error)))
        if not any(result.review for result in results):
            raise CodePreflightError("panel_failed", "Every panel provider failed")
        return PanelReviewResult(results=results, consensus=self._consensus(results))

    def _consensus(self, results: list[PanelProviderResult]) -> list[ConsensusFinding]:
        groups: list[tuple[list[str], list[Finding]]] = []
        for result in results:
            if not result.review:
                continue
            for finding in result.review.findings:
                matching = next(
                    (group for group in groups if group[1] and self._related(group[1][0], finding)),
                    None,
                )
                if matching:
                    matching[0].append(result.provider)
                    matching[1].append(finding)
                else:
                    groups.append(([result.provider], [finding]))
        consensus = []
        for providers, findings in groups:
            identity = hashlib.sha256(
                f"{findings[0].evidence[0].path}|{findings[0].title}".encode()
            ).hexdigest()[:12]
            consensus.append(
                ConsensusFinding(
                    key=identity,
                    providers=providers,
                    findings=findings,
                    agreement=len(set(providers)),
                    severity_conflict=len({finding.severity for finding in findings}) > 1,
                )
            )
        return sorted(consensus, key=lambda item: (-item.agreement, item.key))

    def _related(self, left: Finding, right: Finding) -> bool:
        left_location, right_location = left.evidence[0], right.evidence[0]
        if left_location.path != right_location.path:
            return False
        overlaps = not (
            left_location.end_line < right_location.start_line
            or right_location.end_line < left_location.start_line
        )
        if not overlaps:
            return False
        left_tokens = self._tokens(left.title)
        right_tokens = self._tokens(right.title)
        union = left_tokens | right_tokens
        return bool(union) and len(left_tokens & right_tokens) / len(union) >= 0.35

    def _tokens(self, value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if token not in {"the", "a", "an", "is", "may", "can", "potential"}
        }
