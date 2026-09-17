from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .models import PullRequestDraft, Severity
from .review import EventEmitter, ReviewOrchestrator


def prepare_pull_request(
    root: Path, payload: dict[str, Any], emit: EventEmitter
) -> PullRequestDraft:
    review = ReviewOrchestrator().review(
        root,
        {**payload, "target": "pull_request", "depth": "deep"},
        emit,
    )
    title = _title(review.summary)
    changed = "\n".join(f"- `{path}`" for path in review.context.changed_files)
    if review.context.checks:
        testing = "\n".join(
            f"- {check.name}: **{check.status.value}**"
            + (f" (exit {check.exit_code})" if check.exit_code is not None else "")
            for check in review.context.checks
        )
    else:
        testing = "- No automated checks were run by CodePreFlight."

    risks = [
        finding
        for finding in review.findings
        if finding.severity in {Severity.CRITICAL, Severity.WARNING}
    ]
    risk_text = (
        "- AI review did not complete: structured provider output remained invalid after repair."
        if review.status == "failed"
        else "\n".join(
            f"- **{finding.severity.value.title()}**: {finding.title} "
            f"(`{finding.evidence[0].path}:{finding.evidence[0].start_line}`)"
            for finding in risks
        )
        if risks
        else "- No verified critical or warning findings."
    )
    recommendations = sorted(
        {test for finding in review.findings for test in finding.suggested_tests}
    )
    recommended_text = (
        "\n".join(f"- {test}" for test in recommendations)
        if recommendations
        else "- No additional tests were recommended by the review."
    )
    breaking = [
        finding
        for finding in review.findings
        if "breaking" in (finding.title + " " + finding.impact).lower()
    ]
    breaking_text = (
        "\n".join(f"- {finding.title}: {finding.impact}" for finding in breaking)
        if breaking
        else "- None identified."
    )
    description = f"""## Summary

{review.summary}

## Changed files

{changed}

## Checks run

{testing}

## Recommended testing

{recommended_text}

## Risk areas

{risk_text}

## Breaking changes

{breaking_text}
"""
    return PullRequestDraft(title=title, description=description, review=review)


def _title(summary: str) -> str:
    first = re.split(r"[.!?]\s|\n", summary.strip(), maxsplit=1)[0].strip()
    return first[:72].rstrip(" .") or "Update repository changes"
