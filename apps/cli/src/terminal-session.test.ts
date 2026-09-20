import { PassThrough } from "node:stream";
import { describe, expect, it, vi } from "vitest";
import { TerminalSession, interactiveEffects } from "./terminal-session.js";
import { WorkflowCoordinator } from "./workflow-coordinator.js";

describe("terminal lifecycle", () => {
  it("enters, yields ownership, resumes, and restores idempotently", () => {
    vi.stubEnv("CI", "");
    vi.stubEnv("TERM", "xterm");
    const output = Object.assign(new PassThrough(), { isTTY: true });
    const input = Object.assign(new PassThrough(), {
      isTTY: true,
      isRaw: true,
      setRawMode: vi.fn(),
    });
    let text = "";
    output.on("data", (chunk) => {
      text += chunk.toString();
    });
    const terminal = new TerminalSession(
      false,
      output as typeof process.stdout,
      input as unknown as typeof process.stdin,
    );
    terminal.enter();
    terminal.suspend();
    terminal.resume();
    terminal.dispose();
    terminal.dispose();
    expect(text.match(/\?1049h/g)).toHaveLength(2);
    expect(text.match(/\?1049l/g)).toHaveLength(2);
    expect(input.setRawMode).toHaveBeenCalledWith(false);
    vi.unstubAllEnvs();
  });
  it("disables effects for non-TTY, CI and dumb terminals", () => {
    expect(interactiveEffects(false, {})).toBe(false);
    expect(interactiveEffects(true, { CI: "1" })).toBe(false);
    expect(interactiveEffects(true, { TERM: "dumb" })).toBe(false);
  });
});

describe("interruption window", () => {
  it("cancels local work immediately and requires two provider Escapes", () => {
    const flow = new WorkflowCoordinator();
    expect(flow.interrupt("Preflight", true, 0)).toBe("cancel");
    expect(flow.interrupt("Provider", true, 0)).toBe("confirm");
    expect(flow.interrupt("Provider", true, 1999)).toBe("cancel");
    expect(flow.interrupt("Provider", true, 3000)).toBe("confirm");
    expect(flow.interrupt("Provider", true, 5001)).toBe("confirm");
    expect(flow.interrupt(undefined, false, 6000)).toBe("idle");
  });
});
