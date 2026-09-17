import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import {
  PROTOCOL_VERSION,
  parseEngineEvent,
  type EngineCommand,
  type EngineEvent,
  type EngineRequest,
} from "./protocol.js";

function repositoryRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
}

export class EngineClient {
  async request(
    command: EngineCommand,
    repositoryPath: string,
    payload: Record<string, unknown> = {},
    onEvent?: (event: EngineEvent) => void,
  ): Promise<Record<string, unknown>> {
    const requestId = randomUUID();
    const child = this.startEngine();
    const request: EngineRequest = {
      protocolVersion: PROTOCOL_VERSION,
      requestId,
      command,
      repositoryPath,
      payload,
    };

    return await new Promise((resolvePromise, reject) => {
      let settled = false;
      let stderr = "";
      const lines = createInterface({ input: child.stdout });

      const stop = (error?: Error): void => {
        if (settled) return;
        settled = true;
        lines.close();
        if (!child.killed) child.kill("SIGTERM");
        if (error) reject(error);
      };

      child.stderr.on("data", (chunk: Buffer) => {
        stderr += chunk.toString();
      });

      lines.on("line", (line) => {
        try {
          const event = parseEngineEvent(line);
          if (event.requestId !== requestId) return;
          onEvent?.(event);
          if (event.event === "error") {
            stop(new Error(event.error?.message ?? "Engine request failed"));
          } else if (event.event === "complete") {
            settled = true;
            lines.close();
            resolvePromise(event.payload ?? {});
          }
        } catch (error) {
          stop(error instanceof Error ? error : new Error(String(error)));
        }
      });

      child.on("error", (error) => stop(error));
      child.on("exit", (code) => {
        if (!settled) {
          stop(
            new Error(
              `Engine exited with code ${String(code)}${stderr ? `: ${stderr.trim()}` : ""}`,
            ),
          );
        }
      });

      child.stdin.write(`${JSON.stringify(request)}\n`);
      child.stdin.end();
    });
  }

  status(repositoryPath: string, onEvent?: (event: EngineEvent) => void) {
    return this.request("status", repositoryPath, {}, onEvent);
  }

  private startEngine(): ChildProcessWithoutNullStreams {
    const configured = process.env.CODEPREFLIGHT_ENGINE_COMMAND;
    if (configured) {
      const [command, ...args] = configured.split(" ");
      return spawn(command, args, { stdio: ["pipe", "pipe", "pipe"] });
    }

    const root = repositoryRoot();
    return spawn(
      "uv",
      ["run", "--project", resolve(root, "engine"), "codepreflight-engine"],
      { cwd: root, stdio: ["pipe", "pipe", "pipe"] },
    );
  }
}
