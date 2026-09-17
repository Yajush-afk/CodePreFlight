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


def test_blast_radius_finds_call_routes_and_configuration(git_repository: Path) -> None:
    (git_repository / "api.py").write_text(
        'def refresh_token():\n    return True\n\napp.post("/token/refresh")\n',
        encoding="utf-8",
    )
    (git_repository / "settings.toml").write_text("token_ttl = 300\n", encoding="utf-8")
    (git_repository / "consumer.py").write_text("result = refresh_token()\n", encoding="utf-8")
    (git_repository / "client.py").write_text('endpoint = "/token/refresh"\n', encoding="utf-8")
    (git_repository / "config_reader.py").write_text(
        'value = settings["token_ttl"]\n', encoding="utf-8"
    )
    git(git_repository, "add", ".")
    git(git_repository, "commit", "-m", "Add relationship fixture")

    signals = BlastRadiusAnalyzer().analyze(git_repository, ["api.py", "settings.toml"])

    by_path = {item.path: item for item in signals}
    assert by_path["consumer.py"].relationship == "call site"
    assert by_path["consumer.py"].confidence == "confirmed"
    assert by_path["client.py"].relationship == "route reference"
    assert by_path["config_reader.py"].relationship == "configuration reference"
    assert by_path["config_reader.py"].confidence == "confirmed"


def test_unsupported_language_uses_textual_inference(git_repository: Path) -> None:
    (git_repository / "rules.custom").write_text("function authorize\n", encoding="utf-8")
    (git_repository / "consumer.custom").write_text(
        "load rules and call authorize\n", encoding="utf-8"
    )
    git(git_repository, "add", ".")
    git(git_repository, "commit", "-m", "Add custom language fixture")

    signals = BlastRadiusAnalyzer().analyze(git_repository, ["rules.custom"])

    assert signals[0].relationship == "textual reference"
    assert signals[0].confidence == "inferred"
