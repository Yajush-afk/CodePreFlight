import { describe, expect, it } from "vitest";
import type { EngineEvent } from "./protocol.js";
import { RequestActivityTracker } from "./request-activity.js";

describe("request activity diagnostics", () => {
  it("reports exact scan location, cached work, and last provider activity", () => {
    let now = 0;
    const tracker = new RequestActivityTracker("scan", () => now);
    tracker.record({
      protocolVersion: 3,
      requestId: "scan",
      event: "scan_progress",
      payload: {
        stage: "review",
        status: "started",
        batch: 4,
        batches: 7,
        completedBatches: 3,
      },
    } satisfies EngineEvent);
    now = 28_000;
    tracker.record({
      protocolVersion: 3,
      requestId: "scan",
      event: "progress",
      payload: { kind: "provider_heartbeat", elapsedMs: 28_000 },
    } satisfies EngineEvent);
    now = 100_000;

    const message = tracker.describeFailure("Provider connection closed");

    expect(message).toContain("reviewing batch 4 of 7");
    expect(message).toContain("3 completed batch results are cached locally");
    expect(message).toContain("Last provider activity: 1m 12s ago");
    expect(message).toContain("Cause: Provider connection closed");
  });
});
