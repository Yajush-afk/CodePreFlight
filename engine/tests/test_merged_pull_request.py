from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest
from conftest import git

from codepreflight_engine.errors import CodePreflightError
from codepreflight_engine.merged_pull_request import (
    MergedPullRequestResolver,
    MergedPullRequestSource,
)
from codepreflight_engine.models import ProviderDescriptor, ProviderKind, ProviderState
from codepreflight_engine.review import ReviewOrchestrator


def completed(args: list[str], payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")


def test_resolves_merged_pr_from_github_without_local_commits(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(
        git_repository,
        "remote",
        "add",
        "origin",
        "https://github.com/example/project.git",
    )
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[1:4] == ["auth", "status", "--hostname"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[1:3] == ["pr", "view"]:
            return completed(
                args,
                {
                    "number": 12,
                    "title": "Fix historical bug",
                    "url": "https://github.com/example/project/pull/12",
                    "state": "MERGED",
                    "mergedAt": "2026-09-20T10:00:00Z",
                    "baseRefName": "main",
                    "headRefName": "fix/history",
                    "mergeCommit": {"oid": "deadbeef" * 5},
                    "files": [{"path": "feature.py", "additions": 2, "deletions": 1}],
                },
            )
        if args[1:3] == ["pr", "diff"]:
            return subprocess.CompletedProcess(
                args,
                0,
                "diff --git a/feature.py b/feature.py\n"
                "--- a/feature.py\n+++ b/feature.py\n@@ -1 +1,2 @@\n-old\n+new\n+bug\n",
                "",
            )
        if args[1] == "api":
            return completed(
                args,
                {
                    "encoding": "base64",
                    "content": base64.b64encode(b"new\nbug\n").decode(),
                },
            )
        raise AssertionError(args)

    monkeypatch.setattr("codepreflight_engine.merged_pull_request.shutil.which", lambda _: "gh")
    monkeypatch.setattr("codepreflight_engine.merged_pull_request.subprocess.run", run)

    source = MergedPullRequestResolver().resolve(git_repository, "12")

    assert source.number == 12
    assert source.revision == "deadbeef" * 5
    assert source.files == {"feature.py": "new\nbug\n"}
    assert "feature.py" in source.patch
    assert all(command[1] not in {"checkout", "fetch", "switch"} for command in calls)


def test_rejects_pull_request_that_is_not_merged(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(
        git_repository,
        "remote",
        "add",
        "origin",
        "https://github.com/example/project.git",
    )

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[1:4] == ["auth", "status", "--hostname"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return completed(
            args,
            {
                "number": 13,
                "title": "Still open",
                "url": "https://github.com/example/project/pull/13",
                "state": "OPEN",
                "mergedAt": None,
                "baseRefName": "main",
                "headRefName": "feature",
                "mergeCommit": None,
                "files": [],
            },
        )

    monkeypatch.setattr("codepreflight_engine.merged_pull_request.shutil.which", lambda _: "gh")
    monkeypatch.setattr("codepreflight_engine.merged_pull_request.subprocess.run", run)

    with pytest.raises(CodePreflightError) as error:
        MergedPullRequestResolver().resolve(git_repository, "13")

    assert error.value.code == "pull_request_not_merged"


def test_reviews_historical_evidence_without_running_current_checkout_checks(
    git_repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = MergedPullRequestSource(
        number=12,
        title="Fix historical bug",
        url="https://github.com/example/project/pull/12",
        merged_at="2026-09-20T10:00:00Z",
        base_branch="main",
        head_branch="fix/history",
        revision="deadbeef" * 5,
        patch=(
            "diff --git a/feature.py b/feature.py\n"
            "--- a/feature.py\n+++ b/feature.py\n@@ -1 +1,2 @@\n-old\n+new\n+bug\n"
        ),
        changed_files=["feature.py"],
        files={"feature.py": "new\nbug\n"},
    )

    class Adapter:
        descriptor = ProviderDescriptor(
            id="ollama",
            name="Ollama",
            kind=ProviderKind.LOCAL,
            state=ProviderState.READY,
            sends_code_remotely=False,
        )

        def review(self, prompt: str, schema: dict[str, object]) -> str:
            assert "Current-checkout checks were not run" in prompt
            return json.dumps(
                {
                    "summary": "One historical concern.",
                    "findings": [
                        {
                            "severity": "warning",
                            "title": "Historical bug remains",
                            "explanation": "The merged code contains a bug marker.",
                            "impact": "The merged behavior can fail.",
                            "confidence": "high",
                            "evidence": [
                                {
                                    "path": "feature.py",
                                    "start_line": 2,
                                    "end_line": 2,
                                }
                            ],
                            "recommendation": "Remove the bug marker.",
                            "suggested_tests": [],
                        }
                    ],
                }
            )

    monkeypatch.setattr(
        "codepreflight_engine.review.ProviderRegistry",
        lambda config: type("Registry", (), {"adapter": lambda self, provider: Adapter()})(),
    )
    monkeypatch.setattr(
        "codepreflight_engine.review.MergedPullRequestResolver.resolve",
        lambda self, root, selector: source,
    )
    monkeypatch.setattr(
        "codepreflight_engine.checks.CheckRunner.run",
        lambda *args, **kwargs: pytest.fail("historical review ran current-checkout checks"),
    )

    result = ReviewOrchestrator().review(
        git_repository,
        {"target": "merged_pull_request", "pullRequest": "12", "provider": "ollama"},
        lambda event, payload: None,
    )

    assert result.context.target == "merged_pull_request"
    assert result.context.checks == []
    assert result.findings[0].verification.value == "verified"
