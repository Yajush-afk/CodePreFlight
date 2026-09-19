import { describe, expect, it } from "vitest";
import { providerAuthPlan, providerAuthStatusPlan } from "./provider-auth.js";

describe("providerAuthPlan", () => {
  it("delegates Codex authentication to the official CLI", () => {
    expect(providerAuthPlan("codex")).toEqual({
      command: "codex",
      args: ["login"],
      experimental: false,
    });
  });

  it("verifies authentication with the provider-owned status command", () => {
    expect(providerAuthStatusPlan("codex")).toEqual({
      command: "codex",
      args: ["login", "status"],
    });
    expect(providerAuthStatusPlan("opencode")).toEqual({
      command: "opencode",
      args: ["auth", "list"],
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
