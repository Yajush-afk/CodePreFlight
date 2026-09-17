from pathlib import Path

from codepreflight_engine.hooks import END, START, HookManager


def test_install_preview_does_not_modify_hook(git_repository: Path) -> None:
    hook = git_repository / ".git" / "hooks" / "pre-commit"
    original = "#!/bin/sh\necho existing\n"
    hook.write_text(original, encoding="utf-8")

    result = HookManager(git_repository).install("pre-commit", write=False)

    assert result["written"] is False
    assert START in result["preview"]
    assert hook.read_text(encoding="utf-8") == original


def test_install_and_remove_restores_existing_hook(git_repository: Path) -> None:
    hook = git_repository / ".git" / "hooks" / "pre-commit"
    original = "#!/bin/sh\necho existing\n"
    hook.write_text(original, encoding="utf-8")
    manager = HookManager(git_repository)

    manager.install("pre-commit", write=True)
    installed = hook.read_text(encoding="utf-8")
    assert START in installed and END in installed and "echo existing" in installed

    manager.remove("pre-commit", write=True)
    assert hook.read_text(encoding="utf-8") == original


def test_disable_and_enable_managed_hook(git_repository: Path) -> None:
    manager = HookManager(git_repository)
    manager.install("pre-push", write=True)

    manager.set_disabled("pre-push", disabled=True, write=True)
    assert manager.status("pre-push")["disabled"] is True

    manager.set_disabled("pre-push", disabled=False, write=True)
    assert manager.status("pre-push")["disabled"] is False
