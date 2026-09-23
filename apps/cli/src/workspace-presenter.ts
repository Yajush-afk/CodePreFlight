import type {
  SessionHeader,
  TranscriptEntry,
  SessionOverlayItem,
} from "./session-controller.js";

export interface TranscriptLine {
  text: string;
  code: boolean;
}

export class WorkspacePresenter {
  scanApproval(manifest: Record<string, unknown>): string {
    const files = (manifest.files ?? []) as Array<Record<string, unknown>>;
    return [
      `${String(manifest.eligibleFiles)} eligible files · ${String(manifest.excludedFiles)} excluded · ${String(manifest.redactions)} redactions`,
      `${Number(manifest.totalSelectedCharacters ?? 0).toLocaleString()} selected characters · approximately ${String(manifest.providerRequests)} provider requests (repair may add requests)`,
      `Concurrent review requests: up to ${String(manifest.parallelRequests ?? 1)}`,
      `Reviewer: ${String(manifest.provider)} · ${String(manifest.model)} · ${String(manifest.variant ?? "default")}`,
      `Destination: ${String(manifest.destination)} (${String(manifest.privacyCategory)})`,
      `Planned checks: ${JSON.stringify(manifest.plannedChecks)}`,
      `Cache available: ${manifest.cacheHit ? "yes" : "no"}`,
      `Repository: ${String(manifest.repositoryHead)} · plan ${String(manifest.planFingerprint)}`,
      "This approval is only for this exact full scan.",
      "Sources (PgUp/PgDn to inspect):",
      ...files.map(
        (file) =>
          `${String(file.status)} · ${String(file.path)} · ${String(file.reason)}`,
      ),
    ].join("\n");
  }
  viewport(
    text: string,
    width: number,
    height: number,
    offset: number,
  ): string {
    const lines = text.split("\n").flatMap((line) => {
      const characters = Array.from(line);
      const rows: string[] = [];
      for (
        let index = 0;
        index < characters.length;
        index += Math.max(10, width)
      )
        rows.push(
          characters.slice(index, index + Math.max(10, width)).join(""),
        );
      return rows.length ? rows : [""];
    });
    const start = Math.min(offset, Math.max(0, lines.length - height));
    return lines.slice(start, start + height).join("\n");
  }
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
  ): TranscriptLine[] {
    const lines = entries.flatMap((entry) => {
      const prefix =
        entry.kind === "user" ? "You › " : entry.kind === "error" ? "× " : "";
      let fenced = false;
      const body = entry.body.split("\n").flatMap((line) => {
        if (line.trim().startsWith("```")) {
          fenced = !fenced;
          return [];
        }
        return [
          { text: !entry.title ? `${prefix}${line}` : line, code: fenced },
        ];
      });
      return [
        ...(entry.title
          ? [{ text: `${prefix}${entry.title}`, code: false }]
          : []),
        ...body,
        { text: "", code: false },
      ];
    });
    const wrapped = lines.flatMap((line) => {
      if (!line.text) return [line];
      const chunks: TranscriptLine[] = [];
      const characters = Array.from(line.text);
      for (
        let index = 0;
        index < characters.length;
        index += Math.max(10, width)
      )
        chunks.push({
          text: characters.slice(index, index + Math.max(10, width)).join(""),
          code: line.code,
        });
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
