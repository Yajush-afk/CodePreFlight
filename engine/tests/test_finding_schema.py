import json

import pytest

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.finding_schema import (
    parse_provider_response,
    provider_output_schema,
    strict_provider_schema,
)
from codepreflight_engine.models import RepositoryAnswer


def test_provider_schema_requires_every_object_property_for_codex() -> None:
    schema = provider_output_schema()

    assert schema["required"] == ["summary", "findings"]
    evidence = schema["$defs"]["EvidenceLocation"]
    assert evidence["required"] == ["path", "start_line", "end_line", "symbol"]
    assert "default" not in evidence["properties"]["symbol"]
    finding = schema["$defs"]["FindingDraft"]
    assert finding["required"] == list(finding["properties"])


def test_follow_up_schema_requires_nullable_evidence_fields_for_codex() -> None:
    schema = strict_provider_schema(RepositoryAnswer)

    assert schema["required"] == ["answer", "evidence", "uncertainty"]
    evidence = schema["$defs"]["ExplanationEvidence"]
    assert evidence["required"] == ["path", "line", "commit"]
    assert {"type": "null"} in evidence["properties"]["line"]["anyOf"]
    assert "default" not in evidence["properties"]["line"]


def test_parses_json_inside_markdown_fence() -> None:
    output = "```json\n" + json.dumps({"summary": "Clean.", "findings": []}) + "\n```"

    assert parse_provider_response(output).summary == "Clean."


def test_rejects_unstructured_provider_output() -> None:
    with pytest.raises(CodePreflightError) as error:
        parse_provider_response("Everything looks fine.")

    assert error.value.code == "provider_output_invalid"
