import type { FindingView } from "./findings-presenter.js";

export interface ReviewView {
  status?: string;
  summary?: string;
  findings?: FindingView[];
  blocking?: boolean;
}

export type QuestionContextResult =
  | { payload: Record<string, unknown>; error?: never }
  | { payload?: never; error: string };

export class ReviewConversationContext {
  private activeReview?: ReviewView;
  private activeTarget?: string;
  private selectedIndex?: number;

  get review(): ReviewView | undefined {
    return this.activeReview;
  }

  get target(): string | undefined {
    return this.activeTarget;
  }

  get findings(): FindingView[] {
    return this.activeReview?.findings ?? [];
  }

  activate(review: ReviewView, target: string): void {
    this.activeReview = review;
    this.activeTarget = target;
    this.selectedIndex = undefined;
  }

  clear(): void {
    this.activeReview = undefined;
    this.activeTarget = undefined;
    this.selectedIndex = undefined;
  }

  clearSelection(): void {
    this.selectedIndex = undefined;
  }

  select(index: number): FindingView | undefined {
    const finding = this.findings[index - 1];
    if (finding) this.selectedIndex = index;
    return finding;
  }

  questionPayload(question: string): QuestionContextResult {
    const resolved = this.resolveFindings(question);
    if ("error" in resolved) return resolved;
    const target = this.activeReview
      ? "review"
      : /branch|commit/i.test(question)
        ? "branch"
        : "repository";
    return {
      payload: {
        mode: "ask",
        question,
        target,
        reviewContext: this.activeReview
          ? {
              target: this.activeTarget ?? "staged",
              summary: this.activeReview.summary ?? "",
              findings: resolved.findings,
            }
          : undefined,
      },
    };
  }

  private resolveFindings(
    question: string,
  ): { findings: Array<FindingView & { index: number }> } | { error: string } {
    const references = this.findingReferences(question);
    if (!references.length && this.selectedIndex)
      references.push(this.selectedIndex);
    if (references.length && !this.activeReview)
      return { error: "No review is active. Run a review first." };
    const missing = references.filter((index) => !this.findings[index - 1]);
    if (missing.length)
      return {
        error: `Finding ${missing.join(", ")} is not in the active review.`,
      };
    const findings = references.length
      ? references.map((index) => ({ ...this.findings[index - 1], index }))
      : this.findings
          .slice(0, 10)
          .map((finding, index) => ({ ...finding, index: index + 1 }));
    return { findings };
  }

  private findingReferences(question: string): number[] {
    const match = question.match(
      /\bfindings?\s+((?:\d+\s*(?:(?:,|and|&|to|-)\s*\d+\s*)*)+)/i,
    );
    if (!match) return [];
    return [...new Set((match[1].match(/\d+/g) ?? []).map(Number))];
  }
}
