# Provider setup and authentication

Start with:

```bash
preflight provider list
preflight provider models ollama
preflight provider test codex --yes
```

Provider readiness is reported separately for installation, authentication, model selection, and
invocation compatibility. The workspace presents one result: Ready, Action required, or
Unavailable. A running Ollama daemon without the configured model is not ready. CodePreFlight
never silently replaces an invalid default. Authentication alone never verifies invocation.
Successful synthetic tests and manual reviews record private, configuration-bound health
evidence; scans and automation require it. Changing model, variant, executable/version, or
destination invalidates that evidence.

CodePreFlight uses provider standard service only. Fast-tier model aliases such as names ending in
`-fast` are excluded from model selection and rejected in configuration. Model variants control
reasoning effort; they do not enable a faster billing or service tier.

## Subscription CLIs

```bash
preflight provider login codex
preflight provider models codex
preflight provider variants codex --model <model>
preflight provider use codex --model <model> --variant <variant> --write
preflight provider use codex --write

preflight provider login opencode
preflight provider models opencode
preflight provider variants opencode --model <provider/model>
preflight provider use opencode --model <provider/model> --variant <variant> --write
```

These commands default to a private per-repository preference under `.git/codepreflight/`.
Add `--global` to make the selection your machine-wide default. Add `--team` only when the
team intentionally wants to commit the provider choice in `.codepreflight.toml`.

The login process belongs to the provider CLI. The TUI temporarily yields terminal control, then
verifies authentication with the provider-owned status command and refreshes readiness. OpenCode
requires an explicit standard-tier model selection after authentication. Claude CLI reuse is
experimental and shows policy and billing guidance before activation.

Inside the TUI, use `/model` to choose a model and `/variant` to choose its reasoning variant.
`/varient` is accepted as a spelling alias. The model picker recommends using a capable
non-flagship model for routine reviews so flagship credits remain available for unusually difficult
changes.

## Local Ollama

```bash
preflight provider models ollama
preflight provider pull qwen2.5-coder:7b --yes
preflight provider use ollama --model qwen2.5-coder:7b --write
preflight provider test ollama --yes
```

Ollama is classified as local inference and requires a loopback endpoint. Remote Ollama URLs
are rejected rather than mislabeled local. Readiness queries the configured endpoint;
the configured model must already exist before the provider becomes review-capable.

## API providers

API configuration stores only the environment-variable name, model, and endpoint. Export the
credential in the shell or a secret manager; never place its value in any CodePreFlight
configuration file.

Before a remote interactive request, the session shows destination, selected context size,
redactions, and the context manifest. Consent lasts for that provider and open session only.
Full-repository scans always require a separate confirmation. Auto and Auto+ use a distinct scoped
grant under `.git/codepreflight/automation-grant.json`; it contains no credentials.

Preflight preserves standard proxy and TLS certificate environment settings for CLI
invocation, without printing their values. It never runs provider logout. See [reset guidance](RESET.md)
before clearing local state; doing so does not reset provider-owned sign-in.

## Opt-in live validation

Normal tests use synthetic fixtures without model usage. After configuring an installed
provider, explicitly opt in to one synthetic live test from the project root:

```bash
CODEPREFLIGHT_LIVE_PROVIDERS=1 CODEPREFLIGHT_LIVE_PROVIDER=codex \
  uv run --project engine pytest engine/tests/test_live_providers.py
```

This can consume provider usage but sends no repository content. It neither logs in nor
logs out. Without the provider selector, all ready adapters are tested; unavailable adapters
are skipped. An explicitly selected provider that is not ready fails with setup guidance.
