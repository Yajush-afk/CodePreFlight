import { describe, expect, it, vi } from "vitest";
import type { Key } from "ink";
import { handleWorkspaceKey, type WorkspaceInput } from "./workspace-input.js";

function context(overrides: Partial<WorkspaceInput> = {}): WorkspaceInput {
  return {
    controller: {
      submit: vi.fn(),
      confirm: vi.fn(),
      interrupt: vi.fn(),
      dispose: vi.fn(),
      history: vi.fn(() => "/scanfull"),
    },
    state: {},
    input: "",
    suggestions: [],
    suggestionIndex: 0,
    suggestionsLoading: false,
    terminalHandoff: false,
    setInput: vi.fn(),
    setSuggestions: vi.fn(),
    setSuggestionsDismissed: vi.fn(),
    setSuggestionIndex: vi.fn(),
    setScrollOffset: vi.fn(),
    exit: vi.fn(),
    ...overrides,
  } as unknown as WorkspaceInput;
}
const escape = { escape: true } as Key;

describe("workspace keyboard priority", () => {
  it("dismisses loading suggestions without cancelling work", () => {
    const state = context({ suggestionsLoading: true, input: "/review" });
    handleWorkspaceKey(state, "", escape);
    expect(state.setSuggestionsDismissed).toHaveBeenCalledWith(true);
    expect(state.controller.interrupt).not.toHaveBeenCalled();
    expect(state.setInput).not.toHaveBeenCalled();
  });
  it("closes overlays before clearing text or interrupting", () => {
    const state = context({ input: "draft" });
    state.state.overlay = { kind: "preview", title: "Graph", body: "" };
    handleWorkspaceKey(state, "", escape);
    expect(state.controller.submit).toHaveBeenCalledWith("/close");
    expect(state.setInput).not.toHaveBeenCalled();
    expect(state.controller.interrupt).not.toHaveBeenCalled();
  });
  it("clears composer before cancelling confirmations", () => {
    const state = context({ input: "draft" });
    handleWorkspaceKey(state, "", escape);
    expect(state.setInput).toHaveBeenCalledWith("");
    expect(state.controller.interrupt).not.toHaveBeenCalled();
  });
  it("delegates operation interruption, but Ctrl+C explicitly exits", () => {
    const state = context();
    handleWorkspaceKey(state, "", escape);
    expect(state.controller.interrupt).toHaveBeenCalledOnce();
    expect(state.exit).not.toHaveBeenCalled();
    handleWorkspaceKey(state, "c", { ctrl: true } as Key);
    expect(state.controller.dispose).toHaveBeenCalledOnce();
    expect(state.exit).toHaveBeenCalledOnce();
  });
  it("scrolls an empty transcript composer and reserves command history for Ctrl+P/N", () => {
    const state = context();
    handleWorkspaceKey(state, "", { upArrow: true } as Key);
    handleWorkspaceKey(state, "", { downArrow: true } as Key);
    expect(state.setScrollOffset).toHaveBeenCalledTimes(2);
    expect(state.controller.history).not.toHaveBeenCalled();
    expect(state.setInput).not.toHaveBeenCalled();

    handleWorkspaceKey(state, "p", { ctrl: true } as Key);
    expect(state.controller.history).toHaveBeenCalledWith("previous");
  });
});
