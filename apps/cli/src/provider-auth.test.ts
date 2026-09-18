import { describe, expect, it } from "vitest";
import { providerAuthPlan } from "./provider-auth.js";

describe("providerAuthPlan", () => {
  it("delegates Codex authentication to the official CLI", () => {
    expect(providerAuthPlan("codex")).toEqual({
      command: "codex",
      args: ["login"],
      experimental: false,
    });
  });

  it("marks Claude subscription login experimental", () => {
    expect(providerAuthPlan("claude")).toMatchObject({
      command: "claude",
      args: ["login"],
      experimental: true,
    });
  });

  it("rejects providers without an interactive login", () => {
    expect(() => providerAuthPlan("ollama")).toThrow(
      "Ollama does not require authentication",
    );
  });
});
