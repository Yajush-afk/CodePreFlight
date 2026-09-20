import type { SessionHeader, TranscriptEntry } from "./session-controller.js";

export class WorkspacePresenter {
  transcript(
    entries: TranscriptEntry[],
    width: number,
    height: number,
    offset = 0,
  ): string[] {
    const lines = entries.flatMap((entry) => {
      const prefix =
        entry.kind === "user" ? "You › " : entry.kind === "error" ? "× " : "";
      return [
        entry.title ? `${prefix}${entry.title}` : undefined,
        ...entry.body
          .split("\n")
          .map((line) => (!entry.title ? `${prefix}${line}` : line)),
        "",
      ].filter((line): line is string => line !== undefined);
    });
    const wrapped = lines.flatMap((line) => {
      if (!line) return [""];
      const chunks: string[] = [];
      const characters = Array.from(line);
      for (
        let index = 0;
        index < characters.length;
        index += Math.max(10, width)
      )
        chunks.push(
          characters.slice(index, index + Math.max(10, width)).join(""),
        );
      return chunks;
    });
    const end = Math.max(height, wrapped.length - offset);
    return wrapped.slice(Math.max(0, end - height), end);
  }
  recommendation(header?: SessionHeader): string {
    if (!header) return "Open Preflight inside a Git repository; /status retries inspection.";
    if (header.providerAvailability !== "ready")
      return "Set up your reviewer with /provider; local Git features remain available.";
    if (header.conflicts) return "Resolve Git conflicts before reviewing.";
    if (header.staged)
      return "Ready to review staged changes? Type /reviewstaged.";
    if (header.unstaged || header.untracked)
      return "Inspect your changes with /files.";
    return "Choose /review to inspect a commit or branch.";
  }
}
