import time
from pathlib import Path

from codepreflight_engine.checks import CheckRunner
from codepreflight_engine.models import CheckDefinition, CheckStatus


def test_reports_passed_and_failed_checks(tmp_path: Path) -> None:
    definitions = [
        CheckDefinition(name="pass", command=["python", "-c", "print('ok')"]),
        CheckDefinition(name="fail", command=["python", "-c", "raise SystemExit(3)"]),
    ]

    results = CheckRunner().run(tmp_path, definitions)

    assert results[0].status == CheckStatus.PASSED
    assert results[0].output.strip() == "ok"
    assert results[1].status == CheckStatus.FAILED
    assert results[1].exit_code == 3


def test_runs_checks_concurrently_and_keeps_recommendations_distinct(tmp_path: Path) -> None:
    definitions = [
        CheckDefinition(
            name="slow-one",
            command=["python", "-c", "import time; time.sleep(0.4)"],
        ),
        CheckDefinition(
            name="slow-two",
            command=["python", "-c", "import time; time.sleep(0.4)"],
        ),
        CheckDefinition(name="manual", command=["python", "-V"], run=False),
    ]

    started = time.monotonic()
    results = CheckRunner().run(tmp_path, definitions, concurrency=2)
    duration = time.monotonic() - started

    # Sequential execution takes at least 0.8 seconds before interpreter startup.
    assert duration < 0.75
    assert [result.status for result in results] == [
        CheckStatus.PASSED,
        CheckStatus.PASSED,
        CheckStatus.RECOMMENDED,
    ]
