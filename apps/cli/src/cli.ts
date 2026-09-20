#!/usr/bin/env node
import { Command } from "commander";
import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import React from "react";
import { render } from "ink";
import { EngineClient, EngineRequestError } from "./engine-client.js";
import {
  printExplanation,
  printPanel,
  printReview,
  printValue,
} from "./format.js";
import type { EngineEvent } from "./protocol.js";
import {
  loginProvider,
  ollamaPullPlan,
  providerAuthPlan,
  runInteractiveProviderCommand,
} from "./provider-auth.js";
import { App } from "./tui.js";
import { TerminalSession } from "./terminal-session.js";

const program = new Command();
const client = new EngineClient();

function printCommitPreparation(
  preparation: Record<string, unknown>,
  json: boolean,
  proposed = false,
): void {
  if (json) printValue(preparation, true);
  else {
    printReview(preparation.review);
    if (proposed)
      process.stdout.write(`Proposed commit: ${String(preparation.message)}\n`);
  }
}

function printProviderDisclosure(event: EngineEvent): void {
  if (event.event !== "consent_required") return;
  const provider = event.payload?.provider as
    { name?: string; kind?: string } | undefined;
  const manifest = event.payload?.manifest as
    | {
        total_characters?: number;
        redactions?: number;
        secret_scanner?: string;
      }
    | undefined;
  process.stderr.write(
    `Provider disclosure: ${provider?.name ?? "unknown"} (${provider?.kind ?? "unknown"}); ` +
      `destination ${String((event.payload?.destination as { address?: string } | undefined)?.address ?? provider?.name ?? "unknown")}; ` +
      `${manifest?.total_characters ?? event.payload?.contextCharacters ?? 0} context characters; ` +
      `${manifest?.redactions ?? event.payload?.redactions ?? 0} redactions; ` +
      `scanner ${manifest?.secret_scanner ?? "built-in"}.\n`,
  );
}

function printFullScanManifest(event: EngineEvent): void {
  if (event.event !== "consent_required" || !event.payload?.fullScan) return;
  const manifest = event.payload.manifest as Record<string, unknown>;
  process.stderr.write(
    `Full scan manifest: ${String(manifest.eligibleFiles)} eligible; ` +
      `${String(manifest.excludedFiles)} excluded; ${String(manifest.redactions)} redactions; ` +
      `${String(manifest.totalSelectedCharacters)} selected characters; ` +
      `approximately ${String(manifest.providerRequests)} provider requests (repair may add requests); ` +
      `destination ${String(manifest.destination)} (${String(manifest.privacyCategory)}).\n` +
      `Reviewer: ${String(manifest.provider)} · ${String(manifest.model)} · ${String(manifest.variant ?? "default")}\n` +
      `Planned checks: ${JSON.stringify(manifest.plannedChecks)}\n` +
      `Cache available: ${manifest.cacheHit ? "yes" : "no"}\n` +
      `Preview fingerprint: ${String(manifest.planFingerprint)}\n`,
  );
}

program
  .name("preflight")
  .description(
    "Inspect and review repository changes before they enter Git history",
  )
  .version("0.1.0")
  .option("--inline", "use inline terminal output instead of fullscreen")
  .showHelpAfterError();

function engineCommand(
  name: "status" | "doctor" | "providers",
  description: string,
): void {
  program
    .command(name)
    .description(description)
    .option("--json", "print machine-readable JSON")
    .action(async (options: { json?: boolean }) => {
      try {
        const result = await client.request(name, resolve(process.cwd()));
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    });
}

engineCommand("status", "show repository status and detected project context");
engineCommand("doctor", "check the local CodePreFlight environment");
engineCommand("providers", "show detected AI providers");

const scan = program
  .command("scan")
  .description("run guarded repository scans");
scan
  .command("full")
  .description("scan a clean synchronized configured base branch")
  .option("--provider <provider>", "override the configured provider")
  .option("--yes", "approve this full scan after reviewing its manifest")
  .option("--plan <fingerprint>", "fingerprint of the scan preview you approve")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      provider?: string;
      yes?: boolean;
      json?: boolean;
      plan?: string;
    }) => {
      try {
        const result = await client.request(
          "scan",
          resolve(process.cwd()),
          {
            action: "full",
            provider: options.provider,
            fullScanApproved: Boolean(options.yes),
            planFingerprint: options.plan,
          },
          (event) => {
            printFullScanManifest(event);
            if (!options.json && event.event === "scan_progress") {
              process.stderr.write(
                `${String(event.payload?.message ?? "Scanning")}\n`,
              );
            }
          },
        );
        if (options.json) printValue(result, true);
        else printReview(result);
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        if (
          !options.yes &&
          error instanceof EngineRequestError &&
          error.code === "full_scan_confirmation_required"
        ) {
          process.stderr.write(
            `Rerun with --yes --plan ${String(error.details?.planFingerprint ?? "<fingerprint>")} only after reviewing this manifest.\n`,
          );
        }
        process.exitCode = 2;
      }
    },
  );

const automation = program
  .command("automation")
  .description("configure personal review cadence and automation grants");

automation
  .command("status")
  .description("show review mode, grant, and background jobs")
  .option("--json", "print machine-readable JSON")
  .action(async (options: { json?: boolean }) => {
    try {
      const result = await client.request(
        "automation",
        resolve(process.cwd()),
        { action: "status" },
      );
      printValue(result, Boolean(options.json));
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

automation
  .command("mode <mode>")
  .description("preview or select manual, auto, or auto_plus review mode")
  .option("--write", "apply the mode and managed-hook changes")
  .option("--json", "print machine-readable JSON")
  .action(
    async (mode: string, options: { write?: boolean; json?: boolean }) => {
      try {
        const result = await client.request(
          "automation",
          resolve(process.cwd()),
          { action: "configure", mode, write: Boolean(options.write) },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

for (const action of ["grant", "revoke_grant"] as const) {
  automation
    .command(action === "grant" ? "grant" : "revoke")
    .description(
      action === "grant"
        ? "preview or approve the current scoped automation grant"
        : "preview or revoke the repository automation grant",
    )
    .option("--write", "apply the grant change")
    .option("--json", "print machine-readable JSON")
    .action(async (options: { write?: boolean; json?: boolean }) => {
      try {
        const result = await client.request(
          "automation",
          resolve(process.cwd()),
          { action, write: Boolean(options.write) },
        );
        if (action === "grant" && options.write) {
          const resumed =
            (result.resumedJobs as Array<{ id?: string }> | undefined) ?? [];
          for (const job of resumed) {
            if (job.id) launchAutomationWorker(job.id);
          }
        }
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    });
}

function launchAutomationWorker(jobId: string): void {
  const executable = process.argv[1];
  if (!executable) return;
  const worker = spawn(
    process.execPath,
    [executable, "automation", "worker", jobId],
    {
      cwd: process.cwd(),
      detached: true,
      stdio: "ignore",
      env: process.env,
    },
  );
  worker.unref();
}

automation
  .command("event <event>")
  .description(
    "handle a managed launch, refresh, post-commit, or pre-push event",
  )
  .option("--json", "print machine-readable JSON")
  .action(async (event: string, options: { json?: boolean }) => {
    try {
      const result = await client.request(
        "automation",
        resolve(process.cwd()),
        { action: "event", event },
      );
      const job = result.job as
        { id?: string; coalesced?: boolean; status?: string } | undefined;
      if (job?.id && !job.coalesced && job.status === "queued") {
        launchAutomationWorker(job.id);
      }
      if (result.waitingForConsent) {
        process.stderr.write(
          "CodePreflight automation is waiting for an approved repository grant; continuing fail-open.\n",
        );
      }
      if (result.blocking) process.exitCode = 1;
      if (options.json) printValue(result, true);
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

automation
  .command("worker <jobId>", { hidden: true })
  .description("run one bounded queued automation job")
  .action(async (jobId: string) => {
    try {
      await client.request("automation", resolve(process.cwd()), {
        action: "worker",
        jobId,
      });
    } catch {
      process.exitCode = 2;
    }
  });

const workspace = program
  .command("workspace")
  .description(
    "inspect repository files, branches, commits, and pull requests",
  );
for (const action of ["tree", "branches", "commits", "pr"] as const) {
  workspace
    .command(action)
    .description(`show repository ${action}`)
    .option("--json", "print machine-readable JSON")
    .action(async (options: { json?: boolean }) => {
      try {
        const result = await client.request(
          "workspace",
          resolve(process.cwd()),
          { action },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    });
}

program
  .command("switch <branch>")
  .description(
    "preview or execute a guarded switch to an existing local branch",
  )
  .option("--yes", "approve the branch switch after a fresh safety preview")
  .option("--json", "print machine-readable JSON")
  .action(
    async (branch: string, options: { yes?: boolean; json?: boolean }) => {
      try {
        const preview = await client.request(
          "git_action",
          resolve(process.cwd()),
          { action: "switch_preview", branch },
        );
        if (!options.yes) {
          printValue(preview, Boolean(options.json));
          process.stderr.write(
            "Preview only; rerun with --yes to execute the approved switch.\n",
          );
          return;
        }
        if (!preview.allowed) {
          printValue(preview, Boolean(options.json));
          process.exitCode = 2;
          return;
        }
        const result = await client.request(
          "git_action",
          resolve(process.cwd()),
          {
            action: "switch_execute",
            branch,
            approved: true,
            expectedHead: preview.expectedHead,
          },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

const provider = program
  .command("provider")
  .description("configure and verify AI providers");

provider
  .command("list")
  .description(
    "show provider installation, authentication, model, and readiness",
  )
  .option("--json", "print machine-readable JSON")
  .action(async (options: { json?: boolean }) => {
    try {
      const result = await client.request("provider", resolve(process.cwd()), {
        action: "list",
      });
      printValue(result, Boolean(options.json));
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

provider
  .command("login <provider>")
  .description("launch the provider-owned interactive authentication flow")
  .option("--yes", "approve launching the provider CLI")
  .action(async (providerId: string, options: { yes?: boolean }) => {
    try {
      const plan = providerAuthPlan(providerId);
      if (plan.warning) process.stderr.write(`${plan.warning}\n`);
      let approved = Boolean(options.yes);
      if (!approved && process.stdin.isTTY && process.stdout.isTTY) {
        const prompt = createInterface({
          input: process.stdin,
          output: process.stdout,
        });
        const answer = await prompt.question(
          `Launch ${plan.command} ${plan.args.join(" ")} using the provider-owned login flow? [y/N] `,
        );
        prompt.close();
        approved = answer.trim().toLowerCase() === "y";
      }
      if (!approved) {
        process.stderr.write("Provider login was not launched.\n");
        process.exitCode = 3;
        return;
      }
      await loginProvider(providerId);
      const result = await client.request("provider", resolve(process.cwd()), {
        action: "list",
      });
      printValue(result, false);
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

provider
  .command("models <provider>")
  .description("list models discoverable through a provider CLI")
  .option("--json", "print machine-readable JSON")
  .action(async (providerId: string, options: { json?: boolean }) => {
    try {
      const result = await client.request("provider", resolve(process.cwd()), {
        action: "models",
        provider: providerId,
      });
      printValue(result, Boolean(options.json));
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

provider
  .command("variants <provider>")
  .description("list reasoning variants for a selected provider model")
  .requiredOption("--model <model>", "model whose variants should be listed")
  .option("--json", "print machine-readable JSON")
  .action(
    async (providerId: string, options: { model: string; json?: boolean }) => {
      try {
        const result = await client.request(
          "provider",
          resolve(process.cwd()),
          {
            action: "variants",
            provider: providerId,
            model: options.model,
          },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

provider
  .command("test <provider>")
  .description("run a synthetic review without sending repository content")
  .option("--yes", "approve consuming provider usage for the smoke test")
  .option("--json", "print machine-readable JSON")
  .action(
    async (providerId: string, options: { yes?: boolean; json?: boolean }) => {
      if (!options.yes) {
        process.stderr.write(
          "A provider smoke test may consume provider usage; rerun with --yes.\n",
        );
        process.exitCode = 3;
        return;
      }
      try {
        const result = await client.request(
          "provider",
          resolve(process.cwd()),
          { action: "test", provider: providerId },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

provider
  .command("use <provider>")
  .description("preview or save a private repository provider and model")
  .option("--model <model>", "select a provider model")
  .option("--variant <variant>", "select the model reasoning variant")
  .option(
    "--global",
    "write the XDG user configuration as the default for all repositories",
  )
  .option(
    "--team",
    "write the shareable .codepreflight.toml instead of a private preference",
  )
  .option("--write", "apply the previewed configuration")
  .option("--json", "print machine-readable JSON")
  .action(
    async (
      providerId: string,
      options: {
        model?: string;
        variant?: string;
        global?: boolean;
        team?: boolean;
        write?: boolean;
        json?: boolean;
      },
    ) => {
      if (options.global && options.team) {
        process.stderr.write("Choose either --global or --team, not both.\n");
        process.exitCode = 2;
        return;
      }
      try {
        const result = await client.request(
          "provider",
          resolve(process.cwd()),
          {
            action: "configure",
            provider: providerId,
            model: options.model,
            variant: options.variant,
            scope: options.global
              ? "global"
              : options.team
                ? "team"
                : "personal",
            write: Boolean(options.write),
          },
        );
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

provider
  .command("pull <model>")
  .description("download an Ollama model through the official Ollama CLI")
  .option("--yes", "approve downloading the model")
  .action(async (model: string, options: { yes?: boolean }) => {
    try {
      const plan = ollamaPullPlan(model);
      if (!options.yes) {
        process.stderr.write(
          `Model download requires confirmation; rerun with --yes to launch ${plan.command} ${plan.args.join(" ")}.\n`,
        );
        process.exitCode = 3;
        return;
      }
      await runInteractiveProviderCommand(plan);
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

program
  .command("init")
  .description("preview or create optional shared team configuration")
  .option("--team", "work with the shareable .codepreflight.toml")
  .option("--write", "write the proposed team configuration and trust it")
  .option(
    "--trust",
    "privately trust this repository and any existing team configuration",
  )
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      team?: boolean;
      write?: boolean;
      trust?: boolean;
      json?: boolean;
    }) => {
      if (options.write && !options.team) {
        process.stderr.write(
          "Creating a repository file is now explicit; rerun with --team --write.\n",
        );
        process.exitCode = 2;
        return;
      }
      if (!options.team && !options.trust) {
        printValue(
          {
            configured: true,
            repositoryFileCreated: false,
            message:
              "No repository file is required for personal use. Provider and model choices are stored privately under .git/codepreflight/. Use preflight init --trust when approving authenticated provider CLI access, or preflight init --team to preview an optional shared team configuration.",
          },
          Boolean(options.json),
        );
        return;
      }
      try {
        const result = await client.request("init", resolve(process.cwd()), {
          write: Boolean(options.write),
          trust: Boolean(options.trust),
        });
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

program
  .command("review")
  .description("review repository changes")
  .option("--staged", "review the staged change set")
  .option("--commit <revision>", "review a reachable local commit")
  .option("--branch", "review the current branch against its base")
  .option("--base <branch>", "override the detected base branch")
  .option("--provider <provider>", "override the configured provider")
  .option(
    "--approve",
    "approve sending the context package to a remote provider",
  )
  .option("--no-cache", "bypass and replace a cached review")
  .option("--hook", "run non-interactively for a managed Git hook")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      staged?: boolean;
      commit?: string;
      branch?: boolean;
      base?: string;
      provider?: string;
      approve?: boolean;
      cache?: boolean;
      hook?: boolean;
      json?: boolean;
    }) => {
      const targets = [
        Boolean(options.staged),
        Boolean(options.commit),
        Boolean(options.branch),
      ].filter(Boolean).length;
      if (targets !== 1) {
        process.stderr.write(
          "Choose exactly one review target: --staged, --commit <revision>, or --branch\n",
        );
        process.exitCode = 2;
        return;
      }
      try {
        const result = await client.request(
          "review",
          resolve(process.cwd()),
          {
            target: options.commit
              ? "commit"
              : options.branch
                ? "branch"
                : "staged",
            revision: options.commit,
            base: options.base,
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
            noCache: options.cache === false,
            hook: Boolean(options.hook),
          },
          (event) => {
            printProviderDisclosure(event);
            if (!options.json && event.event === "progress") {
              process.stderr.write(
                `${String(event.payload?.message ?? "Working")}\n`,
              );
            }
          },
        );
        if (options.json) printValue(result, true);
        else printReview(result);
        if (options.hook && Boolean(result.blocking)) process.exitCode = 1;
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

const hooks = program
  .command("hooks")
  .description("manage CodePreFlight Git hooks safely");
for (const action of ["install", "remove", "disable", "enable"] as const) {
  hooks
    .command(`${action} <hook>`)
    .description(`${action} a managed pre-commit or pre-push hook`)
    .option("--write", "apply the previewed hook change")
    .option("--json", "print machine-readable JSON")
    .action(
      async (hook: string, options: { write?: boolean; json?: boolean }) => {
        try {
          const result = await client.request("hooks", resolve(process.cwd()), {
            action,
            hook,
            write: Boolean(options.write),
          });
          printValue(result, Boolean(options.json));
        } catch (error) {
          process.stderr.write(
            `${error instanceof Error ? error.message : String(error)}\n`,
          );
          process.exitCode = 2;
        }
      },
    );
}
hooks
  .command("status <hook>")
  .description("show managed hook status")
  .option("--json", "print machine-readable JSON")
  .action(async (hook: string, options: { json?: boolean }) => {
    try {
      const result = await client.request("hooks", resolve(process.cwd()), {
        action: "status",
        hook,
      });
      printValue(result, Boolean(options.json));
    } catch (error) {
      process.stderr.write(
        `${error instanceof Error ? error.message : String(error)}\n`,
      );
      process.exitCode = 2;
    }
  });

const pr = program
  .command("pr")
  .description("prepare pull-request review material");
pr.command("prepare")
  .description("run a deep branch review and prepare a PR draft")
  .option("--base <branch>", "override the detected base branch")
  .option("--provider <provider>", "override the configured provider")
  .option(
    "--approve",
    "approve sending the context package to a remote provider",
  )
  .option("--json", "print machine-readable JSON")
  .option("--yes", "approve displaying or exporting the generated PR draft")
  .option("--output <path>", "write the approved PR description to a file")
  .action(
    async (options: {
      base?: string;
      provider?: string;
      approve?: boolean;
      json?: boolean;
      yes?: boolean;
      output?: string;
    }) => {
      try {
        const result = await client.request(
          "pr_prepare",
          resolve(process.cwd()),
          {
            base: options.base,
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
          },
          printProviderDisclosure,
        );
        let approved = Boolean(options.yes);
        if (!approved && process.stdin.isTTY && process.stdout.isTTY) {
          const prompt = createInterface({
            input: process.stdin,
            output: process.stdout,
          });
          const confirmation = await prompt.question(
            `Approve generated PR draft "${String(result.title)}" for display/export? [y/N] `,
          );
          prompt.close();
          approved = confirmation.trim().toLowerCase() === "y";
        }
        if (!approved) {
          process.stderr.write(
            "PR draft was prepared but not displayed or exported; rerun with --yes after review.\n",
          );
          process.exitCode = 3;
          return;
        }
        if (options.output) {
          await writeFile(
            resolve(options.output),
            `# ${String(result.title)}\n\n${String(result.description)}`,
            "utf8",
          );
          process.stdout.write(
            `Approved PR description written to ${resolve(options.output)}\n`,
          );
        } else if (options.json) printValue(result, true);
        else {
          process.stdout.write(
            `PR title: ${String(result.title)}\n\n${String(result.description)}\n`,
          );
          printReview(result.review);
        }
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

const cache = program
  .command("cache")
  .description("inspect or clear the local review cache");
for (const action of ["status", "clear"] as const) {
  cache
    .command(action)
    .description(`${action} the privacy-safe local review cache`)
    .option("--json", "print machine-readable JSON")
    .action(async (options: { json?: boolean }) => {
      try {
        const result = await client.request("cache", resolve(process.cwd()), {
          action,
        });
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    });
}

const explain = program
  .command("explain")
  .description("explain repository changes and history");
for (const mode of ["diff", "branch"] as const) {
  explain
    .command(mode)
    .description(
      `explain the current ${mode === "diff" ? "staged diff" : "branch"}`,
    )
    .option("--base <branch>", "override the detected base branch")
    .option("--provider <provider>", "override the configured provider")
    .option("--approve", "approve sending evidence to a remote provider")
    .option("--json", "print machine-readable JSON")
    .action(
      async (options: {
        base?: string;
        provider?: string;
        approve?: boolean;
        json?: boolean;
      }) => {
        try {
          const result = await client.request(
            "explain",
            resolve(process.cwd()),
            {
              mode,
              base: options.base,
              provider: options.provider,
              remoteApproved: Boolean(options.approve),
            },
            printProviderDisclosure,
          );
          if (options.json) printValue(result, true);
          else printExplanation(result);
        } catch (error) {
          process.stderr.write(
            `${error instanceof Error ? error.message : String(error)}\n`,
          );
          process.exitCode = 2;
        }
      },
    );
}
explain
  .command("history <path>")
  .description("explain why a file or selected line reached its current state")
  .option("--line <line>", "line number to explain", Number)
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending evidence to a remote provider")
  .option("--json", "print machine-readable JSON")
  .action(
    async (
      path: string,
      options: {
        line?: number;
        provider?: string;
        approve?: boolean;
        json?: boolean;
      },
    ) => {
      try {
        const result = await client.request(
          "explain",
          resolve(process.cwd()),
          {
            mode: "history",
            path,
            line: options.line,
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
          },
          printProviderDisclosure,
        );
        if (options.json) printValue(result, true);
        else printExplanation(result);
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

program
  .command("ask <question>")
  .description("ask a question scoped to the current repository changes")
  .option("--branch", "use the branch change set instead of staged changes")
  .option("--base <branch>", "override the detected base branch")
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending evidence to a remote provider")
  .option("--json", "print machine-readable JSON")
  .action(
    async (
      question: string,
      options: {
        branch?: boolean;
        base?: string;
        provider?: string;
        approve?: boolean;
        json?: boolean;
      },
    ) => {
      try {
        const result = await client.request(
          "explain",
          resolve(process.cwd()),
          {
            mode: "ask",
            question,
            target: options.branch ? "branch" : "staged",
            base: options.base,
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
          },
          printProviderDisclosure,
        );
        if (options.json) printValue(result, true);
        else printExplanation(result);
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

program
  .command("panel")
  .description("compare independent reviews from multiple providers")
  .requiredOption(
    "--providers <providers>",
    "comma-separated provider identifiers",
  )
  .option("--branch", "review the branch instead of staged changes")
  .option("--base <branch>", "override the detected base branch")
  .option("--approve", "approve sending evidence to remote providers")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      providers: string;
      branch?: boolean;
      base?: string;
      approve?: boolean;
      json?: boolean;
    }) => {
      try {
        const providers = options.providers
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean);
        const result = await client.request(
          "panel_review",
          resolve(process.cwd()),
          {
            providers,
            target: options.branch ? "branch" : "staged",
            base: options.base,
            remoteApproved: Boolean(options.approve),
          },
          printProviderDisclosure,
        );
        if (options.json) printValue(result, true);
        else printPanel(result);
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

program
  .command("commit")
  .description("review staged changes, approve a message, and create a commit")
  .option("--provider <provider>", "override the configured provider")
  .option(
    "--approve",
    "approve sending the context package to a remote provider",
  )
  .option("--message <message>", "replace the proposed commit message")
  .option("--yes", "approve the final commit non-interactively")
  .option("--bypass-review-policy", "allow a commit despite blocking findings")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      provider?: string;
      approve?: boolean;
      message?: string;
      yes?: boolean;
      bypassReviewPolicy?: boolean;
      json?: boolean;
    }) => {
      try {
        const preparation = await client.request(
          "commit",
          resolve(process.cwd()),
          {
            action: "prepare",
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
          },
          printProviderDisclosure,
        );
        const review = preparation.review as { blocking?: boolean };
        if (review.blocking && !options.bypassReviewPolicy) {
          printCommitPreparation(preparation, Boolean(options.json));
          process.stderr.write(
            "Verified findings block this commit; inspect them or pass --bypass-review-policy explicitly.\n",
          );
          process.exitCode = 1;
          return;
        }

        let message = options.message ?? String(preparation.message ?? "");
        let approved = Boolean(options.yes);
        if (!approved) {
          if (!process.stdin.isTTY || !process.stdout.isTTY) {
            printCommitPreparation(preparation, Boolean(options.json), true);
            process.stderr.write(
              "Interactive approval requires a terminal; use --message and --yes.\n",
            );
            process.exitCode = 3;
            return;
          }
          const prompt = createInterface({
            input: process.stdin,
            output: process.stdout,
          });
          const edited = await prompt.question(`Commit message [${message}]: `);
          if (edited.trim()) message = edited.trim();
          const confirmation = await prompt.question(
            `Create commit with \"${message}\"? [y/N] `,
          );
          prompt.close();
          approved = confirmation.trim().toLowerCase() === "y";
        }
        if (!approved) {
          process.stderr.write("Commit cancelled.\n");
          process.exitCode = 3;
          return;
        }
        const result = await client.request("commit", resolve(process.cwd()), {
          action: "execute",
          approved: true,
          message,
          fingerprint: preparation.fingerprint,
        });
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(
          `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 2;
      }
    },
  );

program.action(async (options: { inline?: boolean }) => {
  if (!process.stdin.isTTY) {
    printValue(await client.request("status", resolve(process.cwd())), false);
    return;
  }
  const terminal = new TerminalSession(Boolean(options.inline));
  terminal.install();
  try {
    const application = render(
      React.createElement(App, {
        repositoryPath: resolve(process.cwd()),
        terminal,
      }),
      { exitOnCtrlC: false },
    );
    await application.waitUntilExit();
  } finally {
    terminal.onExit?.();
    terminal.dispose();
  }
});
await program.parseAsync(process.argv);
