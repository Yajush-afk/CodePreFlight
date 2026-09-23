import React from "react";
import { Box, Text } from "ink";

interface Segment {
  text: string;
  bold?: boolean;
  code?: boolean;
}

function safe(value: string): string {
  return value.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, "");
}

function segments(value: string): Segment[] {
  const result: Segment[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let start = 0;
  for (const match of value.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > start) result.push({ text: value.slice(start, index) });
    const token = match[0];
    result.push(
      token.startsWith("**")
        ? { text: token.slice(2, -2), bold: true }
        : { text: token.slice(1, -1), code: true },
    );
    start = index + token.length;
  }
  if (start < value.length) result.push({ text: value.slice(start) });
  return result.length ? result : [{ text: value }];
}

export function TerminalMarkdownLine({
  value,
  colorEnabled = true,
  code = false,
}: {
  value: string;
  colorEnabled?: boolean;
  code?: boolean;
}): React.JSX.Element {
  const clean = safe(value);
  const heading = /^(#{1,6})\s+(.+)$/.exec(clean);
  const bullet = /^[-*]\s+(.+)$/.exec(clean);
  const numbered = /^(\d+)\.\s+(.+)$/.exec(clean);
  const prefix = bullet ? "• " : numbered ? `${numbered[1]}. ` : "";
  const content = heading?.[2] ?? bullet?.[1] ?? numbered?.[2] ?? clean;
  return (
    <Text
      bold={Boolean(heading)}
      color={heading && colorEnabled ? "cyan" : undefined}
      dimColor={code}
    >
      {prefix}
      {segments(content).map((segment, index) => (
        <Text
          key={index}
          bold={segment.bold}
          color={segment.code && colorEnabled ? "cyan" : undefined}
          inverse={segment.code}
        >
          {segment.text}
        </Text>
      ))}
    </Text>
  );
}

export function TerminalMarkdown({
  value,
  height,
  offset = 0,
  colorEnabled = true,
}: {
  value: string;
  height: number;
  offset?: number;
  colorEnabled?: boolean;
}): React.JSX.Element {
  let fenced = false;
  const lines = safe(value)
    .split("\n")
    .flatMap((line) => {
      if (line.trim().startsWith("```")) {
        fenced = !fenced;
        return [];
      }
      return [{ value: line, code: fenced }];
    });
  const start = Math.min(offset, Math.max(0, lines.length - height));
  return (
    <Box flexDirection="column">
      {lines.slice(start, start + height).map((line, index) => (
        <TerminalMarkdownLine
          key={index}
          value={line.value}
          code={line.code}
          colorEnabled={colorEnabled}
        />
      ))}
    </Box>
  );
}
