import { describe, expect, it, vi } from "vitest";
import { EngineRequestError } from "./engine-client.js";
import type { EngineCommand, EngineEvent } from "./protocol.js";
import { SessionController, type SessionEngine } from "./session-controller.js";

const snapshot = {
  root: "/repo",
  branch: "feature/auth",
  base_branch: "main",
  upstream: "origin/feature/auth",
  ahead: 2,
  behind: 0,
  files: [{ path: "auth.py", staged: true, unstaged: false, untracked: false }],
  conflicts: [],
};

const providers = {
  providers: [
    {
      id: "codex",
      name: "Codex CLI",
      availability: "ready",
      authentication: "authenticated",
      model: "not_applicable",
      sends_code_remotely: true,
    },
  ],
};

class FakeEngine implements SessionEngine {
  requests: Array<{
    command: EngineCommand;
    payload: Record<string, unknown>;
  }> = [];
  reviewApproved = false;

  async request(
    command: EngineCommand,
    _repositoryPath: string,
    payload: Record<string, unknown> = {},
    onEvent?: (event: EngineEvent) => void,
  ): Promise<Record<string, unknown>> {
    this.requests.push({ command, payload });
    if (command === "status") {
      return {
        repository: snapshot,
        configuration: { review: { provider: "codex" } },
        trusted: true,
      };
    }
    if (command === "provider") return providers;
    if (command === "review") {
      if (!payload.remoteApproved) {
        onEvent?.({
          protocolVersion: 2,
          requestId: "review",
          event: "consent_required",
          payload: {
            provider: {
              id: "codex",
              name: "Codex CLI",
              kind: "subscription_cli",
            },
            manifest: {
              total_characters: 1200,
              redactions: 0,
              secret_scanner: "built-in",
            },
          },
        });
        throw new EngineRequestError(
          "Approval required",
          "provider_consent_required",
          true,
        );
      }
      this.reviewApproved = true;
      return {
        status: "completed",
        summary: "One issue found.",
        findings: [
          {
            id: "finding-1",
            severity: "warning",
            title: "Expired tokens are accepted",
            explanation: "Expiration validation was removed.",
            impact: "Expired sessions remain valid.",
            verification: "verified",
            recommendation: "Restore expiration validation.",
            evidence: [{ path: "auth.py", start_line: 42, end_line: 42 }],
          },
        ],
      };
    }
    if (command === "explain") {
      return {
        result: {
          answer: "The branch changes token validation.",
          evidence: [],
        },
      };
    }
    throw new Error(`Unexpected command: ${command}`);
  }

  dispose(): void {}
}

describe("SessionController", () => {
  it("starts an ephemeral repository session with provider context", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });

    await controller.start();

    expect(controller.state.header).toMatchObject({
      repository: "repo",
      branch: "feature/auth",
      baseBranch: "main",
      ahead: 2,
      behind: 0,
      provider: "Codex CLI",
    });
    expect(controller.state.transcript.at(-1)?.body).toContain("1 staged");
  });

  it("routes slash commands without using repository chat", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/status");

    expect(
      engine.requests.filter((request) => request.command === "explain"),
    ).toHaveLength(0);
    expect(controller.state.transcript.at(-1)?.title).toBe("Repository status");
  });

  it("asks once for remote consent and retries the review", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/review staged");
    const decision = controller.state.pendingDecision;
    expect(decision?.body).toContain("1,200 characters");

    await controller.confirm(decision!.id, true);

    expect(engine.reviewApproved).toBe(true);
    expect(controller.state.pendingDecision).toBeUndefined();
    expect(controller.state.transcript.at(-1)?.kind).toBe("review");
  });

  it("routes plain text to repository-scoped questions", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("What changed on this branch?");

    expect(engine.requests.at(-1)).toMatchObject({
      command: "explain",
      payload: {
        mode: "ask",
        question: "What changed on this branch?",
        target: "branch",
      },
    });
    expect(controller.state.transcript.at(-1)?.body).toBe(
      "The branch changes token validation.",
    );
  });

  it("previews and confirms provider selection", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/provider use codex");
    const decision = controller.state.pendingDecision;
    expect(decision?.title).toContain("codex");

    await controller.confirm(decision!.id, true);

    expect(engine.requests).toContainEqual({
      command: "provider",
      payload: {
        action: "configure",
        provider: "codex",
        model: undefined,
        write: true,
      },
    });
  });

  it("clears the in-memory transcript without writing session data", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    const listener = vi.fn();
    controller.subscribe(listener);
    await controller.start();

    await controller.submit("/clear");

    expect(controller.state.transcript).toEqual([]);
    expect(listener).toHaveBeenCalled();
  });
});
