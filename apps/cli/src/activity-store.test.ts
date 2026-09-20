import { describe, expect, it } from "vitest";
import { ActivityStore } from "./activity-store.js";

describe("ActivityStore", () => {
  it("updates records, cancels running operations, and forgets them on exit", () => {
    const store = new ActivityStore();
    store.update({
      id: "1",
      actor: "Git",
      category: "repository",
      status: "running",
      command: "git status",
      mutability: "read_only",
      approval: "not_required",
    });
    expect(store.describe()).toContain("git status");
    store.cancel();
    expect(store.describe()).toContain("cancelled");
    store.clear();
    expect(store.describe()).toContain("No operations");
  });
});
