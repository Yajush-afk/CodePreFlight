import type { EngineCommand, EngineEvent } from "./protocol.js";

interface ScanProgress {
  stage: string;
  batch?: number;
  batches?: number;
  completedBatches: number;
  activeBatches?: number[];
}

export class RequestActivityTracker {
  private lastActivityAt: number;
  private lastProviderActivityAt?: number;
  private scan?: ScanProgress;

  constructor(
    private readonly command: EngineCommand,
    private readonly clock: () => number = Date.now,
  ) {
    this.lastActivityAt = this.clock();
  }

  record(event: EngineEvent): void {
    const now = this.clock();
    this.lastActivityAt = now;
    if (event.event === "scan_progress") {
      const stage = String(event.payload?.stage ?? "");
      this.scan = {
        stage,
        batch: this.number(event.payload?.batch),
        batches: this.number(event.payload?.batches),
        completedBatches: this.number(event.payload?.completedBatches) ?? 0,
        activeBatches: Array.isArray(event.payload?.activeBatches)
          ? event.payload.activeBatches
              .map((item: unknown) =>
                this.number((item as { batch?: unknown })?.batch),
              )
              .filter(
                (item: number | undefined): item is number =>
                  item !== undefined,
              )
          : undefined,
      };
      if (stage === "review" && event.payload?.status === "started")
        this.lastProviderActivityAt = now;
    }
    if (
      event.event === "provider_delta" ||
      (event.event === "progress" &&
        event.payload?.kind === "provider_heartbeat") ||
      (event.event === "operation_started" &&
        event.payload?.actor === "Provider")
    ) {
      this.lastProviderActivityAt = now;
    }
  }

  idleForMs(): number {
    return Math.max(0, this.clock() - this.lastActivityAt);
  }

  failureDetails(): Record<string, unknown> {
    return {
      scan: this.scan,
      idleForMs: this.idleForMs(),
      lastProviderActivityMsAgo:
        this.lastProviderActivityAt === undefined
          ? undefined
          : Math.max(0, this.clock() - this.lastProviderActivityAt),
    };
  }

  describeFailure(cause: string): string {
    if (this.command !== "scan" || !this.scan) return cause;
    const lines = [
      this.location(),
      this.cacheSummary(),
      this.providerSummary(),
    ];
    lines.push(`Cause: ${cause}`);
    return lines.join("\n");
  }

  private location(): string {
    if (this.scan?.stage === "review" && this.scan.activeBatches?.length) {
      const batches = this.scan.activeBatches.join(" and ");
      return `Scan interrupted while reviewing ${this.scan.activeBatches.length > 1 ? "batches" : "batch"} ${batches} of ${this.scan.batches}`;
    }
    if (this.scan?.stage === "review" && this.scan.batch && this.scan.batches)
      return `Scan interrupted while reviewing batch ${this.scan.batch} of ${this.scan.batches}`;
    if (this.scan?.stage === "verification")
      return "Scan interrupted during evidence verification";
    if (this.scan?.stage === "synthesis")
      return "Scan interrupted while synthesizing the final review";
    if (this.scan?.stage === "checks")
      return "Scan interrupted while running deterministic checks";
    return "Scan interrupted before the current stage completed";
  }

  private cacheSummary(): string {
    const count = this.scan?.completedBatches ?? 0;
    return `${count} completed batch result${count === 1 ? " is" : "s are"} cached locally`;
  }

  private providerSummary(): string {
    if (this.lastProviderActivityAt === undefined)
      return "Last provider activity: not observed";
    const elapsed = Math.max(0, this.clock() - this.lastProviderActivityAt);
    return `Last provider activity: ${this.duration(elapsed)} ago`;
  }

  private duration(milliseconds: number): string {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  }

  private number(value: unknown): number | undefined {
    return typeof value === "number" && Number.isFinite(value)
      ? value
      : undefined;
  }
}
