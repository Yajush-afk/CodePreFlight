from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from codepreflight_engine.processes import run_bounded_process


def test_process_output_is_bounded_while_process_runs(tmp_path: Path) -> None:
    result = run_bounded_process(
        [sys.executable, "-c", "print('x' * 1000000)"],
        cwd=tmp_path,
        timeout=5,
        max_output_bytes=1024,
    )

    assert len(result.stdout.encode()) <= 1024
    assert result.truncated is True


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group behavior")
def test_timeout_terminates_spawned_child_processes(tmp_path: Path) -> None:
    terminated = tmp_path / "child-terminated"
    ready = tmp_path / "child-ready"
    child = (
        "import signal,sys,time; from pathlib import Path; "
        f"terminated=Path({str(terminated)!r}); ready=Path({str(ready)!r}); "
        "signal.signal(signal.SIGTERM, lambda *_: (terminated.write_text('yes'), sys.exit(0))); "
        "ready.write_text('yes'); time.sleep(30)"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        f"ready=Path({str(ready)!r}); "
        "deadline=time.time()+2; "
        "\nwhile not ready.exists() and time.time() < deadline: time.sleep(0.01)"
        "\ntime.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded_process(
            [sys.executable, "-c", parent],
            cwd=tmp_path,
            timeout=0.5,
            max_output_bytes=1024,
        )

    assert terminated.read_text(encoding="utf-8") == "yes"
