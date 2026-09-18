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

## Subscription CLIs

```bash
preflight provider login codex
preflight provider use codex --write

preflight provider login opencode
preflight provider models opencode
preflight provider use opencode --model <model> --write
```

The login process belongs to the provider CLI. The TUI temporarily yields terminal control, then
refreshes readiness. Claude CLI reuse is experimental and shows policy and billing guidance before
activation.

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
credential in the shell or a secret manager; never place its value in `.codepreflight.toml`.

Before a remote interactive request, the session shows destination, selected context size,
redactions, and the context manifest. Consent lasts for that provider and open session only.
Full-repository scans always require a separate confirmation. Auto and Auto+ use a distinct scoped
grant under `.git/codepreflight/automation-grant.json`; it contains no credentials.
