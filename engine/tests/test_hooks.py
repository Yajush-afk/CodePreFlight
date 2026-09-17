from pathlib import Path

from codepreflight_engine.hooks import START, HookManager


def test_install_preview_does_not_modify_hook(git_repository: Path) -> None:
    hook = git_repository / ".git" / "hooks" / "pre-commit"
    original = "#!/bin/sh\necho existing\n"
    hook.write_text(original, encoding="utf-8")

    result = HookManager(git_repository).install("pre-commit", write=False)

    assert result["written"] is False
    assert result["action"] == "manual_integration"
    assert START in result["snippet"]
    assert hook.read_text(encoding="utf-8") == original


def test_install_never_modifies_an_unknown_existing_hook(git_repository: Path) -> None:
    hook = git_repository / ".git" / "hooks" / "pre-commit"
    original = "#!/bin/sh\necho existing\n"
    hook.write_text(original, encoding="utf-8")
    manager = HookManager(git_repository)

    result = manager.install("pre-commit", write=True)

    assert result["written"] is False
    assert result["action"] == "manual_integration"
    assert hook.read_text(encoding="utf-8") == original


def test_unknown_hook_without_shebang_also_gets_manual_snippet(git_repository: Path) -> None:
    hook = git_repository / ".git" / "hooks" / "pre-push"
    hook.write_text("run-existing-manager\n", encoding="utf-8")

    result = HookManager(git_repository).install("pre-push", write=True)

    assert result["action"] == "manual_integration"
    assert hook.read_text(encoding="utf-8") == "run-existing-manager\n"


def test_reinstall_and_remove_managed_hook(git_repository: Path) -> None:
    manager = HookManager(git_repository)
    manager.install("pre-commit", write=True)

    reinstalled = manager.install("pre-commit", write=True)
    assert reinstalled["written"] is True
    assert START in (git_repository / ".git" / "hooks" / "pre-commit").read_text()

    manager.remove("pre-commit", write=True)
    assert not (git_repository / ".git" / "hooks" / "pre-commit").exists()


def test_disable_and_enable_managed_hook(git_repository: Path) -> None:
    manager = HookManager(git_repository)
    manager.install("pre-push", write=True)

    manager.set_disabled("pre-push", disabled=True, write=True)
    assert manager.status("pre-push")["disabled"] is True

    manager.set_disabled("pre-push", disabled=False, write=True)
    assert manager.status("pre-push")["disabled"] is False


def test_fail_closed_configuration_is_explicit_in_hook(git_repository: Path) -> None:
    (git_repository / ".codepreflight.toml").write_text(
        "[hooks]\nfail_closed = true\n", encoding="utf-8"
    )

    result = HookManager(git_repository).install("pre-commit", write=False)

    assert "blocking (fail-closed)" in result["preview"]
    assert 'exit "$codepreflight_status"' in result["preview"]
