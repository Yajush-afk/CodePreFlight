import React, { useEffect, useState } from "react";
import { Box, Text, useApp, useInput, useStdin, useStdout } from "ink";
import TextInput from "ink-text-input";
import SelectInput from "ink-select-input";
import { loginProvider } from "./provider-auth.js";
import {
  SessionController,
  type SessionState,
  type SessionAction,
} from "./session-controller.js";
import type { Suggestion } from "./command-registry.js";
import { TerminalSession, interactiveEffects } from "./terminal-session.js";
import { WorkspacePresenter } from "./workspace-presenter.js";
import { WorkingIndicator } from "./working-indicator.js";

interface AppProps {
  repositoryPath: string;
  controller?: SessionController;
  terminal?: TerminalSession;
}

interface SessionViewProps {
  state: SessionState;
  input: string;
  onInput: (value: string) => void;
  onSubmit: (value: string) => void;
  terminalWidth?: number;
  terminalHeight?: number;
  colorEnabled?: boolean;
  terminalHandoff?: boolean;
  onSelect?: (action: SessionAction) => void;
  suggestions?: Suggestion[];
  suggestionIndex?: number;
  suggestionsLoading?: boolean;
  fullscreen?: boolean;
  animate?: boolean;
  scrollOffset?: number;
}

const SEVERITY_COLORS: Record<string, "red" | "yellow" | "cyan" | "gray"> = {
  CRITICAL: "red",
  WARNING: "yellow",
  SUGGESTION: "cyan",
  INFORMATIONAL: "gray",
};

// Declarative terminal layout; keep workflow decisions in the controller.
export function SessionView({
  state,
  input,
  onInput,
  onSubmit,
  terminalWidth = 100,
  terminalHeight = 40,
  colorEnabled = true,
  terminalHandoff = false,
  onSelect,
  suggestions = [],
  suggestionIndex = 0,
  suggestionsLoading = false,
  fullscreen = false,
  animate = false,
  scrollOffset = 0,
}: SessionViewProps): React.JSX.Element {
  if (terminalHandoff) return <></>;
  const header = state.header;
  const accent = colorEnabled ? "cyan" : undefined;
  const presenter = new WorkspacePresenter();
  const menuOpen =
    !state.overlay &&
    !state.pendingDecision &&
    (suggestions.length > 0 || suggestionsLoading);
  const bodyHeight = Math.max(4, terminalHeight - (menuOpen ? 18 : 11));
  const lines = presenter.transcript(
    state.transcript,
    Math.max(10, terminalWidth - 4),
    bodyHeight,
    scrollOffset,
  );
  const overlay = state.overlay;
  return (
    <Box
      flexDirection="column"
      paddingX={1}
      width={terminalWidth}
      height={fullscreen ? terminalHeight : undefined}
    >
      <Text bold color={accent}>
        ──✈ PREFLIGHT{" "}
        <Text color={undefined}>
          {header
            ? `  ${header.repository} / ${header.branch}`
            : state.started
              ? "  repository unavailable"
              : "  opening repository…"}
        </Text>
      </Text>
      {header && (
        <Text dimColor>
          +{header.staged} staged · ~{header.unstaged} changed · ?
          {header.untracked} new
          {header.conflicts ? ` · ${header.conflicts} conflicts` : ""}
        </Text>
      )}
      <Box
        flexDirection="column"
        flexGrow={1}
        height={bodyHeight}
        overflowY="hidden"
        marginTop={1}
      >
        {state.pendingDecision ? (
          <>
            <Text bold color={colorEnabled ? "yellow" : undefined}>
              {state.pendingDecision.title}
            </Text>
            <Text>
              {state.pendingDecision.body
                .split("\n")
                .slice(scrollOffset, scrollOffset + Math.max(1, bodyHeight - 3))
                .join("\n")}
            </Text>
            <Text color={colorEnabled ? "yellow" : undefined}>
              y {state.pendingDecision.confirmLabel} · n cancel · PgUp/PgDn
              inspect
            </Text>
          </>
        ) : overlay ? (
          <>
            <Text bold color={accent}>
              {overlay.title}
            </Text>
            {overlay.body && (
              <Text>
                {overlay.body
                  .split("\n")
                  .slice(
                    scrollOffset,
                    scrollOffset +
                      Math.max(2, bodyHeight - (overlay.items?.length ? 8 : 2)),
                  )
                  .join("\n")}
              </Text>
            )}
            {overlay.items?.length ? (
              <SelectInput
                items={overlay.items.map((item) => ({
                  label: item.label,
                  value: item,
                }))}
                onSelect={({ value }) =>
                  value.action
                    ? onSelect?.(value.action)
                    : onSubmit(value.command ?? "")
                }
                limit={Math.max(2, Math.min(8, bodyHeight - 4))}
              />
            ) : null}
            <Text dimColor>Esc back · PgUp/PgDn inspect</Text>
          </>
        ) : (
          lines.map((line, index) => {
            const severity = Object.keys(SEVERITY_COLORS).find((value) =>
              line.includes(value),
            );
            return (
              <Text
                key={index}
                wrap="truncate-end"
                color={
                  colorEnabled && severity
                    ? SEVERITY_COLORS[severity]
                    : undefined
                }
              >
                {line || " "}
              </Text>
            );
          })
        )}
      </Box>
      {state.pipeline && (
        <Text dimColor>
          {state.pipeline
            .map(
              (item) =>
                `${item.status === "complete" ? "✓" : item.status === "failed" ? "×" : item.status === "active" ? "◐" : "○"} ${item.label}`,
            )
            .join("  ")}
        </Text>
      )}
      {state.activity && (
        <WorkingIndicator
          label={
            state.activeActor === "Provider"
              ? `${header?.provider ?? "Reviewer"} is reviewing…`
              : `Preflight: ${state.activity}`
          }
          animate={animate}
        />
      )}
      {state.interruptionNotice && (
        <Text color={colorEnabled ? "yellow" : undefined}>
          {state.interruptionNotice}
        </Text>
      )}
      {menuOpen && (
        <Box flexDirection="column">
          {suggestionsLoading ? (
            <WorkingIndicator
              label="Loading suggestions…"
              animate={animate && !state.activity}
            />
          ) : (
            suggestions.slice(0, 6).map((item, index) => (
              <Text
                key={item.value}
                color={index === suggestionIndex ? accent : undefined}
              >
                {index === suggestionIndex ? "›" : " "} {item.label}{" "}
                <Text dimColor>{item.disabled ?? item.context}</Text>
              </Text>
            ))
          )}
          <Text dimColor>
            ↑↓ choose · Tab complete · Enter select · Esc dismiss
          </Text>
        </Box>
      )}
      {!state.busy && !overlay && !state.pendingDecision && !menuOpen && (
        <Text dimColor>{presenter.recommendation(header)}</Text>
      )}
      <Box borderStyle="single" borderColor={accent} paddingX={1}>
        <Text color={accent}>› </Text>
        <TextInput
          value={input}
          onChange={onInput}
          onSubmit={onSubmit}
          focus={!state.pendingDecision && !overlay}
          placeholder="Ask about this repository, or type /"
        />
      </Box>
      <Text dimColor wrap="truncate-end">
        {header?.providerAvailability === "ready"
          ? `Reviewer: ${header.provider} · ${header.providerModel ?? "default model"} · ${header.providerVariant ?? "default effort"} · ${header.providerPrivacy ?? "provider"} · ${header.reviewMode.replace("_plus", "+")}`
          : `Reviewer unavailable: ${header?.providerAuthentication === "required" ? "authentication required" : "setup needed"} · /provider to fix`}
      </Text>
      <Text dimColor>
        /help · PgUp/PgDn history · Esc interrupt · Ctrl+C exit
      </Text>
    </Box>
  );
}

export function App({
  repositoryPath,
  controller: supplied,
  terminal,
}: AppProps): React.JSX.Element {
  const { exit } = useApp();
  const { setRawMode } = useStdin();
  const { stdout } = useStdout();
  const [terminalHandoff, setTerminalHandoff] = useState(false);
  const [controller] = useState(
    () =>
      supplied ??
      new SessionController({
        repositoryPath,
        loginProvider: async (provider) => {
          setTerminalHandoff(true);
          await new Promise<void>((resolve) => setImmediate(resolve));
          setRawMode(false);
          terminal?.suspend();
          try {
            await loginProvider(provider);
          } finally {
            terminal?.resume();
            setRawMode(true);
            setTerminalHandoff(false);
          }
        },
      }),
  );
  const [state, setState] = useState<SessionState>(controller.state);
  const [input, setInput] = useState("");
  const [scrollOffset, setScrollOffset] = useState(0);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);

  useEffect(() => {
    if (terminal) terminal.onExit = () => controller.dispose();
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
  useEffect(
    () => setScrollOffset(0),
    [state.overlay?.title, state.pendingDecision?.id],
  );
  const [dimensions, setDimensions] = useState({
    width: stdout.columns ?? 100,
    height: stdout.rows ?? 40,
  });

  useEffect(() => {
    const unsubscribe = controller.subscribe(setState);
    void controller.start();
    return () => {
      unsubscribe();
      controller.dispose();
    };
  }, [controller]);

  useEffect(() => {
    if (state.shouldExit) exit();
  }, [state.shouldExit, exit]);

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

  useInput(
    (value, key) => {
      if (key.ctrl && value === "c") {
        controller.dispose();
        exit();
        return;
      }
      if (
        (suggestions.length || suggestionsLoading) &&
        !state.overlay &&
        !state.pendingDecision
      ) {
        if (key.escape) {
          setSuggestions([]);
          setSuggestionsDismissed(true);
          return;
        }
        if (!suggestions.length) return;
        if (key.upArrow) {
          setSuggestionIndex(
            (index) => (index + suggestions.length - 1) % suggestions.length,
          );
          return;
        }
        if (key.downArrow) {
          setSuggestionIndex((index) => (index + 1) % suggestions.length);
          return;
        }
        if (key.tab) {
          setInput(suggestions[suggestionIndex]!.completion);
          return;
        }
      }
      if (key.escape) {
        if (state.overlay) {
          void controller.submit("/close");
          return;
        }
        if (input) {
          setInput("");
          return;
        }
        if (state.pendingDecision) {
          void controller.confirm(state.pendingDecision.id, false);
          return;
        }
        controller.interrupt();
        return;
      }
      if (key.pageUp)
        setScrollOffset((offset) =>
          state.overlay || state.pendingDecision
            ? Math.max(0, offset - 5)
            : offset + 5,
        );
      if (key.pageDown)
        setScrollOffset((offset) =>
          state.overlay || state.pendingDecision
            ? offset + 5
            : Math.max(0, offset - 5),
        );
      if (!state.overlay && !state.pendingDecision && !state.busy) {
        if (key.upArrow) setInput(controller.history("previous"));
        if (key.downArrow) setInput(controller.history("next"));
      }
      if (state.pendingDecision && (value === "y" || value === "n")) {
        void controller.confirm(state.pendingDecision.id, value === "y");
      }
    },
    { isActive: !terminalHandoff },
  );

  const submit = (value: string): void => {
    if (state.busy) return;
    setScrollOffset(0);
    const choice = suggestions[suggestionIndex];
    if (!state.overlay && choice) {
      if (choice.disabled) return;
      if (choice.argument) {
        setInput(choice.completion);
        return;
      }
      value = choice.completion;
    }
    setSuggestions([]);
    setInput("");
    void controller.submit(value);
  };

  return (
    <SessionView
      state={state}
      input={input}
      onInput={(value) => {
        setSuggestionsDismissed(false);
        setInput(value);
      }}
      onSubmit={submit}
      onSelect={(action) => {
        void controller.select(action);
      }}
      suggestions={suggestions}
      suggestionIndex={suggestionIndex}
      suggestionsLoading={suggestionsLoading}
      terminalWidth={dimensions.width}
      terminalHeight={dimensions.height}
      colorEnabled={!process.env.NO_COLOR}
      terminalHandoff={terminalHandoff}
      fullscreen={terminal?.enabled}
      animate={
        interactiveEffects(Boolean(stdout.isTTY)) &&
        process.env.PREFLIGHT_NO_ANIMATION !== "1"
      }
      scrollOffset={scrollOffset}
    />
  );
}
