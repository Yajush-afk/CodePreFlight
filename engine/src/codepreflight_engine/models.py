from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EngineRequest(StrictModel):
    protocolVersion: Literal[1]
    requestId: str = Field(min_length=1)
    command: Literal["doctor", "init", "providers", "review", "status"]
    repositoryPath: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class EngineFailure(StrictModel):
    code: str
    message: str
    recoverable: bool
    details: dict[str, Any] | None = None


class EngineEvent(StrictModel):
    protocolVersion: Literal[1] = 1
    requestId: str
    event: Literal[
        "ready",
        "progress",
        "consent_required",
        "provider_delta",
        "finding",
        "complete",
        "error",
    ]
    payload: dict[str, Any] | None = None
    error: EngineFailure | None = None


class ChangeKind(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    UNMERGED = "unmerged"
    UNTRACKED = "untracked"
    TYPE_CHANGED = "type_changed"
    UNKNOWN = "unknown"


class FileChange(StrictModel):
    path: str
    kind: ChangeKind
    staged: bool = False
    unstaged: bool = False
    untracked: bool = False
    previous_path: str | None = None


class Remote(StrictModel):
    name: str
    fetch_url: str | None = None
    push_url: str | None = None


class ProjectContext(StrictModel):
    languages: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    test_tools: list[str] = Field(default_factory=list)
    lint_tools: list[str] = Field(default_factory=list)
    build_tools: list[str] = Field(default_factory=list)
    attention_areas: list[str] = Field(default_factory=list)


class RepositorySnapshot(StrictModel):
    root: str
    branch: str | None
    detached_head: str | None
    base_branch: str | None
    upstream: str | None
    ahead: int
    behind: int
    remotes: list[Remote]
    files: list[FileChange]
    conflicts: list[str]
    project: ProjectContext


class ProviderKind(StrEnum):
    LOCAL = "local"
    SUBSCRIPTION_CLI = "subscription_cli"
    API = "api"


class ProviderState(StrEnum):
    READY = "ready"
    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"
    NOT_CONFIGURED = "not_configured"
    ERROR = "error"


class ProviderDescriptor(StrictModel):
    id: str
    name: str
    kind: ProviderKind
    state: ProviderState
    executable: str | None = None
    version: str | None = None
    sends_code_remotely: bool
    detail: str | None = None


class CheckDefinition(StrictModel):
    name: str
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=1800)


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class CheckResult(StrictModel):
    name: str
    command: list[str]
    status: CheckStatus
    exit_code: int | None = None
    duration_ms: int
    output: str = ""


class ContextEntry(StrictModel):
    path: str
    reason: str
    included_characters: int = 0
    status: Literal["included", "excluded", "redacted", "truncated"]


class ContextManifest(StrictModel):
    entries: list[ContextEntry]
    total_characters: int
    limit_characters: int
    redactions: int


class ContextPackage(StrictModel):
    content: str
    manifest: ContextManifest
    staged_files: list[str]
    checks: list[CheckResult]


class ReviewPreparation(StrictModel):
    provider: ProviderDescriptor
    context: ContextPackage
    analysis: str
