import React, { useEffect, useState } from "react";
import { Box, Text, useApp, useInput, useStdin } from "ink";
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
}

const SEVERITY_COLORS: Record<string, "red" | "yellow" | "cyan" | "gray"> = {
  CRITICAL: "red",
  WARNING: "yellow",
  SUGGESTION: "cyan",
  INFORMATIONAL: "gray",
};

function TranscriptItem({
  entry,
}: {
  entry: TranscriptEntry;
}): React.JSX.Element {
  if (entry.kind === "user") {
    return (
      <Box marginTop={1}>
        <Text color="cyan" bold>
          You › {entry.body}
        </Text>
      </Box>
    );
  }
  const titleColor =
    entry.kind === "error"
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
          {entry.kind === "error" ? "! " : entry.kind === "review" ? "◆ " : ""}
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
            color={severity ? SEVERITY_COLORS[severity] : undefined}
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
}: SessionViewProps): React.JSX.Element {
  const header = state.header;
  const recent = state.transcript.slice(-24);
  return (
    <Box flexDirection="column" paddingX={1}>
      <Box justifyContent="space-between">
        <Text bold color="cyan">
          ✈ PREFLIGHT
        </Text>
        <Text dimColor>inspect before your code takes off</Text>
      </Box>

      {header ? (
        <Box flexDirection="column" marginTop={1}>
          <Box gap={1}>
            <Text bold>{header.repository}</Text>
            <Text color="cyan">{header.branch}</Text>
            <Text dimColor>→ {header.baseBranch}</Text>
            <Text color={header.behind > 0 ? "yellow" : undefined}>
              ↑{header.ahead} ↓{header.behind}
            </Text>
          </Box>
          <Box gap={2}>
            <Text color="green">{header.staged} staged</Text>
            <Text color="yellow">{header.unstaged} unstaged</Text>
            <Text color="magenta">{header.untracked} untracked</Text>
            <Text color={header.conflicts ? "red" : undefined}>
              {header.conflicts} conflicts
            </Text>
            <Text>
              Provider: <Text bold>{header.provider}</Text>
              {header.providerAvailability && (
                <Text
                  color={
                    header.providerAvailability === "ready" ? "green" : "yellow"
                  }
                >
                  {` · ${header.providerAvailability}`}
                </Text>
              )}
            </Text>
            <Text>
              Mode: <Text bold>{header.reviewMode.replace("_", "+")}</Text>
            </Text>
          </Box>
        </Box>
      ) : (
        <Box marginTop={1}>
          <Text color="cyan">Inspecting repository…</Text>
        </Box>
      )}

      <Box marginTop={1} flexDirection="column">
        {recent.map((entry) => (
          <TranscriptItem key={entry.id} entry={entry} />
        ))}
      </Box>

      {state.activity && (
        <Box marginTop={1}>
          <Text color="cyan">◐ {state.activity}</Text>
        </Box>
      )}

      {state.pendingDecision && (
        <Box
          marginTop={1}
          paddingX={1}
          flexDirection="column"
          borderStyle="round"
          borderColor="yellow"
        >
          <Text bold>{state.pendingDecision.title}</Text>
          <Text>{state.pendingDecision.body}</Text>
          <Text color="yellow">
            y {state.pendingDecision.confirmLabel} · n cancel
          </Text>
        </Box>
      )}

      {state.overlay && !state.pendingDecision && (
        <Box
          marginTop={1}
          paddingX={1}
          flexDirection="column"
          borderStyle="round"
          borderColor="cyan"
        >
          <Text bold color="cyan">
            {state.overlay.title}
          </Text>
          {state.overlay.body ? (
            <>
              <Text>{state.overlay.body.slice(0, 12000)}</Text>
              <Text dimColor>Esc close</Text>
            </>
          ) : (
            <SelectInput
              items={(state.overlay.items ?? []).map((item) => ({
                label: item.label,
                value: item.command,
              }))}
              onSelect={(item) => onSubmit(item.value)}
              limit={12}
            />
          )}
        </Box>
      )}

      <Box marginTop={1} borderStyle="single" borderColor="gray" paddingX={1}>
        <Text color="cyan">› </Text>
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
        /tree · /commits · /review staged · /provider · /help · Ctrl+C
        cancel/exit
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
  const [controller] = useState(
    () =>
      supplied ??
      new SessionController({
        repositoryPath,
        loginProvider: async (provider) => {
          setRawMode(false);
          try {
            await loginProvider(provider);
          } finally {
            setRawMode(true);
          }
        },
      }),
  );
  const [state, setState] = useState<SessionState>(controller.state);
  const [input, setInput] = useState("");

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

  useInput(
    (value, key) => {
      if (key.ctrl && value === "c") controller.cancel();
      if (key.escape && state.overlay) void controller.submit("/close");
      if (state.pendingDecision && (value === "y" || value === "n")) {
        void controller.confirm(state.pendingDecision.id, value === "y");
      }
    },
    { isActive: true },
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
    />
  );
}
