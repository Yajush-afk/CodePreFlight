export interface CommandDefinition {
  name: string;
  description: string;
  argument?: string;
}
export interface Suggestion {
  value: string;
  label: string;
  context?: string;
  completion: string;
  argument?: boolean;
  disabled?: string;
}

const DEFINITIONS: Array<[string, string, string?]> = [
  ["status", "Refresh repository status"],
  ["files", "Browse repository files"],
  ["graph", "Show local commit graph"],
  ["branches", "Browse local branches"],
  ["commits", "Browse reachable commits"],
  ["review", "Choose what to review"],
  ["findings", "Explore findings in the active review", "filter"],
  ["scanfull", "Preview a full scan of the clean base branch"],
  ["provider", "Set up your reviewer"],
  ["model", "Choose review model"],
  ["variant", "Choose reasoning effort"],
  ["mode", "Choose review cadence"],
  ["activity", "Inspect commands and outcomes"],
  ["jobs", "Show background reviews"],
  ["commit", "Review and prepare a commit"],
  ["pr", "Inspect an existing PR"],
  ["help", "Show commands and guidance"],
  ["clear", "Clear conversation"],
  ["quit", "Exit"],
  ["reviewstaged", "Review staged changes"],
  ["reviewworking", "Review all uncommitted changes"],
  ["reviewbranch", "Review the branch"],
  ["reviewcommit", "Review a reachable commit", "commit"],
  ["reviewpr", "Deep PR review"],
  ["reviewmergedpr", "Review a merged GitHub PR", "number-or-url"],
  ["providerlogin", "Open provider-owned login", "provider"],
  ["providertest", "Test with synthetic code", "provider"],
  ["providerswitch", "Select a provider", "provider"],
  ["automationgrant", "Approve scoped automation"],
  ["automationrevoke", "Revoke automation"],
  ["switchbranch", "Preview a safe branch switch", "branch"],
  ["file", "Preview a file", "path"],
];

const ALIASES: Record<string, string> = {
  "review staged": "reviewstaged",
  "review branch": "reviewbranch",
  "review commit": "reviewcommit",
  "review pr": "reviewpr",
  "scan full": "scanfull",
  "provider login": "providerlogin",
  "provider test": "providertest",
  "provider use": "providerswitch",
  "automation grant": "automationgrant",
  "automation revoke": "automationrevoke",
  tree: "files",
  switch: "switchbranch",
  varient: "variant",
  "model set": "model",
  "variant set": "variant",
  "mode set": "mode",
};

export function relevance(value: string, query: string): number {
  const text = value.toLowerCase(),
    search = query.toLowerCase();
  if (!search) return 4;
  if (text === search) return 0;
  if (text.startsWith(search)) return 1;
  if (text.split(/[\s/_-]+/).some((token) => token.startsWith(search)))
    return 2;
  let index = 0;
  for (const char of text) if (char === search[index]) index++;
  return index === search.length ? 3 : 99;
}

export class CommandRegistry {
  readonly definitions: CommandDefinition[] = DEFINITIONS.map(
    ([name, description, argument]) => ({ name, description, argument }),
  );
  correction(input: string): string | undefined {
    const value = input.slice(1);
    const alias = Object.keys(ALIASES).find(
      (key) => value === key || value.startsWith(`${key} `),
    );
    return alias ? `/${ALIASES[alias]}${value.slice(alias.length)}` : undefined;
  }
  parse(input: string): {
    name: string;
    argument: string;
    definition?: CommandDefinition;
  } {
    const space = input.indexOf(" ");
    const name = input.slice(1, space < 0 ? undefined : space);
    return {
      name,
      argument: space < 0 ? "" : input.slice(space + 1).trim(),
      definition: this.definitions.find((item) => item.name === name),
    };
  }
  suggestions(input: string): Suggestion[] {
    return this.definitions
      .map((item, index) => ({
        item,
        index,
        rank: relevance(item.name, input.slice(1)),
      }))
      .filter((item) => item.rank < 99)
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map(({ item }) => ({
        value: item.name,
        label: `/${item.name}`,
        context: item.description,
        completion: `/${item.name}${item.argument ? " " : ""}`,
        argument: Boolean(item.argument),
      }));
  }
  help(): string {
    return this.definitions
      .map(
        (item) =>
          `/${item.name}${item.argument ? ` <${item.argument}>` : ""} — ${item.description}`,
      )
      .join("\n");
  }
}
