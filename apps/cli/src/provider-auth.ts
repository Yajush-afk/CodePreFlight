import { spawn } from "node:child_process";

export interface ProviderAuthPlan {
  command: string;
  args: string[];
  experimental: boolean;
  warning?: string;
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
