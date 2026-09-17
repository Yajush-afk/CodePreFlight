from __future__ import annotations

import subprocess

import httpx
import pytest

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


def test_process_provider_timeout_is_distinct(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(["provider"], 1)

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(CodePreflightError) as error:
        run_provider_process(["provider"], prompt="review", cwd=tmp_path, timeout=1)

    assert error.value.code == "provider_timeout"
    assert error.value.recoverable is True
