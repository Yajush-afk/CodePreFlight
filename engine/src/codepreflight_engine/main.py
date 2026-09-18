from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .adapters import ProviderRegistry
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
from .provider_setup import configure_provider, provider_models
from .providers import discover_providers
from .pull_request import prepare_pull_request
from .repository import RepositoryInspector
from .review import ReviewOrchestrator
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
    if request.command == "workspace":
        complete(request.requestId, RepositoryWorkspace().run(path, request.payload))
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
            complete(
                request.requestId,
                ProviderRegistry(config).smoke_test(provider_id),
            )
            return
        if action == "models":
            complete(request.requestId, provider_models(str(request.payload.get("provider", ""))))
            return
        if action == "configure":
            complete(
                request.requestId,
                configure_provider(
                    provider_root,
                    provider_id=str(request.payload.get("provider", "")),
                    model=(str(request.payload["model"]) if request.payload.get("model") else None),
                    global_scope=bool(request.payload.get("global", False)),
                    write=bool(request.payload.get("write", False)),
                ),
            )
            return
        if action != "list":
            raise CodePreflightError(
                "invalid_provider_action",
                "Provider action must be list, models, test, or configure",
            )
        complete(
            request.requestId,
            {
                "providers": [
                    provider.model_dump(mode="json") for provider in discover_providers(config)
                ]
            },
        )
        return
    if request.command == "commit":
        snapshot = RepositoryInspector().inspect(path)
        root = Path(snapshot.root)
        action = request.payload.get("action")
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
