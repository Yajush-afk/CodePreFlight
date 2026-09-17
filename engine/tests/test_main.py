import json
from pathlib import Path

from codepreflight_engine.main import handle_line


def test_protocol_returns_structured_error_for_invalid_request(
    capsys: object, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    handle_line(json.dumps({"protocolVersion": 2, "requestId": "bad"}))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    event = json.loads(captured.out)

    assert event["event"] == "error"
    assert event["error"]["code"] == "invalid_request"


def test_status_request_returns_snapshot(
    git_repository: Path, capsys: object, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    handle_line(
        json.dumps(
            {
                "protocolVersion": 1,
                "requestId": "status-1",
                "command": "status",
                "repositoryPath": str(git_repository),
                "payload": {},
            }
        )
    )
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    event = json.loads(captured.out)

    assert event["event"] == "complete"
    assert event["payload"]["repository"]["branch"] == "main"
    log = (state / "codepreflight" / "events.jsonl").read_text(encoding="utf-8")
    record = json.loads(log)
    assert record["command"] == "status"
    assert record["event"] == "complete"
    assert str(git_repository) not in log


def test_local_log_excludes_request_payload_and_repository_content(
    git_repository: Path, capsys: object, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    handle_line(
        json.dumps(
            {
                "protocolVersion": 1,
                "requestId": "super-secret-source-content-request",
                "command": "status",
                "repositoryPath": str(git_repository),
                "payload": {"secret": "super-secret-source-content"},
            }
        )
    )
    capsys.readouterr()  # type: ignore[attr-defined]

    log = (state / "codepreflight" / "events.jsonl").read_text(encoding="utf-8")
    assert "super-secret-source-content" not in log
    assert str(git_repository) not in log
