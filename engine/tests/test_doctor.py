from pathlib import Path

from codepreflight_engine.doctor import doctor_report


def test_doctor_reports_runtime_protocol_tools_and_config(git_repository: Path) -> None:
    report = doctor_report(git_repository)

    assert report["protocol"] == {"version": 1, "compatible": True}
    assert report["runtime"]["python"]["healthy"] is True
    assert report["tools"]["git"]["available"] is True
    assert report["tools"]["node"]["minimum"] == "22.0"
    assert report["configuration"]["repository"]["path"].endswith(".codepreflight.toml")
    assert isinstance(report["providers"], list)
