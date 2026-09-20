import {
  CommandRegistry,
  relevance,
  type Suggestion,
} from "./command-registry.js";

export class SuggestionCoordinator {
  private cache = new Map<string, Promise<Suggestion[]>>();
  private recent = new Map<string, number>();
  private sequence = 0;
  constructor(
    private registry: CommandRegistry,
    private load: (command: string) => Promise<Suggestion[]>,
  ) {}
  invalidate(): void {
    this.cache.clear();
  }
  record(input: string): void {
    this.recent.set(input.trim(), ++this.sequence);
  }
  clear(): void {
    this.invalidate();
    this.recent.clear();
  }
  private recency(completion: string): number {
    return this.recent.get(completion.trim()) ?? 0;
  }
  async suggest(input: string): Promise<Suggestion[]> {
    if (!input.startsWith("/")) return [];
    const parsed = this.registry.parse(input);
    if (!input.includes(" ") || !parsed.definition?.argument)
      return this.commandSuggestions(input);
    let pending = this.cache.get(parsed.name);
    if (!pending) {
      pending = this.load(parsed.name).catch((error) => {
        this.cache.delete(parsed.name);
        throw error;
      });
      this.cache.set(parsed.name, pending);
    }
    const items = await pending;
    return items
      .map((item, index) => ({
        item,
        index,
        rank: Math.min(
          relevance(item.value, parsed.argument),
          Math.max(2, relevance(item.context ?? "", parsed.argument)),
        ),
      }))
      .filter((item) => item.rank < 99)
      .sort(
        (a, b) =>
          a.rank - b.rank ||
          this.recency(b.item.completion) - this.recency(a.item.completion) ||
          a.index - b.index,
      )
      .map(({ item }) => item);
  }
  private commandSuggestions(input: string): Suggestion[] {
    return this.registry.suggestions(input).sort((a, b) => {
      const rank =
        relevance(a.value, input.slice(1)) - relevance(b.value, input.slice(1));
      if (rank) return rank;
      // Explicit product ordering: /mo always prefers /model over /mode.
      if (
        input === "/mo" &&
        ["model", "mode"].includes(a.value) &&
        ["model", "mode"].includes(b.value)
      )
        return Number(a.value === "mode") - Number(b.value === "mode");
      return this.recency(b.completion) - this.recency(a.completion);
    });
  }
}
