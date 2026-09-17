import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { EngineClient } from "./engine-client.js";

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
});
