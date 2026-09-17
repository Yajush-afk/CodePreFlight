from types import SimpleNamespace

import pytest

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.secrets import redact_secrets, verify_with_external_scanner


def test_redacts_common_secret_assignments() -> None:
    result = redact_secrets('api_key = "abcdefghijklmnopqrstuv"')

    assert result.count == 1
    assert "abcdefghijklmnopqrstuv" not in result.content
    assert "[REDACTED]" in result.content


def test_leaves_normal_code_unchanged() -> None:
    content = "token_count = 12"

    assert redact_secrets(content).content == content


def test_redacts_complete_private_key_block() -> None:
    content = "-----BEGIN PRIVATE KEY-----\nmaterial\n-----END PRIVATE KEY-----"

    result = redact_secrets(content)

    assert result.safe is True
    assert "material" not in result.content


def test_external_scanner_blocks_remaining_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("codepreflight_engine.secrets.shutil.which", lambda name: "/gitleaks")
    monkeypatch.setattr(
        "codepreflight_engine.secrets.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="[]", stderr=""),
    )

    with pytest.raises(CodePreflightError) as error:
        verify_with_external_scanner("unsupported credential")

    assert error.value.code == "unsafe_secret_content"
