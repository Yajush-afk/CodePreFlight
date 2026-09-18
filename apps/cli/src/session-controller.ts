import { basename } from "node:path";
import {
  EngineClient,
  EngineRequestError,
  type EngineRequestOptions,
} from "./engine-client.js";
import type { EngineCommand, EngineEvent } from "./protocol.js";

export interface SessionEngine {
  request(
    command: EngineCommand,
    repositoryPath: string,
    payload?: Record<string, unknown>,
    onEvent?: (event: EngineEvent) => void,
    options?: EngineRequestOptions,
  ): Promise<Record<string, unknown>>;
  dispose(): void;
}

export interface SessionHeader {
  repository: string;
  root: string;
  branch: string;
  baseBranch: string;
  upstream: string;
  ahead: number;
  behind: number;
  staged: number;
  unstaged: number;
  untracked: number;
  conflicts: number;
  provider: string;
  providerId?: string;
  providerAvailability?: string;
}

export interface TranscriptEntry {
  id: string;
  kind:
    "system" | "user" | "status" | "progress" | "error" | "review" | "answer";
  title?: string;
  body: string;
  data?: Record<string, unknown>;
}

export interface PendingDecision {
  id: string;
  title: string;
  body: string;
  confirmLabel: string;
}

export interface SessionOverlayItem {
  label: string;
  value: string;
  command: string;
}

export interface SessionOverlay {
  kind: "tree" | "branches" | "commits" | "providers" | "preview";
  title: string;
  items?: SessionOverlayItem[];
  body?: string;
}

export interface SessionState {
  started: boolean;
  busy: boolean;
  activity?: string;
  header?: SessionHeader;
  transcript: TranscriptEntry[];
  pendingDecision?: PendingDecision;
  overlay?: SessionOverlay;
  shouldExit: boolean;
}

interface SnapshotFile {
  staged?: boolean;
  unstaged?: boolean;
  untracked?: boolean;
}

interface RepositorySnapshot {
  root?: string;
  branch?: string | null;
  detached_head?: string | null;
  base_branch?: string | null;
  upstream?: string | null;
  ahead?: number;
  behind?: number;
  files?: SnapshotFile[];
  conflicts?: string[];
}

interface ProviderView {
  id?: string;
  name?: string;
  availability?: string;
  authentication?: string;
  model?: string;
  model_name?: string | null;
  sends_code_remotely?: boolean;
  detail?: string;
}

interface ReviewFinding {
  id?: string;
  severity?: string;
  title?: string;
  explanation?: string;
  impact?: string;
  verification?: string;
  recommendation?: string;
  evidence?: Array<{ path?: string; start_line?: number; end_line?: number }>;
}

interface ReviewView {
  status?: string;
  summary?: string;
  findings?: ReviewFinding[];
  blocking?: boolean;
}

type Listener = (state: SessionState) => void;
type Retry = () => Promise<void>;
type ProviderLogin = (provider: string) => Promise<void>;

const HELP = [
  "/status — refresh repository state",
  "/tree — browse tracked and untracked files",
  "/branches — inspect and safely switch local branches",
  "/commits — browse and review reachable commits",
  "/review staged|commit <revision>|branch|pr — run a focused review",
  "/pr — detect an open pull request with GitHub CLI",
  "/provider — inspect provider readiness",
  "/provider login <id> — launch provider-owned authentication",
  "/provider use <id> [model] — preview and select a provider",
  "/provider test <id> — run a synthetic readiness test",
  "/help — show commands",
  "/clear — clear this ephemeral transcript",
  "/close — close the active browser",
  "/quit — exit CodePreflight",
  "Plain text asks a repository-scoped Git or review question.",
].join("\n");

export class SessionController {
  private currentState: SessionState = {
    started: false,
    busy: false,
    transcript: [],
    shouldExit: false,
  };
  private readonly listeners = new Set<Listener>();
  private readonly retries = new Map<string, Retry>();
  private readonly consentDecisions = new Set<string>();
  private readonly approvedProviders = new Set<string>();
  private active?: AbortController;
  private sequence = 0;
  private providers: ProviderView[] = [];
  private activeProviderId?: string;
  private lastReview?: ReviewView;
  private disclosure?: {
    providerId: string;
    providerName: string;
    kind: string;
    characters: number;
    redactions: number;
  };

  constructor(
    private readonly options: {
      repositoryPath: string;
      engine?: SessionEngine;
      loginProvider?: ProviderLogin;
    },
  ) {
    this.engine = options.engine ?? new EngineClient({ persistent: true });
  }

  private readonly engine: SessionEngine;

  get state(): SessionState {
    return this.currentState;
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.currentState);
    return () => this.listeners.delete(listener);
  }

  async start(): Promise<void> {
    if (this.currentState.started) return;
    this.patch({ busy: true, activity: "Inspecting repository…" });
    try {
      await this.refreshContext();
      const header = this.currentState.header;
      this.append({
        kind: "system",
        title: "Ready for preflight",
        body: header
          ? `${header.staged} staged · ${header.unstaged} unstaged · ${header.untracked} untracked · ${header.conflicts} conflicts\nTry /review staged, /status, /provider, or ask what changed.`
          : "Repository session started. Try /status or /help.",
      });
      this.patch({ started: true, busy: false, activity: undefined });
    } catch (error) {
      this.appendError(error);
      this.patch({ started: true, busy: false, activity: undefined });
    }
  }

  async submit(input: string): Promise<void> {
    const value = input.trim();
    if (!value || this.currentState.busy || this.currentState.pendingDecision)
      return;
    if (value === "/clear") {
      this.patch({ transcript: [] });
      return;
    }
    if (value.startsWith("/") && this.currentState.overlay) {
      this.patch({ overlay: undefined });
    }
    this.append({ kind: "user", body: value });
    if (value.startsWith("/")) await this.runCommand(value);
    else await this.ask(value);
  }

  async confirm(decisionId: string, approved: boolean): Promise<void> {
    if (this.currentState.pendingDecision?.id !== decisionId) return;
    const retry = this.retries.get(decisionId);
    this.retries.delete(decisionId);
    this.patch({ pendingDecision: undefined });
    if (!approved) {
      this.append({
        kind: "system",
        body: "Action cancelled; no repository changes were made.",
      });
      return;
    }
    if (this.consentDecisions.delete(decisionId) && this.disclosure?.providerId)
      this.approvedProviders.add(this.disclosure.providerId);
    await retry?.();
  }

  cancel(): void {
    if (this.active) {
      this.active.abort();
      this.active = undefined;
      this.patch({ busy: false, activity: undefined });
      this.append({ kind: "system", body: "Active request cancelled." });
    } else {
      this.patch({ shouldExit: true });
    }
  }

  dispose(): void {
    this.active?.abort();
    this.active = undefined;
    this.retries.clear();
    this.consentDecisions.clear();
    this.approvedProviders.clear();
    this.listeners.clear();
    this.engine.dispose();
    this.currentState = {
      started: false,
      busy: false,
      transcript: [],
      shouldExit: true,
    };
  }

  private async runCommand(value: string): Promise<void> {
    const [command, ...args] = value.slice(1).split(/\s+/);
    if (command === "quit" || command === "exit") {
      this.patch({ shouldExit: true });
      return;
    }
    if (command === "help") {
      this.append({ kind: "system", title: "Commands", body: HELP });
      return;
    }
    if (command === "close") {
      this.patch({ overlay: undefined });
      return;
    }
    if (command === "status") {
      await this.runBusy("Refreshing repository status…", async () => {
        await this.refreshContext();
        this.appendStatus();
      });
      return;
    }
    if (command === "review") {
      const target = args[0] ?? "staged";
      if (
        !(["staged", "commit", "branch", "pr"] as string[]).includes(target)
      ) {
        this.append({
          kind: "error",
          title: "Unknown review target",
          body: "Use /review staged, /review commit <revision>, /review branch, or /review pr.",
        });
        return;
      }
      if (target === "commit" && !args[1]) {
        this.append({
          kind: "error",
          title: "Commit required",
          body: "Select a commit with /commits or pass /review commit <revision>.",
        });
        return;
      }
      await this.review(target === "pr" ? "pull_request" : target, args[1]);
      return;
    }
    if (command === "tree" || command === "branches" || command === "commits") {
      await this.openWorkspace(command);
      return;
    }
    if (command === "file" && args[0]) {
      await this.previewFile(decodeURIComponent(args[0]));
      return;
    }
    if (command === "switch" && args[0]) {
      await this.previewSwitch(decodeURIComponent(args[0]));
      return;
    }
    if (command === "pr") {
      await this.detectPullRequest();
      return;
    }
    if (command === "provider") {
      if (args[0] === "login" && args[1]) {
        await this.login(args[1]);
      } else if (args[0] === "use" && args[1]) {
        await this.configureProvider(args[1], args[2]);
      } else if (args[0] === "test" && args[1]) {
        this.requestDecision(
          `Test ${args[1]}?`,
          "This sends synthetic code only, but may consume provider usage.",
          "run smoke test",
          async () => this.testProvider(args[1]),
        );
      } else this.openProviders();
      return;
    }
    this.append({
      kind: "error",
      title: "Unknown command",
      body: `/${command} is not available. Use /help to see supported commands.`,
    });
  }

  private async refreshContext(): Promise<void> {
    const request = this.beginRequest();
    const [status, providerResult] = await Promise.all([
      this.engine.request(
        "status",
        this.options.repositoryPath,
        {},
        undefined,
        { signal: request.signal },
      ),
      this.engine.request(
        "provider",
        this.options.repositoryPath,
        { action: "list" },
        undefined,
        { signal: request.signal },
      ),
    ]);
    this.finishRequest(request);
    const snapshot = status.repository as RepositorySnapshot;
    const configuration = status.configuration as
      { review?: { provider?: string } } | undefined;
    this.providers =
      (providerResult.providers as ProviderView[] | undefined) ?? [];
    this.activeProviderId = configuration?.review?.provider;
    const selected = this.providers.find(
      (item) => item.id === this.activeProviderId,
    );
    const files = snapshot.files ?? [];
    const root = snapshot.root ?? this.options.repositoryPath;
    this.patch({
      header: {
        repository: basename(root),
        root,
        branch:
          snapshot.branch ??
          `detached @ ${snapshot.detached_head ?? "unknown"}`,
        baseBranch: snapshot.base_branch ?? "not detected",
        upstream: snapshot.upstream ?? "no upstream",
        ahead: snapshot.ahead ?? 0,
        behind: snapshot.behind ?? 0,
        staged: files.filter((file) => file.staged).length,
        unstaged: files.filter((file) => file.unstaged).length,
        untracked: files.filter((file) => file.untracked).length,
        conflicts: snapshot.conflicts?.length ?? 0,
        provider: selected?.name ?? "Not configured",
        providerId: selected?.id,
        providerAvailability: selected?.availability,
      },
    });
  }

  private appendStatus(): void {
    const header = this.currentState.header;
    if (!header) return;
    this.append({
      kind: "status",
      title: "Repository status",
      body:
        `${header.branch} → ${header.baseBranch} · ${header.ahead} ahead / ${header.behind} behind\n` +
        `${header.staged} staged · ${header.unstaged} unstaged · ${header.untracked} untracked · ${header.conflicts} conflicts`,
    });
  }

  private appendProviders(): void {
    const body = this.providers
      .map(
        (provider) =>
          `${provider.id === this.activeProviderId ? "●" : "○"} ${provider.name ?? provider.id} · ${provider.availability ?? "unknown"} · ${provider.authentication ?? "unknown"}` +
          `${provider.model_name ? ` · ${provider.model_name}` : ""}` +
          `${provider.detail ? `\n  ${provider.detail}` : ""}`,
      )
      .join("\n");
    this.append({
      kind: "status",
      title: "Providers",
      body: body || "No providers detected.",
    });
  }

  private openProviders(): void {
    this.appendProviders();
    this.patch({
      overlay: {
        kind: "providers",
        title: "Review providers",
        items: this.providers.map((provider) => ({
          label: `${provider.id === this.activeProviderId ? "●" : "○"} ${provider.name ?? provider.id} · ${provider.availability ?? "unknown"}`,
          value: provider.id ?? "unknown",
          command: `/provider use ${provider.id ?? ""}${provider.model_name ? ` ${provider.model_name}` : ""}`,
        })),
      },
    });
  }

  private async openWorkspace(
    action: "tree" | "branches" | "commits",
  ): Promise<void> {
    await this.runBusy(`Loading ${action}…`, async () => {
      const result = await this.engine.request(
        "workspace",
        this.options.repositoryPath,
        { action },
      );
      const raw =
        (result.items as Array<Record<string, unknown>> | undefined) ?? [];
      const items = raw.map((item) => {
        if (action === "tree") {
          const path = String(item.path ?? "");
          return {
            label: `${String(item.status ?? "clean").padEnd(16)} ${path}`,
            value: path,
            command: `/file ${encodeURIComponent(path)}`,
          };
        }
        if (action === "branches") {
          const branch = String(item.name ?? "");
          return {
            label: `${item.current ? "●" : "○"} ${branch} · ${String(item.subject ?? "")}`,
            value: branch,
            command: item.current
              ? "/close"
              : `/switch ${encodeURIComponent(branch)}`,
          };
        }
        const revision = String(item.oid ?? "");
        return {
          label: `${item.merge ? "merge " : ""}${String(item.shortOid ?? "")} · ${String(item.subject ?? "")}`,
          value: revision,
          command: `/review commit ${revision}`,
        };
      });
      this.patch({
        overlay: {
          kind: action,
          title:
            action === "tree"
              ? "Repository tree"
              : action === "branches"
                ? "Local branches"
                : "Current branch commits",
          items,
        },
      });
    });
  }

  private async previewFile(path: string): Promise<void> {
    await this.runBusy(`Opening ${path}…`, async () => {
      const result = await this.engine.request(
        "workspace",
        this.options.repositoryPath,
        { action: "file", path },
      );
      this.patch({
        overlay: {
          kind: "preview",
          title: path,
          body: String(
            result.diff ?? result.content ?? "No preview available.",
          ),
        },
      });
    });
  }

  private async previewSwitch(branch: string): Promise<void> {
    await this.runBusy(`Checking switch to ${branch}…`, async () => {
      const preview = await this.engine.request(
        "git_action",
        this.options.repositoryPath,
        { action: "switch_preview", branch },
      );
      this.patch({ overlay: undefined });
      if (!preview.allowed) {
        this.append({
          kind: "error",
          title: "Branch switch blocked",
          body: `Local paths would be overwritten:\n${((preview.collisions as string[]) ?? []).join("\n")}`,
        });
        return;
      }
      const preserved = ((preview.preservedPaths as string[]) ?? []).join(", ");
      this.requestDecision(
        `Switch to ${branch}?`,
        `Current branch: ${String(preview.currentBranch)}\nPreserved local paths: ${preserved || "none"}`,
        "switch branch",
        async () => {
          await this.runBusy(`Switching to ${branch}…`, async () => {
            await this.engine.request(
              "git_action",
              this.options.repositoryPath,
              {
                action: "switch_execute",
                branch,
                approved: true,
                expectedHead: preview.expectedHead,
              },
            );
            this.lastReview = undefined;
            this.disclosure = undefined;
            await this.refreshContext();
            this.append({
              kind: "system",
              title: "Branch changed",
              body: `Switched to ${branch}. Branch-scoped review context was cleared.`,
            });
          });
        },
      );
    });
  }

  private async detectPullRequest(): Promise<void> {
    await this.runBusy("Checking GitHub pull requests…", async () => {
      const result = await this.engine.request(
        "workspace",
        this.options.repositoryPath,
        { action: "pr" },
      );
      this.append({
        kind: "status",
        title: "Pull request",
        body: result.found
          ? `#${String(result.number)} · ${String(result.state)} · ${String(result.url)}\nBase: ${String(result.baseBranch)} · local HEAD ${result.localHeadMatches ? "matches" : "differs from"} remote head`
          : "No open pull request was found for the current branch.",
      });
    });
  }

  private async login(provider: string): Promise<void> {
    if (!this.options.loginProvider) {
      this.append({
        kind: "error",
        title: "Interactive login unavailable",
        body: `Run preflight provider login ${provider} in another terminal.`,
      });
      return;
    }
    await this.runBusy(`Opening ${provider} login…`, async () => {
      await this.options.loginProvider?.(provider);
      await this.refreshContext();
      this.append({
        kind: "system",
        body: `${provider} authentication refreshed.`,
      });
    });
  }

  private async configureProvider(
    provider: string,
    model?: string,
  ): Promise<void> {
    await this.runBusy("Preparing provider configuration…", async () => {
      const preview = await this.engine.request(
        "provider",
        this.options.repositoryPath,
        { action: "configure", provider, model, write: false },
      );
      this.append({
        kind: "status",
        title: "Provider configuration preview",
        body: String(
          preview.diff ?? preview.preview ?? "No configuration change.",
        ),
      });
      this.requestDecision(
        `Use ${provider}${model ? ` · ${model}` : ""}?`,
        "This updates the repository's non-secret .codepreflight.toml configuration.",
        "write configuration",
        async () => {
          await this.runBusy("Saving provider configuration…", async () => {
            await this.engine.request("provider", this.options.repositoryPath, {
              action: "configure",
              provider,
              model,
              write: true,
            });
            await this.refreshContext();
            this.append({
              kind: "system",
              body: `${provider} is now the review provider.`,
            });
          });
        },
      );
    });
  }

  private async testProvider(provider: string): Promise<void> {
    await this.runBusy(
      `Testing ${provider} with synthetic content…`,
      async () => {
        const result = await this.engine.request(
          "provider",
          this.options.repositoryPath,
          {
            action: "test",
            provider,
          },
        );
        this.append({
          kind: "status",
          title: "Provider test",
          body: `${provider} · ${result.ready ? "ready" : "failed"}\n${String(result.summary ?? "")}`,
        });
      },
    );
  }

  private async review(target: string, revision?: string): Promise<void> {
    if (!this.activeProviderId) {
      this.append({
        kind: "error",
        title: "Select a review provider",
        body: "Use /provider to inspect available providers, then run /provider use <id>.",
      });
      return;
    }
    const retry = async (): Promise<void> => this.review(target, revision);
    await this.runBusy(
      `Preparing ${target.replace("_", " ")} review…`,
      async () => {
        this.disclosure = undefined;
        const request = this.beginRequest();
        try {
          const result = await this.engine.request(
            "review",
            this.options.repositoryPath,
            {
              target,
              revision,
              remoteApproved: this.activeProviderId
                ? this.approvedProviders.has(this.activeProviderId)
                : false,
            },
            (event) => this.handleEngineEvent(event),
            { signal: request.signal },
          );
          this.lastReview = result as ReviewView;
          this.appendReview(this.lastReview);
        } catch (error) {
          if (
            error instanceof EngineRequestError &&
            error.code === "provider_consent_required" &&
            this.disclosure
          ) {
            this.requestConsent(retry);
            return;
          }
          throw error;
        } finally {
          this.finishRequest(request);
        }
      },
    );
  }

  private async ask(question: string): Promise<void> {
    const findingMatch = question.match(/^explain finding\s+(\d+)$/i);
    if (findingMatch && this.lastReview) {
      const finding = this.lastReview.findings?.[Number(findingMatch[1]) - 1];
      if (finding) {
        this.append({
          kind: "answer",
          title: finding.title,
          body: `${finding.explanation}\nImpact: ${finding.impact}\nInspect: ${finding.recommendation}`,
        });
        return;
      }
    }
    if (!this.activeProviderId) {
      this.append({
        kind: "error",
        title: "Select a review provider",
        body: "Repository questions require a provider. Use /provider first.",
      });
      return;
    }
    const target = /branch|commit/i.test(question) ? "branch" : "staged";
    const retry = async (): Promise<void> => this.ask(question);
    await this.runBusy("Gathering repository evidence…", async () => {
      this.disclosure = undefined;
      const request = this.beginRequest();
      try {
        try {
          const response = await this.engine.request(
            "explain",
            this.options.repositoryPath,
            {
              mode: "ask",
              question,
              target,
              remoteApproved: this.activeProviderId
                ? this.approvedProviders.has(this.activeProviderId)
                : false,
            },
            (event) => this.handleEngineEvent(event),
            { signal: request.signal },
          );
          const result = response.result as
            | { answer?: string; summary?: string; uncertainty?: string }
            | undefined;
          this.append({
            kind: "answer",
            body:
              result?.answer ??
              result?.summary ??
              "The provider returned no explanation.",
          });
        } catch (error) {
          if (
            error instanceof EngineRequestError &&
            error.code === "provider_consent_required" &&
            this.disclosure
          ) {
            this.requestConsent(retry);
            return;
          }
          throw error;
        }
      } finally {
        this.finishRequest(request);
      }
    });
  }

  private handleEngineEvent(event: EngineEvent): void {
    if (event.event === "progress") {
      this.patch({ activity: String(event.payload?.message ?? "Working…") });
    }
    if (event.event === "consent_required") {
      const provider = event.payload?.provider as
        { id?: string; name?: string; kind?: string } | undefined;
      const manifest = event.payload?.manifest as
        { total_characters?: number; redactions?: number } | undefined;
      this.disclosure = {
        providerId: provider?.id ?? "unknown",
        providerName: provider?.name ?? "unknown provider",
        kind: provider?.kind ?? "unknown",
        characters: manifest?.total_characters ?? 0,
        redactions: manifest?.redactions ?? 0,
      };
    }
  }

  private requestConsent(retry: Retry): void {
    if (!this.disclosure) return;
    const id = this.nextId("decision");
    this.retries.set(id, retry);
    this.consentDecisions.add(id);
    this.patch({
      pendingDecision: {
        id,
        title: `Send context to ${this.disclosure.providerName}?`,
        body:
          `${this.disclosure.kind} · ${this.disclosure.characters.toLocaleString()} characters · ` +
          `${this.disclosure.redactions} redactions\nApproval lasts only for this provider and open session.`,
        confirmLabel: "Approve once for this session",
      },
    });
  }

  private requestDecision(
    title: string,
    body: string,
    confirmLabel: string,
    retry: Retry,
  ): void {
    const id = this.nextId("decision");
    this.retries.set(id, retry);
    this.patch({ pendingDecision: { id, title, body, confirmLabel } });
  }

  private appendReview(review: ReviewView): void {
    const findings = review.findings ?? [];
    const body = [
      review.summary ?? "No summary returned.",
      ...findings.map((finding, index) => {
        const evidence = finding.evidence?.[0];
        return `${index + 1}. ${(finding.severity ?? "info").toUpperCase()} · ${finding.title ?? "Finding"} · ${evidence?.path ?? "unknown"}:${evidence?.start_line ?? "?"} · ${finding.verification ?? "unverified"}`;
      }),
      findings.length
        ? "Ask “explain finding 1” for detail."
        : "No verified findings.",
    ].join("\n");
    this.append({
      kind: "review",
      title: review.blocking ? "Review · blocking" : "Review complete",
      body,
      data: review as Record<string, unknown>,
    });
  }

  private async runBusy(
    label: string,
    operation: () => Promise<void>,
  ): Promise<void> {
    this.patch({ busy: true, activity: label });
    try {
      await operation();
    } catch (error) {
      if (!(
        error instanceof EngineRequestError && error.code === "engine_cancelled"
      )) {
        this.appendError(error);
      }
    } finally {
      this.patch({ busy: false, activity: undefined });
    }
  }

  private appendError(error: unknown): void {
    const failure = error instanceof Error ? error : new Error(String(error));
    const detail =
      failure instanceof EngineRequestError && failure.details?.actions
        ? `\nRecovery: ${JSON.stringify(failure.details.actions)}`
        : "";
    this.append({
      kind: "error",
      title: "Request could not be completed",
      body: `${failure.message}${detail}`,
    });
  }

  private beginRequest(): AbortController {
    this.active?.abort();
    const request = new AbortController();
    this.active = request;
    return request;
  }

  private finishRequest(request: AbortController): void {
    if (this.active === request) this.active = undefined;
  }

  private append(entry: Omit<TranscriptEntry, "id">): void {
    this.patch({
      transcript: [
        ...this.currentState.transcript,
        { ...entry, id: this.nextId("entry") },
      ],
    });
  }

  private patch(update: Partial<SessionState>): void {
    this.currentState = { ...this.currentState, ...update };
    for (const listener of this.listeners) listener(this.currentState);
  }

  private nextId(prefix: string): string {
    this.sequence += 1;
    return `${prefix}-${this.sequence}`;
  }
}
