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
import {
  EngineClient,
  EngineRequestError,
  type EngineRequestOptions,
} from "./engine-client.js";

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
process.stdout.write(JSON.stringify({protocolVersion:3,requestId:"",event:"ready",payload:{}}) + "\\n");
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
process.stdout.write(JSON.stringify({protocolVersion:3,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.on("data", chunk => {
  const request = JSON.parse(chunk.toString());
  process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"error",error:{code:"provider_model_missing",message:"Model missing",recoverable:true,details:{actions:[{type:"pull_ollama_model",provider:"ollama",model:"qwen2.5-coder:7b"}]}}}) + "\\n");
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

  it("allows a progressing scan to outlive the ordinary request deadline", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-heartbeat-"));
    const engine = join(fixture, "heartbeat-engine.mjs");
    writeFileSync(
      engine,
      `#!/usr/bin/env node
process.stdout.write(JSON.stringify({protocolVersion:3,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.on("data", chunk => {
  const request = JSON.parse(chunk.toString());
  process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"scan_progress",payload:{stage:"review",status:"started",batch:2,batches:4,completedBatches:1,message:"Reviewing batch 2 of 4"}}) + "\\n");
  const heartbeat = setInterval(() => process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"progress",payload:{kind:"provider_heartbeat",actor:"Provider",elapsedMs:20,message:"Provider process is still running"}}) + "\\n"), 20);
  setTimeout(() => { clearInterval(heartbeat); process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"complete",payload:{status:"completed"}}) + "\\n"); }, 130);
});
`,
    );
    chmodSync(engine, 0o755);
    const client = new EngineClient({
      engineCommand: [engine],
      requestTimeoutMs: 50,
    });

    const result = await client.request("scan", repository, {}, undefined, {
      timeoutMs: null,
      idleTimeoutMs: 45,
    } as unknown as EngineRequestOptions);

    expect(result.status).toBe("completed");
    client.dispose();
    rmSync(fixture, { recursive: true, force: true });
  });

  it("reports the last scan location when provider activity goes idle", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-idle-"));
    const engine = join(fixture, "idle-engine.mjs");
    writeFileSync(
      engine,
      `#!/usr/bin/env node
process.stdout.write(JSON.stringify({protocolVersion:3,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.on("data", chunk => {
  const request = JSON.parse(chunk.toString());
  process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"scan_progress",payload:{stage:"review",status:"started",batch:4,batches:7,completedBatches:3,message:"Reviewing batch 4 of 7"}}) + "\\n");
});
setInterval(() => {}, 1000);
`,
    );
    chmodSync(engine, 0o755);
    const client = new EngineClient({
      engineCommand: [engine],
      requestTimeoutMs: 70,
    });

    await expect(
      client.request("scan", repository, {}, undefined, {
        timeoutMs: null,
        idleTimeoutMs: 35,
      } as unknown as EngineRequestOptions),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      code: "engine_request_idle_timeout",
      message: expect.stringContaining(
        "Scan interrupted while reviewing batch 4 of 7",
      ),
    });
    client.dispose();
    rmSync(fixture, { recursive: true, force: true });
  });

  it("adds scan location to provider failures without changing their code", async () => {
    const fixture = mkdtempSync(join(tmpdir(), "codepreflight-scan-failure-"));
    const engine = join(fixture, "failing-scan-engine.mjs");
    writeFileSync(
      engine,
      `#!/usr/bin/env node
process.stdout.write(JSON.stringify({protocolVersion:3,requestId:"",event:"ready",payload:{}}) + "\\n");
process.stdin.on("data", chunk => {
  const request = JSON.parse(chunk.toString());
  process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"scan_progress",payload:{stage:"review",status:"started",batch:4,batches:7,completedBatches:3}}) + "\\n");
  process.stdout.write(JSON.stringify({protocolVersion:3,requestId:request.requestId,event:"error",error:{code:"provider_timeout",message:"Provider timed out after 180 seconds",recoverable:true}}) + "\\n");
});
`,
    );
    chmodSync(engine, 0o755);

    await expect(
      new EngineClient({ engineCommand: [engine] }).request("scan", repository),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      code: "provider_timeout",
      message: expect.stringContaining(
        "3 completed batch results are cached locally",
      ),
    });
    rmSync(fixture, { recursive: true, force: true });
  });
});
