import {
  CommandRegistry,
  relevance,
  type Suggestion,
} from "./command-registry.js";

export class SuggestionCoordinator {
  private cache = new Map<string, Promise<Suggestion[]>>();
  constructor(
    private registry: CommandRegistry,
    private load: (command: string) => Promise<Suggestion[]>,
  ) {}
  invalidate(): void {
    this.cache.clear();
  }
  async suggest(input: string): Promise<Suggestion[]> {
    if (!input.startsWith("/")) return [];
    const parsed = this.registry.parse(input);
    if (!input.includes(" ") || !parsed.definition?.argument)
      return this.registry.suggestions(input);
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
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map(({ item }) => item);
  }
}
