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
            `${record.summary ?? `${record.actor} · ${record.category}`} · ${record.status}${record.durationMs === undefined ? "" : ` · ${record.durationMs}ms`}\n  ${record.command ?? "No shell command"}\n  ${record.mutability} · approval: ${record.approval}${record.reason ? ` · ${record.reason}` : ""}`,
        )
        .join("\n") || "No operations recorded in this session."
    );
  }
}
