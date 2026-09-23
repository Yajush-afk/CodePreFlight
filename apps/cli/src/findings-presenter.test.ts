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

  it("builds semantic terminal markdown for finding details", () => {
    const detail = new FindingsPresenter().detail(1, {
      ...finding("verified"),
      explanation: "Validation was removed.",
      suggested_tests: ["Reject an expired token"],
    });
    expect(detail).toContain("# Example finding");
    expect(detail).toContain("## What happened");
    expect(detail).toContain("- Reject an expired token");
  });
});
