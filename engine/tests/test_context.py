from pathlib import Path

from conftest import git

from codepreflight_engine.context import ContextBuilder


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
