import { describe, expect, it, vi } from "vitest";
import { SessionStateStore } from "./session-state.js";

describe("SessionStateStore", () => {
  it("owns transcript identity and listener publication", () => {
    const store = new SessionStateStore();
    const listener = vi.fn();
    store.subscribe(listener);
    const id = store.append({ kind: "system", body: "Started" });
    store.updateTranscriptEntry(id, "Ready");

    expect(id).toBe("entry-1");
    expect(store.state.transcript).toEqual([
      { id: "entry-1", kind: "system", body: "Ready" },
    ]);
    expect(listener).toHaveBeenLastCalledWith(store.state);
  });

  it("owns typed pipeline transitions", () => {
    const store = new SessionStateStore();
    store.setPipeline(["snapshot", "provider", "verify"], 0);
    store.advancePipeline("provider");
    expect(store.state.pipeline?.map((item) => item.status)).toEqual([
      "complete",
      "active",
      "pending",
    ]);
    store.completePipeline();
    expect(
      store.state.pipeline?.every((item) => item.status === "complete"),
    ).toBe(true);
  });

  it("stops publishing after disposal and clears ephemeral state", () => {
    const store = new SessionStateStore();
    const listener = vi.fn();
    store.subscribe(listener);
    store.append({ kind: "user", body: "ephemeral" });
    store.dispose();
    store.patch({ busy: true });

    expect(store.state.transcript).toEqual([]);
    expect(store.state.shouldExit).toBe(true);
    expect(store.state.busy).toBe(false);
  });
});
