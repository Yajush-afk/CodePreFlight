export interface ScanProgressView {
  stage?: string;
  status?: string;
  batch?: number;
  batches?: number;
  completedBatches?: number;
  resumedBatches?: number;
  sources?: string[];
  activeBatches?: Array<{ batch: number; sources: string[] }>;
  characters?: number;
  message?: string;
}

export class ScanActivityPresenter {
  progress(progress: ScanProgressView): string {
    if (progress.stage === "checks")
      return progress.status === "completed"
        ? `Preflight completed deterministic checks\n${progress.message ?? "Check results are ready."}`
        : "Preflight is running approved checks";
    if (progress.stage === "review") return this.review(progress);
    if (progress.stage === "verification")
      return "Preflight is verifying findings\nChecking cited files, lines, and repository evidence.";
    if (progress.stage === "synthesis")
      return "Preflight is assembling the verified report";
    return progress.message ?? "Preflight is processing the repository scan.";
  }

  heartbeat(progress: ScanProgressView | undefined, elapsedMs: number): string {
    if (progress?.stage === "review" && progress.batches) {
      const active = progress.activeBatches?.length
        ? progress.activeBatches
        : progress.batch
          ? [{ batch: progress.batch, sources: progress.sources ?? [] }]
          : [];
      const label =
        active.length > 1
          ? `batches ${active.map((item) => item.batch).join(" and ")}`
          : `batch ${active[0]?.batch ?? progress.batch ?? 0}`;
      const sources =
        active.length > 1
          ? active
              .map(
                (item) =>
                  `${item.batch}: ${this.sources({ sources: item.sources }).replace("Included: ", "")}`,
              )
              .join("\n")
          : this.sources({ sources: active[0]?.sources ?? progress.sources });
      return `Preflight is reviewing ${label} of ${progress.batches} · ${this.duration(elapsedMs)} elapsed\n${sources}`;
    }
    return `Preflight is waiting for analysis · ${this.duration(elapsedMs)} elapsed`;
  }

  private review(progress: ScanProgressView): string {
    const batch = progress.batch ?? 0;
    const batches = progress.batches ?? 0;
    if (progress.status === "rate_limited")
      return `${progress.message ?? "Preflight reduced concurrent requests to one"}\nCompleted results remain cached; remaining batches will run one at a time.`;
    if (progress.activeBatches?.length)
      return this.heartbeat(progress, 0).replace(" · 0s elapsed", "");
    if (progress.status === "cached")
      return `Preflight reused cached batch ${batch} of ${batches}\nNo new review request was needed.`;
    if (progress.status === "completed")
      return `Preflight completed batch ${batch} of ${batches}\n${Math.max(0, batches - (progress.completedBatches ?? batch))} batches remain.`;
    return `Preflight is reviewing batch ${batch} of ${batches}\n${this.sources(progress)}`;
  }

  private sources(progress: ScanProgressView): string {
    const sources = progress.sources ?? [];
    if (!sources.length) return "Context: source list unavailable";
    return `Included: ${sources.join(" · ")}`;
  }

  private duration(milliseconds: number): string {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  }
}
