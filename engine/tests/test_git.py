from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.git import GitRunner


def test_git_runner_rejects_output_over_configured_bound(git_repository: Path) -> None:
    (git_repository / "large.txt").write_text("x" * 200, encoding="utf-8")
    git(git_repository, "add", "large.txt")
    git(git_repository, "commit", "-m", "Add large fixture")

    with pytest.raises(CodePreflightError) as error:
        GitRunner(git_repository, max_output_bytes=50).run("show", "HEAD:large.txt")

    assert error.value.code == "git_output_limit"
