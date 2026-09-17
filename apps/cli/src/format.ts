export function printValue(value: unknown, json: boolean): void {
  if (json) {
    process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${formatHuman(value)}\n`);
}

interface ReviewView {
  summary?: string;
  blocking?: boolean;
  rejected_findings?: number;
  provider?: { name?: string };
  findings?: Array<{
    severity?: string;
    title?: string;
    impact?: string;
    confidence?: string;
    verification?: string;
    recommendation?: string;
    evidence?: Array<{ path?: string; start_line?: number; end_line?: number }>;
    suggested_tests?: string[];
  }>;
  context?: { checks?: Array<{ name?: string; status?: string }> };
}

export function printReview(value: unknown): void {
  const review = value as ReviewView;
  process.stdout.write(`Provider: ${review.provider?.name ?? "unknown"}\n`);
  process.stdout.write(`Summary: ${review.summary ?? "No summary returned."}\n`);
  const checks = review.context?.checks ?? [];
  if (checks.length) {
    process.stdout.write(`Checks: ${checks.map((check) => `${check.name}: ${check.status}`).join(" · ")}\n`);
  }
  const findings = review.findings ?? [];
  process.stdout.write(
    `Findings: ${findings.length}${review.rejected_findings ? ` · ${review.rejected_findings} rejected during verification` : ""}\n`,
  );
  for (const finding of findings) {
    const evidence = finding.evidence?.[0];
    process.stdout.write(
      `\n${finding.severity?.toUpperCase()} · ${finding.title}\n` +
        `${evidence?.path ?? "unknown"}:${evidence?.start_line ?? "?"}-${evidence?.end_line ?? "?"}\n` +
        `${finding.impact}\n` +
        `Confidence: ${finding.confidence} · Verification: ${finding.verification}\n` +
        `Inspect: ${finding.recommendation}\n`,
    );
    if (finding.suggested_tests?.length) {
      process.stdout.write(`Suggested tests: ${finding.suggested_tests.join("; ")}\n`);
    }
  }
  if (review.blocking) process.stdout.write("\nReview policy: blocking\n");
}

function formatHuman(value: unknown, indent = 0): string {
  if (Array.isArray(value)) {
    return value
      .map((item) => `${" ".repeat(indent)}- ${formatHuman(item, indent + 2)}`)
      .join("\n");
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        if (item && typeof item === "object") {
          return `${" ".repeat(indent)}${key}:\n${formatHuman(item, indent + 2)}`;
        }
        return `${" ".repeat(indent)}${key}: ${String(item)}`;
      })
      .join("\n");
  }
  return `${" ".repeat(indent)}${String(value)}`;
}
