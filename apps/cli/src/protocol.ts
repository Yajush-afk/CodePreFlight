import {
  ENGINE_EVENTS,
  PROTOCOL_VERSION,
  type EngineCommand,
  type EngineEventName,
  type FindingLifecycleState,
  type FindingSeverity,
  type GitOperationRisk,
} from "./protocol.generated.js";

export {
  PROTOCOL_VERSION,
  type EngineCommand,
  type FindingLifecycleState,
  type FindingSeverity,
  type GitOperationRisk,
} from "./protocol.generated.js";

export interface EvidenceContract {
  path: string;
  start_line: number;
  end_line: number;
  symbol?: string | null;
}

export interface FindingContract {
  id: string;
  severity: FindingSeverity;
  lifecycle: FindingLifecycleState;
  category: string;
  title: string;
  explanation: string;
  impact: string;
  confidence: "high" | "medium" | "low";
  verification: "verified" | "partially_verified" | "unverified" | "rejected";
  verification_notes: string[];
  evidence: EvidenceContract[];
  recommendation: string;
  suggested_tests: string[];
  legacy_severity?: "warning" | "suggestion" | "informational" | null;
}

export interface FindingReconciliationContract {
  finding_id: string;
  outcome: "present" | "resolved" | "uncertain";
  explanation: string;
  evidence: EvidenceContract[];
}

export interface FindingLedgerItemContract {
  id: string;
  branch: string;
  category: string;
  path: string;
  symbol: string;
  title: string;
  explanation: string;
  impact: string;
  recommendation: string;
  severity: FindingSeverity;
  legacy_severity: "warning" | "suggestion" | "informational" | null;
  confidence: "high" | "medium" | "low";
  verification: "verified" | "partially_verified" | "unverified" | "rejected";
  lifecycle: FindingLifecycleState;
  first_seen_snapshot: string;
  last_seen_snapshot: string;
  last_evaluated_snapshot: string | null;
  last_commit: string;
  target: string;
  provider_id: string;
  provider_model: string | null;
  dismissal_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface FindingOccurrenceContract {
  review_id: string;
  snapshot: string;
  commit_oid: string;
  target: string;
  severity: FindingSeverity;
  verification: FindingContract["verification"];
  evidence: EvidenceContract[];
  observed_at: string;
}

export interface FindingTransitionContract {
  from_state: FindingLifecycleState;
  to_state: FindingLifecycleState;
  reason: string;
  review_id?: string | null;
  commit_oid?: string | null;
  created_at: string;
}

export interface FindingDetailContract {
  finding: FindingLedgerItemContract;
  occurrences: FindingOccurrenceContract[];
  transitions: FindingTransitionContract[];
}

export interface GitOperationPlanContract {
  id: string;
  action: string;
  commands: string[];
  fingerprint: string;
  risk: GitOperationRisk;
  confirmation: "explicit" | "typed";
  head_oid?: string;
  index_fingerprint?: string;
  worktree_fingerprint?: string;
  refs?: Record<string, string>;
  selected_paths?: string[];
  selected_hunks?: string[];
  source?: string;
  destination?: string;
  expected_effects?: string[];
  expected_conflicts?: string[];
  hook_involvement?: boolean;
  editor_involvement?: boolean;
  credential_helper_involvement?: boolean;
  recovery_limitations?: string[];
  preview?: string | null;
  expires_at?: string | null;
}

export interface ConflictStateContract {
  operation: string;
  files: string[];
  can_continue: boolean;
  can_abort: boolean;
  editor_available?: boolean;
  mergetool_available?: boolean;
}

export interface GitOperationResultContract {
  plan_id: string;
  action: string;
  status: "completed" | "failed" | "cancelled" | "conflicted";
  message: string;
  exit_code?: number;
  repository?: RepositoryViewContract;
  conflict?: ConflictStateContract;
}

export interface FileChangeContract {
  path: string;
  kind: string;
  staged: boolean;
  unstaged: boolean;
  untracked: boolean;
  ignored: boolean;
  previous_path?: string | null;
}

export interface RepositoryViewContract {
  root: string;
  branch: string | null;
  base_branch: string | null;
  upstream: string | null;
  ahead: number;
  behind: number;
  files: FileChangeContract[];
  conflicts: string[];
  [key: string]: unknown;
}

export interface WorkspaceViewContract {
  repository: RepositoryViewContract;
  findings: FindingContract[];
  mode: "manual" | "auto" | "auto_plus";
  provider?: Record<string, unknown> | null;
  active_plan?: GitOperationPlanContract | null;
}

export interface EngineRequest {
  protocolVersion: typeof PROTOCOL_VERSION;
  requestId: string;
  command: EngineCommand;
  repositoryPath: string;
  payload: Record<string, unknown>;
}

export interface EngineError {
  code: string;
  message: string;
  recoverable: boolean;
  details?: Record<string, unknown>;
}

export interface EngineEvent {
  protocolVersion: typeof PROTOCOL_VERSION;
  requestId: string;
  event: EngineEventName;
  payload?: Record<string, unknown>;
  error?: EngineError;
}

export class EngineProtocolError extends Error {}

export function parseEngineEvent(line: string): EngineEvent {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new EngineProtocolError("Engine emitted invalid JSON");
  }

  if (!value || typeof value !== "object") {
    throw new EngineProtocolError("Engine event must be an object");
  }

  const event = value as Partial<EngineEvent>;
  if (event.protocolVersion !== PROTOCOL_VERSION) {
    throw new EngineProtocolError(
      `Unsupported engine protocol version: ${String(event.protocolVersion)}. Exit Preflight, rebuild or reinstall the matching engine and CLI, then restart.`,
    );
  }
  if (typeof event.requestId !== "string" || typeof event.event !== "string") {
    throw new EngineProtocolError("Engine event is missing required fields");
  }
  if (!ENGINE_EVENTS.includes(event.event as EngineEventName)) {
    throw new EngineProtocolError(
      `Engine emitted unknown event: ${event.event}`,
    );
  }
  return event as EngineEvent;
}
