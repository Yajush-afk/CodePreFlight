// PROTOTYPE: three workspace structures, switchable with 1/2/3 or arrow keys.
import { createCliRenderer } from "@opentui/core";
import {
  createRoot,
  useKeyboard,
  useRenderer,
  useTerminalDimensions,
} from "@opentui/react";
import { useRef, useState, type ReactNode } from "react";

const palette = {
  accent: "#5eead4",
  base: "#7cb7ff",
  current: "#d8a2ff",
  critical: "#ff667a",
  high: "#ff9f5a",
  medium: "#ffe066",
  low: "#70b7ff",
  success: "#75e69a",
  muted: "#a6b0bf",
  border: "#758296",
  panel: "#11151c",
};

const commits = [
  "● 60a9735  Render findings as terminal Markdown",
  "├─● c477e50  Add transcript-only copy view",
  "●─╮ 488d975  Fix structured follow-up responses",
  "├─● f6c4386  Improve review exploration",
  "●─╮ 93c3db8  Fix long scan timeouts",
  "╰─● 6d57122  Render real commit topology",
];

const initialMessages = [
  { who: "You", body: "Review the working tree before I commit." },
  {
    who: "Preflight",
    body: "I checked 4 changed files and ran 2 approved checks.",
  },
  {
    who: "Preflight",
    body: "Review completed with 2 findings. One needs attention before commit.",
  },
];

function Title({ children }: { children: string }) {
  return (
    <text fg={palette.accent}>
      <strong>{children}</strong>
    </text>
  );
}

function Header({ compact = false }: { compact?: boolean }) {
  return (
    <box
      height={3}
      border
      borderStyle="rounded"
      borderColor={palette.border}
      paddingLeft={1}
      paddingRight={1}
      justifyContent="space-between"
    >
      {!compact && <text fg={palette.muted}>~/my_repo/code-preflight</text>}
      <text fg={palette.accent}>
        <strong>◇ CODEPREFLIGHT</strong>
      </text>
      <text>
        <span fg={palette.success}>Codex ready</span>{" "}
        <span fg={palette.current}>manual</span>{" "}
        <span fg={palette.current}>feature/ui</span>
      </text>
    </box>
  );
}

function RepositorySummary({ compact = false }: { compact?: boolean }) {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={palette.border}
      title=" Repository summary "
      padding={1}
      flexGrow={1}
    >
      <text fg={palette.accent}>
        <strong>code-preflight</strong>
      </text>
      <text>
        <span fg={palette.current}>feature/ui</span> →{" "}
        <span fg={palette.base}>main</span>
      </text>
      <text fg={palette.muted}>2 ahead · upstream current</text>
      <text>
        <span fg={palette.success}>+ 2 staged</span>{" "}
        <span fg={palette.medium}>~ 1 modified</span>
      </text>
      <text>
        <span fg={palette.low}>? 1 untracked</span>{" "}
        <span fg={palette.success}>! 0 conflicts</span>
      </text>
      {!compact && <text fg={palette.accent}>Next: review staged changes</text>}
    </box>
  );
}

function Findings({ compact = false }: { compact?: boolean }) {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={palette.border}
      title=" Findings "
      padding={1}
      flexGrow={1}
    >
      <text>
        <span fg={palette.critical}>◆ CRITICAL 0</span>{" "}
        <span fg={palette.high}>▲ HIGH 1</span>
      </text>
      <text>
        <span fg={palette.medium}>● MEDIUM 1</span>{" "}
        <span fg={palette.low}>○ LOW 0</span>
      </text>
      <text fg={palette.high}>H1 Token refresh accepts expired sessions</text>
      {!compact && (
        <text fg={palette.medium}>
          M2 Missing regression coverage · needs re-review
        </text>
      )}
      <text fg={palette.muted}>Enter inspect · f filter · d dismiss</text>
    </box>
  );
}

function Changes() {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={palette.border}
      title=" Changes "
      padding={1}
      flexGrow={1}
    >
      <text fg={palette.success}>● staged</text>
      <text> M engine/review.py</text>
      <text> A apps/cli/finding-card.tsx</text>
      <text fg={palette.medium}>● unstaged</text>
      <text> M README.md</text>
      <text fg={palette.low}>● untracked</text>
      <text> ? notes/demo.md</text>
      <text fg={palette.muted}>s stage · u unstage · space select hunk</text>
    </box>
  );
}

function FindingCard() {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="double"
      borderColor={palette.high}
      title=" H1 · HIGH · OPEN "
      padding={1}
      marginTop={1}
    >
      <text>
        <strong>Token refresh accepts expired sessions</strong>
      </text>
      <text fg={palette.muted}>
        verified · engine/auth.py:84 · confidence high
      </text>
      <text>
        Expired refresh tokens reach the rotation path without the expected
        timestamp check.
      </text>
      <text fg={palette.high}>
        Inspect the expiry guard and add a regression test for an expired token.
      </text>
    </box>
  );
}

function AgentPanel({
  roomy = false,
  messages,
  composerFocused,
  draft,
  onDraftChange,
  onSubmit,
}: {
  roomy?: boolean;
  messages: Array<{ who: string; body: string }>;
  composerFocused: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: (value: string) => void;
}) {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={palette.accent}
      title=" Agent Panel "
      padding={1}
      flexGrow={1}
    >
      <scrollbox
        flexGrow={1}
        stickyScroll
        stickyStart="bottom"
        scrollbarOptions={{ visible: true }}
      >
        {messages.map((message, index) => (
          <box key={index} flexDirection="column" marginBottom={1}>
            <text fg={message.who === "You" ? palette.current : palette.accent}>
              <strong>{message.who}</strong>
            </text>
            <text>{message.body}</text>
          </box>
        ))}
        <FindingCard />
        {roomy && (
          <text fg={palette.muted}>
            Ask why this happens, what could break, or which tests to run.
          </text>
        )}
      </scrollbox>
      <box height={1}>
        <text fg={palette.muted}>
          ✓ snapshot ✓ checks ◐ review ○ verify ○ summary
        </text>
      </box>
      <box
        height={3}
        border
        borderStyle="rounded"
        borderColor={palette.accent}
        paddingLeft={1}
      >
        <input
          id="agent-composer"
          placeholder="Ask about this repository, or type /"
          focused={composerFocused}
          value={draft}
          onInput={onDraftChange}
          onSubmit={() => onSubmit(draft)}
        />
      </box>
      <box height={1} justifyContent="space-between">
        <text fg={palette.muted}>gpt-5.6-luna · medium · manual</text>
        <text fg={palette.muted}>/help · Tab focus · Esc cancel</text>
      </box>
    </box>
  );
}

function History({ compact = false }: { compact?: boolean }) {
  return (
    <box
      flexDirection="column"
      border
      borderStyle="rounded"
      borderColor={palette.border}
      title=" Local History "
      padding={1}
      flexGrow={1}
    >
      <text fg={palette.success}>◇ working tree · 4 changes</text>
      <text>
        <span fg={palette.current}>C</span> feature/ui{" "}
        <span fg={palette.base}>B</span> main
      </text>
      {commits.slice(0, compact ? 4 : commits.length).map((commit, index) => (
        <text key={commit} fg={index < 2 ? palette.current : palette.base}>
          {commit}
        </text>
      ))}
      <text fg={palette.muted}>Display only · /graph</text>
    </box>
  );
}

function Cockpit(props: AgentPanelProps) {
  return (
    <box flexDirection="row" flexGrow={1} gap={1}>
      <box width="25%" flexDirection="column" gap={1}>
        <RepositorySummary />
        <Findings />
      </box>
      <box width="55%">
        <AgentPanel {...props} />
      </box>
      <box width="20%">
        <History />
      </box>
    </box>
  );
}

function AgentFocus(props: AgentPanelProps) {
  return (
    <box flexDirection="row" flexGrow={1} gap={1}>
      <box width="20%" flexDirection="column" gap={1}>
        <RepositorySummary compact />
        <Changes />
      </box>
      <box width="60%">
        <AgentPanel roomy {...props} />
      </box>
      <box width="20%" flexDirection="column" gap={1}>
        <Findings compact />
        <History compact />
      </box>
    </box>
  );
}

function WorkQueue(props: AgentPanelProps) {
  return (
    <box flexDirection="column" flexGrow={1} gap={1}>
      <box height="62%" flexDirection="row" gap={1}>
        <box width="34%" flexDirection="column" gap={1}>
          <Findings />
          <Changes />
        </box>
        <box width="66%">
          <AgentPanel roomy {...props} />
        </box>
      </box>
      <box height="38%" flexDirection="row" gap={1}>
        <box width="34%">
          <RepositorySummary compact />
        </box>
        <box width="66%">
          <History compact />
        </box>
      </box>
    </box>
  );
}

type AgentPanelProps = Parameters<typeof AgentPanel>[0];

const variants = [
  { name: "Cockpit", render: Cockpit },
  { name: "Agent focus", render: AgentFocus },
  { name: "Work queue", render: WorkQueue },
];

type NarrowView = "agent" | "repository" | "changes" | "findings";

function NarrowWorkspace({
  view,
  agentPanelProps,
}: {
  view: NarrowView;
  agentPanelProps: AgentPanelProps;
}) {
  const selectedView = {
    agent: <AgentPanel roomy {...agentPanelProps} />,
    repository: <RepositorySummary />,
    changes: <Changes />,
    findings: <Findings />,
  }[view];

  return (
    <box flexDirection="column" flexGrow={1} gap={1}>
      <box height={1}>
        <text>
          <span fg={palette.current}>feature/ui</span> →{" "}
          <span fg={palette.base}>main</span>
          {"  "}
          <span fg={palette.success}>+2</span>{" "}
          <span fg={palette.medium}>~1</span> <span fg={palette.low}>?1</span>
          {"  "}
          <span fg={palette.accent}>{view.toUpperCase()}</span>
        </text>
      </box>
      {selectedView}
    </box>
  );
}

function CompactWorkspace({ children }: { children: ReactNode }) {
  return (
    <box flexDirection="row" flexGrow={1} gap={1}>
      <box width="28%" flexDirection="column" gap={1}>
        <RepositorySummary compact />
        <Changes />
        <Findings compact />
      </box>
      <box width="72%">{children}</box>
    </box>
  );
}

function App() {
  const renderer = useRenderer();
  const { width, height } = useTerminalDimensions();
  const compactMode = width < 100 || height < 32;
  const [variant, setVariant] = useState(0);
  const [narrowView, setNarrowView] = useState<NarrowView>("agent");
  const [composerFocused, setComposerFocused] = useState(true);
  const composerFocusedRef = useRef(true);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState(initialMessages);
  const updateComposerFocus = (focused: boolean) => {
    composerFocusedRef.current = focused;
    setComposerFocused(focused);
  };

  const submitMessage = (value: string) => {
    const question = value.trim();
    if (!question) return;
    setMessages((current) => [
      ...current,
      { who: "You", body: question },
      {
        who: "Preflight",
        body: "Prototype preview only: no repository or provider request was made.",
      },
    ]);
    setDraft("");
  };

  useKeyboard((key) => {
    if (composerFocusedRef.current) {
      if (key.name === "escape") {
        if (draft) setDraft("");
        key.preventDefault();
        key.stopPropagation();
        return;
      }
      if (key.name === "tab") {
        const focused = renderer.currentFocusedRenderable;
        if (focused?.id === "agent-composer") {
          renderer.blurRenderable(focused);
        }
        updateComposerFocus(false);
        key.preventDefault();
        key.stopPropagation();
      } else if (key.ctrl && key.name === "q") {
        key.preventDefault();
        key.stopPropagation();
        renderer.destroy();
      }
      return;
    }
    if (key.name === "tab") {
      updateComposerFocus(true);
      setNarrowView("agent");
      key.preventDefault();
      key.stopPropagation();
      return;
    }
    if (key.name === "escape" || key.name === "q") {
      key.preventDefault();
      key.stopPropagation();
      renderer.destroy();
      return;
    }
    if (key.name === "left") {
      setVariant((value) => (value + variants.length - 1) % variants.length);
      key.preventDefault();
      key.stopPropagation();
      return;
    }
    if (key.name === "right") {
      setVariant((value) => (value + 1) % variants.length);
      key.preventDefault();
      key.stopPropagation();
      return;
    }
    if (["1", "2", "3"].includes(key.name)) {
      setVariant(Number(key.name) - 1);
      key.preventDefault();
      key.stopPropagation();
      return;
    }
    if (compactMode && ["a", "r", "c", "f"].includes(key.name)) {
      const views: Record<string, NarrowView> = {
        a: "agent",
        r: "repository",
        c: "changes",
        f: "findings",
      };
      setNarrowView(views[key.name]);
      updateComposerFocus(false);
      key.preventDefault();
      key.stopPropagation();
    }
  });

  const agentPanelProps: AgentPanelProps = {
    messages,
    composerFocused,
    draft,
    onDraftChange: setDraft,
    onSubmit: submitMessage,
  };
  const selectedVariant = variants[variant];
  const keyboardHelp = compactMode
    ? composerFocused
      ? "Tab panels · Ctrl+C exits"
      : "1/2/3 layout · A/R/C/F panels · Tab input · q exits"
    : composerFocused
      ? "Tab switches layout keys · Ctrl+C exits"
      : "1/2/3 or ←/→ layout · Tab composer · q exits";
  const workspace = compactMode ? (
    <NarrowWorkspace view={narrowView} agentPanelProps={agentPanelProps} />
  ) : width < 140 ? (
    <CompactWorkspace>
      <AgentPanel roomy {...agentPanelProps} />
    </CompactWorkspace>
  ) : (
    selectedVariant.render(agentPanelProps)
  );

  return (
    <box
      flexDirection="column"
      width="100%"
      height="100%"
      padding={1}
      gap={1}
      backgroundColor={palette.panel}
    >
      <Header compact={compactMode} />
      {workspace}
      <box height={1} justifyContent="center">
        <text fg={palette.muted}>
          ←{" "}
          <span fg={palette.accent}>
            <strong>
              {variant + 1} · {selectedVariant.name}
            </strong>
          </span>{" "}
          → {keyboardHelp} · prototype data only
        </text>
      </box>
    </box>
  );
}

const renderer = await createCliRenderer({ exitOnCtrlC: true });
createRoot(renderer).render(<App />);
