import { useInput, type Key } from "ink";
import type { Dispatch, SetStateAction } from "react";
import type { SessionController, SessionState } from "./session-controller.js";
import type { Suggestion } from "./command-registry.js";

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
    context.setInput(suggestions[context.suggestionIndex]!.completion);
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
  const { state, controller } = context;
  if (key.pageUp || key.pageDown) {
    const direction = key.pageUp ? -5 : 5;
    const overlay = Boolean(state.overlay || state.pendingDecision);
    context.setScrollOffset((offset) =>
      Math.max(0, offset + (overlay ? direction : -direction)),
    );
  }
  if (!state.overlay && !state.pendingDecision && !state.busy) {
    if (key.upArrow) context.setInput(controller.history("previous"));
    if (key.downArrow) context.setInput(controller.history("next"));
  }
  if (state.pendingDecision && ["y", "n"].includes(value)) {
    void controller.confirm(state.pendingDecision.id, value === "y");
  }
}

export function useWorkspaceInput(context: WorkspaceInput): void {
  useInput(
    (value, key) => {
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
    },
    { isActive: !context.terminalHandoff },
  );
}
