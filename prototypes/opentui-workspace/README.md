# OpenTUI workspace prototype

This is throwaway code for one question: which boxed workspace structure should
become CodePreFlight's production terminal interface?

Run from the repository root:

```sh
npm install
npm run prototype:workspace
```

Use `1`, `2`, or `3` (or the left/right arrows) to compare the layouts. Press
`Esc` or `q` to exit. The prototype uses fake data and cannot mutate a Git
repository or contact an AI provider.

The variants intentionally disagree about structure:

1. **Cockpit** — the agreed three-column repository, agent, and history layout.
2. **Agent focus** — a wide agent panel with compact side rails.
3. **Work queue** — findings and changes lead the workflow, with history below.
