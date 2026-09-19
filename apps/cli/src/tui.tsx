import React, { useEffect, useState } from "react";
import { Box, Text, useApp, useInput, useStdin, useStdout } from "ink";
import TextInput from "ink-text-input";
import SelectInput from "ink-select-input";
import { loginProvider } from "./provider-auth.js";
import {
  SessionController,
  type SessionState,
  type TranscriptEntry,
} from "./session-controller.js";

interface AppProps {
  repositoryPath: string;
  controller?: SessionController;
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
}

const SEVERITY_COLORS: Record<string, "red" | "yellow" | "cyan" | "gray"> = {
  CRITICAL: "red",
  WARNING: "yellow",
  SUGGESTION: "cyan",
  INFORMATIONAL: "gray",
};

function TranscriptItem({
  entry,
  colorEnabled,
}: {
  entry: TranscriptEntry;
  colorEnabled: boolean;
}): React.JSX.Element {
  if (entry.kind === "user") {
    return (
      <Box marginTop={1}>
        <Text color={colorEnabled ? "cyan" : undefined} bold>
          You › {entry.body}
        </Text>
      </Box>
    );
  }
  const titleColor = !colorEnabled
    ? undefined
    : entry.kind === "error"
      ? "red"
      : entry.kind === "review"
        ? "yellow"
        : entry.kind === "answer"
          ? "green"
          : undefined;
  return (
    <Box marginTop={1} flexDirection="column">
      {entry.title && (
        <Text bold color={titleColor}>
          {entry.kind === "error"
            ? "× "
            : entry.kind === "review"
              ? "◆ "
              : entry.kind === "answer"
                ? "↳ "
                : entry.kind === "status"
                  ? "i "
                  : "· "}
          {entry.title}
        </Text>
      )}
      {entry.body.split("\n").map((line, index) => {
        const severity = Object.keys(SEVERITY_COLORS).find((value) =>
          line.includes(value),
        );
        return (
          <Text
            key={`${entry.id}-${index}`}
            color={
              colorEnabled && severity ? SEVERITY_COLORS[severity] : undefined
            }
          >
            {line}
          </Text>
        );
      })}
    </Box>
  );
}

export function SessionView({
  state,
  input,
  onInput,
  onSubmit,
  terminalWidth = 100,
  terminalHeight = 40,
  colorEnabled = true,
  terminalHandoff = false,
}: SessionViewProps): React.JSX.Element {
  if (terminalHandoff) return <></>;
  const header = state.header;
  const narrow = terminalWidth < 96;
  const recent = state.transcript.slice(
    -Math.max(6, Math.min(narrow ? 12 : 24, terminalHeight - 17)),
  );
  const accent = colorEnabled ? "cyan" : undefined;
  return (
    <Box flexDirection="column" paddingX={1}>
      <Box justifyContent="space-between">
        <Text bold color={accent}>
          {narrow ? "──✈ PREFLIGHT" : "────✈  CODE PREFLIGHT"}
        </Text>
        {!narrow && <Text dimColor>repository quality control</Text>}
      </Box>

      {header ? (
        <Box flexDirection="column" marginTop={1}>
          <Text>
            <Text bold>{header.repository}</Text>
            {"  "}
            <Text color={accent}>{header.branch}</Text>
            <Text dimColor> → {header.baseBranch}</Text>
            {"  "}
            <Text
              color={colorEnabled && header.behind > 0 ? "yellow" : undefined}
            >
              local ↑{header.ahead} ↓{header.behind}
            </Text>
          </Text>
          <Text>
            <Text color={colorEnabled ? "green" : undefined}>
              +{header.staged} staged
            </Text>
            {"  "}
            <Text color={colorEnabled ? "yellow" : undefined}>
              ~{header.unstaged} changed
            </Text>
            {"  "}
            <Text color={colorEnabled ? "magenta" : undefined}>
              ?{header.untracked} new
            </Text>
            {"  "}
            <Text color={colorEnabled && header.conflicts ? "red" : undefined}>
              !{header.conflicts} conflicts
            </Text>
          </Text>
          <Text>
            provider <Text bold>{header.provider}</Text> [
            {header.providerAvailability ?? "unknown"}] · auth{" "}
            {header.providerAuthentication ?? "unknown"} · model{" "}
            {header.providerModel ?? "not applicable"} · variant{" "}
            {header.providerVariant ?? "provider default"}
          </Text>
          <Text>
            privacy {header.providerPrivacy ?? "unknown"} · mode{" "}
            <Text bold>{header.reviewMode.replace("_", "+")}</Text> · PR{" "}
            {header.pullRequest ?? "not checked"}
          </Text>
        </Box>
      ) : (
        <Box marginTop={1}>
          <Text color={accent}>Inspecting repository…</Text>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        {recent.map((entry) => (
          <TranscriptItem
            key={entry.id}
            entry={entry}
            colorEnabled={colorEnabled}
          />
        ))}
      </Box>

      {state.pipeline && (
        <Box marginTop={1} gap={narrow ? 1 : 2} flexWrap="wrap">
          {state.pipeline.map((item) => (
            <Text
              key={item.label}
              color={
                !colorEnabled
                  ? undefined
                  : item.status === "failed"
                    ? "red"
                    : item.status === "complete"
                      ? "green"
                      : item.status === "active"
                        ? "cyan"
                        : "gray"
              }
            >
              {item.status === "complete"
                ? "✓"
                : item.status === "active"
                  ? "◐"
                  : item.status === "failed"
                    ? "×"
                    : "○"}{" "}
              {item.label}
            </Text>
          ))}
        </Box>
      )}

      {state.activity && (
        <Box marginTop={1}>
          <Text color={accent}>◐ {state.activity}</Text>
        </Box>
      )}

      {state.pendingDecision && (
        <Box
          marginTop={1}
          paddingX={1}
          flexDirection="column"
          borderStyle={narrow ? "single" : "round"}
          borderColor={colorEnabled ? "yellow" : undefined}
        >
          <Text bold>{state.pendingDecision.title}</Text>
          <Text>{state.pendingDecision.body}</Text>
          <Text color={colorEnabled ? "yellow" : undefined}>
            y {state.pendingDecision.confirmLabel} · n cancel
          </Text>
        </Box>
      )}

      {state.overlay && !state.pendingDecision && (
        <Box
          marginTop={1}
          paddingX={1}
          flexDirection="column"
          borderStyle={narrow ? "single" : "round"}
          borderColor={accent}
        >
          <Text bold color={accent}>
            {state.overlay.title}
          </Text>
          {state.overlay.body && (
            <>
              <Text>
                {state.overlay.body
                  .split("\n")
                  .slice(0, Math.max(8, terminalHeight - 12))
                  .join("\n")}
              </Text>
            </>
          )}
          {state.overlay.items?.length ? (
            <SelectInput
              items={(state.overlay.items ?? []).map((item) => ({
                label: item.label,
                value: item.command,
              }))}
              onSelect={(item) => onSubmit(item.value)}
              limit={12}
            />
          ) : null}
          <Text dimColor>Esc close</Text>
        </Box>
      )}

      <Box marginTop={1} borderStyle="single" borderColor={accent} paddingX={1}>
        <Text color={accent}>preflight › </Text>
        <TextInput
          value={input}
          onChange={onInput}
          onSubmit={onSubmit}
          focus={!state.busy && !state.pendingDecision && !state.overlay}
          placeholder={
            state.busy ? "Working…" : "Ask about this repository or type /help"
          }
        />
      </Box>
      <Text dimColor>
        {narrow
          ? "/help · ↑↓ history · Ctrl+C cancel"
          : "/tree · /commits · /review staged · /mode · /help · ↑↓ history · Ctrl+C cancel/exit"}
      </Text>
    </Box>
  );
}

export function App({
  repositoryPath,
  controller: supplied,
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
          try {
            await loginProvider(provider);
          } finally {
            setRawMode(true);
            setTerminalHandoff(false);
          }
        },
      }),
  );
  const [state, setState] = useState<SessionState>(controller.state);
  const [input, setInput] = useState("");
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
      if (key.ctrl && value === "c") controller.cancel();
      if (key.escape && state.overlay) void controller.submit("/close");
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
    setInput("");
    void controller.submit(value);
  };

  return (
    <SessionView
      state={state}
      input={input}
      onInput={setInput}
      onSubmit={submit}
      terminalWidth={dimensions.width}
      terminalHeight={dimensions.height}
      colorEnabled={!process.env.NO_COLOR}
      terminalHandoff={terminalHandoff}
    />
  );
}
