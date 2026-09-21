import { describe, expect, it, vi } from "vitest";
import {
  EngineRequestError,
  type EngineRequestOptions,
} from "./engine-client.js";
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
      readiness: { state: "ready", invocationVerified: true },
      authentication: "authenticated",
      model: "not_applicable",
      model_name: "subscription default",
      kind: "subscription_cli",
      sends_code_remotely: true,
    },
  ],
};

class FakeEngine implements SessionEngine {
  requests: Array<{
    command: EngineCommand;
    payload: Record<string, unknown>;
  }> = [];
  requestOptions: EngineRequestOptions[] = [];
  reviewApproved = false;
  automationMode = "manual";

  async request(
    command: EngineCommand,
    _repositoryPath: string,
    payload: Record<string, unknown> = {},
    onEvent?: (event: EngineEvent) => void,
    options?: EngineRequestOptions,
  ): Promise<Record<string, unknown>> {
    this.requests.push({ command, payload });
    if (options) this.requestOptions.push(options);
    if (command === "status") {
      return {
        repository: snapshot,
        configuration: { review: { provider: "codex" } },
        trusted: true,
      };
    }
    if (command === "provider") {
      if (payload.action === "models") {
        return {
          provider: payload.provider,
          serviceTier: "standard",
          models: ["gpt-flagship", "gpt-economy"],
          details: [
            {
              id: "gpt-flagship",
              label: "Flagship",
              description: "Most capable",
            },
            { id: "gpt-economy", label: "Economy", description: "Lower usage" },
          ],
        };
      }
      if (payload.action === "variants") {
        return {
          provider: payload.provider,
          model: payload.model,
          variants: ["low", "medium", "high"],
          defaultVariant: "medium",
        };
      }
      if (payload.action === "configure") {
        return {
          provider: payload.provider,
          model: payload.model,
          variant: payload.variant,
          written: payload.write,
          diff: "provider configuration diff",
        };
      }
      return providers;
    }
    if (command === "automation") {
      if (payload.action === "status") {
        return { mode: this.automationMode, grant: null, jobs: [] };
      }
      if (payload.action === "event") {
        return this.automationMode === "manual"
          ? { mode: "manual", action: "none" }
          : {
              mode: this.automationMode,
              action: "detect_pr",
              prDetection: {
                found: true,
                number: 42,
                reviewFingerprintCurrent: false,
              },
            };
      }
      if (payload.action === "configure") {
        return {
          mode: payload.mode,
          written: payload.write,
          hookResults: [
            { hook: "post-commit", action: "install" },
            { hook: "pre-push", action: "install" },
          ],
        };
      }
      if (payload.action === "grant") {
        return { written: payload.write, grant: { provider: "codex" } };
      }
      return { written: payload.write, revoked: true };
    }
    if (command === "workspace") {
      if (payload.action === "tree") {
        return {
          items: [{ path: "auth.py", status: "modified", tracked: true }],
        };
      }
      if (payload.action === "branches") {
        return {
          current: "feature/auth",
          items: [
            { name: "feature/auth", current: true, subject: "Work" },
            { name: "main", current: false, subject: "Stable" },
          ],
        };
      }
      if (payload.action === "commits") {
        return {
          items: [{ oid: "abc123", shortOid: "abc123", subject: "Work" }],
        };
      }
      if (payload.action === "file") {
        return { path: payload.path, diff: "diff --git a/auth.py b/auth.py" };
      }
      if (payload.action === "pr") return { found: false };
    }
    if (command === "git_action") {
      if (payload.action === "switch_preview") {
        return {
          allowed: true,
          currentBranch: "feature/auth",
          targetBranch: payload.branch,
          expectedHead: "abc123",
          preservedPaths: [],
          collisions: [],
        };
      }
      return { branch: payload.branch };
    }
    if (command === "scan") {
      if (!payload.fullScanApproved) {
        onEvent?.({
          protocolVersion: 3,
          requestId: "scan",
          event: "consent_required",
          payload: {
            fullScan: true,
            manifest: {
              eligibleFiles: 12,
              excludedFiles: 3,
              redactions: 1,
              totalSelectedCharacters: 24000,
              providerRequests: 4,
              destination: "Codex CLI",
              privacyCategory: "subscription_cli",
            },
          },
        });
        throw new EngineRequestError(
          "Full scan confirmation required",
          "full_scan_confirmation_required",
          true,
        );
      }
      onEvent?.({
        protocolVersion: 3,
        requestId: "scan",
        event: "scan_progress",
        payload: {
          stage: "review",
          status: "started",
          batch: 2,
          batches: 4,
          completedBatches: 1,
          sources: ["engine/src/review.py", "engine/tests/test_review.py"],
          characters: 18000,
        },
      });
      onEvent?.({
        protocolVersion: 3,
        requestId: "scan",
        event: "progress",
        payload: {
          kind: "provider_heartbeat",
          actor: "Provider",
          elapsedMs: 72000,
        },
      });
      return {
        status: "completed",
        summary: "Full scan complete.",
        findings: [],
      };
    }
    if (command === "commit") {
      if (payload.action === "prepare") {
        return {
          message: "feat: generated message",
          fingerprint: "fingerprint-123",
          review: {
            status: "completed",
            summary: "Staged changes reviewed.",
            findings: [],
            blocking: false,
          },
        };
      }
      return { commit: "deadbeef", message: payload.message };
    }
    if (command === "review") {
      if (!payload.remoteApproved) {
        onEvent?.({
          protocolVersion: 3,
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
      providerAuthentication: "authenticated",
      providerModel: "subscription default",
      providerPrivacy: "remote subscription_cli",
    });
    expect(controller.state.transcript.at(-1)?.body).toContain("1 staged");
  });

  it("shows Auto pull-request detection in the launch header", async () => {
    const engine = new FakeEngine();
    engine.automationMode = "auto";
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });

    await controller.start();

    expect(controller.state.header?.pullRequest).toBe("#42 · review due");
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

    await controller.submit("/reviewstaged");
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

    await controller.submit("/providerswitch codex");
    const decision = controller.state.pendingDecision;
    expect(decision?.title).toContain("codex");

    await controller.confirm(decision!.id, true);

    expect(engine.requests).toContainEqual({
      command: "provider",
      payload: {
        action: "configure",
        provider: "codex",
        model: undefined,
        variant: undefined,
        scope: "personal",
        write: true,
      },
    });
  });

  it("opens model and variant selectors without speed-tier choices", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/model");
    expect(controller.state.overlay?.title).toBe("Choose review model");
    expect(controller.state.overlay?.body).toContain("non-flagship");
    expect(controller.state.overlay?.items?.map((item) => item.value)).toEqual([
      "gpt-flagship",
      "gpt-economy",
    ]);

    await controller.select({ kind: "model", value: "gpt-economy" });
    const modelDecision = controller.state.pendingDecision;
    await controller.confirm(modelDecision!.id, true);

    await controller.submit("/variant");
    expect(controller.state.overlay?.title).toBe("Choose model variant");
    expect(controller.state.overlay?.items?.map((item) => item.value)).toEqual([
      "low",
      "medium",
      "high",
    ]);
  });

  it("confirms provider login before handing terminal control to the provider", async () => {
    const engine = new FakeEngine();
    const login = vi.fn(async () => {});
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
      loginProvider: login,
    });
    await controller.start();

    await controller.submit("/providerlogin codex");
    expect(login).not.toHaveBeenCalled();
    const decision = controller.state.pendingDecision;
    expect(decision?.title).toBe("Authenticate Codex CLI?");

    await controller.confirm(decision!.id, true);
    expect(login).toHaveBeenCalledWith("codex");
    expect(controller.state.transcript.at(-1)?.body).toContain(
      "authentication verified",
    );
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

  it("opens repository browsers and routes a commit selection deterministically", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/commits");

    expect(controller.state.overlay?.kind).toBe("commits");
    expect(controller.state.overlay?.items?.[0]?.action).toEqual({
      kind: "commit",
      value: "abc123",
    });
  });

  it("previews and explicitly confirms a local branch switch", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/switchbranch main");
    const decision = controller.state.pendingDecision;
    expect(decision?.title).toBe("Switch to main?");

    await controller.confirm(decision!.id, true);

    expect(engine.requests).toContainEqual({
      command: "git_action",
      payload: {
        action: "switch_execute",
        branch: "main",
        approved: true,
        expectedHead: "abc123",
      },
    });
    expect(controller.state.transcript.at(-1)?.title).toBe("Branch changed");
  });

  it("previews and confirms a personal review-mode change", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.select({ kind: "mode", value: "auto_plus" });
    const decision = controller.state.pendingDecision;
    expect(decision?.title).toContain("Auto+");
    await controller.confirm(decision!.id, true);

    expect(engine.requests).toContainEqual({
      command: "automation",
      payload: { action: "configure", mode: "auto_plus", write: true },
    });
  });

  it("requires a dedicated confirmation for every full scan", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    const activities: string[] = [];
    controller.subscribe((state) => {
      if (state.activity) activities.push(state.activity);
    });
    await controller.start();

    await controller.submit("/scanfull");
    const decision = controller.state.pendingDecision;
    expect(decision?.body).toContain("12 eligible files");
    expect(decision?.body).toContain(
      "This approval is only for this exact full scan",
    );

    await controller.confirm(decision!.id, true);

    expect(engine.requests.at(-1)).toMatchObject({
      command: "scan",
      payload: { fullScanApproved: true },
    });
    expect(engine.requestOptions.at(-1)).toMatchObject({
      timeoutMs: null,
      idleTimeoutMs: 240000,
    });
    expect(activities).toContainEqual(
      expect.stringContaining("Codex CLI is reviewing batch 2 of 4"),
    );
    expect(activities).toContainEqual(
      expect.stringContaining("batch 2 of 4 · 1m 12s elapsed"),
    );
    expect(controller.state.transcript.at(-1)?.body).toContain(
      "Full scan complete.",
    );
  });

  it("keeps ephemeral command history and opens discoverable help", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();
    await controller.submit("/status");
    await controller.submit("/help");

    expect(controller.state.overlay?.kind).toBe("help");
    expect(controller.state.overlay?.body).toContain("/scanfull");
    expect(controller.history("previous")).toBe("/help");
    expect(controller.history("previous")).toBe("/status");
    expect(controller.history("next")).toBe("/help");
  });

  it("reviews and explicitly confirms an edited commit message", async () => {
    const engine = new FakeEngine();
    const controller = new SessionController({
      repositoryPath: "/repo",
      engine,
    });
    await controller.start();

    await controller.submit("/commit fix: restore token validation");
    const decision = controller.state.pendingDecision;
    expect(decision?.body).toContain("fix: restore token validation");
    await controller.confirm(decision!.id, true);

    expect(engine.requests).toContainEqual({
      command: "commit",
      payload: {
        action: "execute",
        approved: true,
        message: "fix: restore token validation",
        fingerprint: "fingerprint-123",
      },
    });
    expect(controller.state.transcript.at(-1)?.title).toBe("Commit created");
  });
});
