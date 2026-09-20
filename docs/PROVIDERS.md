# Provider setup and authentication

Start with:

```bash
preflight provider list
preflight provider models ollama
preflight provider test codex --yes
```

Provider readiness is reported separately for installation, authentication, model selection, and
invocation compatibility. A running Ollama daemon without the configured model is degraded, not
ready. CodePreFlight never silently replaces an invalid default.

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

Ollama is classified as local inference. The configured model must already exist before the
provider becomes review-capable.

## API providers

API configuration stores only the environment-variable name, model, and endpoint. Export the
credential in the shell or a secret manager; never place its value in any CodePreFlight
configuration file.

Before a remote interactive request, the session shows destination, selected context size,
redactions, and the context manifest. Consent lasts for that provider and open session only.
Full-repository scans always require a separate confirmation. Auto and Auto+ use a distinct scoped
grant under `.git/codepreflight/automation-grant.json`; it contains no credentials.
