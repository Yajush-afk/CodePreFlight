import json

import pytest

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.finding_schema import parse_provider_response


def test_parses_json_inside_markdown_fence() -> None:
    output = "```json\n" + json.dumps({"summary": "Clean.", "findings": []}) + "\n```"

    assert parse_provider_response(output).summary == "Clean."


def test_rejects_unstructured_provider_output() -> None:
    with pytest.raises(CodePreflightError) as error:
        parse_provider_response("Everything looks fine.")

    assert error.value.code == "provider_output_invalid"
