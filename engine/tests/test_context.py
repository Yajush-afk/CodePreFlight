from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.context import ContextBuilder, ContextPlanner
from codepreflight_engine.errors import CodePreflightError


def test_empty_context_never_runs_checks(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Checks must not run for an empty review")

    monkeypatch.setattr("codepreflight_engine.context.CheckRunner.run", unexpected)
    with pytest.raises(CodePreflightError, match="no staged changes"):
        ContextBuilder().build(git_repository, {"checks": []})


def test_context_planner_does_not_execute_checks(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (git_repository / "feature.py").write_text("value = 1\n")
    git(git_repository, "add", "feature.py")

    def unexpected(*args: object, **kwargs: object) -> None:
        pytest.fail("Context planning is read-only")

    monkeypatch.setattr("codepreflight_engine.context.CheckRunner.run", unexpected)
    first = ContextPlanner().plan(git_repository, {})
    second = ContextPlanner().plan(git_repository, {})
    assert first.content == second.content
    assert first.manifest == second.manifest


def test_builds_redacted_context_for_staged_change(git_repository: Path) -> None:
    source = git_repository / "auth.py"
    source.write_text('api_key = "abcdefghijklmnopqrstuv"\n', encoding="utf-8")
    git(git_repository, "add", "auth.py")

    package = ContextBuilder().build(
        git_repository,
        {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
    )

    assert package.staged_files == ["auth.py"]
    assert "abcdefghijklmnopqrstuv" not in package.content
    assert package.manifest.redactions >= 1


def test_respects_ignore_rules(git_repository: Path) -> None:
    generated = git_repository / "generated.js"
    generated.write_text("const generated = true;\n", encoding="utf-8")
    git(git_repository, "add", "generated.js")

    package = ContextBuilder().build(
        git_repository,
        {
            "review": {"context_limit": 60000},
            "ignore": ["generated.js"],
            "checks": [],
            "rules": [],
        },
    )

    entry = next(item for item in package.manifest.entries if item.path == "generated.js")
    assert entry.status == "excluded"
    assert "const generated" not in package.content


def test_staged_context_excludes_unstaged_edits(git_repository: Path) -> None:
    source = git_repository / "feature.py"
    source.write_text("value = 'staged'\n", encoding="utf-8")
    git(git_repository, "add", "feature.py")
    source.write_text("value = 'unstaged-secret-behavior'\n", encoding="utf-8")

    package = ContextBuilder().build(
        git_repository,
        {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
    )

    assert "value = 'staged'" in package.content
    assert "unstaged-secret-behavior" not in package.content


def test_adds_related_tests_and_interfaces_deterministically(git_repository: Path) -> None:
    (git_repository / "auth.py").write_text("def token():\n    return 'old'\n", encoding="utf-8")
    (git_repository / "test_auth.py").write_text(
        "from auth import token\n\ndef test_token():\n    assert token()\n", encoding="utf-8"
    )
    (git_repository / "auth.pyi").write_text("def token() -> str: ...\n", encoding="utf-8")
    git(git_repository, "add", "auth.py", "test_auth.py", "auth.pyi")
    git(git_repository, "commit", "-m", "Add auth fixtures")
    (git_repository / "auth.py").write_text("def token():\n    return 'new'\n", encoding="utf-8")
    git(git_repository, "add", "auth.py")

    package = ContextBuilder().build(
        git_repository,
        {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
    )

    reasons = {entry.path: entry.reason for entry in package.manifest.entries}
    assert reasons["test_auth.py"].startswith("related test")
    assert reasons["auth.pyi"].startswith("related interface")


def test_excludes_common_generated_binary_and_oversized_content(git_repository: Path) -> None:
    (git_repository / "dist").mkdir()
    (git_repository / "dist" / "generated.js").write_text("generated\n", encoding="utf-8")
    (git_repository / "binary.data").write_bytes(b"text\x00binary")
    (git_repository / "large.txt").write_text("x" * 500_001, encoding="utf-8")
    git(git_repository, "add", "-f", "dist/generated.js", "binary.data", "large.txt")

    package = ContextBuilder().build(
        git_repository,
        {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
    )

    entries = {entry.path: entry for entry in package.manifest.entries}
    assert entries["dist/generated.js"].status == "excluded"
    assert entries["binary.data"].reason == "binary content"
    assert "exceeds" in entries["large.txt"].reason
    assert "generated" not in package.content
    assert "text\x00binary" not in package.content


def test_stops_when_private_key_cannot_be_safely_redacted(git_repository: Path) -> None:
    (git_repository / "broken.pem").write_text(
        "-----BEGIN PRIVATE KEY-----\nunterminated\n", encoding="utf-8"
    )
    git(git_repository, "add", "broken.pem")

    with pytest.raises(CodePreflightError) as error:
        ContextBuilder().build(
            git_repository,
            {"review": {"context_limit": 60000}, "ignore": [], "checks": [], "rules": []},
        )

    assert error.value.code == "unsafe_secret_content"
