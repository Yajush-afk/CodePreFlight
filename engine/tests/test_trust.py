from pathlib import Path

from conftest import git

from codepreflight_engine.trust import is_trusted, trust_repository


def test_config_or_remote_change_invalidates_repository_trust(git_repository: Path) -> None:
    config = git_repository / ".codepreflight.toml"
    config.write_text('version = 1\n[review]\npolicy = "warning"\n', encoding="utf-8")
    git(git_repository, "remote", "add", "origin", "https://github.com/example/one.git")
    trust_repository(git_repository)
    assert is_trusted(git_repository) is True

    config.write_text('version = 1\n[review]\npolicy = "block"\n', encoding="utf-8")
    assert is_trusted(git_repository) is False

    trust_repository(git_repository)
    git(git_repository, "remote", "set-url", "origin", "https://github.com/example/two.git")
    assert is_trusted(git_repository) is False
