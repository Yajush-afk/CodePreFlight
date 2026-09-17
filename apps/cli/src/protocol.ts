export const PROTOCOL_VERSION = 1 as const;

export type EngineCommand =
  | "cache"
  | "commit"
  | "doctor"
  | "explain"
  | "hooks"
  | "init"
  | "panel_review"
  | "pr_prepare"
  | "providers"
  | "review"
  | "status";

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
  event:
    | "ready"
    | "progress"
    | "consent_required"
    | "provider_delta"
    | "finding"
    | "complete"
    | "error";
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
      `Unsupported engine protocol version: ${String(event.protocolVersion)}`,
    );
  }
  if (typeof event.requestId !== "string" || typeof event.event !== "string") {
    throw new EngineProtocolError("Engine event is missing required fields");
  }
  return event as EngineEvent;
}
