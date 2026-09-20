import React from "react";
import { render } from "ink-testing-library";
import { describe, expect, it } from "vitest";
import { SessionView } from "./tui.js";

describe("SessionView", () => {
  it("clears the Ink frame while a provider owns the terminal", () => {
    const view = render(
      <SessionView
        state={{ started: true, busy: true, shouldExit: false, transcript: [] }}
        input=""
        onInput={() => {}}
        onSubmit={() => {}}
        terminalHandoff
      />,
    );

    expect(view.lastFrame()).toBe("");
  });

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
            reviewMode: "manual",
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
    expect(frame).toContain("provider Codex CLI [ready]");
    expect(frame).toContain("Expired tokens are accepted");
    expect(frame).toContain("explain finding 1");
  });

  it("renders a focused selectable repository overlay", () => {
    const view = render(
      <SessionView
        state={{
          started: true,
          busy: false,
          shouldExit: false,
          transcript: [],
          overlay: {
            kind: "commits",
            title: "Current branch commits",
            items: [
              {
                label: "abc123 · Fix token validation",
                value: "abc123",
                command: "/reviewcommit abc123",
              },
            ],
          },
        }}
        input=""
        onInput={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(view.lastFrame()).toContain("Current branch commits");
    expect(view.lastFrame()).toContain("Fix token validation");
  });

  it("keeps status semantics and review progress readable in a narrow terminal", () => {
    const view = render(
      <SessionView
        state={{
          started: true,
          busy: true,
          shouldExit: false,
          header: {
            repository: "code-preflight",
            root: "/repo",
            branch: "main",
            baseBranch: "main",
            upstream: "origin/main",
            ahead: 0,
            behind: 0,
            staged: 2,
            unstaged: 1,
            untracked: 1,
            conflicts: 0,
            provider: "Codex CLI",
            providerAvailability: "ready",
            reviewMode: "auto_plus",
          },
          transcript: [],
          pipeline: [
            { label: "snapshot", status: "complete" },
            { label: "provider", status: "active" },
            { label: "verify", status: "pending" },
          ],
        }}
        input=""
        onInput={() => {}}
        onSubmit={() => {}}
        terminalWidth={58}
        terminalHeight={24}
        colorEnabled={false}
      />,
    );

    const frame = view.lastFrame() ?? "";
    expect(frame).toContain("+2 staged");
    expect(frame).toContain("~1 changed");
    expect(frame).toContain("✓ snapshot");
    expect(frame).toContain("◐ provider");
    expect(frame).toContain("○ verify");
    expect(frame).not.toContain("repository quality control");
  });
});
