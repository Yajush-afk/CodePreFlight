from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .protocol_generated import PROTOCOL_VERSION, EngineCommand, EngineEventName, ProtocolVersion


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EngineRequest(StrictModel):
    protocolVersion: ProtocolVersion
    requestId: str = Field(min_length=1)
    command: EngineCommand
    repositoryPath: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class EngineFailure(StrictModel):
    code: str
    message: str
    recoverable: bool
    details: dict[str, Any] | None = None


class EngineEvent(StrictModel):
    protocolVersion: ProtocolVersion = PROTOCOL_VERSION
    requestId: str
    event: EngineEventName
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
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class FileChange(StrictModel):
    path: str
    kind: ChangeKind
    staged: bool = False
    unstaged: bool = False
    untracked: bool = False
    ignored: bool = False
    previous_path: str | None = None


class Remote(StrictModel):
    name: str
    fetch_url: str | None = None
    push_url: str | None = None


class GitHubRepository(StrictModel):
    host: str
    owner: str
    name: str
    url: str


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
    merge_base: str | None
    upstream: str | None
    ahead: int
    behind: int
    remotes: list[Remote]
    github: GitHubRepository | None = None
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


class InstallationState(StrEnum):
    INSTALLED = "installed"
    MISSING = "missing"


class AuthenticationState(StrEnum):
    AUTHENTICATED = "authenticated"
    REQUIRED = "required"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class ModelState(StrEnum):
    READY = "ready"
    MISSING = "missing"
    SELECTION_REQUIRED = "selection_required"
    NOT_APPLICABLE = "not_applicable"


class InvocationState(StrEnum):
    VERIFIED = "verified"
    UNTESTED = "untested"
    INCOMPATIBLE = "incompatible"
    FAILED = "failed"


class ProviderAvailability(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderDescriptor(StrictModel):
    id: str
    name: str
    kind: ProviderKind
    # `state` remains during the protocol transition for older direct-command consumers.
    state: ProviderState | None = None
    installation: InstallationState = InstallationState.INSTALLED
    authentication: AuthenticationState = AuthenticationState.NOT_APPLICABLE
    model: ModelState = ModelState.NOT_APPLICABLE
    invocation: InvocationState = InvocationState.UNTESTED
    availability: ProviderAvailability = ProviderAvailability.READY
    model_name: str | None = None
    variant_name: str | None = None
    experimental: bool = False
    executable: str | None = None
    version: str | None = None
    sends_code_remotely: bool
    detail: str | None = None


class CheckDefinition(StrictModel):
    name: str
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=1800)
    run: bool = True


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    RECOMMENDED = "recommended"


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
    secret_scanner: str = "built-in"


class ContextPackage(StrictModel):
    content: str
    manifest: ContextManifest
    changed_files: list[str]
    checks: list[CheckResult]
    target: Literal[
        "staged", "working", "commit", "branch", "pull_request", "merged_pull_request"
    ] = "staged"
    base_revision: str | None = None
    revision: str | None = None
    comparison_note: str | None = None

    @property
    def staged_files(self) -> list[str]:
        return self.changed_files


class ReviewPreparation(StrictModel):
    provider: ProviderDescriptor
    context: ContextPackage
    analysis: str = ""


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingLifecycle(StrEnum):
    OPEN = "open"
    NEEDS_REREVIEW = "needs_rereview"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class VerificationState(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


class FindingCategory(StrEnum):
    BUG = "bug"
    SECURITY = "security"
    COMPATIBILITY = "compatibility"
    PERFORMANCE = "performance"
    ERROR_HANDLING = "error_handling"
    TESTING = "testing"
    CONFIGURATION = "configuration"
    OTHER = "other"


class EvidenceLocation(StrictModel):
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    symbol: str | None = None


class FindingDraft(StrictModel):
    severity: Severity
    category: FindingCategory = FindingCategory.OTHER
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1)
    impact: str = Field(min_length=1)
    confidence: Confidence
    evidence: list[EvidenceLocation] = Field(min_length=1)
    recommendation: str = Field(min_length=1)
    suggested_tests: list[str] = Field(default_factory=list)


class Finding(FindingDraft):
    id: str
    verification: VerificationState
    verification_notes: list[str] = Field(default_factory=list)
    lifecycle: FindingLifecycle = FindingLifecycle.OPEN
    legacy_severity: Literal["warning", "suggestion", "informational"] | None = None


class FindingReconciliation(StrictModel):
    finding_id: str
    outcome: Literal["present", "resolved", "uncertain"]
    explanation: str = Field(min_length=1)
    evidence: list[EvidenceLocation] = Field(default_factory=list)


class GitOperationRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    IRREVERSIBLE = "irreversible"


class GitConfirmation(StrEnum):
    EXPLICIT = "explicit"
    TYPED = "typed"


class GitOperationPlan(StrictModel):
    id: str
    action: str
    commands: list[str]
    fingerprint: str
    risk: GitOperationRisk
    confirmation: GitConfirmation
    head_oid: str | None = None
    index_fingerprint: str | None = None
    worktree_fingerprint: str | None = None
    refs: dict[str, str] = Field(default_factory=dict)
    selected_paths: list[str] = Field(default_factory=list)
    selected_hunks: list[str] = Field(default_factory=list)
    source: str | None = None
    destination: str | None = None
    expected_effects: list[str] = Field(default_factory=list)
    expected_conflicts: list[str] = Field(default_factory=list)
    hook_involvement: bool = False
    editor_involvement: bool = False
    credential_helper_involvement: bool = False
    recovery_limitations: list[str] = Field(default_factory=list)
    preview: str | None = None
    expires_at: str | None = None


class ConflictState(StrictModel):
    operation: str
    files: list[str]
    can_continue: bool
    can_abort: bool
    editor_available: bool = False
    mergetool_available: bool = False


class ConflictFileDetail(StrictModel):
    path: str
    binary: bool = False
    base: str | None = None
    ours: str | None = None
    theirs: str | None = None
    working: str | None = None
    truncated: bool = False


class ConflictInspection(StrictModel):
    operation: str | None = None
    files: list[str] = Field(default_factory=list)
    details: list[ConflictFileDetail] = Field(default_factory=list)
    can_continue: bool = False
    can_abort: bool = False
    editor_available: bool = False
    editor_name: str | None = None
    mergetool_available: bool = False
    mergetool_name: str | None = None


class GitOperationResult(StrictModel):
    plan_id: str
    action: str
    status: Literal["completed", "failed", "cancelled", "conflicted"]
    message: str
    exit_code: int | None = None
    repository: RepositorySnapshot | None = None
    conflict: ConflictState | None = None
    requires_terminal_handoff: bool = False
    handoff_command: list[str] | None = None


class WorkspaceViewData(StrictModel):
    repository: RepositorySnapshot
    findings: list[Finding] = Field(default_factory=list)
    mode: Literal["manual", "auto", "auto_plus"]
    provider: ProviderDescriptor | None = None
    active_plan: GitOperationPlan | None = None


class ProviderReviewResponse(StrictModel):
    summary: str = Field(min_length=1)
    findings: list[FindingDraft] = Field(default_factory=list)
    reconciliations: list[FindingReconciliation] = Field(default_factory=list)


class BlastRadiusItem(StrictModel):
    path: str
    relationship: str
    evidence: str
    confidence: Literal["confirmed", "inferred"]


class ReviewFailure(StrictModel):
    code: str
    message: str
    provider_response: str
    attempts: int


class ReviewResult(StrictModel):
    provider: ProviderDescriptor
    summary: str
    findings: list[Finding]
    rejected_findings: int
    context: ContextPackage
    blocking: bool
    fingerprint: str
    cache_hit: bool = False
    blast_radius: list[BlastRadiusItem] = Field(default_factory=list)
    status: Literal["completed", "failed"] = "completed"
    failure: ReviewFailure | None = None


class CommitPreparation(StrictModel):
    message: str
    fingerprint: str
    review: ReviewResult


class PullRequestDraft(StrictModel):
    title: str
    description: str
    review: ReviewResult


class ExplanationEvidence(StrictModel):
    path: str
    line: int | None = None
    commit: str | None = None


class ExplanationResponse(StrictModel):
    summary: str
    before: str | None = None
    after: str | None = None
    side_effects: list[str] = Field(default_factory=list)
    evidence: list[ExplanationEvidence] = Field(default_factory=list)


class RepositoryAnswer(StrictModel):
    answer: str
    evidence: list[ExplanationEvidence] = Field(default_factory=list)
    uncertainty: str | None = None


class ConsensusFinding(StrictModel):
    key: str
    providers: list[str]
    findings: list[Finding]
    agreement: int
    severity_conflict: bool


class PanelProviderResult(StrictModel):
    provider: str
    review: ReviewResult | None = None
    error: str | None = None


class PanelReviewResult(StrictModel):
    results: list[PanelProviderResult]
    consensus: list[ConsensusFinding]
