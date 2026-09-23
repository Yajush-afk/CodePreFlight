export interface OperationRecord {
  id: string;
  actor: "Preflight" | "Git" | "Check" | "Provider";
  category: string;
  command?: string;
  status: string;
  mutability: string;
  approval: string;
  durationMs?: number;
  exitCode?: number;
  reason?: string;
  summary?: string;
}

export function describeRecentOperation(
  record: OperationRecord,
): string | undefined {
  if (!record.command || (record.actor !== "Git" && record.actor !== "Check"))
    return undefined;
  const outcome =
    record.status === "running"
      ? "is running"
      : record.status === "completed" || record.status === "passed"
        ? "ran"
        : record.status === "recommended" || record.status === "skipped"
          ? "skipped"
          : "finished";
  return `Preflight ${outcome} ${record.command}${record.status === "running" ? "" : ` · ${record.status}`}`;
}

export class ActivityStore {
  private records = new Map<string, OperationRecord>();

  update(record: OperationRecord): void {
    this.records.set(record.id, record);
    if (this.records.size > 500)
      this.records.delete(this.records.keys().next().value!);
  }

  cancel(): void {
    for (const [id, record] of this.records) {
      if (record.status === "running")
        this.records.set(id, { ...record, status: "cancelled" });
    }
  }

  clear(): void {
    this.records.clear();
  }

  describe(): string {
    return (
      Array.from(this.records.values())
        .map(
          (record) =>
            `${record.summary ?? this.label(record)} · ${record.status}${record.durationMs === undefined ? "" : ` · ${record.durationMs}ms`}\n  ${record.command ?? "No shell command"}\n  ${record.mutability} · approval: ${record.approval}${record.reason ? ` · ${record.reason}` : ""}`,
        )
        .join("\n") || "No operations recorded in this session."
    );
  }

  private label(record: OperationRecord): string {
    if (record.actor === "Git") return "Preflight checked Git state";
    if (record.actor === "Check") return "Preflight ran a repository check";
    if (record.actor === "Provider")
      return "Preflight requested review analysis";
    return `Preflight ${record.category}`;
  }
}
