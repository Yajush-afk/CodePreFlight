from pathlib import Path

from codepreflight_engine.runtime_identity import RuntimeIdentity


def test_runtime_identity_detects_source_changes(monkeypatch, tmp_path: Path) -> None:
    package = tmp_path / "codepreflight_engine"
    package.mkdir()
    source = package / "sample.py"
    source.write_text("before = True\n")
    monkeypatch.setattr(
        "codepreflight_engine.runtime_identity.__file__", package / "runtime_identity.py"
    )

    identity = RuntimeIdentity.capture()
    assert identity.changed() is False

    source.write_text("after = False\n")
    assert identity.changed() is True
