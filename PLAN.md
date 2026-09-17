# CodePreFlight Implementation Plan

## 1. Objective

Build CodePreFlight as a local-first terminal tool that inspects Git repositories, runs deterministic checks, constructs focused review context, invokes a developer-selected AI provider, verifies the returned findings, and assists with safe Git workflows.

The product uses a TypeScript terminal interface and a Python review engine. The first supported platforms are macOS and Linux. The first distribution is a source installation exposing the `preflight` command.

The first meaningful release includes repository status, initialization, provider discovery, staged review, structured findings, commit assistance, and optional pre-commit integration. Branch, pre-push, and pull-request workflows follow after the staged workflow is reliable.

## 2. System architecture

### TypeScript CLI and TUI

The TypeScript layer owns:

- the `preflight` executable and direct subcommands;
- the interactive terminal application;
- keyboard navigation and view state;
- progress, review, finding, and confirmation screens;
- starting and supervising the Python engine;
- rendering structured engine events;
- collecting explicit approval for provider requests and Git mutations.

Use Node.js, TypeScript, React, Ink, and Commander. Keep workflow state in explicit reducers rather than embedding repository or provider logic in views.

### Python review engine

The Python layer owns:

- read-only Git and repository inspection;
- configuration resolution and repository trust;
- deterministic check execution;
- diff and context construction;
- ignore handling and secret detection;
- provider discovery and invocation;
- structured-response parsing;
- evidence verification and finding deduplication;
- commit-message and pull-request summary generation;
- controlled Git mutations after approval.

Use Python 3.12 or newer, `uv`, Pydantic, `httpx`, and `asyncio`. Invoke Git through argument-safe subprocess calls instead of using GitPython.

### Process seam

The TypeScript application starts the Python engine as a local child process. Interactive sessions keep one engine process for the session; direct commands start one process and exit after completion.

Communication uses versioned newline-delimited JSON. Standard output is reserved for protocol events, while diagnostic logs use standard error. Every request contains a protocol version, request identifier, command, repository path, and typed payload.

Engine events include:

- `ready` for the protocol handshake;
- `progress` for concise pipeline updates;
- `consent_required` before remote transmission;
- `provider_delta` for optional streamed provider output;
- `finding` for an individually validated finding;
- `complete` for the final result;
- `error` for a typed recoverable or terminal failure.

The canonical protocol schema lives in `protocol/`. TypeScript types and Python models are generated or validated from that schema, and CI rejects stale generated artifacts.

## 3. Major modules

### RepositoryInspector

Produces one `RepositorySnapshot` containing the repository root, branch, base branch, upstream, remotes, ahead/behind state, conflicts, changed files, detected languages, and relevant project tooling.

The interface remains read-only. It does not fetch, stage, switch branches, or modify repository state.

### ReviewOrchestrator

Owns the complete review pipeline:

1. validate the repository and trust state;
2. capture the Repository Snapshot;
3. resolve the Review Target and Change Set;
4. run approved Checks;
5. construct and scan the Context Package;
6. disclose the Provider destination;
7. invoke the Provider Adapter;
8. parse and verify Findings;
9. apply Review Policy;
10. return a complete `ReviewResult`.

### ContextBuilder

Selects context in this order:

1. the selected diff and changed-line metadata;
2. Repository Rules;
3. Check results;
4. code surrounding changed hunks;
5. imported interfaces and direct callers;
6. related existing tests;
7. affected configuration;
8. relevant Git history when required by the review depth.

It excludes configured ignores, generated files, binaries, build output, vendored code, and unsupported oversized content. Every inclusion, exclusion, redaction, and truncation appears in the Context Manifest.

### ProviderRegistry

Discovers configured providers and routes review requests through a shared Provider Adapter interface. Each adapter reports its installation, version, authentication state, privacy category, supported capabilities, and compatibility.

Initial adapters:

- Ollama local inference;
- Codex CLI;
- Claude Code CLI;
- OpenCode CLI;
- an OpenAI-compatible BYOK endpoint.

CLI providers run in an isolated temporary directory with editing tools disabled. They receive the curated Context Package rather than unrestricted repository access. Incompatible versions are reported instead of being invoked with guessed arguments.

### CheckRunner

Runs only Checks approved for a trusted repository. It supports concurrency limits, timeouts, cancellation, bounded output, and explicit working directories. Results distinguish passed, failed, skipped, timed out, and recommended-but-not-run Checks.

### SafetyPolicy

Owns:

- repository trust;
- configuration safety;
- secret scanning and redaction;
- provider privacy disclosures;
- Git mutation confirmation;
- hook blocking and bypass behavior;
- path containment and subprocess restrictions.

### EngineClient and WorkflowController

`EngineClient` hides process startup, handshake, request correlation, streaming, cancellation, and failure recovery from the UI.

`WorkflowController` coordinates status, review, commit, hooks, and pull-request preparation using the engine interface. It contains no Git parsing or provider-specific behavior.

## 4. Public command interface

```text
preflight
preflight status
preflight init
preflight doctor
preflight providers
preflight review --staged
preflight review --branch [--base <branch>]
preflight commit
preflight hooks install pre-commit
preflight hooks install pre-push
preflight hooks status
preflight hooks remove <hook>
preflight pr prepare [--base <branch>]
```

Direct commands support `--json` where structured automation output is useful.

Exit codes:

- `0`: operation completed and policy permits continuation;
- `1`: verified Findings violate the configured blocking policy;
- `2`: engine, configuration, provider, or protocol failure;
- `3`: developer cancellation.

Hooks fail open on operational errors by default. A repository may explicitly opt into fail-closed behavior.

## 5. Configuration model

Configuration precedence is:

```text
CLI flags → repository configuration → global configuration → detected defaults
```

Global configuration uses the platform's XDG configuration directory. Shareable repository configuration is stored in `.codepreflight.toml`. Runtime state and cache data live inside `.git/codepreflight/`.

Configuration covers:

- default providers by responsibility;
- provider model selection;
- review depth and blocking policy;
- approved test, lint, typecheck, and build commands;
- Repository Rules;
- ignored paths;
- base branch override;
- commit-message convention;
- hook behavior.

API credentials are read from environment variables or provider-owned authentication. Repository configuration may name an environment variable but may not contain a secret value.

A cloned repository is untrusted by default. Approval is recorded against its canonical path, remote identity, and configuration digest. Changing executable Check commands invalidates trust.

## 6. Review model

### Review depths

**Fast Review** examines staged changes, direct context, approved quick Checks, obvious correctness failures, secrets, debug code, and missing directly related tests.

**Standard Review** examines the complete branch Change Set, related files, cross-commit interactions, tests, and moderate compatibility or architectural concerns.

**Deep Review** examines pull-request changes, architecture, public interfaces, compatibility, security, performance, repository conventions, broader tests, and relevant history.

### Finding structure

Each Finding contains:

- severity: Critical, Warning, Suggestion, or Informational;
- concise title;
- explanation of the problem;
- repository Evidence with file and line locations;
- engineering impact;
- confidence: high, medium, or low;
- verification state;
- recommended inspection or change;
- suggested tests.

Verification states are `verified`, `partially_verified`, `unverified`, and `rejected`. Model output cannot assign its own verification state; the engine derives it from repository Evidence.

The default Review Policy is warning-only. Suggestions and Informational Findings never block by default. AI output alone never performs a Git mutation.

## 7. Implementation phases

### Phase 0: Foundation and contracts

Deliver:

- the npm and `uv` workspaces;
- formatting, linting, typing, testing, and CI configuration;
- the `preflight` executable shell;
- the Python engine entry point;
- the canonical protocol schema;
- process handshake and error events;
- domain glossary and architectural decision records.

Complete when TypeScript starts Python, completes a versioned handshake, exchanges a typed request and response, handles cancellation, and reports incompatible protocol versions.

### Phase 1: Repository inspection and status

Deliver:

- the argument-safe Git runner;
- repository root and branch discovery;
- upstream, remote, default/base branch, and merge-base detection;
- staged, unstaged, untracked, renamed, deleted, and conflicted file states;
- ahead/behind information without automatic fetching;
- language, package manager, test, lint, typecheck, and build-tool detection;
- attention-area classification for authentication, migrations, deployment, public interfaces, secrets, and tests;
- `preflight status` in TUI and JSON formats.

Complete when clean, dirty, detached, unborn, conflicted, no-remote, and subdirectory invocation scenarios produce correct snapshots without mutating or contacting a remote repository.

### Phase 2: Initialization, configuration, trust, and providers

Deliver:

- global and repository TOML loading;
- schema validation and configuration precedence;
- `preflight init` with detected, reviewable defaults;
- repository trust and trust invalidation;
- `preflight doctor`;
- provider discovery and `preflight providers`;
- provider privacy categories and health states.

Complete when an untrusted repository cannot execute configured commands, secret values are rejected from repository configuration, and missing providers do not prevent local status inspection.

### Phase 3: Deterministic checks and context construction

Deliver:

- approved Check execution with concurrency, cancellation, and timeouts;
- staged diff parsing and changed-hunk mapping;
- focused surrounding-code extraction;
- import, interface, caller, configuration, and test discovery;
- ignore handling and binary/generated-file detection;
- secret scanning and supported redaction;
- Context Manifest generation;
- deterministic context budgeting.

Complete when the same repository state produces the same Context Manifest, excluded material cannot enter a provider request, and actual Check results remain distinct from recommended Checks.

### Phase 4: AI review and provider adapters

Deliver:

- a deterministic fake provider for tests;
- Ollama, Codex CLI, Claude Code, OpenCode, and OpenAI-compatible adapters;
- Provider discovery, version compatibility, timeouts, and cancellation;
- Fast, Standard, and Deep review instructions;
- structured response validation and one repair attempt;
- path, line, symbol, changed-code, and test-reference verification;
- deterministic Finding deduplication and ranking;
- Review Policy evaluation.

Complete when providers cannot edit the repository, malformed or unsupported output fails clearly, Findings contain inspectable Evidence, and provider failures cannot silently become successful Reviews.

### Phase 5: Staged review TUI

Deliver:

- the interactive repository overview;
- a staged-review action and `preflight review --staged`;
- progress and Check-result presentation;
- provider destination and context disclosure;
- streamed and final Finding views;
- severity and verification filters;
- Finding details for Evidence, relevant diff, related files, history, and suggested tests;
- cancellation and retry flows.

Complete when a developer can open CodePreFlight, understand the repository state, review staged work, inspect every Finding's Evidence, and exit without repository mutation.

### Phase 6: Commit workflow and pre-commit integration

Deliver:

- commit-message generation from the reviewed staged diff;
- editable message preview;
- staged Change Set fingerprinting before and after review;
- forced re-review when the staged Change Set changes;
- explicit final commit approval;
- safe managed pre-commit hook installation, status, and removal;
- refusal to overwrite unknown existing hooks;
- manual integration instructions for existing hook managers;
- standard `--no-verify` bypass support;
- source-install and uninstall documentation.

This phase is the first MVP milestone.

Complete when a new user can install from source, initialize a repository, select a provider, review staged changes, inspect structured Findings, approve a commit message, and create a commit without existing hooks being overwritten.

### Phase 7: Branch, pre-push, and pull-request workflows

Deliver:

- branch merge-base resolution with explicit fallback behavior;
- `preflight review --branch` using Standard Review;
- optional managed pre-push integration;
- `preflight pr prepare` using Deep Review;
- branch summaries and risk areas;
- PR title and description generation;
- truthful sections for tests run, tests recommended, manual checks, breaking changes, and unresolved Findings;
- approved export of the PR draft.

Complete when multi-commit changes are reviewed as one Change Set, ambiguous base branches require developer selection, and generated PR text never claims unexecuted testing.

Creating or updating a GitHub pull request remains outside this phase.

### Phase 8: Blast radius and repository history

Deliver:

- relationships derived from imports, symbols, interfaces, routes, configuration, and tests;
- confirmed and inferred Blast Radius results;
- descriptive Attention Signals instead of numeric risk scores;
- Git log, blame, file-history, and commit-diff evidence collection;
- repository-scoped history questions;
- diff and branch explanations grounded in before/after behavior.

Complete when affected areas distinguish confirmed references from inference and history explanations identify the commits and files that support them.

### Phase 9: Caching, multi-provider review, and release hardening

Deliver:

- a local Review cache keyed by Review Fingerprint;
- explicit cache inspection and clearing;
- multi-provider second-opinion Reviews;
- grouping of overlapping Findings with provider attribution;
- presentation of conflicting provider opinions;
- privacy-safe structured logs;
- clean macOS and Linux installation verification;
- privacy, security, troubleshooting, contribution, upgrade, and uninstall documentation.

Complete when cache invalidation responds to all Review inputs, provider agreement is presented as evidence rather than truth, and no telemetry or credentials are stored.

## 8. Testing strategy

### Unit tests

Cover Git output parsing, configuration precedence, trust digests, ignore rules, redaction, context selection, Review Fingerprints, structured-output parsing, Finding verification, deduplication, and protocol validation.

### Repository integration tests

Use temporary Git repositories containing clean, dirty, detached, conflicted, renamed, deleted, no-remote, multi-commit, and existing-hook scenarios.

### Process contract tests

Use fake Git and Provider executables to test fragmented streaming output, malformed JSON, stderr noise, timeouts, authentication failures, cancellation, crashes, and incompatible versions.

### Live provider tests

Keep live Ollama and external-provider tests opt-in so ordinary development and CI do not spend tokens or require credentials.

### Review evaluation corpus

Maintain seeded examples for authentication regressions, validation errors, API compatibility breaks, schema/migration mismatches, concurrency defects, resource leaks, missing tests, accidental credentials, debug code, and safe changes that should return no Findings.

Measure verified detections, false positives, rejected hallucinations, provider failures, context size, and latency. Publish only reproducible measurements from the corpus.

## 9. Deferred scope

The following are intentionally deferred until the core review workflow is reliable:

- automatic code editing or autonomous fixes;
- push, force-push, merge, rebase, reset, checkout, or branch deletion;
- automatic GitHub pull-request creation or comments;
- a hosted inference backend;
- a browser interface;
- Windows support;
- bundled installers;
- roast presentation mode.
