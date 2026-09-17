#!/usr/bin/env node
import { Command } from "commander";
import { resolve } from "node:path";
import { EngineClient } from "./engine-client.js";
import { printValue } from "./format.js";

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

program.action(() => program.help());
await program.parseAsync(process.argv);
