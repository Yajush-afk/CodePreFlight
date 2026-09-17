from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.base import BaseResolver
from codepreflight_engine.errors import CodePreflightError


def test_configured_base_branch_has_precedence(git_repository: Path) -> None:
    git(git_repository, "branch", "develop")
    git(git_repository, "switch", "-c", "feature")

    result = BaseResolver().resolve(
        git_repository,
        config={"git": {"base_branch": "develop"}},
        required=True,
    )

    assert result is not None
    assert result.branch == "develop"


def test_ambiguous_fallback_requires_selection(git_repository: Path) -> None:
    git(git_repository, "branch", "master")
    git(git_repository, "switch", "-c", "feature")

    with pytest.raises(CodePreflightError) as error:
        BaseResolver().resolve(git_repository, required=True)

    assert error.value.code == "base_branch_ambiguous"
