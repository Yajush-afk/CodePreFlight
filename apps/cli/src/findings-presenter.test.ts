import { describe, expect, it } from "vitest";

import { FindingsPresenter, type FindingView } from "./findings-presenter.js";

const finding = (verification?: string): FindingView => ({
  severity: "warning",
  title: "Example finding",
  verification,
});

describe("FindingsPresenter", () => {
  it("counts only fully verified findings as verified", () => {
    const summary = new FindingsPresenter().summary([
      finding("verified"),
      finding("partially_verified"),
      finding("unverified"),
      finding(),
    ]);

    expect(summary).toContain("1 verified · 1 partially verified");
  });
});
