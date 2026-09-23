import { describe, expect, it } from "vitest";
import { ScanActivityPresenter } from "./scan-activity-presenter.js";

describe("scan activity presentation", () => {
  const presenter = new ScanActivityPresenter();

  it("renders factual batch telemetry with deterministic supporting copy", () => {
    const message = presenter.progress({
      stage: "review",
      status: "started",
      batch: 2,
      batches: 6,
      sources: [
        "engine/src/review.py:1-120",
        "engine/tests/test_review.py:1-80",
      ],
      characters: 18_000,
    });

    expect(message).toContain("Preflight is reviewing batch 2 of 6");
    expect(message).toContain("engine/src/review.py:1-120");
    expect(message).not.toContain("Codex CLI");
  });

  it("keeps heartbeat copy tied to the current real batch", () => {
    const message = presenter.heartbeat(
      {
        stage: "review",
        batch: 4,
        batches: 7,
        sources: ["apps/cli/src/tui.tsx:1-90"],
      },
      72_000,
    );

    expect(message).toContain("batch 4 of 7 · 1m 12s elapsed");
    expect(message).toContain("apps/cli/src/tui.tsx:1-90");
  });

  it("names both active batches and their exact source ranges", () => {
    const message = presenter.heartbeat(
      {
        stage: "review",
        batches: 14,
        activeBatches: [
          { batch: 4, sources: ["apps/cli/src/tui.tsx:1-80"] },
          {
            batch: 5,
            sources: ["engine/src/codepreflight_engine/scan.py:81-160"],
          },
        ],
      },
      3_000,
    );
    expect(message).toContain("batches 4 and 5 of 14 · 3s elapsed");
    expect(message).toContain("apps/cli/src/tui.tsx:1-80");
    expect(message).toContain("engine/src/codepreflight_engine/scan.py:81-160");
  });

  it("does not hide batch paths or miscount completion under concurrency", () => {
    const sources = Array.from(
      { length: 6 },
      (_, index) => `src/file${index}.py:1-10`,
    );
    const active = presenter.progress({
      stage: "review",
      status: "started",
      batch: 3,
      batches: 8,
      sources,
    });
    expect(active).toContain("src/file5.py:1-10");
    expect(active).not.toContain("+3 more");

    const completed = presenter.progress({
      stage: "review",
      status: "completed",
      batch: 6,
      batches: 8,
      completedBatches: 3,
    });
    expect(completed).toContain("5 batches remain");
  });

  it("uses restrained standard copy without roast jokes", () => {
    const message = presenter.progress({
      stage: "synthesis",
      status: "started",
      completedBatches: 6,
      batches: 6,
    });

    expect(message).toContain("Preflight is assembling");
    expect(message).not.toMatch(/life choices|roast|terrible|impressive/i);
  });
});
