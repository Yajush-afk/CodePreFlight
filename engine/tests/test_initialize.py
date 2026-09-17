from pathlib import Path

from codepreflight_engine.initialize import initialize_repository
from codepreflight_engine.trust import is_trusted


def test_writes_and_trusts_repository_configuration(git_repository: Path) -> None:
    result = initialize_repository(git_repository, write=True)

    assert result["written"] is True
    assert (git_repository / ".codepreflight.toml").exists()
    assert is_trusted(git_repository) is True


def test_preview_does_not_write_configuration(git_repository: Path) -> None:
    result = initialize_repository(git_repository, write=False)

    assert result["written"] is False
    assert not (git_repository / ".codepreflight.toml").exists()
    assert result["diff"].startswith("--- /dev/null")
    assert "+++ " in result["diff"]


def test_existing_configuration_can_be_reviewed_and_retrusted(git_repository: Path) -> None:
    initialize_repository(git_repository, write=True)
    config = git_repository / ".codepreflight.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace('policy = "warning"', 'policy = "block"'),
        encoding="utf-8",
    )
    assert is_trusted(git_repository) is False

    result = initialize_repository(git_repository, write=False, trust=True)

    assert result["trusted"] is True
    assert is_trusted(git_repository) is True
