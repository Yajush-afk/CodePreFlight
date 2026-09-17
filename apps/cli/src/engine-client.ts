import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface, type Interface } from "node:readline";
import {
  PROTOCOL_VERSION,
  parseEngineEvent,
  type EngineCommand,
  type EngineEvent,
  type EngineRequest,
} from "./protocol.js";

const HANDSHAKE_TIMEOUT_MS = 5_000;
const REQUEST_TIMEOUT_MS = 5 * 60_000;
const MAX_DIAGNOSTIC_CHARACTERS = 12_000;

function repositoryRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
}

export interface EngineClientOptions {
  persistent?: boolean;
  requestTimeoutMs?: number;
  onDiagnostic?: (message: string) => void;
  engineCommand?: readonly string[];
}

export interface EngineRequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export class EngineRequestError extends Error {
  constructor(
    message: string,
    readonly code = "engine_error",
    readonly recoverable = false,
  ) {
    super(message);
    this.name = "EngineRequestError";
  }
}

interface PendingRequest {
  resolve: (value: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  onEvent?: (event: EngineEvent) => void;
  timeout: NodeJS.Timeout;
  removeAbortListener?: () => void;
}

class EngineConnection {
  private readonly child: ChildProcessWithoutNullStreams;
  private readonly lines: Interface;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly ready: Promise<void>;
  private readyEvent?: EngineEvent;
  private readySettled = false;
  private closed = false;
  private diagnostics = "";

  constructor(
    private readonly keepAlive: boolean,
    private readonly requestTimeoutMs: number,
    private readonly onDiagnostic: ((message: string) => void) | undefined,
    private readonly onClosed: () => void,
    private readonly engineCommand: readonly string[] | undefined,
  ) {
    this.child = this.startEngine();
    this.lines = createInterface({ input: this.child.stdout });
    this.ready = new Promise((resolveReady, rejectReady) => {
      const timeout = setTimeout(() => {
        const error = new EngineRequestError(
          "Python engine did not complete the protocol handshake within 5 seconds",
          "engine_handshake_timeout",
          true,
        );
        rejectReady(error);
        this.fail(error);
      }, HANDSHAKE_TIMEOUT_MS);
      this.lines.on("line", (line) => {
        try {
          const event = parseEngineEvent(line);
          if (event.event === "ready") {
            if (this.readySettled) {
              throw new EngineRequestError(
                "Engine emitted more than one ready event",
                "duplicate_ready_event",
              );
            }
            this.readySettled = true;
            this.readyEvent = event;
            clearTimeout(timeout);
            resolveReady();
            return;
          }
          if (!this.readySettled) {
            throw new EngineRequestError(
              "Engine emitted an event before the ready handshake",
              "event_before_handshake",
            );
          }
          this.handleEvent(event);
        } catch (error) {
          const failure =
            error instanceof Error ? error : new Error(String(error));
          if (!this.readySettled) rejectReady(failure);
          this.fail(failure);
        }
      });
      this.child.once("error", (error) => {
        clearTimeout(timeout);
        const failure =
          (error as NodeJS.ErrnoException).code === "ENOENT"
            ? new EngineRequestError(
                "Cannot start the Python engine because its launcher is not installed or not on PATH",
                "engine_launcher_missing",
              )
            : new EngineRequestError(
                `Cannot start the Python engine: ${error.message}`,
              );
        rejectReady(failure);
        this.fail(failure);
      });
    });

    this.child.stderr.on("data", (chunk: Buffer) => {
      const message = chunk.toString();
      this.diagnostics = (this.diagnostics + message).slice(
        -MAX_DIAGNOSTIC_CHARACTERS,
      );
      this.onDiagnostic?.(message);
    });
    this.child.once("exit", (code, signal) => {
      if (this.closed) return;
      const detail = this.diagnostics.trim();
      this.fail(
        new EngineRequestError(
          `Engine exited unexpectedly (${signal ?? `code ${String(code)}`})${detail ? `: ${detail}` : ""}`,
          "engine_exited",
          true,
        ),
      );
    });
  }

  async request(
    request: EngineRequest,
    onEvent?: (event: EngineEvent) => void,
    options: EngineRequestOptions = {},
  ): Promise<Record<string, unknown>> {
    await this.ready;
    if (this.closed) {
      throw new EngineRequestError(
        "Python engine connection is closed",
        "engine_closed",
        true,
      );
    }
    if (options.signal?.aborted) {
      throw new EngineRequestError(
        "Engine request cancelled",
        "engine_cancelled",
        true,
      );
    }
    onEvent?.(this.readyEvent as EngineEvent);
    if (options.signal?.aborted) {
      throw new EngineRequestError(
        "Engine request cancelled",
        "engine_cancelled",
        true,
      );
    }
    return await new Promise((resolveRequest, rejectRequest) => {
      const duration = options.timeoutMs ?? this.requestTimeoutMs;
      const timeout = setTimeout(() => {
        const error = new EngineRequestError(
          `Engine request timed out after ${duration} ms`,
          "engine_request_timeout",
          true,
        );
        rejectRequest(error);
        this.terminate(error);
      }, duration);
      const pending: PendingRequest = {
        resolve: resolveRequest,
        reject: rejectRequest,
        onEvent,
        timeout,
      };
      if (options.signal) {
        const cancel = (): void => {
          const error = new EngineRequestError(
            "Engine request cancelled",
            "engine_cancelled",
            true,
          );
          rejectRequest(error);
          this.terminate(error);
        };
        options.signal.addEventListener("abort", cancel, { once: true });
        pending.removeAbortListener = () =>
          options.signal?.removeEventListener("abort", cancel);
      }
      this.pending.set(request.requestId, pending);
      this.child.stdin.write(`${JSON.stringify(request)}\n`);
      if (!this.keepAlive) this.child.stdin.end();
    });
  }

  dispose(): void {
    this.terminate(
      new EngineRequestError(
        "Engine session closed",
        "engine_session_closed",
        true,
      ),
    );
  }

  private handleEvent(event: EngineEvent): void {
    const pending = this.pending.get(event.requestId);
    if (!pending) return;
    pending.onEvent?.(event);
    if (event.event === "error") {
      this.finish(event.requestId);
      pending.reject(
        new EngineRequestError(
          event.error?.message ?? "Engine request failed",
          event.error?.code,
          event.error?.recoverable,
        ),
      );
    } else if (event.event === "complete") {
      this.finish(event.requestId);
      pending.resolve(event.payload ?? {});
    }
  }

  private finish(requestId: string): void {
    const pending = this.pending.get(requestId);
    if (!pending) return;
    clearTimeout(pending.timeout);
    pending.removeAbortListener?.();
    this.pending.delete(requestId);
  }

  private fail(error: Error): void {
    if (this.closed) return;
    this.closed = true;
    for (const [requestId, pending] of this.pending) {
      this.finish(requestId);
      pending.reject(error);
    }
    this.lines.close();
    this.onClosed();
    this.killProcessGroup("SIGTERM");
  }

  private terminate(error: Error): void {
    if (this.closed) return;
    this.fail(error);
    const force = setTimeout(() => this.killProcessGroup("SIGKILL"), 1_000);
    force.unref();
  }

  private killProcessGroup(signal: NodeJS.Signals): void {
    if (this.child.exitCode !== null || this.child.signalCode !== null) return;
    try {
      if (this.child.pid && process.platform !== "win32") {
        process.kill(-this.child.pid, signal);
        // macOS can acknowledge a process-group signal before the group leader handles it.
        // Signal the engine directly as well; descendants still receive the group signal.
        this.child.kill(signal);
      } else this.child.kill(signal);
    } catch {
      this.child.kill(signal);
    }
  }

  private startEngine(): ChildProcessWithoutNullStreams {
    const spawnOptions = {
      stdio: ["pipe", "pipe", "pipe"] as ["pipe", "pipe", "pipe"],
      detached: process.platform !== "win32",
    };
    if (this.engineCommand?.length) {
      const [command, ...args] = this.engineCommand;
      return spawn(command, args, spawnOptions);
    }
    const configured = process.env.CODEPREFLIGHT_ENGINE_COMMAND;
    if (configured) {
      const [command, ...args] = configured.trim().split(/\s+/);
      return spawn(command, args, spawnOptions);
    }
    const root = repositoryRoot();
    return spawn(
      "uv",
      ["run", "--project", resolve(root, "engine"), "codepreflight-engine"],
      { ...spawnOptions, cwd: root },
    );
  }
}

export class EngineClient {
  private connection?: EngineConnection;

  constructor(private readonly options: EngineClientOptions = {}) {}

  async request(
    command: EngineCommand,
    repositoryPath: string,
    payload: Record<string, unknown> = {},
    onEvent?: (event: EngineEvent) => void,
    options: EngineRequestOptions = {},
  ): Promise<Record<string, unknown>> {
    const request: EngineRequest = {
      protocolVersion: PROTOCOL_VERSION,
      requestId: randomUUID(),
      command,
      repositoryPath,
      payload,
    };
    const connection = this.options.persistent
      ? (this.connection ??= this.createConnection(true))
      : this.createConnection(false);
    return await connection.request(request, onEvent, options);
  }

  status(
    repositoryPath: string,
    onEvent?: (event: EngineEvent) => void,
    options?: EngineRequestOptions,
  ): Promise<Record<string, unknown>> {
    return this.request("status", repositoryPath, {}, onEvent, options);
  }

  dispose(): void {
    this.connection?.dispose();
    this.connection = undefined;
  }

  private createConnection(keepAlive: boolean): EngineConnection {
    let connection: EngineConnection;
    connection = new EngineConnection(
      keepAlive,
      this.options.requestTimeoutMs ?? REQUEST_TIMEOUT_MS,
      this.options.onDiagnostic,
      () => {
        if (this.connection === connection) this.connection = undefined;
      },
      this.options.engineCommand,
    );
    return connection;
  }
}
