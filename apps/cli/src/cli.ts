#!/usr/bin/env node
import { Command } from "commander";
import { resolve } from "node:path";
import React from "react";
import { render } from "ink";
import { EngineClient } from "./engine-client.js";
import { printValue } from "./format.js";
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
  .option("--provider <provider>", "override the configured provider")
  .option("--approve", "approve sending the context package to a remote provider")
  .option("--json", "print machine-readable JSON")
  .action(
    async (options: {
      staged?: boolean;
      provider?: string;
      approve?: boolean;
      json?: boolean;
    }) => {
      if (!options.staged) {
        process.stderr.write("Phase 2 supports staged review; pass --staged\n");
        process.exitCode = 2;
        return;
      }
      try {
        const result = await client.request(
          "review",
          resolve(process.cwd()),
          {
            target: "staged",
            provider: options.provider,
            remoteApproved: Boolean(options.approve),
          },
          (event) => {
            if (!options.json && event.event === "progress") {
              process.stderr.write(`${String(event.payload?.message ?? "Working")}\n`);
            }
          },
        );
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
