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
  return (
    <Box
      width={38}
      flexShrink={0}
      flexDirection="column"
      paddingLeft={2}
      overflowY="hidden"
    >
      <Text bold>Local commit graph</Text>
      {new GitGraphPresenter()
        .lines(graph)
        .slice(0, Math.max(1, height - 2))
        .map((line, index) => (
          <Text
            key={index}
            wrap="truncate-end"
            color={
              !colorEnabled
                ? undefined
                : line.lane === "base"
                  ? "blue"
                  : line.lane === "current"
                    ? "cyan"
                    : "gray"
            }
          >
            {line.text}
          </Text>
        ))}
      <Text dimColor>Display only · /graph</Text>
    </Box>
  );
}
