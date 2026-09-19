from __future__ import annotations

import json
import re

from pydantic import ValidationError

from .errors import CodePreflightError
from .models import ProviderReviewResponse


def provider_output_schema() -> dict[str, object]:
    schema = ProviderReviewResponse.model_json_schema()
    _make_strict_provider_schema(schema)
    return schema


def _make_strict_provider_schema(value: object) -> None:
    """Make Pydantic's schema compatible with strict provider output schemas.

    Codex/OpenAI require every object property to be listed in ``required``.
    Optional values remain optional through their nullable type, not omission.
    Defaults are validation behavior and are not part of the provider contract.
    """
    if isinstance(value, list):
        for item in value:
            _make_strict_provider_schema(item)
        return
    if not isinstance(value, dict):
        return
    value.pop("default", None)
    properties = value.get("properties")
    if isinstance(properties, dict):
        value["required"] = list(properties)
        value["additionalProperties"] = False
    for child in value.values():
        _make_strict_provider_schema(child)


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
