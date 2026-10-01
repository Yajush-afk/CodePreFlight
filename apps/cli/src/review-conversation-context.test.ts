import { describe, expect, it } from "vitest";
import { ReviewConversationContext } from "./review-conversation-context.js";

const findings = [
  { severity: "high", title: "First" },
  { severity: "medium", title: "Second" },
  { severity: "low", title: "Third" },
];

describe("ReviewConversationContext", () => {
  it("keeps plural follow-ups scoped to the active review snapshot", () => {
    const context = new ReviewConversationContext();
    context.activate({ summary: "Review", findings }, "branch");

    expect(context.questionPayload("Explain findings 1, 2 and 3")).toEqual({
      payload: {
        mode: "ask",
        question: "Explain findings 1, 2 and 3",
        target: "review",
        reviewContext: {
          target: "branch",
          summary: "Review",
          findings: [
            { ...findings[0], index: 1 },
            { ...findings[1], index: 2 },
            { ...findings[2], index: 3 },
          ],
        },
      },
    });
  });

  it("uses the selected finding for an implicit follow-up", () => {
    const context = new ReviewConversationContext();
    context.activate({ findings }, "working");
    context.select(2);

    const result = context.questionPayload("Why would this happen?");

    expect(result).toMatchObject({
      payload: {
        reviewContext: { target: "working", findings: [{ index: 2 }] },
      },
    });
  });

  it("rejects missing finding references without changing snapshots", () => {
    const context = new ReviewConversationContext();
    context.activate({ findings }, "commit");
    expect(context.questionPayload("Explain finding 9")).toEqual({
      error: "Finding 9 is not in the active review.",
    });
    expect(context.target).toBe("commit");
  });

  it("clears all ephemeral review context on branch/session invalidation", () => {
    const context = new ReviewConversationContext();
    context.activate({ findings }, "branch");
    context.select(1);
    context.clear();

    expect(context.review).toBeUndefined();
    expect(context.findings).toEqual([]);
    expect(
      context.questionPayload("What changed on this branch?"),
    ).toMatchObject({
      payload: { target: "branch", reviewContext: undefined },
    });
  });
});
