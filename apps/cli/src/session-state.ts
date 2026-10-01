import type { GitGraph } from "./git-graph-presenter.js";
import type { ScanProgressView } from "./scan-activity-presenter.js";

export interface SessionHeader {
  repository: string;
  root: string;
  branch: string;
  baseBranch: string;
  upstream: string;
  ahead: number;
  behind: number;
  staged: number;
  unstaged: number;
  untracked: number;
  conflicts: number;
  provider: string;
  providerId?: string;
  providerAvailability?: string;
  providerAuthentication?: string;
  providerModel?: string;
  providerVariant?: string;
  providerPrivacy?: string;
  pullRequest?: string;
  reviewMode: string;
}

export interface TranscriptEntry {
  id: string;
  kind:
    "system" | "user" | "status" | "progress" | "error" | "review" | "answer";
  title?: string;
  body: string;
  data?: Record<string, unknown>;
}

export interface PendingDecision {
  id: string;
  title: string;
  body: string;
  confirmLabel: string;
}

export interface SessionOverlayItem {
  label: string;
  value: string;
  command?: string;
  action?: SessionAction;
}

export interface SessionAction {
  kind:
    | "model"
    | "variant"
    | "provider"
    | "mode"
    | "file"
    | "branch"
    | "commit"
    | "review"
    | "finding"
    | "setup"
    | "close";
  value: string;
}

export interface SessionOverlay {
  kind:
    | "tree"
    | "branches"
    | "commits"
    | "providers"
    | "preview"
    | "help"
    | "findings"
    | "finding";
  title: string;
  items?: SessionOverlayItem[];
  body?: string;
}

export interface SessionState {
  started: boolean;
  busy: boolean;
  activity?: string;
  activeActor?: string;
  interruptionNotice?: string;
  header?: SessionHeader;
  graph?: GitGraph;
  transcriptOnly?: boolean;
  scanProgress?: ScanProgressView;
  scanBatchStartedAt?: number;
  recentOperation?: string;
  transcript: TranscriptEntry[];
  pendingDecision?: PendingDecision;
  overlay?: SessionOverlay;
  pipeline?: Array<{
    label: string;
    status: "pending" | "active" | "complete" | "failed";
  }>;
  shouldExit: boolean;
}

type Listener = (state: SessionState) => void;

export class SessionStateStore {
  private current: SessionState = {
    started: false,
    busy: false,
    transcript: [],
    shouldExit: false,
  };
  private readonly listeners = new Set<Listener>();
  private sequence = 0;
  private disposed = false;

  get state(): SessionState {
    return this.current;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.current);
    return () => this.listeners.delete(listener);
  }

  patch(update: Partial<SessionState>): void {
    if (this.disposed) return;
    this.current = { ...this.current, ...update };
    for (const listener of this.listeners) listener(this.current);
  }

  append(entry: Omit<TranscriptEntry, "id">): string {
    const id = this.nextId("entry");
    this.patch({ transcript: [...this.current.transcript, { ...entry, id }] });
    return id;
  }

  updateTranscriptEntry(id: string, body: string): void {
    this.patch({
      transcript: this.current.transcript.map((entry) =>
        entry.id === id ? { ...entry, body } : entry,
      ),
    });
  }

  nextId(prefix: string): string {
    this.sequence += 1;
    return `${prefix}-${this.sequence}`;
  }

  setPipeline(labels: string[], activeIndex: number): void {
    this.patch({
      pipeline: labels.map((label, index) => ({
        label,
        status:
          index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending",
      })),
    });
  }

  advancePipeline(label: string): void {
    const pipeline = this.current.pipeline;
    if (!pipeline) return;
    const activeIndex = pipeline.findIndex((item) => item.label === label);
    if (activeIndex < 0) return;
    this.patch({
      pipeline: pipeline.map((item, index) => ({
        ...item,
        status:
          index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending",
      })),
    });
  }

  completePipeline(): void {
    if (!this.current.pipeline) return;
    this.patch({
      pipeline: this.current.pipeline.map((item) => ({
        ...item,
        status: "complete" as const,
      })),
    });
  }

  dispose(): void {
    this.disposed = true;
    this.listeners.clear();
    this.current = {
      started: false,
      busy: false,
      transcript: [],
      shouldExit: true,
    };
  }
}
