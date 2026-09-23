import { useInput, type Key } from "ink";
import type { Dispatch, SetStateAction } from "react";
import type { SessionController, SessionState } from "./session-controller.js";
import type { Suggestion } from "./command-registry.js";
export { sanitizeComposerInput } from "./composer-input.js";

type Setter<T> = Dispatch<SetStateAction<T>>;
export interface WorkspaceInput {
  controller: SessionController;
  state: SessionState;
  input: string;
  suggestions: Suggestion[];
  suggestionIndex: number;
  suggestionsLoading: boolean;
  terminalHandoff: boolean;
  setInput: Setter<string>;
  replaceInput: (value: string) => void;
  setSuggestions: Setter<Suggestion[]>;
  setSuggestionsDismissed: Setter<boolean>;
  setSuggestionIndex: Setter<number>;
  setScrollOffset: Setter<number>;
  exit: () => void;
}

function suggestionKey(context: WorkspaceInput, key: Key): boolean {
  const { suggestions, state } = context;
  if (state.overlay || state.pendingDecision) return false;
  if (!suggestions.length && !context.suggestionsLoading) return false;
  if (key.escape) {
    context.setSuggestions([]);
    context.setSuggestionsDismissed(true);
    return true;
  }
  if (!suggestions.length) return true;
  if (key.upArrow || key.downArrow) {
    const direction = key.upArrow ? -1 : 1;
    context.setSuggestionIndex(
      (index) => (index + direction + suggestions.length) % suggestions.length,
    );
    return true;
  }
  if (key.tab) {
    context.replaceInput(suggestions[context.suggestionIndex]!.completion);
    return true;
  }
  return false;
}

export function escapeWorkspace(context: WorkspaceInput): void {
  const { controller, state } = context;
  if (state.overlay) {
    void controller.submit("/close");
  } else if (context.input) {
    context.setInput("");
  } else if (state.pendingDecision) {
    void controller.confirm(state.pendingDecision.id, false);
  } else {
    controller.interrupt();
  }
}

function navigateWorkspace(
  context: WorkspaceInput,
  value: string,
  key: Key,
): void {
  scrollWorkspace(context, key);
  if (historyWorkspace(context, value, key)) return;
  if (context.state.pendingDecision && ["y", "n"].includes(value))
    void context.controller.confirm(
      context.state.pendingDecision.id,
      value === "y",
    );
}

function scrollWorkspace(context: WorkspaceInput, key: Key): void {
  if (key.pageUp || key.pageDown) {
    scrollPage(context, key.pageUp ? -5 : 5);
    return;
  }
  scrollArrow(context, key);
}

function scrollPage(context: WorkspaceInput, step: number): void {
  const overlay = Boolean(
    context.state.overlay || context.state.pendingDecision,
  );
  context.setScrollOffset((offset) =>
    Math.max(0, offset + (overlay ? step : -step)),
  );
}

function scrollArrow(context: WorkspaceInput, key: Key): void {
  const overlay = Boolean(
    context.state.overlay || context.state.pendingDecision,
  );
  if (
    context.state.overlay?.kind === "finding" &&
    (key.upArrow || key.downArrow)
  ) {
    context.setScrollOffset((offset) =>
      Math.max(0, offset + (key.downArrow ? 1 : -1)),
    );
    return;
  }
  if (!context.input && !overlay && key.upArrow)
    context.setScrollOffset((offset) => offset + 1);
  if (!context.input && !overlay && key.downArrow)
    context.setScrollOffset((offset) => Math.max(0, offset - 1));
}

function historyWorkspace(
  context: WorkspaceInput,
  value: string,
  key: Key,
): boolean {
  if (
    context.state.overlay ||
    context.state.pendingDecision ||
    !key.ctrl ||
    !["p", "n"].includes(value)
  )
    return false;
  context.replaceInput(
    context.controller.history(value === "p" ? "previous" : "next"),
  );
  return true;
}

export function useWorkspaceInput(context: WorkspaceInput): void {
  useInput((value, key) => handleWorkspaceKey(context, value, key), {
    isActive: !context.terminalHandoff,
  });
}

export function handleWorkspaceKey(
  context: WorkspaceInput,
  value: string,
  key: Key,
): void {
  if (key.ctrl && value === "c") {
    context.controller.dispose();
    context.exit();
    return;
  }
  if (suggestionKey(context, key)) return;
  if (key.escape) {
    escapeWorkspace(context);
    return;
  }
  navigateWorkspace(context, value, key);
}
