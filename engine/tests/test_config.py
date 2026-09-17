from pathlib import Path

import pytest

from codepreflight_engine.config import load_config
from codepreflight_engine.errors import CodePreflightError


def test_repository_config_rejects_embedded_secret(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "global"))
    (git_repository / ".codepreflight.toml").write_text(
        '[provider]\napi_key = "should-not-be-here"\n', encoding="utf-8"
    )

    with pytest.raises(CodePreflightError, match="may contain a secret"):
        load_config(git_repository)


def test_repository_values_override_global_values(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "config"
    global_file = config_home / "codepreflight" / "config.toml"
    global_file.parent.mkdir(parents=True)
    global_file.write_text('[review]\ndepth = "standard"\n', encoding="utf-8")
    (git_repository / ".codepreflight.toml").write_text(
        '[review]\ndepth = "fast"\n', encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    assert load_config(git_repository)["review"]["depth"] == "fast"


def test_config_validation_reports_precise_field(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    (git_repository / ".codepreflight.toml").write_text(
        '[review]\npolicy = "sometimes"\n', encoding="utf-8"
    )

    with pytest.raises(CodePreflightError) as error:
        load_config(git_repository)

    assert error.value.code == "invalid_config"
    assert error.value.details == {
        "fields": [
            {
                "field": "review.policy",
                "message": "Input should be 'informational', 'warning' or 'block'",
            }
        ]
    }
