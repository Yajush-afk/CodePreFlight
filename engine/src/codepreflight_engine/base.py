from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CodePreflightError
from .git import GitRunner


@dataclass(frozen=True)
class BaseResolution:
    branch: str
    revision: str


class BaseResolver:
    def resolve(
        self,
        root: Path,
        *,
        explicit: str | None = None,
        config: dict[str, Any] | None = None,
        required: bool = False,
    ) -> BaseResolution | None:
        git = GitRunner(root)
        configured = self._configured(config or {})
        for candidate in (explicit, configured, self._upstream_candidate(git)):
            if candidate:
                return self._validated(git, candidate)

        remote_head = self._optional(
            git, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
        )
        if remote_head:
            return self._validated(git, remote_head.removeprefix("origin/"))

        fallbacks = [candidate for candidate in ("main", "master") if self._exists(git, candidate)]
        current = self._optional(git, "symbolic-ref", "--quiet", "--short", "HEAD")
        if current in fallbacks:
            return self._validated(git, current)
        if len(fallbacks) > 1:
            raise CodePreflightError(
                "base_branch_ambiguous",
                "Both main and master exist; pass --base or configure [git].base_branch",
                recoverable=True,
            )
        if fallbacks:
            return self._validated(git, fallbacks[0])
        if required:
            raise CodePreflightError(
                "base_branch_required",
                "Base branch could not be determined; pass --base or configure [git].base_branch",
                recoverable=True,
            )
        return None

    def _configured(self, config: dict[str, Any]) -> str | None:
        git_config = config.get("git", {})
        if isinstance(git_config, dict) and git_config.get("base_branch"):
            return str(git_config["base_branch"])
        return str(config["base_branch"]) if config.get("base_branch") else None

    def _upstream_candidate(self, git: GitRunner) -> str | None:
        branch = self._optional(git, "symbolic-ref", "--quiet", "--short", "HEAD")
        upstream = self._optional(git, "rev-parse", "--abbrev-ref", "@{upstream}")
        if not upstream:
            return None
        upstream_branch = upstream.split("/", 1)[-1]
        return upstream_branch if upstream_branch != branch else None

    def _validated(self, git: GitRunner, candidate: str) -> BaseResolution:
        normalized = candidate.removeprefix("origin/")
        revision = normalized
        if not self._exists(git, normalized):
            revision = f"origin/{normalized}"
            if not self._exists(git, revision):
                raise CodePreflightError(
                    "base_branch_invalid",
                    f"Base branch does not exist locally: {candidate}",
                    recoverable=True,
                )
        merge_base = git.run("merge-base", "HEAD", revision, check=False)
        if merge_base.returncode != 0 or not merge_base.stdout.strip():
            raise CodePreflightError(
                "base_branch_invalid",
                f"Cannot determine a merge base with {candidate}",
                recoverable=True,
            )
        return BaseResolution(branch=normalized, revision=merge_base.stdout.strip())

    def _exists(self, git: GitRunner, revision: str) -> bool:
        return (
            git.run("rev-parse", "--verify", f"{revision}^{{commit}}", check=False).returncode == 0
        )

    def _optional(self, git: GitRunner, *args: str) -> str | None:
        result = git.run(*args, check=False)
        return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
