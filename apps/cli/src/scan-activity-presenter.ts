export interface ScanProgressView {
  stage?: string;
  status?: string;
  batch?: number;
  batches?: number;
  completedBatches?: number;
  resumedBatches?: number;
  sources?: string[];
  characters?: number;
  message?: string;
}

export class ScanActivityPresenter {
  progress(progress: ScanProgressView, provider: string): string {
    if (progress.stage === "checks") return this.checks(progress);
    if (progress.stage === "review") return this.review(progress, provider);
    if (progress.stage === "verification")
      return "Preflight is verifying findings\nChecking paths, lines, symbols, and repository evidence.";
    if (progress.stage === "synthesis")
      return `${provider} is synthesizing verified results\nAlmost there—assembling the final evidence-backed review.`;
    return progress.message ?? "Preflight is processing the repository scan.";
  }

  heartbeat(
    progress: ScanProgressView | undefined,
    provider: string,
    elapsedMs: number,
  ): string {
    const elapsed = this.duration(elapsedMs);
    if (progress?.stage === "review" && progress.batch && progress.batches) {
      return `${provider} is still reviewing batch ${progress.batch} of ${progress.batches} · ${elapsed}\n${this.context(progress)}`;
    }
    return `${provider} is still analyzing · ${elapsed}\nThe provider process is active; no additional repository content was sent.`;
  }

  private checks(progress: ScanProgressView): string {
    if (progress.status === "completed")
      return `${progress.message ?? "Deterministic checks completed"}\nPassing the observed results into the review context.`;
    return "Preflight is running approved deterministic checks\nCatching mechanical failures before provider review.";
  }

  private review(progress: ScanProgressView, provider: string): string {
    const batch = progress.batch ?? 0;
    const batches = progress.batches ?? 0;
    if (progress.status === "cached")
      return `Preflight reused cached batch ${batch} of ${batches}\nNo provider request was needed for this unchanged batch.`;
    if (progress.status === "completed") {
      const next =
        batch === batches
          ? "All review batches are complete; evidence verification is next."
          : `Result cached locally; ${batches - batch} review batch${batches - batch === 1 ? " remains" : "es remain"}.`;
      return `Preflight completed batch ${batch} of ${batches}\n${next}`;
    }
    return `${provider} is reviewing batch ${batch} of ${batches}\n${this.context(progress)}`;
  }

  private context(progress: ScanProgressView): string {
    const sources = progress.sources ?? [];
    const area = this.area(sources);
    if (progress.characters && progress.characters >= 30_000)
      return `${area} context · dense cross-file batch; giving the relationships a careful pass.`;
    if (progress.batch === progress.batches)
      return `${area} context · final batch before evidence verification.`;
    const first = sources[0];
    const remaining = Math.max(0, sources.length - 1);
    return first
      ? `${area} context · ${first}${remaining ? ` + ${remaining} related source${remaining === 1 ? "" : "s"}` : ""}`
      : `${area} context · building the next evidence-backed section.`;
  }

  private area(sources: string[]): string {
    const frontend = sources.some((path) =>
      /(^apps\/cli\/|\.(tsx?|jsx?|css|scss)$)/i.test(path),
    );
    const backend = sources.some((path) =>
      /(^engine\/|(^|\/)(api|server|backend)(\/|\.)|\.py$)/i.test(path),
    );
    const tests = sources.some((path) =>
      /(^|\/)(tests?|specs?)(\/|\.)|\.(test|spec)\./i.test(path),
    );
    const selected = [
      frontend && "frontend",
      backend && "backend",
      tests && "tests",
    ].filter(Boolean);
    return selected.length ? selected.join(" + ") : "repository";
  }

  private duration(milliseconds: number): string {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    if (seconds < 60) return `${seconds}s elapsed`;
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s elapsed`;
  }
}
