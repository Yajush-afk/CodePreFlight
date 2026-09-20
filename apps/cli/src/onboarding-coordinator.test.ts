import { describe, expect, it } from "vitest";
import {
  OnboardingCoordinator,
  type SetupProvider,
} from "./onboarding-coordinator.js";

const ready: SetupProvider = {
  id: "codex",
  installation: "installed",
  authentication: "authenticated",
  model: "ready",
  model_name: "model",
  availability: "ready",
  readiness: { state: "ready", invocationVerified: true },
  variant_name: "medium",
};

describe("readiness-driven onboarding", () => {
  it("starts at provider selection and resumes only the failed capability", () => {
    const setup = new OnboardingCoordinator();
    expect(setup.next(undefined, false)?.action).toBe("providers");
    expect(setup.next(ready, true)).toBeUndefined();
    expect(
      setup.next({ ...ready, authentication: "required" }, true)?.action,
    ).toBe("login");
    expect(setup.next({ ...ready, model: "missing" }, true)?.action).toBe(
      "model",
    );
  });
  it("allows optional steps to be skipped without marking the provider verified", () => {
    const setup = new OnboardingCoordinator();
    const provider = {
      ...ready,
      readiness: { state: "ready", invocationVerified: false },
      variant_name: undefined,
    };
    expect(setup.next(provider, false)?.action).toBe("variant");
    setup.skip(provider, "variant");
    expect(setup.next(provider, false)?.action).toBe("test");
    setup.skip(provider, "test");
    expect(setup.next(provider, false)?.action).toBe("trust");
    expect(provider.readiness.invocationVerified).toBe(false);
  });
});
