import React from "react";
import { Box, Text } from "ink";
import { GitGraphPresenter, type GitGraph } from "./git-graph-presenter.js";

export function GitGraphView({
  graph,
  height,
  colorEnabled,
}: {
  graph: GitGraph;
  height: number;
  colorEnabled: boolean;
}): React.JSX.Element {
  const color = (tone: string): string | undefined => {
    if (!colorEnabled || tone === "text" || tone === "muted") return undefined;
    if (tone === "base") return "blue";
    if (tone === "current" || tone === "working") return "cyan";
    return "gray";
  };
  return (
    <Box
      width={42}
      flexShrink={0}
      flexDirection="column"
      paddingLeft={2}
      overflowY="hidden"
    >
      <Text bold>Local history</Text>
      {new GitGraphPresenter()
        .lines(graph)
        .slice(0, Math.max(1, height - 2))
        .map((line, index) => (
          <Text key={index} wrap="truncate-end">
            {line.segments.map((segment, segmentIndex) => (
              <Text
                key={segmentIndex}
                color={color(segment.tone)}
                dimColor={segment.dim || segment.tone === "muted"}
              >
                {segment.text}
              </Text>
            ))}
          </Text>
        ))}
      <Text dimColor>Display only · /graph</Text>
    </Box>
  );
}
