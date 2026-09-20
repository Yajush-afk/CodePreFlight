export interface SetupProvider {
  id?: string;
  name?: string;
  installation?: string;
  authentication?: string;
  model?: string;
  model_name?: string | null;
  variant_name?: string | null;
  invocation?: string;
  availability?: string;
  detail?: string;
  readiness?: { state: string; invocationVerified: boolean };
}
export interface SetupStep {
  title: string;
  body: string;
  action: string;
  label: string;
  optional?: boolean;
}

export class OnboardingCoordinator {
  active = false;
  private skipped = new Set<string>();
  skip(provider: SetupProvider | undefined, step: string): void {
    this.skipped.add(`${provider?.id}:${provider?.model_name}:${step}`);
  }
  next(
    provider: SetupProvider | undefined,
    trusted: boolean,
  ): SetupStep | undefined {
    if (!provider)
      return {
        title: "Choose your reviewer",
        body: "Reuse an installed provider CLI or configure an API provider. Local Git features work without AI.",
        action: "providers",
        label: "Choose provider",
      };
    if (provider.installation === "missing")
      return {
        title: "Provider installation needed",
        body: `${provider.name ?? provider.id} is not installed. Install its official CLI outside Preflight, then refresh.`,
        action: "providers",
        label: "Choose another provider",
      };
    const authentication = this.authenticationStep(provider);
    if (authentication) return authentication;
    if (["missing", "selection_required"].includes(provider.model ?? ""))
      return {
        title: "Choose an available model",
        body: "Choose a model you can access. For Ollama, install missing models outside Preflight first.",
        action: "model",
        label: "Choose model",
      };
    const runtime = this.runtimeStep(provider);
    if (runtime) return runtime;
    return this.optionalSteps(provider, trusted);
  }

  private runtimeStep(provider: SetupProvider): SetupStep | undefined {
    if (
      provider.readiness?.state === "unavailable" ||
      provider.invocation === "incompatible"
    )
      return {
        title: "Provider update required",
        body:
          provider.detail ??
          "The installed CLI is incompatible. Update it, then refresh.",
        action: "providers",
        label: "Choose another provider",
      };
    if ((provider.readiness?.state ?? provider.availability) !== "ready")
      return {
        title: "Provider needs attention",
        body:
          provider.detail ?? "Inspect provider configuration before reviewing.",
        action: "providers",
        label: "Inspect providers",
      };
    return undefined;
  }

  private authenticationStep(provider: SetupProvider): SetupStep | undefined {
    if (["required", "unknown"].includes(provider.authentication ?? ""))
      return {
        title: "Sign in to your provider",
        body:
          provider.id === "openai-compatible"
            ? "Set the configured API-key environment variable in your shell and restart Preflight. Never paste credentials into this session."
            : "Provider-owned login may affect the account shared with other applications. Preflight never logs you out.",
        action: provider.id === "openai-compatible" ? "providers" : "login",
        label:
          provider.id === "openai-compatible"
            ? "Choose another provider"
            : "Open official login",
      };
    return undefined;
  }

  private optionalSteps(
    provider: SetupProvider,
    trusted: boolean,
  ): SetupStep | undefined {
    if (
      !provider.variant_name &&
      !this.skipped.has(`${provider.id}:${provider.model_name}:variant`)
    )
      return {
        title: "Reasoning effort (optional)",
        body: "Variants adjust reasoning effort, not service speed. Standard service tier is always used.",
        action: "variant",
        label: "Choose variant",
        optional: true,
      };
    if (
      !provider.readiness?.invocationVerified &&
      !this.skipped.has(`${provider.id}:${provider.model_name}:test`)
    )
      return {
        title: "Test your reviewer (optional)",
        body: "A synthetic test sends no repository code, but may consume provider usage. Full scans and automation require successful invocation evidence.",
        action: "test",
        label: "Review test confirmation",
        optional: true,
      };
    if (!trusted)
      return {
        title: "Review repository trust",
        body: "Trust permits configured checks and local provider CLIs. Inspect the effective configuration before approving.",
        action: "trust",
        label: "Inspect trust request",
      };
    return undefined;
  }
}
