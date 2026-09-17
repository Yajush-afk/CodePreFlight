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
