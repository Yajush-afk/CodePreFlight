from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .config import load_config
from .errors import CodePreflightError
from .git import GitRunner
from .providers import discover_providers
from .repository import RepositoryInspector

ReviewMode = Literal["manual", "auto", "auto_plus"]
JobStatus = Literal[
    "queued",
    "running",
    "waiting_for_consent",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
]
VALID_MODES = {"manual", "auto", "auto_plus"}
VALID_EVENTS = {"launch", "refresh", "post-commit", "pre-push"}


class AutomationManager:
    """Owns repository-local review cadence, grants, and durable jobs."""

    def __init__(self, root: Path) -> None:
        self.root = GitRunner(root).root()
        git_dir = Path(GitRunner(self.root).run("rev-parse", "--git-dir").stdout.strip())
        self.git_dir = git_dir if git_dir.is_absolute() else (self.root / git_dir).resolve()
        self.state_dir = self.git_dir / "codepreflight"
        self.jobs_dir = self.state_dir / "jobs"
        self.results_dir = self.state_dir / "results"
        self.settings_path = self.state_dir / "automation.json"
        self.grant_path = self.state_dir / "automation-grant.json"

    def configure(self, mode: str, *, write: bool) -> dict[str, Any]:
        if mode not in VALID_MODES:
            raise CodePreflightError(
                "invalid_review_mode", "Review mode must be manual, auto, or auto_plus"
            )
        value = {"version": 1, "mode": mode, "updatedAt": self._now()}
        if write:
            self._atomic_json(self.settings_path, value)
        return {
            "mode": mode,
            "written": write,
            "statePath": self._display_path(self.settings_path),
            "hooks": self._hooks_for_mode(mode),
        }

    def status(self, *, stale_after_seconds: int = 300) -> dict[str, Any]:
        mode = self.mode()
        jobs = []
        if self.jobs_dir.exists():
            for path in sorted(self.jobs_dir.glob("*.json")):
                job = self._read_json(path)
                if not job:
                    continue
                if job.get("status") == "running" and self._age(job) >= stale_after_seconds:
                    job["status"] = "interrupted"
                    job["updatedAt"] = self._now()
                    job["message"] = "Worker stopped before recording a result"
                    self._atomic_json(path, job)
                    (self.jobs_dir / f"{job.get('id')}.lock").unlink(missing_ok=True)
                if job.get("status") == "completed":
                    result = self._read_json(self.results_dir / f"{job.get('id')}.json")
                    if result:
                        job = {**job, "result": result}
                jobs.append(job)
        jobs.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
        grant = self._read_json(self.grant_path)
        return {
            "mode": mode,
            "statePath": self._display_path(self.settings_path),
            "grant": self._public_grant(grant),
            "jobs": jobs[:100],
        }

    def mode(self) -> ReviewMode:
        value = self._read_json(self.settings_path) or {}
        mode = str(value.get("mode", "manual"))
        return mode if mode in VALID_MODES else "manual"  # type: ignore[return-value]

    def grant(self, scope: dict[str, Any], *, write: bool) -> dict[str, Any]:
        normalized = self._grant_scope(scope)
        value = {"version": 1, **normalized, "grantedAt": self._now()}
        resumed: list[dict[str, Any]] = []
        if write:
            self._atomic_json(self.grant_path, value)
            for path in sorted(self.jobs_dir.glob("*.json")):
                job = self._read_json(path)
                if job and job.get("status") == "waiting_for_consent":
                    job["status"] = "queued"
                    job["updatedAt"] = self._now()
                    job.pop("message", None)
                    self._atomic_json(path, job)
                    resumed.append(job)
        return {
            "written": write,
            "grant": self._public_grant(value),
            "resumedJobs": resumed,
        }

    def current_scope(self) -> dict[str, Any]:
        config = load_config(self.root)
        provider_id = str(config.get("review", {}).get("provider", ""))
        if not provider_id:
            raise CodePreflightError(
                "provider_required",
                "Select a review provider before enabling automation",
                recoverable=True,
                details={"actions": [{"type": "select_provider"}]},
            )
        provider = next(
            (item for item in discover_providers(config) if item.id == provider_id), None
        )
        if provider is None:
            raise CodePreflightError("provider_not_found", f"Unknown provider: {provider_id}")
        provider_config = config.get("providers", {}).get(provider_id, {})
        executable_version = self._executable_version(provider.executable)
        snapshot = RepositoryInspector().inspect(self.root)
        remote = next(
            (
                item.fetch_url or item.push_url
                for item in snapshot.remotes
                if item.fetch_url or item.push_url
            ),
            str(self.root),
        )
        safe_config = {
            "review": config.get("review", {}),
            "providers": config.get("providers", {}),
            "checks": config.get("checks", []),
            "ignore": config.get("ignore", []),
            "git": config.get("git", {}),
        }
        return {
            "provider": provider.id,
            "kind": provider.kind.value,
            "destination": provider_config.get("base_url")
            or ("local" if not provider.sends_code_remotely else provider.name),
            "executable": provider.executable,
            "executableVersion": executable_version,
            "model": provider.model_name,
            "variant": provider.variant_name,
            "repositoryIdentity": hashlib.sha256(str(remote).encode()).hexdigest(),
            "configurationDigest": self._digest(safe_config),
            "rulesDigest": self._digest(config.get("rules", [])),
        }

    def revoke_grant(self, *, write: bool) -> dict[str, Any]:
        existed = self.grant_path.exists()
        if write:
            self.grant_path.unlink(missing_ok=True)
        return {"written": write, "revoked": existed}

    def grant_status(self, scope: dict[str, Any]) -> dict[str, Any]:
        expected = self._grant_scope(scope)
        grant = self._read_json(self.grant_path)
        if not grant:
            return {"granted": False, "valid": False, "changed": list(expected)}
        changed = sorted(key for key, value in expected.items() if grant.get(key) != value)
        return {
            "granted": True,
            "valid": not changed,
            "changed": changed,
            "grant": self._public_grant(grant),
        }

    def event(self, event: str, scope: dict[str, Any] | None = None) -> dict[str, Any]:
        if event not in VALID_EVENTS:
            raise CodePreflightError("invalid_automation_event", f"Unsupported event: {event}")
        mode = self.mode()
        if mode == "manual":
            return {"mode": mode, "action": "none"}
        revision = GitRunner(self.root).run("rev-parse", "HEAD").stdout.strip()
        if event == "post-commit" and mode == "auto_plus":
            return {
                "mode": mode,
                "action": "queued",
                "job": self.enqueue("commit", revision, scope or {}),
            }
        if event == "pre-push" and mode == "auto_plus":
            return {"mode": mode, "action": "review_branch", "revision": revision}
        return {"mode": mode, "action": "detect_pr", "revision": revision}

    def enqueue(
        self,
        target: str,
        revision: str,
        scope: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        material = json.dumps(
            {"target": target, "revision": revision, "scope": scope}, sort_keys=True
        )
        fingerprint = hashlib.sha256(material.encode()).hexdigest()
        job_id = fingerprint[:20]
        path = self.jobs_dir / f"{job_id}.json"
        existing = self._read_json(path)
        if existing and existing.get("status") in {
            "queued",
            "running",
            "waiting_for_consent",
            "completed",
        }:
            return {**existing, "coalesced": True}
        now = self._now()
        job = {
            "id": job_id,
            "fingerprint": fingerprint,
            "target": target,
            "revision": revision,
            "scope": scope,
            "metadata": metadata or {},
            "status": "queued",
            "createdAt": now,
            "updatedAt": now,
        }
        self._atomic_json(path, job)
        return {**job, "coalesced": False}

    def job(self, job_id: str) -> dict[str, Any]:
        self._validate_job_id(job_id)
        value = self._read_json(self.jobs_dir / f"{job_id}.json")
        if not value:
            raise CodePreflightError("automation_job_not_found", f"Unknown job: {job_id}")
        return value

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        *,
        message: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self.job(job_id)
        job["status"] = status
        job["updatedAt"] = self._now()
        if message:
            job["message"] = message
        if status == "running":
            job["workerPid"] = os.getpid()
        if result is not None:
            self._atomic_json(self.results_dir / f"{job_id}.json", result)
            job["resultPath"] = self._display_path(self.results_dir / f"{job_id}.json")
        self._atomic_json(self.jobs_dir / f"{job_id}.json", job)
        return job

    def claim_job(self, job_id: str) -> bool:
        self._validate_job_id(job_id)
        lock = self.jobs_dir / f"{job_id}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        return True

    def release_job(self, job_id: str) -> None:
        self._validate_job_id(job_id)
        (self.jobs_dir / f"{job_id}.lock").unlink(missing_ok=True)

    def _hooks_for_mode(self, mode: str) -> list[str]:
        return [] if mode == "manual" else ["post-commit", "pre-push"]

    def _grant_scope(self, scope: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "provider",
            "kind",
            "destination",
            "executable",
            "executableVersion",
            "model",
            "variant",
            "repositoryIdentity",
            "configurationDigest",
            "rulesDigest",
        )
        return {field: scope.get(field) for field in fields}

    def _public_grant(self, grant: dict[str, Any] | None) -> dict[str, Any] | None:
        if not grant:
            return None
        return {key: value for key, value in grant.items() if "key" not in key.lower()}

    def _validate_job_id(self, job_id: str) -> None:
        if len(job_id) != 20 or any(character not in "0123456789abcdef" for character in job_id):
            raise CodePreflightError("invalid_automation_job", "Invalid automation job identifier")

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodePreflightError(
                "automation_state_invalid", f"Cannot read automation state: {path.name}"
            ) from error
        return value if isinstance(value, dict) else None

    def _display_path(self, path: Path) -> str:
        return f".git/{path.relative_to(self.git_dir).as_posix()}"

    def _age(self, job: dict[str, Any]) -> float:
        try:
            updated = datetime.fromisoformat(str(job["updatedAt"]))
            return max(0.0, time.time() - updated.timestamp())
        except (KeyError, ValueError):
            return 10**9

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()

    def _digest(self, value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def _executable_version(self, executable: str | None) -> str | None:
        if not executable:
            return None
        try:
            result = subprocess.run(
                [executable, "--version"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unknown"
        output = (result.stdout or result.stderr).strip().splitlines()
        return output[0][:200] if output else "unknown"
