from pathlib import Path

from codepreflight_engine.doctor import doctor_report


def test_doctor_reports_runtime_protocol_tools_and_config(git_repository: Path) -> None:
    report = doctor_report(git_repository)

    assert report["protocol"] == {"version": 3, "compatible": True}
    assert report["runtime"]["python"]["healthy"] is True
    assert report["tools"]["git"]["available"] is True
    assert report["tools"]["node"]["minimum"] == "22.0"
    assert report["configuration"]["repository"]["path"].endswith(".codepreflight.toml")
    assert report["configuration"]["personal"]["path"].endswith(
        ".git/codepreflight/preferences.toml"
    )
    assert isinstance(report["providers"], list)
    assert report["privacy"]["telemetry"] is False
    assert report["privacy"]["logContainsRepositoryContent"] is False
