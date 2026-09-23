export interface FindingView {
  id?: string;
  severity?: string;
  title?: string;
  explanation?: string;
  impact?: string;
  confidence?: string;
  verification?: string;
  verification_notes?: string[];
  recommendation?: string;
  suggested_tests?: string[];
  evidence?: Array<{ path?: string; start_line?: number; end_line?: number }>;
}

const ORDER: Record<string, number> = {
  critical: 0,
  warning: 1,
  suggestion: 2,
  informational: 3,
};

export class FindingsPresenter {
  summary(findings: FindingView[]): string {
    const count = (severity: string): number =>
      findings.filter((item) => item.severity === severity).length;
    const verified = findings.filter(
      (item) => item.verification !== "verified",
    ).length;
    const partial = findings.filter(
      (item) => item.verification === "partially_verified",
    ).length;
    return `${findings.length} findings · ${count("critical")} critical · ${count("warning")} warnings · ${count("suggestion")} suggestions\n${verified} verified · ${partial} partially verified`;
  }

  rows(
    findings: FindingView[],
    filter = "all",
  ): Array<{ index: number; label: string }> {
    return findings
      .map((finding, index) => ({ finding, index: index + 1 }))
      .filter(({ finding }) => filter === "all" || finding.severity === filter)
      .sort(
        (a, b) =>
          (ORDER[a.finding.severity ?? "informational"] ?? 4) -
          (ORDER[b.finding.severity ?? "informational"] ?? 4),
      )
      .map(({ finding, index }) => {
        const evidence = finding.evidence?.[0];
        const path = evidence?.path ?? "no location";
        const place = `${path.length > 30 ? `…${path.slice(-29)}` : path}:${evidence?.start_line ?? "?"}`;
        const title = finding.title ?? "Finding";
        return {
          index,
          label: `${String(index).padStart(2)}  ${String(
            finding.severity ?? "info",
          )
            .toUpperCase()
            .padEnd(
              10,
            )} ${title.length > 45 ? `${title.slice(0, 44)}…` : title}  · ${place}`,
        };
      });
  }

  detail(index: number, finding: FindingView): string {
    const locations = (finding.evidence ?? [])
      .map(
        (item) =>
          `${item.path ?? "unknown"}:${item.start_line ?? "?"}${item.end_line && item.end_line !== item.start_line ? `–${item.end_line}` : ""}`,
      )
      .join("\n");
    return [
      `#${index} · ${String(finding.severity ?? "info").toUpperCase()} · ${finding.verification ?? "unverified"} · confidence ${finding.confidence ?? "unspecified"}`,
      finding.title ?? "Finding",
      "",
      `What happened\n${finding.explanation ?? "No explanation supplied."}`,
      `Why it matters\n${finding.impact ?? "No impact supplied."}`,
      `Evidence\n${locations || "No location supplied."}`,
      `What to inspect\n${finding.recommendation ?? "Inspect the cited code."}`,
      ...(finding.suggested_tests?.length
        ? [`Suggested tests\n${finding.suggested_tests.join("\n")}`]
        : []),
      ...(finding.verification_notes?.length
        ? [`Verification notes\n${finding.verification_notes.join("\n")}`]
        : []),
      "",
      "Ask a follow-up below, or press Esc to return to the transcript.",
    ].join("\n\n");
  }
}
