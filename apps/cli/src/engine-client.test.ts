import { execFileSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { EngineClient, EngineRequestError } from "./engine-client.js";

const repository = mkdtempSync(join(tmpdir(), "codepreflight-protocol-"));

function git(...args: string[]): void {
  execFileSync("git", args, { cwd: repository, stdio: "ignore" });
}

git("init", "-b", "main");
git("config", "user.name", "CodePreFlight Tests");
git("config", "user.email", "tests@codepreflight.local");
writeFileSync(join(repository, "README.md"), "# Protocol fixture\n");
git("add", "README.md");
git("commit", "-m", "Initial commit");

afterAll(() => rmSync(repository, { recursive: true, force: true }));

describe("EngineClient process protocol", () => {
  it("waits for the Python handshake before completing a request", async () => {
    const events: string[] = [];

    const result = await new EngineClient().request(
      "status",
      repository,
      {},
      (event) => {
        events.push(event.event);
      },
    );

    expect(events[0]).toBe("ready");
    expect((result.repository as { branch: string }).branch).toBe("main");
  });

  it("reuses one engine process for an interactive session", async () => {
    const client = new EngineClient({ persistent: true });
    const processIds: number[] = [];
    const captureReady = (event: {
      event: string;
      payload?: Record<string, unknown>;
    }): void => {
      if (event.event === "ready")
        processIds.push(Number(event.payload?.processId));
    };

    await client.status(repository, captureReady);
    await client.request("doctor", repository, {}, captureReady);
    client.dispose();

    expect(processIds).toHaveLength(2);
    expect(processIds[0]).toBe(processIds[1]);
  });

  it("cancels an active process group and allows temporary cleanup", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-cancel-"));
    const marker = join(fixture, "provider.tmp");
    const engine = join(fixture, "fake-engine.mjs");
    writeFileSync(
      engine,
      `#!/usr/bin/env node
import { rmSync, writeFileSync } from "node:fs";
process.on("SIGTERM", () => { rmSync(${JSON.stringify(marker)}, {force:true}); process.exit(0); });
writeFileSync(${JSON.stringify(marker)}, "active");
process.stdout.write(JSON.stringify({protocolVersion:2,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.resume();
`,
    );
    chmodSync(engine, 0o755);
    const controller = new AbortController();
    const client = new EngineClient({
      persistent: true,
      engineCommand: [engine],
    });
    let markReady: (() => void) | undefined;
    const ready = new Promise<void>((resolveReady) => {
      markReady = resolveReady;
    });
    const pending = client.request(
      "status",
      repository,
      {},
      (event) => {
        if (event.event === "ready") markReady?.();
      },
      { signal: controller.signal },
    );

    await ready;
    controller.abort();

    await expect(pending).rejects.toMatchObject<Partial<EngineRequestError>>({
      code: "engine_cancelled",
    });
    for (let attempt = 0; attempt < 100 && existsSync(marker); attempt += 1) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 20));
    }
    expect(existsSync(marker)).toBe(false);
    rmSync(fixture, { recursive: true, force: true });
  });

  it("reports malformed engine output clearly", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-malformed-"));
    const engine = join(fixture, "malformed-engine.mjs");
    writeFileSync(
      engine,
      '#!/usr/bin/env node\nprocess.stdout.write("not-json\\n");\n',
    );
    chmodSync(engine, 0o755);

    await expect(
      new EngineClient({ engineCommand: [engine] }).status(repository),
    ).rejects.toThrow("Engine emitted invalid JSON");
    rmSync(fixture, { recursive: true, force: true });
  });

  it("reports a missing engine launcher clearly", async () => {
    await expect(
      new EngineClient({
        engineCommand: [join(repository, "missing-engine")],
      }).status(repository),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      code: "engine_launcher_missing",
    });
  });

  it("preserves structured recovery details from engine failures", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-recovery-"));
    const engine = join(fixture, "recovery-engine.mjs");
    writeFileSync(
      engine,
      `#!/usr/bin/env node
process.stdout.write(JSON.stringify({protocolVersion:2,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.on("data", chunk => {
  const request = JSON.parse(chunk.toString());
  process.stdout.write(JSON.stringify({protocolVersion:2,requestId:request.requestId,event:"error",error:{code:"provider_model_missing",message:"Model missing",recoverable:true,details:{actions:[{type:"pull_ollama_model",provider:"ollama",model:"qwen2.5-coder:7b"}]}}}) + "\\n");
});
`,
    );
    chmodSync(engine, 0o755);

    await expect(
      new EngineClient({ engineCommand: [engine] }).status(repository),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      code: "provider_model_missing",
      recoverable: true,
      details: {
        actions: [
          {
            type: "pull_ollama_model",
            provider: "ollama",
            model: "qwen2.5-coder:7b",
          },
        ],
      },
    });
    rmSync(fixture, { recursive: true, force: true });
  });
});
