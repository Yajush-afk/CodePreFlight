import json
from pathlib import Path

from codepreflight_engine.main import handle_line


def test_protocol_returns_structured_error_for_invalid_request(capsys: object) -> None:
    handle_line(json.dumps({"protocolVersion": 2, "requestId": "bad"}))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    event = json.loads(captured.out)

    assert event["event"] == "error"
    assert event["error"]["code"] == "invalid_request"


def test_status_request_returns_snapshot(git_repository: Path, capsys: object) -> None:
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
