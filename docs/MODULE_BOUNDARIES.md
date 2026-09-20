# Workflow boundaries

The NDJSON v3 protocol is the public seam between the TypeScript terminal and
the Python engine. Direct commands and interactive sessions share it.

## Terminal

- SessionController owns ephemeral session state and exposes typed user actions.
- CommandRegistry and SuggestionCoordinator own command discovery and argument data.
- OnboardingCoordinator derives the next recovery step from current capabilities.
- WorkflowCoordinator owns interruption policy; terminal ownership is handled by TerminalSession.
- WorkspacePresenter and GitGraphPresenter turn state into display data.
- ActivityStore maintains sanitized operation records.
- Workspace hooks own subscriptions, terminal handoff, resize and asynchronous suggestions.
  Keyboard routing lives separately from the declarative Ink layout.

## Engine

- The command-handler registry routes protocol requests without a dispatch conditional.
- ContextPlanner selects deterministic evidence; ContextBuilder supplies approved check results.
- Review consent, provider invocation/one repair attempt, verification rules and blocking policy
  are separate responsibilities.
- ScanPlanner constructs an immutable read-only preview. ScanExecutor replans, validates
  explicit approval, executes checks once and performs bounded review work.
- Provider health evidence is separate from authentication and provider configuration.

## Complexity gates

Run `make check`. Ruff C901 limits Python complexity to 10. The TypeScript compiler
API checker limits functions/methods to complexity 12 and 80 lines, excluding generated
artifacts and tests. SessionView is the only reviewed exception: it is declarative
terminal rendering, with workflow decisions outside it. New exemptions require review.
