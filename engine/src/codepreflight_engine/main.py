from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .activity import activity_scope
from .adapters import ProviderRegistry
from .automation import AutomationManager
from .cache import ReviewCache
from .commit import create_commit, prepare_commit
from .config import load_config
from .doctor import doctor_report
from .errors import CodePreflightError
from .git_actions import GitActions
from .hooks import HookManager
from .initialize import initialize_repository
from .intelligence import RepositoryIntelligence
from .local_log import log_operation
from .models import EngineEvent, EngineFailure, EngineRequest
from .panel import PanelReviewer
from .protocol_generated import ENGINE_COMMANDS, PROTOCOL_VERSION
from .provider_setup import configure_provider, provider_models, provider_variants
from .providers import discover_providers
from .pull_request import prepare_pull_request
from .readiness import ProviderHealth, review_readiness
from .repository import RepositoryInspector
from .review import ReviewOrchestrator
from .scan import FullScanOrchestrator
from .trust import is_trusted
from .workspace import RepositoryWorkspace


def emit(event: EngineEvent) -> None:
    sys.stdout.write(event.model_dump_json(exclude_none=True, by_alias=True) + "\n")
    sys.stdout.flush()


def complete(request_id: str, payload: dict[str, Any]) -> None:
    emit(EngineEvent(requestId=request_id, event="complete", payload=payload))


def request_event(request_id: str, event: str, payload: dict[str, Any]) -> None:
    emit(EngineEvent(requestId=request_id, event=event, payload=payload))  # type: ignore[arg-type]


def dispatch(request: EngineRequest) -> None:
    path = Path(request.repositoryPath).resolve()
    if request.command == "automation":
        snapshot = RepositoryInspector().inspect(path)
        root = Path(snapshot.root)
        manager = AutomationManager(root)
        action = str(request.payload.get("action", "status"))
        if action == "status":
            complete(request.requestId, manager.status())
            return
        if action == "configure":
            mode = str(request.payload.get("mode", "manual"))
            write = bool(request.payload.get("write", False))
            result = manager.configure(mode, write=write)
            hook_manager = HookManager(root)
            hooks = []
            for hook in ("post-commit", "pre-push"):
                hooks.append(
                    hook_manager.install(hook, write=write)
                    if mode != "manual"
                    else hook_manager.remove(hook, write=write)
                )
            complete(request.requestId, {**result, "hookResults": hooks})
            return
        if action == "grant":
            scope = manager.current_scope()
            complete(
                request.requestId,
                manager.grant(scope, write=bool(request.payload.get("write", False))),
            )
            return
        if action == "revoke_grant":
            complete(
                request.requestId,
                manager.revoke_grant(write=bool(request.payload.get("write", False))),
            )
            return
        if action == "event":
            event_result = manager.event(
                str(request.payload.get("event", "refresh")),
                manager.current_scope() if manager.mode() != "manual" else None,
            )
            event_action = event_result.get("action")
            if event_action == "detect_pr":
                try:
                    pr = RepositoryWorkspace().run(root, {"action": "pr"})
                except CodePreflightError as error:
                    complete(
                        request.requestId,
                        {
                            **event_result,
                            "prDetection": {
                                "available": False,
                                "code": error.code,
                                "message": str(error),
                            },
                        },
                    )
                    return
                if pr.get("found"):
                    job = manager.enqueue(
                        "pull_request",
                        str(pr["localHead"]),
                        manager.current_scope(),
                        metadata={"base": pr.get("baseBranch"), "url": pr.get("url")},
                    )
                    event_result = {**event_result, "job": job}
                complete(request.requestId, {**event_result, "prDetection": pr})
                return
            if event_action == "review_branch":
                scope = manager.current_scope()
                grant = manager.grant_status(scope)
                if not grant["valid"]:
                    complete(
                        request.requestId,
                        {**event_result, "waitingForConsent": True, "grant": grant},
                    )
                    return
                review_result = ReviewOrchestrator().review(
                    root,
                    {
                        "target": "branch",
                        "provider": scope["provider"],
                        "remoteApproved": True,
                        "hook": True,
                        "automation": True,
                    },
                    lambda event, payload: request_event(request.requestId, event, payload),
                )
                pr_job = None
                try:
                    pr = RepositoryWorkspace().run(root, {"action": "pr"})
                    if pr.get("found"):
                        pr_job = manager.enqueue(
                            "pull_request",
                            str(pr["localHead"]),
                            scope,
                            metadata={"base": pr.get("baseBranch"), "url": pr.get("url")},
                        )
                except CodePreflightError:
                    pass
                complete(
                    request.requestId,
                    {
                        **event_result,
                        "review": review_result.model_dump(mode="json"),
                        "blocking": review_result.blocking,
                        "job": pr_job,
                    },
                )
                return
            complete(request.requestId, event_result)
            return
        if action == "worker":
            job_id = str(request.payload.get("jobId", ""))
            job = manager.job(job_id)
            if not manager.claim_job(job_id):
                complete(request.requestId, {"job": job, "coalesced": True})
                return
            try:
                scope = manager.current_scope()
                grant = manager.grant_status(scope)
                if not grant["valid"]:
                    waiting = manager.update_job(
                        job_id,
                        "waiting_for_consent",
                        message=(
                            "Automation grant is missing or no longer matches provider settings"
                        ),
                    )
                    request_event(request.requestId, "job_update", {"job": waiting})
                    complete(request.requestId, waiting)
                    return
                running = manager.update_job(job_id, "running")
                request_event(request.requestId, "job_update", {"job": running})
                metadata = job.get("metadata", {})
                review_payload: dict[str, Any] = {
                    "target": job["target"],
                    "revision": job["revision"] if job["target"] == "commit" else None,
                    "base": metadata.get("base"),
                    "provider": scope["provider"],
                    "remoteApproved": True,
                    "hook": True,
                }
                review_result = ReviewOrchestrator().review(
                    root,
                    {**review_payload, "automation": True},
                    lambda event, payload: request_event(request.requestId, event, payload),
                )
                completed = manager.update_job(
                    job_id,
                    "completed",
                    result=review_result.model_dump(mode="json"),
                )
                request_event(request.requestId, "job_update", {"job": completed})
                complete(
                    request.requestId,
                    {"job": completed, "result": review_result.model_dump(mode="json")},
                )
            except Exception as error:
                manager.update_job(job_id, "failed", message=str(error))
                raise
            finally:
                manager.release_job(job_id)
            return
        raise CodePreflightError(
            "invalid_automation_action",
            "Automation action must be status, configure, grant, revoke_grant, event, or worker",
        )
    if request.command == "workspace":
        complete(request.requestId, RepositoryWorkspace().run(path, request.payload))
        return
    if request.command == "scan":
        snapshot = RepositoryInspector().inspect(path)
        action = str(request.payload.get("action", "full"))
        if action not in {"full", "plan", "execute"}:
            raise CodePreflightError("invalid_scan_action", "Scan action must be plan or execute")
        result = FullScanOrchestrator().scan(
            Path(snapshot.root),
            request.payload,
            lambda event, payload: request_event(request.requestId, event, payload),
        )
        complete(request.requestId, result)
        return
    if request.command == "git_action":
        complete(request.requestId, GitActions().run(path, request.payload))
        return
    if request.command == "doctor":
        complete(request.requestId, doctor_report(path))
        return
    if request.command == "cache":
        snapshot = RepositoryInspector().inspect(path)
        cache = ReviewCache(Path(snapshot.root))
        action = request.payload.get("action", "status")
        if action == "status":
            complete(request.requestId, cache.status())
            return
        if action == "clear":
            complete(request.requestId, cache.clear())
            return
        raise CodePreflightError("invalid_cache_action", "Cache action must be status or clear")
    if request.command in {"provider", "providers"}:
        provider_root = Path(RepositoryInspector().inspect(path).root)
        config = load_config(provider_root)
        action = str(request.payload.get("action", "list"))
        if action == "test":
            provider_id = str(request.payload.get("provider", ""))
            if not provider_id:
                raise CodePreflightError(
                    "provider_required", "A provider is required for a smoke test"
                )
            registry = ProviderRegistry(config)
            health = ProviderHealth(provider_root)
            descriptor = registry.adapter(provider_id).descriptor
            try:
                tested = registry.smoke_test(provider_id)
            except Exception:
                health.invalidate(descriptor)
                raise
            health.record(descriptor, config)
            request_event(
                request.requestId,
                "readiness_changed",
                {"provider": provider_id, "readiness": review_readiness(descriptor, verified=True)},
            )
            complete(request.requestId, tested)
            return
        if action == "models":
            complete(request.requestId, provider_models(str(request.payload.get("provider", ""))))
            return
        if action == "variants":
            complete(
                request.requestId,
                provider_variants(
                    str(request.payload.get("provider", "")),
                    str(request.payload.get("model", "")),
                ),
            )
            return
        if action == "configure":
            requested_scope = request.payload.get("scope")
            config_scope = (
                str(requested_scope)
                if requested_scope
                else ("global" if request.payload.get("global") else "personal")
            )
            complete(
                request.requestId,
                configure_provider(
                    provider_root,
                    provider_id=str(request.payload.get("provider", "")),
                    model=(str(request.payload["model"]) if request.payload.get("model") else None),
                    variant=(
                        str(request.payload["variant"]) if request.payload.get("variant") else None
                    ),
                    scope=config_scope,
                    write=bool(request.payload.get("write", False)),
                ),
            )
            return
        if action != "list":
            raise CodePreflightError(
                "invalid_provider_action",
                "Provider action must be list, models, variants, test, or configure",
            )
        complete(
            request.requestId,
            {
                "providers": [
                    {
                        **provider.model_dump(mode="json"),
                        "readiness": review_readiness(
                            provider,
                            verified=ProviderHealth(provider_root).verified(provider, config),
                        ),
                    }
                    for provider in discover_providers(config)
                ]
            },
        )
        return
    if request.command == "commit":
        snapshot = RepositoryInspector().inspect(path)
        root = Path(snapshot.root)
        action = str(request.payload.get("action", ""))
        if action == "prepare":
            preparation = prepare_commit(
                root,
                request.payload,
                lambda event, payload: request_event(request.requestId, event, payload),
            )
            complete(request.requestId, preparation.model_dump(mode="json"))
            return
        if action == "execute":
            complete(request.requestId, create_commit(root, request.payload))
            return
        raise CodePreflightError(
            "invalid_commit_action", "Commit action must be prepare or execute"
        )
    if request.command == "hooks":
        snapshot = RepositoryInspector().inspect(path)
        action = str(request.payload.get("action", "status"))
        hook = str(request.payload.get("hook", "pre-commit"))
        result = HookManager(Path(snapshot.root)).apply(
            action, hook, write=bool(request.payload.get("write", False))
        )
        complete(request.requestId, result)
        return
    if request.command == "explain":
        snapshot = RepositoryInspector().inspect(path)
        result = RepositoryIntelligence().run(
            Path(snapshot.root),
            request.payload,
            lambda event, payload: request_event(request.requestId, event, payload),
        )
        complete(request.requestId, result)
        return
    if request.command == "init":
        init_root = RepositoryInspector().inspect(path).root
        result = initialize_repository(
            Path(init_root),
            write=bool(request.payload.get("write", False)),
            trust=bool(request.payload.get("trust", False)),
        )
        complete(request.requestId, result)
        return
    if request.command == "review":
        snapshot = RepositoryInspector().inspect(path)
        review_result = ReviewOrchestrator().review(
            Path(snapshot.root),
            request.payload,
            lambda event, payload: request_event(request.requestId, event, payload),
        )
        complete(request.requestId, review_result.model_dump(mode="json"))
        return
    if request.command == "panel_review":
        snapshot = RepositoryInspector().inspect(path)
        panel = PanelReviewer().review(
            Path(snapshot.root),
            request.payload,
            lambda event, payload: request_event(request.requestId, event, payload),
        )
        complete(request.requestId, panel.model_dump(mode="json"))
        return
    if request.command == "pr_prepare":
        snapshot = RepositoryInspector().inspect(path)
        draft = prepare_pull_request(
            Path(snapshot.root),
            request.payload,
            lambda event, payload: request_event(request.requestId, event, payload),
        )
        complete(request.requestId, draft.model_dump(mode="json"))
        return
    if request.command == "status":
        snapshot = RepositoryInspector().inspect(path)
        config = load_config(Path(snapshot.root))
        complete(
            request.requestId,
            {
                "repository": snapshot.model_dump(mode="json"),
                "configuration": config,
                "trusted": is_trusted(Path(snapshot.root)),
            },
        )
        return
    raise CodePreflightError("unknown_command", f"Unknown engine command: {request.command}")


def handle_line(line: str) -> None:
    started = time.monotonic()
    request_id = ""
    command = "invalid"
    repository_path = ""
    try:
        raw = json.loads(line)
        if isinstance(raw, dict):
            request_id = str(raw.get("requestId", ""))
            raw_command = str(raw.get("command", "invalid"))
            command = raw_command if raw_command in ENGINE_COMMANDS else "invalid"
            repository_path = str(raw.get("repositoryPath", ""))
        request = EngineRequest.model_validate(raw)
        with activity_scope(
            lambda event, payload: request_event(request.requestId, event, payload)
        ):
            dispatch(request)
        log_operation(
            event="complete",
            command=command,
            request_id=request_id,
            repository_path=repository_path,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except ValidationError as error:
        emit(
            EngineEvent(
                requestId=request_id,
                event="error",
                error=EngineFailure(code="invalid_request", message=str(error), recoverable=False),
            )
        )
        log_operation(
            event="error",
            command=command,
            request_id=request_id,
            repository_path=repository_path,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="invalid_request",
        )
    except CodePreflightError as error:
        emit(
            EngineEvent(
                requestId=request_id,
                event="error",
                error=EngineFailure(
                    code=error.code,
                    message=str(error),
                    recoverable=error.recoverable,
                    details=error.details,
                ),
            )
        )
        log_operation(
            event="error",
            command=command,
            request_id=request_id,
            repository_path=repository_path,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code=error.code,
        )
    except Exception as error:  # defensive process boundary
        emit(
            EngineEvent(
                requestId=request_id,
                event="error",
                error=EngineFailure(code="internal_error", message=str(error), recoverable=False),
            )
        )
        log_operation(
            event="error",
            command=command,
            request_id=request_id,
            repository_path=repository_path,
            duration_ms=int((time.monotonic() - started) * 1000),
            error_code="internal_error",
        )


def main() -> None:
    signal.signal(signal.SIGTERM, _terminate)
    emit(
        EngineEvent(
            requestId="",
            event="ready",
            payload={
                "engineVersion": "0.1.0",
                "protocolVersion": PROTOCOL_VERSION,
                "processId": os.getpid(),
            },
        )
    )
    for line in sys.stdin:
        if line.strip():
            handle_line(line)


def _terminate(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    main()
