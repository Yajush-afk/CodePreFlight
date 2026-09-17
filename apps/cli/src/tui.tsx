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
  status?: "completed" | "failed";
  failure?: { message?: string };
  summary?: string;
  findings?: Array<{
    severity?: string;
    title?: string;
    explanation?: string;
    impact?: string;
    verification?: string;
    recommendation?: string;
    evidence?: Array<{
      path?: string;
      start_line?: number;
      end_line?: number;
    }>;
    suggested_tests?: string[];
  }>;
  rejected_findings?: number;
}

interface FindingDetailView {
  path?: string;
  evidenceDiff?: string;
  relatedFiles?: Array<{
    path?: string;
    relationship?: string;
    confidence?: string;
  }>;
  history?: string[];
  suggestedTests?: string[];
}

const FILTERS = [
  "all",
  "critical",
  "warning",
  "suggestion",
  "informational",
] as const;

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
  const [filterIndex, setFilterIndex] = useState(0);
  const [selectedFinding, setSelectedFinding] = useState(0);
  const [findingDetail, setFindingDetail] = useState<FindingDetailView | null>(
    null,
  );
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

  const runReview = (remoteApproved = false): void => {
    setError(null);
    setReview(null);
    setDisclosure(null);
    setActivity("Preparing staged review…");
    const request = controller();
    client
      .request(
        "review",
        repositoryPath,
        { target: "staged", remoteApproved },
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

  const filter = FILTERS[filterIndex];
  const visibleFindings = (review?.findings ?? []).filter(
    (finding) => filter === "all" || finding.severity === filter,
  );

  const inspectFinding = (): void => {
    const finding = visibleFindings[selectedFinding];
    const evidence = finding?.evidence?.[0];
    if (!finding || !evidence?.path) return;
    setActivity(`Loading evidence for ${evidence.path}…`);
    const request = controller();
    client
      .request(
        "explain",
        repositoryPath,
        {
          mode: "finding",
          target: "staged",
          path: evidence.path,
          suggestedTests: finding.suggested_tests ?? [],
        },
        undefined,
        { signal: request.signal },
      )
      .then((response) => {
        if (activeRequest.current === request) {
          setFindingDetail(response.result as FindingDetailView);
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
    if (input === "a" && disclosure) runReview(true);
    if (input === "f" && review) {
      setFilterIndex((current) => (current + 1) % FILTERS.length);
      setSelectedFinding(0);
      setFindingDetail(null);
    }
    if (key.downArrow && visibleFindings.length) {
      setSelectedFinding((current) =>
        Math.min(current + 1, visibleFindings.length - 1),
      );
      setFindingDetail(null);
    }
    if (key.upArrow && visibleFindings.length) {
      setSelectedFinding((current) => Math.max(current - 1, 0));
      setFindingDetail(null);
    }
    if ((key.return || input === "d") && visibleFindings.length)
      inspectFinding();
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
        <Text dimColor>
          {disclosure
            ? "Press a to approve this disclosed provider request · s status · q exit"
            : "Press s to retry status · q to exit"}
        </Text>
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
          {review.status === "failed" && (
            <Text color="red">Review failed: {review.failure?.message}</Text>
          )}
          <Text dimColor>
            Filter: {filter} · {visibleFindings.length} shown
          </Text>
          {visibleFindings.map((finding, index) => {
            const evidence = finding.evidence?.[0];
            return (
              <Text
                key={`${finding.title}-${index}`}
                inverse={index === selectedFinding}
              >
                {finding.severity?.toUpperCase()} · {finding.title} ·{" "}
                {evidence?.path}:{evidence?.start_line} · {finding.verification}
              </Text>
            );
          })}
          {(review.findings?.length ?? 0) === 0 && (
            <Text color="green">No verified findings.</Text>
          )}
          {visibleFindings[selectedFinding] && (
            <Box marginTop={1} flexDirection="column">
              <Text bold>Selected finding</Text>
              <Text>{visibleFindings[selectedFinding].explanation}</Text>
              <Text>Impact: {visibleFindings[selectedFinding].impact}</Text>
              <Text>
                Inspect: {visibleFindings[selectedFinding].recommendation}
              </Text>
            </Box>
          )}
          {findingDetail && (
            <Box marginTop={1} flexDirection="column">
              <Text bold>Evidence diff</Text>
              <Text>{findingDetail.evidenceDiff || "No diff available."}</Text>
              <Text bold>Related files</Text>
              <Text>
                {findingDetail.relatedFiles?.length
                  ? findingDetail.relatedFiles
                      .map(
                        (item) =>
                          `${item.path} (${item.relationship}, ${item.confidence})`,
                      )
                      .join(" · ")
                  : "No related files found."}
              </Text>
              <Text bold>Relevant history</Text>
              <Text>
                {findingDetail.history?.join("\n") || "No history found."}
              </Text>
              <Text bold>Suggested tests</Text>
              <Text>
                {findingDetail.suggestedTests?.join(" · ") ||
                  "No tests suggested."}
              </Text>
            </Box>
          )}
        </Box>
      )}
      <Box marginTop={1}>
        <Text dimColor>
          r review · a approve disclosed remote review · f filter · ↑/↓ select ·
          enter details · s status · q quit
        </Text>
      </Box>
    </Box>
  );
}
