from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from codepreflight_engine.activity import activity_scope
from codepreflight_engine.adapters.http import _post
from codepreflight_engine.adapters.process import run_provider_process
from codepreflight_engine.errors import CodePreflightError


class FailingResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status
        self.request = httpx.Request("POST", "https://provider.invalid")

    def raise_for_status(self) -> None:
        response = httpx.Response(self.status_code, request=self.request)
        raise httpx.HTTPStatusError("failed", request=self.request, response=response)

    def json(self) -> object:
        return {}


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "provider_authentication_failed"), (429, "provider_rate_limited")],
)
def test_http_provider_failure_codes(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FailingResponse(status))

    with pytest.raises(CodePreflightError) as error:
        _post("https://provider.invalid", json={})

    assert error.value.code == code
    assert error.value.recoverable is True


def test_process_provider_timeout_is_distinct(tmp_path: Path) -> None:
    with pytest.raises(CodePreflightError) as error:
        run_provider_process(
            [sys.executable, "-c", "import time; time.sleep(1)"],
            prompt="review",
            cwd=tmp_path,
            timeout=0.05,
            heartbeat_interval=0.01,
        )

    assert error.value.code == "provider_timeout"
    assert error.value.recoverable is True


def test_process_provider_emits_content_free_heartbeats(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    command = [
        sys.executable,
        "-c",
        "import sys,time; value=sys.stdin.read(); time.sleep(0.08); print(len(value))",
    ]

    with activity_scope(lambda event, payload: events.append((event, payload))):
        result = run_provider_process(
            command,
            prompt="synthetic review",
            cwd=tmp_path,
            timeout=1,
            heartbeat_interval=0.02,
        )

    heartbeats = [
        payload for event, payload in events if payload.get("kind") == "provider_heartbeat"
    ]
    assert result.stdout.strip() == str(len("synthetic review"))
    assert len(heartbeats) >= 2
    assert all(event == "progress" for event, payload in events if payload in heartbeats)
    assert all("prompt" not in payload for payload in heartbeats)
