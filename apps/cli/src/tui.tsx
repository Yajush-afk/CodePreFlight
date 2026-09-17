import React, { useEffect, useState } from "react";
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

export function App({ repositoryPath }: AppProps): React.JSX.Element {
  const { exit } = useApp();
  const [snapshot, setSnapshot] = useState<SnapshotView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activity, setActivity] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewView | null>(null);

  const refresh = (): void => {
    setError(null);
    new EngineClient()
      .status(repositoryPath)
      .then((result) => setSnapshot(result.repository as SnapshotView))
      .catch((reason: unknown) =>
        setError(reason instanceof Error ? reason.message : String(reason)),
      );
  };

  const runReview = (): void => {
    setError(null);
    setReview(null);
    setActivity("Preparing staged review…");
    new EngineClient()
      .request(
        "review",
        repositoryPath,
        { target: "staged", remoteApproved: false },
        (event) => {
          if (event.event === "progress") {
            setActivity(String(event.payload?.message ?? "Reviewing…"));
          }
        },
      )
      .then((result) => {
        setReview(result as ReviewView);
        setActivity(null);
      })
      .catch((reason: unknown) => {
        setActivity(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
  };

  useEffect(refresh, [repositoryPath]);
  useInput((input) => {
    if (input === "q") exit();
    if (input === "s") refresh();
    if (input === "r") runReview();
  });

  if (error) {
    return (
      <Box flexDirection="column" padding={1}>
        <Text color="red">CodePreFlight could not complete the request</Text>
        <Text>{error}</Text>
        <Text dimColor>Press s to retry status · q to exit</Text>
      </Box>
    );
  }
  if (!snapshot) return <Text color="cyan">Inspecting repository…</Text>;

  const files = snapshot.files ?? [];
  const staged = files.filter((file) => file.staged).length;
  const unstaged = files.filter((file) => file.unstaged).length;
  const untracked = files.filter((file) => file.untracked).length;

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
