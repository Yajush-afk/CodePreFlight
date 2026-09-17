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
    command: Literal["doctor", "providers", "status"]
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
    event: Literal["ready", "progress", "complete", "error"]
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
