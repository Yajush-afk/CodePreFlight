import type {
  SessionHeader,
  TranscriptEntry,
  SessionOverlayItem,
} from "./session-controller.js";

export class WorkspacePresenter {
  navigationItems(
    action: "tree" | "branches" | "commits",
    items: Array<Record<string, unknown>>,
  ): SessionOverlayItem[] {
    const presenters = {
      tree: this.fileItem,
      branches: this.branchItem,
      commits: this.commitItem,
    };
    return items.map((item) => presenters[action](item));
  }
  private fileItem(item: Record<string, unknown>): SessionOverlayItem {
    const path = String(item.path ?? "");
    return {
      label: `${String(item.status ?? "clean").padEnd(16)} ${path}`,
      value: path,
      action: { kind: "file", value: path },
    };
  }
  private branchItem(item: Record<string, unknown>): SessionOverlayItem {
    const branch = String(item.name ?? "");
    return {
      label: `${item.current ? "●" : "○"} ${branch} · ${String(item.subject ?? "")}`,
      value: branch,
      action: { kind: item.current ? "close" : "branch", value: branch },
    };
  }
  private commitItem(item: Record<string, unknown>): SessionOverlayItem {
    const revision = String(item.oid ?? "");
    return {
      label: `${item.merge ? "merge " : ""}${String(item.shortOid ?? "")} · ${String(item.subject ?? "")}`,
      value: revision,
      action: { kind: "commit", value: revision },
    };
  }
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
    if (!header)
      return "Open Preflight inside a Git repository; /status retries inspection.";
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
