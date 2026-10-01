export interface GitTerminalHandoff {
  action: "launch_editor" | "launch_mergetool";
  command: [string, ...string[]];
}

export function parseGitTerminalHandoff(
  value: unknown,
): GitTerminalHandoff | null {
  if (!value || typeof value !== "object") return null;
  const result = value as Record<string, unknown>;
  if (result.requires_terminal_handoff !== true) return null;
  const action = result.action;
  const command = result.handoff_command;
  if (
    (action !== "launch_editor" && action !== "launch_mergetool") ||
    !Array.isArray(command) ||
    command.length === 0 ||
    command.some(
      (part) =>
        typeof part !== "string" || part.length === 0 || part.includes("\0"),
    )
  ) {
    throw new Error("The engine returned an invalid terminal handoff.");
  }
  return {
    action,
    command: command as [string, ...string[]],
  };
}
