export function printValue(value: unknown, json: boolean): void {
  if (json) {
    process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
    return;
  }
  process.stdout.write(`${formatHuman(value)}\n`);
}

interface ReviewView {
  status?: "completed" | "failed";
  failure?: { code?: string; message?: string; attempts?: number };
  summary?: string;
  blocking?: boolean;
  cache_hit?: boolean;
  rejected_findings?: number;
  blast_radius?: Array<{
    path?: string;
    relationship?: string;
    confidence?: string;
    evidence?: string;
  }>;
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
  if (review.status === "failed") {
    process.stdout.write(
      `Review failed: ${review.failure?.message ?? review.failure?.code ?? "invalid provider response"}` +
        `${review.failure?.attempts ? ` (after ${review.failure.attempts} attempts)` : ""}\n`,
    );
  }
  if (review.cache_hit)
    process.stdout.write("Cache: hit (repository content was not persisted)\n");
  process.stdout.write(
    `Summary: ${review.summary ?? "No summary returned."}\n`,
  );
  const checks = review.context?.checks ?? [];
  if (checks.length) {
    process.stdout.write(
      `Checks: ${checks.map((check) => `${check.name}: ${check.status}`).join(" · ")}\n`,
    );
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
      process.stdout.write(
        `Suggested tests: ${finding.suggested_tests.join("; ")}\n`,
      );
    }
  }
  if (review.blocking) process.stdout.write("\nReview policy: blocking\n");
  if (review.blast_radius?.length) {
    process.stdout.write("\nPotential blast radius\n");
    for (const item of review.blast_radius) {
      process.stdout.write(
        `- ${item.path}: ${item.relationship} (${item.confidence}) · ${item.evidence}\n`,
      );
    }
  }
}

export function printExplanation(value: unknown): void {
  const response = value as {
    mode?: string;
    result?: {
      summary?: string;
      answer?: string;
      before?: string;
      after?: string;
      side_effects?: string[];
      uncertainty?: string;
      evidence?: Array<{ path?: string; line?: number; commit?: string }>;
    };
  };
  const result = response.result ?? {};
  process.stdout.write(
    `${result.summary ?? result.answer ?? "No explanation returned."}\n`,
  );
  if (result.before) process.stdout.write(`\nBefore\n${result.before}\n`);
  if (result.after) process.stdout.write(`\nAfter\n${result.after}\n`);
  if (result.side_effects?.length) {
    process.stdout.write(
      `\nPotential side effects\n${result.side_effects.map((item) => `- ${item}`).join("\n")}\n`,
    );
  }
  if (result.evidence?.length) {
    process.stdout.write(
      `\nEvidence\n${result.evidence
        .map(
          (item) =>
            `- ${item.path}${item.line ? `:${item.line}` : ""}${item.commit ? ` @ ${item.commit}` : ""}`,
        )
        .join("\n")}\n`,
    );
  }
  if (result.uncertainty)
    process.stdout.write(`\nUncertainty: ${result.uncertainty}\n`);
}

export function printPanel(value: unknown): void {
  const panel = value as {
    results?: Array<{ provider?: string; review?: ReviewView; error?: string }>;
    consensus?: Array<{
      providers?: string[];
      agreement?: number;
      severity_conflict?: boolean;
      findings?: ReviewView["findings"];
    }>;
  };
  for (const result of panel.results ?? []) {
    process.stdout.write(`\nProvider: ${result.provider}\n`);
    if (result.error) process.stdout.write(`Error: ${result.error}\n`);
    else if (result.review) printReview(result.review);
  }
  process.stdout.write("\nCross-provider comparison\n");
  for (const group of panel.consensus ?? []) {
    const finding = group.findings?.[0];
    process.stdout.write(
      `- ${finding?.title ?? "Finding"}: ${group.agreement} provider(s) ` +
        `[${group.providers?.join(", ")}]${group.severity_conflict ? " · severity conflict" : ""}\n`,
    );
  }
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
