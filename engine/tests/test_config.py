from pathlib import Path

import pytest

from codepreflight_engine.config import load_config, personal_config_path
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


def test_personal_preferences_override_provider_without_replacing_team_rules(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "config"
    global_file = config_home / "codepreflight" / "config.toml"
    global_file.parent.mkdir(parents=True)
    global_file.write_text('[review]\nprovider = "ollama"\n', encoding="utf-8")
    (git_repository / ".codepreflight.toml").write_text(
        'rules = ["Public APIs require tests"]\n[review]\npolicy = "block"\nprovider = "codex"\n',
        encoding="utf-8",
    )
    personal = personal_config_path(git_repository)
    personal.parent.mkdir(parents=True)
    personal.write_text(
        '[review]\nprovider = "opencode"\n[providers.opencode]\nmodel = "openai/gpt-5.5"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    config = load_config(git_repository)

    assert config["review"] == {"provider": "opencode", "policy": "block"}
    assert config["providers"]["opencode"]["model"] == "openai/gpt-5.5"
    assert config["rules"] == ["Public APIs require tests"]


def test_personal_preferences_reject_team_only_fields(git_repository: Path) -> None:
    personal = personal_config_path(git_repository)
    personal.parent.mkdir(parents=True)
    personal.write_text('rules = ["Do not allow this here"]\n', encoding="utf-8")

    with pytest.raises(CodePreflightError) as error:
        load_config(git_repository)

    assert error.value.code == "invalid_personal_config"


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
