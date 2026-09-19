import { spawn } from "node:child_process";

export interface ProviderAuthPlan {
  command: string;
  args: string[];
  experimental: boolean;
  warning?: string;
}

export interface ProviderAuthStatusPlan {
  command: string;
  args: string[];
}

const AUTH_PLANS: Record<string, ProviderAuthPlan> = {
  codex: {
    command: "codex",
    args: ["login"],
    experimental: false,
  },
  opencode: {
    command: "opencode",
    args: ["auth", "login"],
    experimental: false,
  },
  claude: {
    command: "claude",
    args: ["login"],
    experimental: true,
    warning:
      "Claude CLI integration is experimental. Confirm the active billing method in Claude before use.",
  },
};

export function providerAuthPlan(provider: string): ProviderAuthPlan {
  if (provider === "ollama") {
    throw new Error(
      "Ollama does not require authentication; install a model instead",
    );
  }
  if (provider === "openai-compatible") {
    throw new Error(
      "OpenAI-compatible providers use an environment-variable API key and have no interactive login",
    );
  }
  const plan = AUTH_PLANS[provider];
  if (!plan) throw new Error(`Unknown provider: ${provider}`);
  return plan;
}

export async function loginProvider(provider: string): Promise<void> {
  const plan = providerAuthPlan(provider);
  await runInteractiveProviderCommand(plan);
  await verifyProviderAuthentication(provider);
}

export function providerAuthStatusPlan(
  provider: string,
): ProviderAuthStatusPlan {
  const plans: Record<string, ProviderAuthStatusPlan> = {
    codex: { command: "codex", args: ["login", "status"] },
    opencode: { command: "opencode", args: ["auth", "list"] },
    claude: { command: "claude", args: ["auth", "status"] },
  };
  const plan = plans[provider];
  if (!plan) throw new Error(`Provider ${provider} has no login status check`);
  return plan;
}

export async function verifyProviderAuthentication(
  provider: string,
): Promise<void> {
  const plan = providerAuthStatusPlan(provider);
  const result = await new Promise<{
    code: number | null;
    output: string;
  }>((resolve, reject) => {
    const child = spawn(plan.command, plan.args, {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk: Buffer | string) => {
      output += chunk.toString();
    });
    child.stderr.on("data", (chunk: Buffer | string) => {
      output += chunk.toString();
    });
    child.once("error", reject);
    child.once("exit", (code) => resolve({ code, output }));
  });
  const clean = result.output.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
  const authenticated =
    result.code === 0 &&
    (provider !== "opencode" || /^\s*[●•]\s+\S+/m.test(clean));
  if (!authenticated) {
    throw new Error(
      `${provider} login completed, but the provider did not report an authenticated account`,
    );
  }
}

export function ollamaPullPlan(model: string): ProviderAuthPlan {
  if (!model.trim()) throw new Error("An Ollama model name is required");
  return {
    command: "ollama",
    args: ["pull", model.trim()],
    experimental: false,
  };
}

export async function runInteractiveProviderCommand(
  plan: ProviderAuthPlan,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const child = spawn(plan.command, plan.args, { stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (code === 0) resolve();
      else
        reject(
          new Error(
            `${plan.command} login exited with ${signal ?? `code ${String(code)}`}`,
          ),
        );
    });
  });
}
