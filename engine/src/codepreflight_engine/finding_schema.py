from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .errors import CodePreflightError
from .models import ProviderReviewResponse


def provider_output_schema() -> dict[str, object]:
    return ProviderReviewResponse.model_json_schema()


def provider_output_schema_json() -> str:
    return json.dumps(provider_output_schema(), separators=(",", ":"))


def parse_provider_response(output: str) -> ProviderReviewResponse:
    candidates = [output.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", output, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    first, last = output.find("{"), output.rfind("}")
    if first >= 0 and last > first:
        candidates.append(output[first : last + 1])

    errors: list[str] = []
    for candidate in dict.fromkeys(candidates):
        try:
            return ProviderReviewResponse.model_validate_json(candidate)
        except (ValidationError, ValueError) as error:
            errors.append(str(error))
    raise CodePreflightError(
        "provider_output_invalid",
        "Provider did not return the required review JSON: " + errors[-1][:500],
    )
