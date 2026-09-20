import { describe, expect, it } from "vitest";
import { GitGraphPresenter, type GitGraph } from "./git-graph-presenter.js";

describe("local graph presentation", () => {
  it("retains lane meaning without color and labels the merge base", () => {
    const graph: GitGraph = {
      lanes: [
        { id: "base", label: "main" },
        { id: "current", label: "feature" },
      ],
      commits: [
        { oid: "abcdef123", parents: [], subject: "Initial", lane: "shared" },
      ],
      mergeBase: "abcdef123",
      workingTree: { staged: 1, unstaged: 2, untracked: 0 },
      current: "feature",
      base: "main",
      fingerprint: "test",
    };
    const presenter = new GitGraphPresenter();
    const lines = presenter
      .lines(graph)
      .map((line) => line.text)
      .join("\n");
    expect(lines).toContain("B │ main");
    expect(lines).toContain("C │ feature");
    expect(lines).toContain("merge base");
    expect(lines).toContain("+1 ~2");
    expect(presenter.summary(graph)).toContain("/graph");
  });
});
