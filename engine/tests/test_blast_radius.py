from pathlib import Path

from conftest import git

from codepreflight_engine.blast_radius import BlastRadiusAnalyzer


def test_blast_radius_finds_importers_and_tests(git_repository: Path) -> None:
    (git_repository / "auth.py").write_text("def token():\n    return 'safe'\n", encoding="utf-8")
    (git_repository / "service.py").write_text(
        "from auth import token\n\nvalue = token()\n", encoding="utf-8"
    )
    (git_repository / "test_auth.py").write_text(
        "from auth import token\n\ndef test_token():\n    assert token()\n", encoding="utf-8"
    )
    git(git_repository, "add", "auth.py", "service.py", "test_auth.py")
    git(git_repository, "commit", "-m", "Add authentication fixture")

    signals = BlastRadiusAnalyzer().analyze(git_repository, ["auth.py"])

    relationships = {(item.path, item.relationship) for item in signals}
    assert ("service.py", "direct import") in relationships
    assert ("test_auth.py", "test reference") in relationships
