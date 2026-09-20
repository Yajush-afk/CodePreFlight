import { useEffect, useState } from "react";
import { useApp, useStdin, useStdout } from "ink";
import { loginProvider } from "./provider-auth.js";
import { SessionController, type SessionState } from "./session-controller.js";
import type { Suggestion } from "./command-registry.js";
import { TerminalSession } from "./terminal-session.js";

export interface WorkspaceOptions {
  repositoryPath: string;
  controller?: SessionController;
  terminal?: TerminalSession;
}

export function useWorkspaceSession(options: WorkspaceOptions) {
  const { setRawMode } = useStdin();
  const { exit } = useApp();
  const [terminalHandoff, setTerminalHandoff] = useState(false);
  const [controller] = useState(
    () =>
      options.controller ??
      new SessionController({
        repositoryPath: options.repositoryPath,
        loginProvider: async (provider) => {
          setTerminalHandoff(true);
          await new Promise<void>((resolve) => setImmediate(resolve));
          setRawMode(false);
          options.terminal?.suspend();
          try {
            await loginProvider(provider);
          } finally {
            options.terminal?.resume();
            setRawMode(true);
            setTerminalHandoff(false);
          }
        },
      }),
  );
  const [state, setState] = useState<SessionState>(controller.state);
  useEffect(() => {
    if (options.terminal) options.terminal.onExit = () => controller.dispose();
    const unsubscribe = controller.subscribe(setState);
    void controller.start();
    return () => {
      unsubscribe();
      controller.dispose();
    };
  }, [controller, options.terminal]);
  useEffect(() => {
    if (state.shouldExit) exit();
  }, [state.shouldExit, exit]);
  return { controller, state, terminalHandoff, exit };
}

export function useWorkspaceDimensions() {
  const { stdout } = useStdout();
  const [dimensions, setDimensions] = useState({
    width: stdout.columns ?? 100,
    height: stdout.rows ?? 40,
  });
  useEffect(() => {
    const resize = (): void =>
      setDimensions({
        width: stdout.columns ?? 100,
        height: stdout.rows ?? 40,
      });
    stdout.on("resize", resize);
    return () => {
      stdout.off("resize", resize);
    };
  }, [stdout]);
  return { ...dimensions, isTTY: Boolean(stdout.isTTY) };
}

export function useCommandSuggestions(
  input: string,
  controller: SessionController,
) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);
  useEffect(() => {
    let current = true;
    if (!input.startsWith("/") || suggestionsDismissed) {
      setSuggestions([]);
      setSuggestionsLoading(false);
      return;
    }
    setSuggestionsLoading(true);
    void controller
      .suggest(input)
      .then((items) => {
        if (current) {
          setSuggestions(items.slice(0, 6));
          setSuggestionIndex(0);
        }
      })
      .catch(() => {
        if (current) setSuggestions([]);
      })
      .finally(() => {
        if (current) setSuggestionsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [input, controller, suggestionsDismissed]);
  return {
    suggestions,
    setSuggestions,
    suggestionIndex,
    setSuggestionIndex,
    suggestionsLoading,
    setSuggestionsDismissed,
  };
}
