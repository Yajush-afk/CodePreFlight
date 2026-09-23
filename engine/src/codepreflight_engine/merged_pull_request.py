from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import pathspec

from .context import BINARY_SUFFIXES, DEFAULT_IGNORES, MAX_CHANGED_EXCERPT
from .errors import CodePreflightError
from .models import ContextEntry, ContextManifest, ContextPackage
from .repository import RepositoryInspector
from .secrets import redact_secrets, verify_with_external_scanner

MAX_PATCH_CHARACTERS = 4_000_000
MAX_HISTORICAL_FILES = 100
MAX_HISTORICAL_FILE_BYTES = 500_000


@dataclass(frozen=True)
class MergedPullRequestSource:
    number: int
    title: str
    url: str
    merged_at: str
    base_branch: str
    head_branch: str
    revision: str
    patch: str
    changed_files: list[str]
    files: dict[str, str]


class MergedPullRequestResolver:
    """Read merged pull-request evidence through authenticated GitHub CLI calls."""

    def list(self, root: Path, limit: int = 30) -> list[dict[str, Any]]:
        executable, repository, host = self._github(root)
        self._require_authentication(executable, host, root)
        bounded = min(max(limit, 1), 100)
        result = self._run(
            executable,
            "pr",
            "list",
            "--repo",
            repository,
            "--state",
            "merged",
            "--limit",
            str(bounded),
            "--json",
            "number,title,url,mergedAt,baseRefName,headRefName,mergeCommit",
            root=root,
        )
        payload = self._json(result.stdout, "GitHub CLI returned invalid merged-PR data")
        if not isinstance(payload, list):
            raise CodePreflightError("github_pr_response_invalid", "Expected a merged-PR list")
        return [item for item in payload if isinstance(item, dict)]

    def resolve(self, root: Path, selector: str) -> MergedPullRequestSource:
        executable, repository, host = self._github(root)
        requested = self._selector(selector, repository, host)
        self._require_authentication(executable, host, root)
        result = self._run(
            executable,
            "pr",
            "view",
            requested,
            "--repo",
            repository,
            "--json",
            "number,title,url,state,mergedAt,baseRefName,headRefName,mergeCommit,files",
            root=root,
        )
        payload = self._json(result.stdout, "GitHub CLI returned invalid pull-request data")
        if not isinstance(payload, dict):
            raise CodePreflightError("github_pr_response_invalid", "Expected pull-request data")
        if str(payload.get("state", "")).upper() != "MERGED" or not payload.get("mergedAt"):
            raise CodePreflightError(
                "pull_request_not_merged",
                f"Pull request {requested} is not merged",
                recoverable=True,
            )
        revision = self._merge_revision(payload)
        file_entries = payload.get("files")
        changed_files = [
            str(item["path"])
            for item in (file_entries if isinstance(file_entries, list) else [])
            if isinstance(item, dict) and item.get("path")
        ][:MAX_HISTORICAL_FILES]
        patch_result = self._run(
            executable,
            "pr",
            "diff",
            requested,
            "--repo",
            repository,
            "--patch",
            root=root,
            output_limit=MAX_PATCH_CHARACTERS,
        )
        if not patch_result.stdout.strip():
            raise CodePreflightError(
                "merged_pr_patch_unavailable",
                f"GitHub did not return a patch for pull request {requested}",
                recoverable=True,
            )
        files = self._historical_files(executable, repository, revision, changed_files, root)
        return MergedPullRequestSource(
            number=int(payload["number"]),
            title=str(payload.get("title") or f"Pull request {requested}"),
            url=str(payload.get("url") or ""),
            merged_at=str(payload["mergedAt"]),
            base_branch=str(payload.get("baseRefName") or "unknown"),
            head_branch=str(payload.get("headRefName") or "unknown"),
            revision=revision,
            patch=patch_result.stdout,
            changed_files=changed_files,
            files=files,
        )

    def _github(self, root: Path) -> tuple[str, str, str]:
        snapshot = RepositoryInspector().inspect(root)
        if snapshot.github is None:
            raise CodePreflightError(
                "github_repository_required",
                "Merged pull-request review requires a GitHub remote",
                recoverable=True,
            )
        executable = shutil.which("gh")
        if not executable:
            raise CodePreflightError(
                "github_cli_missing",
                "Install GitHub CLI to review merged pull requests",
                recoverable=True,
            )
        repository = f"{snapshot.github.owner}/{snapshot.github.name}"
        return executable, repository, snapshot.github.host

    def _require_authentication(self, executable: str, host: str, root: Path) -> None:
        result = self._run(
            executable,
            "auth",
            "status",
            "--hostname",
            host,
            root=root,
            check=False,
        )
        if result.returncode != 0:
            raise CodePreflightError(
                "github_authentication_required",
                f"Authenticate GitHub CLI with `gh auth login --hostname {host}`",
                recoverable=True,
            )

    def _selector(self, selector: str, repository: str, host: str) -> str:
        requested = selector.strip()
        if re.fullmatch(r"\d+", requested):
            return requested
        parsed = urlparse(requested)
        match = re.fullmatch(r"/([^/]+)/([^/]+)/pull/(\d+)/?", parsed.path)
        if parsed.scheme == "https" and parsed.hostname == host and match:
            selected_repo = f"{match.group(1)}/{match.group(2)}"
            if selected_repo.casefold() == repository.casefold():
                return match.group(3)
        raise CodePreflightError(
            "invalid_merged_pr_selector",
            "Choose a pull-request number or URL from this GitHub repository",
            recoverable=True,
        )

    def _merge_revision(self, payload: dict[str, Any]) -> str:
        merge_commit = payload.get("mergeCommit")
        revision = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        if not revision:
            raise CodePreflightError(
                "merged_pr_revision_unavailable",
                "GitHub did not return the merged revision for this pull request",
                recoverable=True,
            )
        return str(revision)

    def _historical_files(
        self,
        executable: str,
        repository: str,
        revision: str,
        paths: Sequence[str],
        root: Path,
    ) -> dict[str, str]:
        files: dict[str, str] = {}
        for path in paths:
            endpoint = f"repos/{repository}/contents/{quote(path, safe='/')}"
            result = self._run(
                executable,
                "api",
                "--method",
                "GET",
                endpoint,
                "-f",
                f"ref={revision}",
                root=root,
                check=False,
                output_limit=MAX_HISTORICAL_FILE_BYTES * 2,
            )
            if result.returncode != 0:
                continue
            payload = self._json(result.stdout, "", required=False)
            if not isinstance(payload, dict) or payload.get("encoding") != "base64":
                continue
            try:
                raw = base64.b64decode(str(payload.get("content", "")), validate=False)
            except ValueError:
                continue
            if len(raw) <= MAX_HISTORICAL_FILE_BYTES and b"\0" not in raw:
                files[path] = raw.decode("utf-8", errors="replace")
        return files

    def _run(
        self,
        *args: str,
        root: Path,
        check: bool = True,
        output_limit: int = 1_000_000,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                list(args),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except subprocess.TimeoutExpired as error:
            raise CodePreflightError(
                "github_cli_timeout", "GitHub CLI timed out while reading pull-request data"
            ) from error
        if len(result.stdout) > output_limit or len(result.stderr) > output_limit:
            raise CodePreflightError(
                "github_cli_output_limit", "GitHub CLI response exceeded the safe output limit"
            )
        if check and result.returncode != 0:
            raise CodePreflightError(
                "github_pr_query_failed",
                result.stderr.strip() or "GitHub CLI pull-request query failed",
                recoverable=True,
            )
        return result

    def _json(self, value: str, message: str, *, required: bool = True) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            if not required:
                return None
            raise CodePreflightError("github_pr_response_invalid", message) from error


class MergedPullRequestContextBuilder:
    """Build bounded review context from an immutable GitHub PR snapshot."""

    def build(self, source: MergedPullRequestSource, config: dict[str, Any]) -> ContextPackage:
        configured = config.get("ignore", [])
        matcher = pathspec.GitIgnoreSpec.from_lines(
            [
                *DEFAULT_IGNORES,
                *(configured if isinstance(configured, list) else []),
            ]
        )
        entries: list[ContextEntry] = []
        eligible = [
            path
            for path in source.changed_files
            if not self._exclude(path, source.files.get(path), matcher, entries)
        ]
        patch = self._selected_patch(source.patch, set(eligible))
        sections = [
            "## Merged pull request\n"
            f"#{source.number} {source.title}\n"
            f"URL: {source.url}\n"
            f"Merged: {source.merged_at}\n"
            f"Historical revision: {source.revision}\n"
            f"Branches: {source.head_branch} -> {source.base_branch}\n"
            "Evidence was read from GitHub without switching or fetching local branches. "
            "Current-checkout checks were not run against this historical change.",
            "## Merged pull request diff\n" + patch,
        ]
        entries.append(
            ContextEntry(
                path="<github-pr-patch>",
                reason="GitHub-provided merged pull-request patch",
                included_characters=len(patch),
                status="included",
            )
        )
        for path in eligible:
            content = source.files.get(path)
            if content is None:
                entries.append(
                    ContextEntry(
                        path=path,
                        reason="historical file unavailable; patch evidence retained",
                        status="included",
                    )
                )
                continue
            excerpt = content[:MAX_CHANGED_EXCERPT]
            sections.append(f"## Historical file context: {path}\n{excerpt}")
            entries.append(
                ContextEntry(
                    path=path,
                    reason="file content at merged revision",
                    included_characters=len(excerpt),
                    status="truncated" if len(content) > len(excerpt) else "included",
                )
            )
        rules = config.get("rules", [])
        if rules:
            rule_text = "\n".join(f"- {rule}" for rule in rules)
            sections.append("## Repository rules\n" + rule_text)
            entries.append(
                ContextEntry(
                    path="<repository-rules>",
                    reason="trusted repository review rules",
                    included_characters=len(rule_text),
                    status="included",
                )
            )
        limit = int(config.get("review", {}).get("context_limit", 60000))
        redacted = redact_secrets("\n\n".join(sections))
        if not redacted.safe:
            raise CodePreflightError(
                "unsafe_secret_content",
                "Merged pull-request context contains a private-key marker that cannot be sent",
                recoverable=True,
            )
        content = redacted.content[:limit]
        if len(redacted.content) > limit:
            entries.append(
                ContextEntry(
                    path="<context-budget>",
                    reason="configured context limit",
                    included_characters=limit,
                    status="truncated",
                )
            )
        return ContextPackage(
            content=content,
            manifest=ContextManifest(
                entries=entries,
                total_characters=len(content),
                limit_characters=limit,
                redactions=redacted.count,
                secret_scanner=verify_with_external_scanner(content),
            ),
            changed_files=eligible,
            checks=[],
            target="merged_pull_request",
            base_revision=f"github:{source.base_branch}",
            revision=source.revision,
            comparison_note="Historical GitHub patch and merged-revision file evidence.",
        )

    def _exclude(
        self,
        path: str,
        content: str | None,
        matcher: pathspec.GitIgnoreSpec,
        entries: list[ContextEntry],
    ) -> bool:
        reason = None
        if matcher.match_file(path):
            reason = "ignore rule"
        elif Path(path).suffix.lower() in BINARY_SUFFIXES:
            reason = "binary file type"
        elif content is not None and len(content.encode()) > MAX_HISTORICAL_FILE_BYTES:
            reason = f"file exceeds {MAX_HISTORICAL_FILE_BYTES}-byte context limit"
        if reason:
            entries.append(ContextEntry(path=path, reason=reason, status="excluded"))
        return reason is not None

    def _selected_patch(self, patch: str, eligible: set[str]) -> str:
        sections = re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE)
        selected = []
        for section in sections:
            match = re.match(r"diff --git a/.+ b/(.+)\n", section)
            if match and match.group(1) in eligible:
                selected.append(section)
        return "".join(selected) or "(eligible file patch unavailable)"
