# OpenTUI workspace prototype

This is throwaway code for one question: which boxed workspace structure should
become CodePreFlight's production terminal interface?

Run from the repository root:

```sh
npm install
npm run prototype:workspace
```

Use `1`, `2`, or `3` (or the left/right arrows) to compare the layouts. The
composer accepts a demo message and replies that no real repository or provider
request was made. Press `Tab` to switch between composer input and layout
shortcuts. Press `q` or `Esc` while layout shortcuts are active, or `Ctrl+C` at
any time, to exit. On terminals narrower than 100 columns or shorter than 32
rows, `A`, `R`, `C`, and `F` switch between Agent, Repository, Changes, and
Findings views.

The prototype uses fake data and cannot mutate a Git repository or contact an
AI provider. Its composer only echoes the submitted question and explains that
the preview has no live backend. It adapts to narrow and short terminals so the
composer remains visible while secondary panels collapse.

The variants intentionally disagree about structure:

1. **Cockpit** — the agreed three-column repository, agent, and history layout.
2. **Agent focus** — a wide agent panel with compact side rails.
3. **Work queue** — findings and changes lead the workflow, with history below.
