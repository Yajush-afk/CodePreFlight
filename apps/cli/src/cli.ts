#!/usr/bin/env node
import { Command } from "commander";
import { resolve } from "node:path";
import { createInterface } from "node:readline/promises";
import React from "react";
import { render } from "ink";
import { EngineClient } from "./engine-client.js";
import { printReview, printValue } from "./format.js";
import { App } from "./tui.js";

const program = new Command();
const client = new EngineClient();

program
  .name("preflight")
  .description("Inspect and review repository changes before they enter Git history")
  .version("0.1.0")
  .showHelpAfterError();

function engineCommand(name: "status" | "doctor" | "providers", description: string): void {
  program
    .command(name)
    .description(description)
    .option("--json", "print machine-readable JSON")
    .action(async (options: { json?: boolean }) => {
      try {
        const result = await client.request(name, resolve(process.cwd()));
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
        process.exitCode = 2;
      }
    });
}

engineCommand("status", "show repository status and detected project context");
engineCommand("doctor", "check the local CodePreFlight environment");
engineCommand("providers", "show detected AI providers");

program
  .command("init")
  .description("detect and configure CodePreFlight for this repository")
  .option("--write", "write the proposed repository configuration and trust it")
  .option("--json", "print machine-readable JSON")
  .action(async (options: { write?: boolean; json?: boolean }) => {
    try {
      const result = await client.request("init", resolve(process.cwd()), {
        write: Boolean(options.write),
      });
      printValue(result, Boolean(options.json));
    } catch (error) {
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 2;
    }
  });

program
  .command("review")
  .description("review repository changes")
  .option("--staged", "review the staged change set")
  .option("--branch", "review the current branch against its base")
  .option("--base <branch>", "override the detected base branch")
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending the context package to a remote provider")
  .option("--hook", "run non-interactively for a managed Git hook")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      staged?: boolean;
      branch?: boolean;
      base?: string;
      provider?: string;
      approve?: boolean;
      hook?: boolean;
      json?: boolean;
    }) => {
      if (options.staged === options.branch) {
        process.stderr.write("Choose exactly one review target: --staged or --branch\n");
        process.exitCode = 2;
        return;
      }
      try {
        const result = await client.request(
          "review",
          resolve(process.cwd()),
          {
            target: options.branch ? "branch" : "staged",
            base: options.base,
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
            hook: Boolean(options.hook),
          },
          (event) => {
            if (!options.json && event.event === "progress") {
              process.stderr.write(`${String(event.payload?.message ?? "Working")}\n`);
            }
          },
        );
        if (options.json) printValue(result, true);
        else printReview(result);
        if (options.hook && Boolean(result.blocking)) process.exitCode = 1;
      } catch (error) {
        process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
        process.exitCode = 2;
      }
    },
  );

const hooks = program.command("hooks").description("manage CodePreFlight Git hooks safely");
for (const action of ["install", "remove", "disable", "enable"] as const) {
  hooks
    .command(`${action} <hook>`)
    .description(`${action} a managed pre-commit or pre-push hook`)
    .option("--write", "apply the previewed hook change")
    .option("--json", "print machine-readable JSON")
    .action(async (hook: string, options: { write?: boolean; json?: boolean }) => {
      try {
        const result = await client.request("hooks", resolve(process.cwd()), {
          action,
          hook,
          write: Boolean(options.write),
        });
        printValue(result, Boolean(options.json));
      } catch (error) {
        process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
        process.exitCode = 2;
      }
    });
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
      process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 2;
    }
  });

const pr = program.command("pr").description("prepare pull-request review material");
pr.command("prepare")
  .description("run a deep branch review and prepare a PR draft")
  .option("--base <branch>", "override the detected base branch")
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending the context package to a remote provider")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: { base?: string; provider?: string; approve?: boolean; json?: boolean }) => {
      try {
        const result = await client.request("pr_prepare", resolve(process.cwd()), {
          base: options.base,
          provider: options.provider,
          remoteApproved: Boolean(options.approve),
        });
        if (options.json) printValue(result, true);
        else {
          process.stdout.write(`PR title: ${String(result.title)}\n\n${String(result.description)}\n`);
          printReview(result.review);
        }
      } catch (error) {
        process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
        process.exitCode = 2;
      }
    },
  );

program
  .command("commit")
  .description("review staged changes, approve a message, and create a commit")
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending the context package to a remote provider")
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
        const preparation = await client.request("commit", resolve(process.cwd()), {
          action: "prepare",
          provider: options.provider,
          remoteApproved: Boolean(options.approve),
        });
        const review = preparation.review as { blocking?: boolean };
        if (review.blocking && !options.bypassReviewPolicy) {
          if (options.json) printValue(preparation, true);
          else printReview(preparation.review);
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
            if (options.json) printValue(preparation, true);
            else {
              printReview(preparation.review);
              process.stdout.write(`Proposed commit: ${String(preparation.message)}\n`);
            }
            process.stderr.write("Interactive approval requires a terminal; use --message and --yes.\n");
            process.exitCode = 3;
            return;
          }
          const prompt = createInterface({ input: process.stdin, output: process.stdout });
          const edited = await prompt.question(`Commit message [${message}]: `);
          if (edited.trim()) message = edited.trim();
          const confirmation = await prompt.question(`Create commit with \"${message}\"? [y/N] `);
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
        process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
        process.exitCode = 2;
      }
    },
  );

program.action(() => {
  render(React.createElement(App, { repositoryPath: resolve(process.cwd()) }));
});
await program.parseAsync(process.argv);
