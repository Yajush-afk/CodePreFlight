import { describe, expect, it, vi } from "vitest";
import { CommandRegistry } from "./command-registry.js";
import { SuggestionCoordinator } from "./suggestion-coordinator.js";

describe("command guidance", () => {
  it("uses single-token commands and ranks model before mode", () => {
    const registry = new CommandRegistry();
    expect(registry.definitions.every((item) => !/\s/.test(item.name))).toBe(
      true,
    );
    expect(
      registry
        .suggestions("/mo")
        .slice(0, 2)
        .map((item) => item.value),
    ).toEqual(["model", "mode"]);
    expect(registry.correction("/review commit abc")).toBe("/reviewcommit abc");
    expect(registry.help()).not.toContain("/scan full");
  });
  it("loads arguments once, filters by context, and invalidates", async () => {
    const load = vi.fn(async () => [
      {
        value: "abc",
        label: "abc",
        context: "Fix authentication",
        completion: "/reviewcommit abc",
      },
    ]);
    const coordinator = new SuggestionCoordinator(new CommandRegistry(), load);
    expect(await coordinator.suggest("/reviewcommit auth")).toHaveLength(1);
    await coordinator.suggest("/reviewcommit abc");
    expect(load).toHaveBeenCalledTimes(1);
    coordinator.invalidate();
    await coordinator.suggest("/reviewcommit ");
    expect(load).toHaveBeenCalledTimes(2);
  });
});
