import { basename } from "node:path";
import {
  EngineClient,
  EngineRequestError,
  type EngineRequestOptions,
} from "./engine-client.js";
import type { EngineCommand, EngineEvent } from "./protocol.js";
import { ActivityStore, type OperationRecord } from "./activity-store.js";
import { CommandRegistry, type Suggestion } from "./command-registry.js";
import { SuggestionCoordinator } from "./suggestion-coordinator.js";
import { OnboardingCoordinator } from "./onboarding-coordinator.js";
import { WorkflowCoordinator } from "./workflow-coordinator.js";
import { GitGraphPresenter, type GitGraph } from "./git-graph-presenter.js";
import { WorkspacePresenter } from "./workspace-presenter.js";

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
  providerAuthentication?: string;
  providerModel?: string;
  providerVariant?: string;
  providerPrivacy?: string;
  pullRequest?: string;
  reviewMode: string;
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
  command?: string;
  action?: SessionAction;
}

export interface SessionAction {
  kind:
    | "model"
    | "variant"
    | "provider"
    | "mode"
    | "file"
    | "branch"
    | "commit"
    | "review"
    | "setup"
    | "close";
  value: string;
}

export interface SessionOverlay {
  kind: "tree" | "branches" | "commits" | "providers" | "preview" | "help";
  title: string;
  items?: SessionOverlayItem[];
  body?: string;
}

export interface SessionState {
  started: boolean;
  busy: boolean;
  activity?: string;
  activeActor?: string;
  interruptionNotice?: string;
  header?: SessionHeader;
  graph?: GitGraph;
  transcript: TranscriptEntry[];
  pendingDecision?: PendingDecision;
  overlay?: SessionOverlay;
  pipeline?: Array<{
    label: string;
    status: "pending" | "active" | "complete" | "failed";
  }>;
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
  installation?: string;
  id?: string;
  name?: string;
  availability?: string;
  readiness?: { state: string; invocationVerified: boolean };
  authentication?: string;
  model?: string;
  model_name?: string | null;
  variant_name?: string | null;
  sends_code_remotely?: boolean;
  detail?: string;
  kind?: string;
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

interface AutomationView {
  mode?: string;
  grant?: Record<string, unknown> | null;
  jobs?: Array<Record<string, unknown>>;
}

type Listener = (state: SessionState) => void;
type Retry = () => Promise<void>;
type ProviderLogin = (provider: string) => Promise<void>;

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
  private automation: AutomationView = {};
  private lastReview?: ReviewView;
  private disclosure?: {
    providerId: string;
    providerName: string;
    kind: string;
    characters: number;
    redactions: number;
  };
  private fullScanManifest?: Record<string, unknown>;
  private pollTimer?: NodeJS.Timeout;
  private readonly seenJobs = new Set<string>();
  private readonly commandHistory: string[] = [];
  private historyIndex = 0;

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
  private readonly activityStore = new ActivityStore();
  private readonly commands = new CommandRegistry();
  private readonly onboarding = new OnboardingCoordinator();
  private readonly workflow = new WorkflowCoordinator();
  private interruptionTimer?: ReturnType<typeof setTimeout>;
  private repositoryTrusted = false;
  private repositoryConfiguration: unknown;
  private readonly suggestions = new SuggestionCoordinator(
    this.commands,
    (command) => this.loadArguments(command),
  );

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
      await this.observeAutomationEvent("launch");
      const header = this.currentState.header;
      this.append({
        kind: "system",
        title: "Ready for preflight",
        body: header
          ? `${header.staged} staged · ${header.unstaged} unstaged · ${header.untracked} untracked · ${header.conflicts} conflicts\nSuggested: ${this.suggestedActions(header).join(" · ")}`
          : "Repository session started. Try /status or /help.",
      });
      this.appendAutomationUpdates();
      this.patch({ started: true, busy: false, activity: undefined });
      if (
        !this.activeProvider() ||
        (this.activeProvider()?.readiness?.state ??
          this.activeProvider()?.availability) !== "ready" ||
        !this.repositoryTrusted
      )
        this.startSetup();
      this.startJobObservation();
    } catch (error) {
      this.appendError(error);
      this.patch({ started: true, busy: false, activity: undefined });
    }
  }

  async submit(input: string): Promise<void> {
    const value = input.trim();
    if (value === "/close") {
      this.patch({ overlay: undefined });
      return;
    }
    if (!value || this.currentState.busy || this.currentState.pendingDecision)
      return;
    if (this.commandHistory.at(-1) !== value) this.commandHistory.push(value);
    this.historyIndex = this.commandHistory.length;
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

  history(direction: "previous" | "next"): string {
    if (!this.commandHistory.length) return "";
    this.historyIndex =
      direction === "previous"
        ? Math.max(0, this.historyIndex - 1)
        : Math.min(this.commandHistory.length, this.historyIndex + 1);
    return this.commandHistory[this.historyIndex] ?? "";
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
    if (this.currentState.busy) {
      this.active?.abort();
      this.engine.dispose();
      this.active = undefined;
      this.retries.clear();
      this.consentDecisions.clear();
      this.activityStore.cancel();
      this.patch({
        busy: false,
        activity: undefined,
        activeActor: undefined,
        pendingDecision: undefined,
        interruptionNotice: undefined,
        pipeline: undefined,
      });
      this.append({ kind: "system", body: "Active request cancelled." });
    }
  }

  interrupt(): void {
    const decision = this.workflow.interrupt(
      this.currentState.activeActor,
      this.currentState.busy,
    );
    if (decision === "cancel") {
      this.cancel();
      return;
    }
    if (decision === "confirm") {
      if (this.interruptionTimer) clearTimeout(this.interruptionTimer);
      this.patch({
        interruptionNotice: `Press Esc again within 2 seconds to stop ${this.currentState.header?.provider ?? "the reviewer"}`,
      });
      this.interruptionTimer = setTimeout(
        () => this.patch({ interruptionNotice: undefined }),
        2000,
      );
    }
  }

  dispose(): void {
    if (this.interruptionTimer) clearTimeout(this.interruptionTimer);
    this.activityStore.clear();
    this.active?.abort();
    this.active = undefined;
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = undefined;
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
    const correction = this.commands.correction(value);
    if (correction) {
      this.requestDecision(
        "Command renamed",
        `Use ${correction} instead.`,
        "use corrected command",
        async () => this.runCommand(correction),
      );
      return;
    }
    const { name, argument } = this.commands.parse(value);
    if (!name.startsWith("review") && name !== "scanfull")
      this.patch({ pipeline: undefined });
    const handlers: Record<string, () => void | Promise<void>> = {
      quit: () => this.patch({ shouldExit: true }),
      help: () =>
        this.patch({
          overlay: {
            kind: "help",
            title: "Commands and questions",
            body: this.commands.help(),
          },
        }),
      close: () => this.patch({ overlay: undefined }),
      status: () =>
        this.runBusy("Refreshing repository status…", async () => {
          await this.refreshContext();
          await this.observeAutomationEvent("refresh");
          this.appendStatus();
        }),
      files: () => this.openWorkspace("tree"),
      graph: () => this.openGraph(),
      branches: () => this.openWorkspace("branches"),
      commits: () => this.openWorkspace("commits"),
      file: () => this.previewFile(argument),
      switchbranch: () => this.previewSwitch(argument),
      pr: () => this.detectPullRequest(),
      review: () => this.openReviewPicker(),
      reviewstaged: () => this.review("staged"),
      reviewbranch: () => this.review("branch"),
      reviewpr: () => this.review("pull_request"),
      reviewcommit: () =>
        argument
          ? this.review("commit", argument)
          : this.openWorkspace("commits"),
      scanfull: () => this.fullScan(false),
      commit: () => this.commit(argument || undefined),
      provider: () => this.startSetup(),
      model: () => this.openModels(),
      variant: () => this.openVariants(),
      providerlogin: () =>
        argument ? this.confirmLogin(argument) : this.openProviders(),
      providerswitch: () =>
        argument ? this.configureProvider(argument) : this.openProviders(),
      providertest: () =>
        this.confirmProviderTest(argument || this.activeProviderId || ""),
      mode: () => this.openModes(),
      jobs: () => this.appendJobs(),
      automationgrant: () => this.configureGrant(false),
      automationrevoke: () => this.configureGrant(true),
      activity: () =>
        this.patch({
          overlay: {
            kind: "preview",
            title: "Session activity",
            body: this.activityStore.describe(),
          },
        }),
    };
    const handler = handlers[name];
    if (handler) await handler();
    else
      this.append({
        kind: "error",
        title: "Unknown command",
        body: `/${name} is unavailable. Use /help.`,
      });
  }

  private confirmProviderTest(provider: string): void {
    this.requestDecision(
      `Test ${provider}?`,
      "Synthetic code only; this may consume provider usage.",
      "run smoke test",
      async () => this.testProvider(provider),
    );
  }

  private openReviewPicker(): void {
    this.patch({
      overlay: {
        kind: "preview",
        title: "What would you like to review?",
        items: ["staged", "branch", "commit", "pull_request"].map((target) => ({
          label: target === "pull_request" ? "Existing PR" : target,
          value: target,
          action: { kind: "review", value: target },
        })),
      },
    });
  }

  async select(action: SessionAction): Promise<void> {
    if (this.currentState.busy || this.currentState.pendingDecision) return;
    this.patch({ overlay: undefined });
    const handlers: Record<SessionAction["kind"], () => void | Promise<void>> =
      {
        model: () =>
          this.configureProvider(this.activeProviderId ?? "", action.value),
        variant: () =>
          this.configureProvider(
            this.activeProviderId ?? "",
            this.activeProvider()?.model_name ?? undefined,
            action.value,
          ),
        provider: () => this.configureProvider(action.value),
        mode: () => this.configureMode(action.value),
        file: () => this.previewFile(action.value),
        branch: () => this.previewSwitch(action.value),
        commit: () => this.review("commit", action.value),
        review: () =>
          action.value === "commit"
            ? this.openWorkspace("commits")
            : this.review(action.value),
        close: () => {},
        setup: () => this.setupAction(action.value),
      };
    await handlers[action.kind]();
  }

  private startSetup(): void {
    this.onboarding.active = true;
    this.continueSetup();
  }

  private continueSetup(): void {
    if (!this.onboarding.active) return;
    const step = this.onboarding.next(
      this.activeProvider(),
      this.repositoryTrusted,
    );
    if (!step) {
      this.onboarding.active = false;
      this.openProviders();
      return;
    }
    const items: SessionOverlayItem[] = [
      {
        label: step.label,
        value: step.action,
        action: { kind: "setup", value: step.action },
      },
    ];
    if (step.optional)
      items.push({
        label: "Skip this optional step",
        value: "next",
        action: { kind: "setup", value: `skip:${step.action}` },
      });
    items.push({
      label: "Continue without AI",
      value: "skip",
      action: { kind: "setup", value: "skip" },
    });
    this.patch({
      overlay: { kind: "providers", title: step.title, body: step.body, items },
    });
  }

  private async setupAction(action: string): Promise<void> {
    if (action === "skip") {
      this.onboarding.active = false;
      this.patch({ overlay: undefined });
      return;
    }
    if (action.startsWith("skip:")) {
      this.onboarding.skip(this.activeProvider(), action.slice(5));
      this.continueSetup();
      return;
    }
    const provider = this.activeProviderId ?? "";
    const handlers: Record<string, () => void | Promise<void>> = {
      providers: () => this.openProviders(),
      login: () => this.confirmLogin(provider),
      model: () => this.openModels(),
      variant: () => this.openVariants(),
      test: () => this.confirmProviderTest(provider),
      trust: () => this.confirmTrust(),
    };
    await handlers[action]?.();
  }

  private confirmTrust(): void {
    this.requestDecision(
      "Trust this repository configuration?",
      JSON.stringify(this.repositoryConfiguration, null, 2),
      "trust configuration",
      async () => {
        await this.runBusy("Saving repository trust…", async () => {
          await this.engine.request("init", this.options.repositoryPath, {
            trust: true,
          });
          await this.refreshContext();
        });
        this.continueSetup();
      },
    );
  }

  async suggest(input: string): Promise<Suggestion[]> {
    const items = await this.suggestions.suggest(input);
    const provider = this.activeProvider();
    return items.map((item) => {
      const requiresAI =
        item.value.startsWith("review") || item.value === "scanfull";
      const ready = provider?.readiness?.state ?? provider?.availability;
      const disabled =
        requiresAI && ready !== "ready"
          ? "Reviewer unavailable · /provider to fix"
          : item.value === "scanfull" &&
              !provider?.readiness?.invocationVerified
            ? "Test your reviewer first · /providertest"
            : undefined;
      return { ...item, disabled };
    });
  }

  private async loadArguments(command: string): Promise<Suggestion[]> {
    if (command.startsWith("provider")) {
      const providers = this.providers.filter(
        (item) => item.installation !== "missing",
      );
      providers.sort(
        (a, b) =>
          Number(b.id === this.activeProviderId) -
          Number(a.id === this.activeProviderId),
      );
      if (command === "providerlogin")
        providers.sort(
          (a, b) =>
            Number(b.authentication === "required") -
            Number(a.authentication === "required"),
        );
      return providers.map((item) => ({
        value: item.id ?? "",
        label: item.name ?? item.id ?? "",
        context: `${item.readiness?.state ?? item.availability} · ${item.authentication}`,
        completion: `/${command} ${item.id}`,
      }));
    }
    const action =
      command === "reviewcommit"
        ? "commits"
        : command === "switchbranch"
          ? "branches"
          : "tree";
    const result = await this.engine.request(
      "workspace",
      this.options.repositoryPath,
      { action },
    );
    const items = (result.items ?? []) as Array<Record<string, unknown>>;
    const eligible = items.filter(
      (item) => action !== "branches" || !item.current,
    );
    if (action === "tree")
      eligible.sort(
        (a, b) => Number(a.status === "clean") - Number(b.status === "clean"),
      );
    return eligible.map((item) => {
      const value = String(item.oid ?? item.name ?? item.path ?? "");
      return {
        value,
        label: String(item.shortOid ?? value),
        context: String(item.subject ?? item.status ?? ""),
        completion: `/${command} ${value}`,
      };
    });
  }

  private async refreshContext(): Promise<void> {
    this.suggestions.invalidate();
    const request = this.beginRequest();
    const [status, providerResult, automationResult] = await Promise.all([
      this.engine.request(
        "status",
        this.options.repositoryPath,
        {},
        (event) => this.handleEngineEvent(event),
        { signal: request.signal },
      ),
      this.engine.request(
        "provider",
        this.options.repositoryPath,
        { action: "list" },
        undefined,
        { signal: request.signal },
      ),
      this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action: "status" },
        undefined,
        { signal: request.signal },
      ),
    ]).finally(() => this.finishRequest(request));
    const snapshot = status.repository as RepositorySnapshot;
    const configuration = status.configuration as
      { review?: { provider?: string } } | undefined;
    this.repositoryTrusted = status.trusted === true;
    this.repositoryConfiguration = status.configuration;
    this.providers =
      (providerResult.providers as ProviderView[] | undefined) ?? [];
    this.activeProviderId = configuration?.review?.provider;
    this.automation = automationResult as AutomationView;
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
        ...this.providerHeader(selected),
        pullRequest: "not checked",
        reviewMode: this.automation.mode ?? "manual",
      },
    });
    await this.refreshGraph();
  }

  private async refreshGraph(announce = false): Promise<void> {
    try {
      const graph = (await this.engine.request(
        "workspace",
        this.options.repositoryPath,
        { action: "graph" },
      )) as unknown as GitGraph;
      if (!Array.isArray(graph.lanes)) return;
      const previous = this.currentState.graph;
      if (previous?.fingerprint === graph.fingerprint) return;
      this.suggestions.invalidate();
      if (previous && announce) {
        this.lastReview = undefined;
        this.fullScanManifest = undefined;
        this.append({
          kind: "system",
          body: `Git changed: ${graph.current} at ${graph.head?.slice(0, 7) ?? "unborn HEAD"}. Review context refreshed.`,
        });
      }
      const header = this.currentState.header;
      this.patch({
        graph,
        header: header
          ? {
              ...header,
              branch: graph.current,
              staged: graph.workingTree.staged,
              unstaged: graph.workingTree.unstaged,
              untracked: graph.workingTree.untracked,
            }
          : header,
      });
    } catch {
      this.patch({ graph: undefined });
    }
  }

  private async openGraph(): Promise<void> {
    await this.runBusy("Reading local commit graph…", async () => {
      await this.refreshGraph();
      const graph = this.currentState.graph;
      this.patch({
        overlay: {
          kind: "preview",
          title: "Local commit graph",
          body: graph
            ? new GitGraphPresenter()
                .lines(graph)
                .map((line) => line.text)
                .join("\n")
            : "Graph unavailable. Use /status to inspect repository state.",
        },
      });
    });
  }

  private providerHeader(
    selected?: ProviderView,
  ): Partial<SessionHeader> & { provider: string } {
    return {
      provider: selected?.name ?? "Not configured",
      providerId: selected?.id,
      providerAvailability:
        selected?.readiness?.state === "action_required"
          ? "Action required"
          : (selected?.readiness?.state ?? selected?.availability),
      providerAuthentication: selected?.authentication,
      providerModel:
        selected?.model_name ??
        (selected?.model === "not_applicable"
          ? "provider default"
          : (selected?.model ?? "unknown")),
      providerVariant: selected?.variant_name ?? "provider default",
      providerPrivacy: selected
        ? selected.sends_code_remotely
          ? `remote ${selected.kind ?? "provider"}`
          : "local"
        : "not configured",
    };
  }

  private openModes(): void {
    const selected = this.automation.mode ?? "manual";
    this.patch({
      overlay: {
        kind: "providers",
        title: "Review cadence",
        items: [
          ["manual", "Manual · reviews only when requested"],
          ["auto", "Auto · review new or changed open PRs"],
          ["auto_plus", "Auto+ · commit, pre-push, and PR reviews"],
        ].map(([mode, label]) => ({
          label: `${mode === selected ? "●" : "○"} ${label}`,
          value: mode,
          action: { kind: "mode", value: mode },
        })),
      },
    });
  }

  private async configureMode(mode: string): Promise<void> {
    await this.runBusy("Preparing review-mode change…", async () => {
      const preview = await this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action: "configure", mode, write: false },
      );
      const hooks = (
        (preview.hookResults as Array<Record<string, unknown>>) ?? []
      )
        .map((item) => `${String(item.hook)}: ${String(item.action)}`)
        .join("\n");
      this.requestDecision(
        `Use ${mode === "auto_plus" ? "Auto+" : mode === "auto" ? "Auto" : "Manual"} mode?`,
        `${mode === "manual" ? "Managed automation hooks will be removed." : "Managed post-commit and pre-push hooks will be installed where safe."}${hooks ? `\n${hooks}` : ""}`,
        "apply mode",
        async () => {
          await this.runBusy("Applying review mode…", async () => {
            const result = await this.engine.request(
              "automation",
              this.options.repositoryPath,
              { action: "configure", mode, write: true },
            );
            await this.refreshContext();
            this.append({
              kind: "system",
              title: "Review mode updated",
              body: `${String(result.mode)} is active.${mode === "manual" ? "" : " Approve an automation grant with /automationgrant before closed-session provider use."}`,
            });
          });
        },
      );
    });
  }

  private async configureGrant(revoke: boolean): Promise<void> {
    await this.runBusy("Inspecting automation grant…", async () => {
      const action = revoke ? "revoke_grant" : "grant";
      const preview = await this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action, write: false },
      );
      this.requestDecision(
        revoke
          ? "Revoke automation grant?"
          : "Approve closed-session automation?",
        revoke
          ? "Queued remote jobs will wait until a new scoped grant is approved."
          : `Scope: ${JSON.stringify(preview.grant)}\nThe grant contains no credentials and invalidates when provider or repository configuration changes.`,
        revoke ? "revoke grant" : "approve scoped grant",
        async () => {
          await this.runBusy("Updating automation grant…", async () => {
            const result = await this.engine.request(
              "automation",
              this.options.repositoryPath,
              {
                action,
                write: true,
              },
            );
            if (!revoke) {
              const resumed =
                (result.resumedJobs as Array<Record<string, unknown>>) ?? [];
              for (const job of resumed) {
                if (job.id) void this.runAutomationJob(String(job.id));
              }
            }
            await this.refreshContext();
            this.append({
              kind: "system",
              body: revoke
                ? "Automation grant revoked."
                : "Scoped automation grant approved.",
            });
          });
        },
      );
    });
  }

  private appendJobs(): void {
    const jobs = this.automation.jobs ?? [];
    this.append({
      kind: "status",
      title: "Automation jobs",
      body: jobs.length
        ? jobs
            .slice(0, 20)
            .map(
              (job) =>
                `${String(job.status)} · ${String(job.target)} · ${String(job.revision).slice(0, 8)}${job.message ? ` · ${String(job.message)}` : ""}`,
            )
            .join("\n")
        : "No automation jobs have been recorded.",
    });
  }

  private appendAutomationUpdates(): void {
    const notable = (this.automation.jobs ?? []).filter((job) => {
      const id = String(job.id ?? "");
      if (!id || this.seenJobs.has(`${id}:${String(job.status)}`)) return false;
      const selected = [
        "completed",
        "failed",
        "interrupted",
        "waiting_for_consent",
      ].includes(String(job.status));
      if (selected) this.seenJobs.add(`${id}:${String(job.status)}`);
      return selected;
    });
    for (const job of notable) {
      const result = job.result as ReviewView | undefined;
      if (job.status === "completed" && result) this.appendReview(result);
      else {
        this.append({
          kind: job.status === "failed" ? "error" : "status",
          title: `Automation · ${String(job.status)}`,
          body: `${String(job.target)} ${String(job.revision).slice(0, 8)}${job.message ? `\n${String(job.message)}` : ""}`,
        });
      }
    }
  }

  private async observeAutomationEvent(
    event: "launch" | "refresh",
  ): Promise<void> {
    try {
      const response = await this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action: "event", event },
      );
      const job = response.job as Record<string, unknown> | undefined;
      const pr = response.prDetection as Record<string, unknown> | undefined;
      this.updatePullRequestHeader(pr);
      if (job?.id && job.status === "queued" && !job.coalesced) {
        void this.runAutomationJob(String(job.id));
      }
    } catch (error) {
      if ((this.automation.mode ?? "manual") !== "manual") {
        this.appendError(error);
      }
    }
  }

  private updatePullRequestHeader(pr?: Record<string, unknown>): void {
    if (pr && this.currentState.header) {
      const pullRequest =
        pr.available === false
          ? `unavailable · ${String(pr.code ?? "configuration")}`
          : pr.found
            ? `#${String(pr.number)} · ${pr.reviewFingerprintCurrent ? "review current" : "review due"}`
            : "none";
      this.patch({
        header: { ...this.currentState.header, pullRequest },
      });
    }
  }

  private async runAutomationJob(jobId: string): Promise<void> {
    try {
      const response = await this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action: "worker", jobId },
      );
      const result = response.result as ReviewView | undefined;
      const job = response.job as Record<string, unknown> | undefined;
      if (job?.id) this.seenJobs.add(`${String(job.id)}:completed`);
      if (result) this.appendReview(result);
      await this.pollAutomationJobs();
    } catch (error) {
      this.appendError(error);
    }
  }

  private startJobObservation(): void {
    if (this.pollTimer) return;
    this.pollTimer = setInterval(() => void this.pollAutomationJobs(), 4000);
    this.pollTimer.unref();
  }

  private async pollAutomationJobs(): Promise<void> {
    if (this.active || this.currentState.busy || this.currentState.shouldExit)
      return;
    try {
      this.automation = (await this.engine.request(
        "automation",
        this.options.repositoryPath,
        { action: "status" },
      )) as AutomationView;
      this.appendAutomationUpdates();
      if (!this.currentState.busy) await this.refreshGraph(true);
    } catch {
      // Polling remains quiet; explicit /jobs surfaces actionable failures.
    }
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

  private suggestedActions(header: SessionHeader): string[] {
    const actions: string[] = [];
    if (!header.providerId || header.providerAvailability !== "ready")
      actions.push("/provider");
    if (header.conflicts) actions.push("resolve conflicts, then /status");
    else if (header.staged) actions.push("/reviewstaged");
    else if (header.unstaged || header.untracked) actions.push("/files");
    else if (header.ahead) actions.push("/reviewbranch");
    else if (header.branch === header.baseBranch) actions.push("/scanfull");
    if (actions.length < 2) actions.push("/commits");
    return actions.slice(0, 3);
  }

  private appendProviders(): void {
    const body = this.providers
      .map(
        (provider) =>
          `${provider.id === this.activeProviderId ? "●" : "○"} ${provider.name ?? provider.id} · ${provider.readiness?.state?.replace("action_required", "Action required") ?? provider.availability ?? "unknown"}` +
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
          label: `${provider.id === this.activeProviderId ? "●" : "○"} ${provider.name ?? provider.id} · ${provider.readiness?.state?.replace("action_required", "Action required") ?? provider.availability ?? "unknown"}`,
          value: provider.id ?? "unknown",
          action: { kind: "provider", value: provider.id ?? "" },
        })),
      },
    });
  }

  private activeProvider(): ProviderView | undefined {
    return this.providers.find((item) => item.id === this.activeProviderId);
  }

  private async openModels(): Promise<void> {
    const provider = this.activeProvider();
    if (!provider?.id) {
      this.append({
        kind: "error",
        title: "Provider required",
        body: "Choose a provider with /provider before selecting a model.",
      });
      return;
    }
    await this.runBusy("Loading standard-tier models…", async () => {
      const result = await this.engine.request(
        "provider",
        this.options.repositoryPath,
        { action: "models", provider: provider.id },
      );
      const models = (result.models as string[] | undefined) ?? [];
      const details =
        (result.details as Array<Record<string, unknown>> | undefined) ?? [];
      const byId = new Map(
        details.map((item) => [String(item.id ?? ""), item]),
      );
      this.patch({
        overlay: {
          kind: "providers",
          title: "Choose review model",
          body: "Recommendation: use a capable non-flagship model for routine reviews to reduce credit usage. Reserve flagship models for unusually difficult changes.\nCodePreFlight uses the standard service tier only; fast-tier models are excluded.",
          items: models.map((model) => {
            const detail = byId.get(model);
            const label = String(detail?.label ?? model);
            const description = String(detail?.description ?? "");
            return {
              label: `${model === provider.model_name ? "●" : "○"} ${label}${description ? ` · ${description}` : ""}`,
              value: model,
              action: { kind: "model", value: model },
            };
          }),
        },
      });
      if (!models.length) {
        this.append({
          kind: "error",
          title: "No discoverable models",
          body: `The ${provider.name ?? provider.id} CLI did not expose a model list.`,
        });
      }
    });
  }

  private async openVariants(): Promise<void> {
    const provider = this.activeProvider();
    const model = provider?.model_name;
    if (!provider?.id || !model) {
      this.append({
        kind: "error",
        title: "Model required",
        body: "Choose an explicit model with /model before selecting a variant.",
      });
      return;
    }
    await this.runBusy("Loading model variants…", async () => {
      const result = await this.engine.request(
        "provider",
        this.options.repositoryPath,
        { action: "variants", provider: provider.id, model },
      );
      const variants = (result.variants as string[] | undefined) ?? [];
      this.patch({
        overlay: {
          kind: "providers",
          title: "Choose model variant",
          body: "Variants adjust reasoning effort, not service speed. CodePreFlight always uses the standard service tier.",
          items: variants.map((variant) => ({
            label: `${variant === provider.variant_name ? "●" : "○"} ${variant}`,
            value: variant,
            action: { kind: "variant", value: variant },
          })),
        },
      });
      if (!variants.length) {
        this.append({
          kind: "status",
          title: "No variants exposed",
          body: `${model} does not expose selectable reasoning variants through ${provider.name ?? provider.id}.`,
        });
      }
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
      const items = new WorkspacePresenter().navigationItems(action, raw);
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

  private async fullScan(approved: boolean): Promise<void> {
    const provider = this.activeProvider();
    if (
      !provider ||
      (provider.readiness?.state ?? provider.availability) !== "ready" ||
      !provider.readiness?.invocationVerified
    ) {
      this.append({
        kind: "error",
        title: "Select a review provider",
        body: "A full scan requires a ready, tested reviewer. Use /provider to finish setup or /providertest to verify the connection.",
      });
      return;
    }
    if (approved)
      this.setPipeline(["checks", "review", "verify", "summary"], 0);
    await this.runBusy("Preparing guarded full scan…", async () => {
      if (!approved) this.fullScanManifest = undefined;
      const request = this.beginRequest();
      try {
        try {
          const result = await this.engine.request(
            "scan",
            this.options.repositoryPath,
            {
              action: "full",
              provider: this.activeProviderId,
              fullScanApproved: approved,
              planFingerprint: approved
                ? this.fullScanManifest?.planFingerprint
                : undefined,
            },
            (event) => this.handleEngineEvent(event),
            { signal: request.signal },
          );
          this.lastReview = result as ReviewView;
          this.appendReview(this.lastReview);
          this.completePipeline();
        } catch (error) {
          if (
            !approved &&
            error instanceof EngineRequestError &&
            error.code === "full_scan_confirmation_required" &&
            this.fullScanManifest
          ) {
            const manifest = this.fullScanManifest;
            this.requestDecision(
              "Run this full repository scan?",
              `${String(manifest.eligibleFiles)} eligible files · ${String(manifest.excludedFiles)} excluded · ${String(manifest.redactions)} redactions\n${Number(manifest.totalSelectedCharacters ?? 0).toLocaleString()} selected characters · approximately ${String(manifest.providerRequests)} provider requests (repair may add requests)\nDestination: ${String(manifest.destination)} (${String(manifest.privacyCategory)})\nPlanned checks: ${JSON.stringify(manifest.plannedChecks)}\nCache available: ${manifest.cacheHit ? "yes" : "no"}\nThis approval is only for this exact full scan.`,
              "approve full scan",
              async () => this.fullScan(true),
            );
            return;
          }
          throw error;
        }
      } finally {
        this.finishRequest(request);
      }
    });
  }

  private async commit(messageOverride?: string): Promise<void> {
    if (!this.activeProviderId) {
      this.append({
        kind: "error",
        title: "Select a review provider",
        body: "The commit flow reviews the staged change first. Use /provider.",
      });
      return;
    }
    const retry = async (): Promise<void> => this.commit(messageOverride);
    this.setPipeline(
      ["snapshot", "checks", "context", "provider", "verify"],
      0,
    );
    await this.runBusy("Reviewing staged changes for commit…", async () => {
      this.disclosure = undefined;
      const request = this.beginRequest();
      try {
        try {
          const preparation = await this.engine.request(
            "commit",
            this.options.repositoryPath,
            {
              action: "prepare",
              provider: this.activeProviderId,
              remoteApproved: this.activeProviderId
                ? this.approvedProviders.has(this.activeProviderId)
                : false,
            },
            (event) => this.handleEngineEvent(event),
            { signal: request.signal },
          );
          const review = preparation.review as ReviewView;
          this.lastReview = review;
          this.appendReview(review);
          this.completePipeline();
          if (review.blocking) {
            this.append({
              kind: "error",
              title: "Commit blocked by review policy",
              body: "Inspect verified blocking findings before committing.",
            });
            return;
          }
          const message = messageOverride ?? String(preparation.message ?? "");
          this.confirmCommit(preparation, message);
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

  private confirmCommit(
    preparation: Record<string, unknown>,
    message: string,
  ): void {
    this.requestDecision(
      "Create this commit?",
      `Message: ${message}\nStaged fingerprint: ${String(preparation.fingerprint).slice(0, 12)}\nUse /commit <message> to provide an edited message before approval.`,
      "create commit",
      async () => {
        await this.runBusy("Creating approved commit…", async () => {
          const result = await this.engine.request(
            "commit",
            this.options.repositoryPath,
            {
              action: "execute",
              approved: true,
              message,
              fingerprint: preparation.fingerprint,
            },
          );
          await this.refreshContext();
          this.append({
            kind: "system",
            title: "Commit created",
            body: `${String(result.commit ?? result.revision ?? "Commit completed")} · ${message}`,
          });
        });
      },
    );
  }

  private confirmLogin(provider: string): void {
    const descriptor = this.providers.find((item) => item.id === provider);
    this.requestDecision(
      `Authenticate ${descriptor?.name ?? provider}?`,
      "CodePreFlight will temporarily clear the TUI and give this provider's official CLI full terminal control. Credentials remain owned by the provider CLI. This may affect the account used by other applications." +
        (provider === "claude"
          ? " Claude CLI is experimental; confirm provider policy and billing before proceeding."
          : ""),
      "open provider login",
      async () => this.login(provider),
    );
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
        body: `${provider} authentication verified.`,
      });
    });
    this.continueSetup();
  }

  private async configureProvider(
    provider: string,
    model?: string,
    variant?: string,
  ): Promise<void> {
    if (!provider) {
      this.append({
        kind: "error",
        title: "Provider required",
        body: "Choose a provider with /provider first.",
      });
      return;
    }
    await this.runBusy("Preparing provider configuration…", async () => {
      const preview = await this.engine.request(
        "provider",
        this.options.repositoryPath,
        {
          action: "configure",
          provider,
          model,
          variant,
          scope: "personal",
          write: false,
        },
      );
      this.append({
        kind: "status",
        title: "Provider configuration preview",
        body: String(
          preview.diff ?? preview.preview ?? "No configuration change.",
        ),
      });
      this.requestDecision(
        `Use ${provider}${model ? ` · ${model}` : ""}${variant ? ` · ${variant}` : ""}?`,
        "This saves a private preference under .git/codepreflight/. Selecting a provider does not establish readiness." +
          (provider === "claude"
            ? " Claude CLI is experimental; verify provider policy and billing before activation."
            : ""),
        "write configuration",
        async () => {
          await this.runBusy("Saving provider configuration…", async () => {
            await this.engine.request("provider", this.options.repositoryPath, {
              action: "configure",
              provider,
              model,
              variant,
              scope: "personal",
              write: true,
            });
            await this.refreshContext();
            this.append({
              kind: "system",
              body: `${provider} is now your private review provider for this repository.`,
            });
          });
          this.onboarding.active = true;
          this.continueSetup();
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
        await this.refreshContext();
      },
    );
    this.continueSetup();
  }

  private async review(target: string, revision?: string): Promise<void> {
    if (
      !this.activeProviderId ||
      (this.activeProvider()?.readiness?.state ??
        this.activeProvider()?.availability) !== "ready"
    ) {
      this.append({
        kind: "error",
        title: "Select a review provider",
        body: "Use /provider to inspect available providers, then run /providerswitch <id>.",
      });
      return;
    }
    const retry = async (): Promise<void> => this.review(target, revision);
    this.setPipeline(
      ["snapshot", "checks", "context", "provider", "verify"],
      0,
    );
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
          this.completePipeline();
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
    this.patch({ pipeline: undefined });
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
    if (event.event.startsWith("operation_")) {
      this.handleOperationEvent(event);
      return;
    }
    if (event.event === "workflow_stage") {
      this.advancePipeline(String(event.payload?.stage ?? ""));
      this.patch({ activeActor: String(event.payload?.actor ?? "Preflight") });
      return;
    }
    if (event.event === "progress") {
      const message = String(event.payload?.message ?? "Working…");
      this.patch({ activity: message });
    }
    if (event.event === "scan_progress") {
      this.patch({ activity: String(event.payload?.message ?? "Scanning…") });
      const stage = String(event.payload?.stage ?? "");
      this.advancePipeline(stage === "verification" ? "verify" : stage);
    }
    if (event.event === "consent_required") this.handleConsentEvent(event);
  }

  private handleOperationEvent(event: EngineEvent): void {
    const record = event.payload as unknown as OperationRecord;
    this.activityStore.update(record);
    if (record.actor !== "Git")
      this.patch({
        activeActor: record.status === "running" ? record.actor : "Preflight",
        activity: `${record.actor} ${record.status === "running" ? "is running" : record.status} ${record.category}`,
      });
  }

  private handleConsentEvent(event: EngineEvent): void {
    if (event.payload?.fullScan) {
      this.fullScanManifest = event.payload.manifest as Record<string, unknown>;
      return;
    }
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
      this.workflow.reset();
      if (this.interruptionTimer) clearTimeout(this.interruptionTimer);
      this.patch({
        busy: false,
        activity: undefined,
        activeActor: undefined,
        interruptionNotice: undefined,
      });
    }
  }

  private appendError(error: unknown): void {
    const failure = error instanceof Error ? error : new Error(String(error));
    const detail =
      failure instanceof EngineRequestError && failure.details?.actions
        ? `\nNext: ${this.formatRecoveryActions(failure.details.actions)}`
        : "";
    this.append({
      kind: "error",
      title: "Request could not be completed",
      body: `${failure.message}${detail}`,
    });
    if (this.currentState.pipeline) {
      this.patch({
        pipeline: this.currentState.pipeline.map((item) =>
          item.status === "active"
            ? { ...item, status: "failed" as const }
            : item,
        ),
      });
    }
  }

  private beginRequest(): AbortController {
    this.active?.abort();
    const request = new AbortController();
    this.active = request;
    return request;
  }

  private formatRecoveryActions(value: unknown): string {
    if (!Array.isArray(value))
      return "Use /help or retry after resolving the reported state.";
    return value
      .map((raw) => {
        const action = raw as Record<string, unknown>;
        const type = String(action.type ?? "retry");
        if (type === "select_provider" || type === "select_model")
          return "/provider";
        if (type === "authenticate_provider")
          return `/providerlogin ${String(action.provider ?? "<provider>")}`;
        if (type === "pull_ollama_model")
          return `preflight provider pull ${String(action.model ?? "<model>")} --yes`;
        if (type === "trust_repository") return "preflight init --trust";
        if (type === "open_configuration")
          return "inspect your private preference, global config, or optional team config";
        if (type === "approve_transmission")
          return "review the manifest and approve";
        return "retry after resolving the reported repository state";
      })
      .join(" · ");
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

  private setPipeline(labels: string[], activeIndex: number): void {
    this.patch({
      pipeline: labels.map((label, index) => ({
        label,
        status:
          index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending",
      })),
    });
  }

  private advancePipeline(label: string): void {
    const pipeline = this.currentState.pipeline;
    if (!pipeline) return;
    const activeIndex = pipeline.findIndex((item) => item.label === label);
    if (activeIndex < 0) return;
    this.patch({
      pipeline: pipeline.map((item, index) => ({
        ...item,
        status:
          index < activeIndex
            ? "complete"
            : index === activeIndex
              ? "active"
              : "pending",
      })),
    });
  }

  private completePipeline(): void {
    if (!this.currentState.pipeline) return;
    this.patch({
      pipeline: this.currentState.pipeline.map((item) => ({
        ...item,
        status: "complete" as const,
      })),
    });
  }
}
