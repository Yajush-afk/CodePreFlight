from codepreflight_engine.secrets import redact_secrets


def test_redacts_common_secret_assignments() -> None:
    result = redact_secrets('api_key = "abcdefghijklmnopqrstuv"')

    assert result.count == 1
    assert "abcdefghijklmnopqrstuv" not in result.content
    assert "[REDACTED]" in result.content


def test_leaves_normal_code_unchanged() -> None:
    content = "token_count = 12"

    assert redact_secrets(content).content == content
