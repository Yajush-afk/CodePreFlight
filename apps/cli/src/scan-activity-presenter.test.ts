import { describe, expect, it } from "vitest";
import { ScanActivityPresenter } from "./scan-activity-presenter.js";

describe("scan activity presentation", () => {
  const presenter = new ScanActivityPresenter();

  it("renders factual batch telemetry with deterministic supporting copy", () => {
    const message = presenter.progress(
      {
        stage: "review",
        status: "started",
        batch: 2,
        batches: 6,
        sources: ["engine/src/review.py", "engine/tests/test_review.py"],
        characters: 18_000,
      },
      "Codex CLI",
    );

    expect(message).toContain("Codex CLI is reviewing batch 2 of 6");
    expect(message).toContain("backend + tests context");
    expect(message).toContain("engine/src/review.py");
  });

  it("keeps heartbeat copy tied to the current real batch", () => {
    const message = presenter.heartbeat(
      {
        stage: "review",
        batch: 4,
        batches: 7,
        sources: ["apps/cli/src/tui.tsx"],
      },
      "Codex CLI",
      72_000,
    );

    expect(message).toContain("batch 4 of 7 · 1m 12s elapsed");
    expect(message).toContain("frontend context");
  });

  it("uses restrained standard copy without roast jokes", () => {
    const message = presenter.progress(
      {
        stage: "synthesis",
        status: "started",
        completedBatches: 6,
        batches: 6,
      },
      "Codex CLI",
    );

    expect(message).toContain("Almost there");
    expect(message).not.toMatch(/life choices|roast|terrible|impressive/i);
  });
});
