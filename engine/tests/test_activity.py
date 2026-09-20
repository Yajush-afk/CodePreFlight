import subprocess

import pytest

from codepreflight_engine.activity import activity_scope, operation, sanitized_command
from codepreflight_engine.errors import CodePreflightError


def test_activity_sanitizes_credentials_and_never_captures_error_content():
    events = []
    with (
        activity_scope(lambda event, payload: events.append((event, payload))),
        pytest.raises(CodePreflightError),
        operation("Provider", "review", ["tool", "--token", "sensitive"]),
    ):
        raise CodePreflightError("provider_timeout", "raw secret response")
    assert events[0][0] == "operation_started"
    assert events[-1][1]["status"] == "timed_out"
    assert "sensitive" not in str(events)
    assert "raw secret response" not in str(events)


def test_command_redaction():
    output = sanitized_command(["tool", "token=private", "https://name:password@host"])
    assert "private" not in output
    assert "password@" not in output


def test_skipped_operation_event():
    events = []
    with (
        activity_scope(lambda event, payload: events.append((event, payload))),
        operation("Check", "validation") as record,
    ):
        record["outcome"] = "skipped"
    assert events[-1][0] == "operation_skipped"


def test_timeout_classification_and_commit_content_redaction():
    events = []
    with (
        activity_scope(lambda event, payload: events.append((event, payload))),
        pytest.raises(subprocess.TimeoutExpired),
        operation("Provider", "review"),
    ):
        raise subprocess.TimeoutExpired(["tool"], 1)
    assert events[-1][1]["status"] == "timed_out"
    assert "private message" not in sanitized_command(["git", "commit", "-m", "private message"])
