import React, { useEffect, useState } from "react";
import { Box, Text } from "ink";
import TextInput from "ink-text-input";
import SelectInput from "ink-select-input";
import { sanitizeComposerInput, useWorkspaceInput } from "./workspace-input.js";
import {
  useWorkspaceSession,
  useWorkspaceDimensions,
  useCommandSuggestions,
  useScanClock,
} from "./workspace-hooks.js";
import {
  SessionController,
  type SessionState,
  type SessionAction,
} from "./session-controller.js";
import type { Suggestion } from "./command-registry.js";
import { TerminalSession, interactiveEffects } from "./terminal-session.js";
import { WorkspacePresenter } from "./workspace-presenter.js";
import { WorkingIndicator } from "./working-indicator.js";
import { GitGraphView } from "./git-graph-view.js";
import { GitGraphPresenter } from "./git-graph-presenter.js";
import { ScanActivityPresenter } from "./scan-activity-presenter.js";

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
  now?: number;
  composerKey?: number;
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
  now = Date.now(),
  composerKey = 0,
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
  const showGraph =
    terminalWidth >= 100 &&
    Boolean(state.graph) &&
    !state.transcriptOnly &&
    !state.overlay &&
    !state.pendingDecision;
  const lines = presenter.transcript(
    state.transcript,
    Math.max(10, terminalWidth - (showGraph ? 42 : 4)),
    bodyHeight,
    scrollOffset,
  );
  const overlay = state.overlay;
  const reviewing =
    state.scanProgress?.stage === "review" &&
    (state.scanProgress.status === "started" ||
      Boolean(state.scanProgress.activeBatches?.length));
  const activity =
    reviewing && state.scanBatchStartedAt
      ? new ScanActivityPresenter().heartbeat(
          state.scanProgress,
          Math.max(0, now - state.scanBatchStartedAt),
        )
      : state.activity;
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
      {terminalWidth < 100 && state.graph && (
        <Text dimColor wrap="truncate-end">
          {new GitGraphPresenter().summary(state.graph)}
        </Text>
      )}
      <Box
        flexDirection="row"
        flexGrow={1}
        height={bodyHeight}
        overflowY="hidden"
      >
        <Box
          flexDirection="column"
          flexGrow={1}
          height={bodyHeight}
          overflowY="hidden"
          marginTop={1}
          width={showGraph ? terminalWidth - 40 : terminalWidth - 2}
        >
          {state.pendingDecision ? (
            <>
              <Text bold color={colorEnabled ? "yellow" : undefined}>
                {state.pendingDecision.title}
              </Text>
              <Text>
                {presenter.viewport(
                  state.pendingDecision.body,
                  terminalWidth - 4,
                  Math.max(1, bodyHeight - 4),
                  scrollOffset,
                )}
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
                  {presenter.viewport(
                    overlay.body,
                    terminalWidth - 4,
                    Math.max(2, bodyHeight - (overlay.items?.length ? 10 : 3)),
                    scrollOffset,
                  )}
                </Text>
              )}
              {overlay.items?.length ? (
                <SelectInput
                  key={overlay.title}
                  items={overlay.items.map((item) => ({
                    key: item.value,
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
              <Text dimColor>
                {overlay.kind === "finding"
                  ? "Ask below about this finding · Esc back · PgUp/PgDn read"
                  : "↑↓ select · Enter open · Esc back · PgUp/PgDn read"}
              </Text>
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
        {showGraph && state.graph && (
          <Box
            borderStyle="single"
            borderColor={colorEnabled ? "gray" : undefined}
          >
            <GitGraphView
              graph={state.graph}
              height={Math.max(1, bodyHeight - 2)}
              colorEnabled={colorEnabled}
            />
          </Box>
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
      {activity && <WorkingIndicator label={activity} animate={animate} />}
      {state.busy &&
        state.recentOperation &&
        state.scanProgress?.stage !== "review" && (
          <Text dimColor wrap="truncate-end">
            {state.recentOperation}
          </Text>
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
          key={composerKey}
          value={input}
          onChange={onInput}
          onSubmit={onSubmit}
          focus={
            !state.pendingDecision && (!overlay || overlay.kind === "finding")
          }
          placeholder="Ask about this repository, or type /"
        />
      </Box>
      <Text dimColor wrap="truncate-end">
        {header?.providerAvailability === "ready"
          ? `Reviewer: ${header.provider} · ${header.providerModel ?? "default model"} · ${header.providerVariant ?? "default effort"} · ${header.providerPrivacy ?? "provider"} · ${header.reviewMode.replace("_plus", "+")}`
          : `Reviewer unavailable: ${header?.providerAuthentication === "required" ? "authentication required" : "setup needed"} · /provider to fix`}
      </Text>
      <Text dimColor>
        /help · /findings · /copyview · ↑↓/PgUp/PgDn scroll · Ctrl+P/N history ·
        Esc interrupt · Ctrl+C exit
      </Text>
    </Box>
  );
}

export function App(options: AppProps): React.JSX.Element {
  const { controller, state, terminalHandoff, exit } =
    useWorkspaceSession(options);
  const [input, setInput] = useState("");
  const [composerRevision, setComposerRevision] = useState(0);
  const [scrollOffset, setScrollOffset] = useState(0);
  const palette = useCommandSuggestions(input, controller);
  const dimensions = useWorkspaceDimensions();
  const now = useScanClock(state);
  useEffect(
    () => setScrollOffset(0),
    [state.overlay?.title, state.pendingDecision?.id],
  );
  const replaceInput = (value: string): void => {
    setInput(value);
    setComposerRevision((revision) => revision + 1);
  };
  useWorkspaceInput({
    controller,
    state,
    input,
    terminalHandoff,
    exit,
    setInput,
    replaceInput,
    setScrollOffset,
    ...palette,
  });
  const submit = (value: string): void => {
    if (state.busy) return;
    setScrollOffset(0);
    const choice = palette.suggestions[palette.suggestionIndex];
    if (!state.overlay && choice) {
      if (choice.disabled) return;
      if (choice.argument) {
        replaceInput(choice.completion);
        return;
      }
      value = choice.completion;
    }
    palette.setSuggestions([]);
    setInput("");
    void controller.submit(value);
  };
  return (
    <SessionView
      state={state}
      input={input}
      onInput={(value) => {
        palette.setSuggestionsDismissed(false);
        setInput(sanitizeComposerInput(value));
      }}
      onSubmit={submit}
      onSelect={(action) => {
        void controller.select(action);
      }}
      suggestions={palette.suggestions}
      suggestionIndex={palette.suggestionIndex}
      suggestionsLoading={palette.suggestionsLoading}
      terminalWidth={dimensions.width}
      terminalHeight={dimensions.height}
      colorEnabled={!process.env.NO_COLOR}
      terminalHandoff={terminalHandoff}
      fullscreen={options.terminal?.enabled}
      animate={
        interactiveEffects(dimensions.isTTY) &&
        process.env.PREFLIGHT_NO_ANIMATION !== "1"
      }
      scrollOffset={scrollOffset}
      now={now}
      composerKey={composerRevision}
    />
  );
}
