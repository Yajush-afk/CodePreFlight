import { describe, expect, it } from "vitest";
import { parseGitTerminalHandoff } from "./git-handoff.js";

describe("parseGitTerminalHandoff", () => {
  it("accepts only approved editor and mergetool argument arrays", () => {
    expect(
      parseGitTerminalHandoff({
        action: "launch_editor",
        requires_terminal_handoff: true,
        handoff_command: ["code", "--wait", "/repo/file.ts"],
      }),
    ).toEqual({
      action: "launch_editor",
      command: ["code", "--wait", "/repo/file.ts"],
    });
  });

  it("ignores ordinary Git results", () => {
    expect(
      parseGitTerminalHandoff({ action: "merge", status: "completed" }),
    ).toBeNull();
  });

  it.each([
    { action: "merge", handoff_command: ["sh"] },
    { action: "launch_mergetool", handoff_command: [] },
    { action: "launch_editor", handoff_command: ["code\0bad"] },
  ])("rejects an invalid handoff: %o", (candidate) => {
    expect(() =>
      parseGitTerminalHandoff({
        ...candidate,
        requires_terminal_handoff: true,
      }),
    ).toThrow("invalid terminal handoff");
  });
});
