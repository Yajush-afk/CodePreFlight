import { describe, expect, it } from "vitest";
import { GitGraphPresenter, type GitGraph } from "./git-graph-presenter.js";

describe("local graph presentation", () => {
  it("draws merge topology and retains meaning without color", () => {
    const graph: GitGraph = {
      lanes: [
        { id: "base", label: "main" },
        { id: "current", label: "feature" },
      ],
      commits: [
        {
          oid: "merge0001",
          parents: ["base00001", "feature01"],
          subject: "Merge feature",
          lane: "base",
        },
        {
          oid: "feature01",
          parents: ["base00001"],
          subject: "Add feature",
          lane: "current",
        },
        {
          oid: "base00001",
          parents: [],
          subject: "Initial",
          lane: "shared",
        },
      ],
      mergeBase: "base00001",
      head: "merge0001",
      baseHead: "base00001",
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
    expect(lines).toContain("◉ main");
    expect(lines).toContain("●─╮ Merge feature");
    expect(lines).toContain("├─● Add feature");
    expect(lines).toContain("merge base");
    expect(lines).toContain("+1 ~2");
    expect(presenter.summary(graph)).toContain("/graph");
  });

  it("uses one continuous rail for linear history", () => {
    const graph: GitGraph = {
      lanes: [{ id: "base", label: "main" }],
      commits: [
        { oid: "second", parents: ["first"], subject: "Second", lane: "base" },
        { oid: "first", parents: [], subject: "First", lane: "base" },
      ],
      head: "second",
      workingTree: { staged: 0, unstaged: 0, untracked: 0 },
      current: "main",
      base: "main",
      fingerprint: "linear",
    };

    const lines = new GitGraphPresenter().lines(graph).map((line) => line.text);
    expect(lines).toContain("◇ working tree  clean");
    expect(lines).toContain("● Second  ◉ main");
    expect(lines).toContain("● First");
  });
});
