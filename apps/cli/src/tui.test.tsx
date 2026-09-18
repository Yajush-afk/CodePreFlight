import React from "react";
import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";
import { SessionView } from "./tui.js";

describe("SessionView", () => {
  it("renders repository context, conversation, and a persistent composer", () => {
    const view = render(
      <SessionView
        state={{
          started: true,
          busy: false,
          shouldExit: false,
          header: {
            repository: "code-preflight",
            root: "/repo",
            branch: "feature/auth",
            baseBranch: "main",
            upstream: "origin/feature/auth",
            ahead: 2,
            behind: 0,
            staged: 1,
            unstaged: 0,
            untracked: 0,
            conflicts: 0,
            provider: "Codex CLI",
            providerId: "codex",
            providerAvailability: "ready",
          },
          transcript: [
            {
              id: "one",
              kind: "review",
              title: "Review complete",
              body: "1. WARNING · Expired tokens are accepted · auth.py:42 · verified",
            },
          ],
        }}
        input="explain finding 1"
        onInput={() => {}}
        onSubmit={() => {}}
      />,
    );

    const frame = view.lastFrame() ?? "";
    expect(frame).toContain("PREFLIGHT");
    expect(frame).toContain("code-preflight");
    expect(frame).toContain("feature/auth");
    expect(frame).toContain("Codex CLI · ready");
    expect(frame).toContain("Expired tokens are accepted");
    expect(frame).toContain("explain finding 1");
  });
});
