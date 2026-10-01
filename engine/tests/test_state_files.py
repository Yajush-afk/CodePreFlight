from pathlib import Path

import pytest

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.state_files import atomic_write_text


def test_atomic_state_write_refuses_symlink_target(tmp_path: Path) -> None:
    destination = tmp_path / "outside"
    destination.write_text("keep", encoding="utf-8")
    target = tmp_path / "state.json"
    target.symlink_to(destination)

    with pytest.raises(CodePreflightError) as error:
        atomic_write_text(target, "replace")

    assert error.value.code == "unsafe_state_path"
    assert destination.read_text(encoding="utf-8") == "keep"


def test_atomic_state_write_refuses_symlinked_parent(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "state"
    parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(CodePreflightError) as error:
        atomic_write_text(parent / "settings.json", "replace")

    assert error.value.code == "unsafe_state_path"
    assert not (outside / "settings.json").exists()
