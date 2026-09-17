import React, { useEffect, useRef, useState } from "react";
import { Box, Text, useApp, useInput } from "ink";
import { EngineClient } from "./engine-client.js";

interface AppProps {
  repositoryPath: string;
}

interface SnapshotView {
  branch?: string | null;
  detached_head?: string | null;
  base_branch?: string | null;
  ahead?: number;
  behind?: number;
  files?: Array<{
    path: string;
    staged: boolean;
    unstaged: boolean;
    untracked: boolean;
    ignored?: boolean;
  }>;
  conflicts?: string[];
  project?: { attention_areas?: string[] };
}

interface ReviewView {
  summary?: string;
  findings?: Array<{
    severity?: string;
    title?: string;
    verification?: string;
    evidence?: Array<{ path?: string; start_line?: number }>;
  }>;
  rejected_findings?: number;
}

interface DisclosureView {
  provider: string;
  kind: string;
  characters: number;
  redactions: number;
  scanner: string;
}

export function App({ repositoryPath }: AppProps): React.JSX.Element {
  const { exit } = useApp();
  const [snapshot, setSnapshot] = useState<SnapshotView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewView | null>(null);
  const [disclosure, setDisclosure] = useState<DisclosureView | null>(null);
  const [client] = useState(() => new EngineClient({ persistent: true }));
  const activeRequest = useRef<AbortController | null>(null);

  const controller = (): AbortController => {
    activeRequest.current?.abort();
    const next = new AbortController();
    activeRequest.current = next;
    return next;
  };

  const refresh = (): void => {
    setError(null);
    const request = controller();
    client
      .status(repositoryPath, undefined, { signal: request.signal })
      .then((result) => {
        if (activeRequest.current === request) {
          setSnapshot(result.repository as SnapshotView);
        }
      })
      .catch((reason: unknown) => {
        if (activeRequest.current === request && !request.signal.aborted) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
  };

  const runReview = (): void => {
    setError(null);
    setReview(null);
    setDisclosure(null);
    setActivity("Preparing staged review…");
    const request = controller();
    client
      .request(
        "review",
        repositoryPath,
        { target: "staged", remoteApproved: false },
        (event) => {
          if (event.event === "progress") {
            setActivity(String(event.payload?.message ?? "Reviewing…"));
          }
          if (event.event === "consent_required") {
            const provider = event.payload?.provider as
              { name?: string; kind?: string } | undefined;
            const manifest = event.payload?.manifest as
              | {
                  total_characters?: number;
                  redactions?: number;
                  secret_scanner?: string;
                }
              | undefined;
            setDisclosure({
              provider: provider?.name ?? "unknown",
              kind: provider?.kind ?? "unknown",
              characters: manifest?.total_characters ?? 0,
              redactions: manifest?.redactions ?? 0,
              scanner: manifest?.secret_scanner ?? "built-in",
            });
          }
        },
        { signal: request.signal },
      )
      .then((result) => {
        if (activeRequest.current === request) {
          setReview(result as ReviewView);
          setActivity(null);
        }
      })
      .catch((reason: unknown) => {
        if (activeRequest.current === request && !request.signal.aborted) {
          setActivity(null);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
  };

  useEffect(() => {
    refresh();
    return () => {
      activeRequest.current?.abort();
      client.dispose();
    };
  }, [repositoryPath]);
  useInput((input, key) => {
    if (input === "q" || (key.ctrl && input === "c")) {
      activeRequest.current?.abort();
      client.dispose();
      exit();
    }
    if (input === "s") refresh();
    if (input === "r") runReview();
  });

  if (error) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="red">CodePreFlight could not complete the request</Text>
        <Text>{error}</Text>
        {disclosure && (
          <Text>
            Disclosure: {disclosure.provider} · {disclosure.kind} ·{" "}
            {disclosure.characters} characters · {disclosure.redactions}{" "}
            redactions · {disclosure.scanner}
          </Text>
        )}
        <Text dimColor>Press s to retry status · q to exit</Text>
      </Box>
    );
  }
  if (!snapshot) return <Text color="cyan">Inspecting repository…</Text>;

  const files = snapshot.files ?? [];
  const staged = files.filter((file) => file.staged).length;
  const unstaged = files.filter((file) => file.unstaged).length;
  const untracked = files.filter((file) => file.untracked).length;
  const ignored = files.filter((file) => file.ignored).length;

  return (
    <Box flexDirection="column" padding={1}>
      <Box justifyContent="space-between">
        <Text bold color="cyan">
          CodePreFlight
        </Text>
        <Text dimColor>repository inspection</Text>
      </Box>
      <Box marginTop={1} flexDirection="column">
        <Text>
          Branch{" "}
          <Text bold>
            {snapshot.branch ?? `detached @ ${snapshot.detached_head}`}
          </Text>
        </Text>
        <Text>Base {snapshot.base_branch ?? "not detected"}</Text>
        <Text>
          Sync {snapshot.ahead ?? 0} ahead · {snapshot.behind ?? 0} behind
        </Text>
      </Box>
      <Box marginTop={1} gap={2}>
        <Text color="green">{staged} staged</Text>
        <Text color="yellow">{unstaged} unstaged</Text>
        <Text color="magenta">{untracked} untracked</Text>
        <Text dimColor>{ignored} ignored</Text>
        <Text color={snapshot.conflicts?.length ? "red" : undefined}>
          {snapshot.conflicts?.length ?? 0} conflicts
        </Text>
      </Box>
      {(snapshot.project?.attention_areas?.length ?? 0) > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold>Attention</Text>
          <Text>{snapshot.project?.attention_areas?.join(" · ")}</Text>
        </Box>
      )}
      {activity && (
        <Box marginTop={1}>
          <Text color="cyan">{activity}</Text>
        </Box>
      )}
      {disclosure && (
        <Box marginTop={1} flexDirection="column">
          <Text bold>Provider disclosure</Text>
          <Text>
            {disclosure.provider} · {disclosure.kind} · {disclosure.characters}{" "}
            characters · {disclosure.redactions} redactions ·{" "}
            {disclosure.scanner}
          </Text>
        </Box>
      )}
      {review && (
        <Box marginTop={1} flexDirection="column">
          <Text bold>Review</Text>
          <Text>{review.summary ?? "No summary returned."}</Text>
          {(review.findings ?? []).map((finding, index) => {
            const evidence = finding.evidence?.[0];
            return (
              <Text key={`${finding.title}-${index}`}>
                {finding.severity?.toUpperCase()} · {finding.title} ·{" "}
                {evidence?.path}:{evidence?.start_line} · {finding.verification}
              </Text>
            );
          })}
          {(review.findings?.length ?? 0) === 0 && (
            <Text color="green">No verified findings.</Text>
          )}
        </Box>
      )}
      <Box marginTop={1}>
        <Text dimColor>r review staged · s refresh status · q quit</Text>
      </Box>
    </Box>
  );
}
