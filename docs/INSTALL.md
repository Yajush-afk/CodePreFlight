# Install CodePreFlight from source

CodePreFlight currently supports macOS and Linux. It requires Node.js 22 or newer,
Python 3.12 or newer, `npm`, `uv`, and Git.

```bash
git clone https://github.com/Yajush-afk/CodePreFlight.git
cd CodePreFlight
make install
npm run build
npm link --workspace @codepreflight/cli
preflight doctor
```

Run `preflight init` inside a repository to preview the detected configuration. Review
that preview, then use `preflight init --write` to create `.codepreflight.toml` and trust
its deterministic checks. The repository configuration is team-shareable; credentials
must stay in environment variables or provider-owned authentication.

## Provider configuration

Run `preflight providers` before selecting a provider. Ollama is the default and keeps
the request on the local machine. CLI providers reuse their own installed authentication.
An OpenAI-compatible endpoint reads its API key from an environment variable.

```toml
[review]
provider = "ollama"
policy = "warning"

[providers.ollama]
model = "qwen2.5-coder:7b"
base_url = "http://127.0.0.1:11434"

[providers.openai-compatible]
model = "gpt-4.1-mini"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

Use `--approve` only after reviewing the destination disclosure for a provider that may
send repository evidence remotely.

## Upgrade and uninstall

Pull the desired revision, rerun `make install`, and rebuild. Before uninstalling, remove
managed hooks from each repository with `preflight hooks remove pre-commit --write` and
`preflight hooks remove pre-push --write`. Then run:

```bash
npm unlink --global @codepreflight/cli
```

Optional local state can be removed from `.git/codepreflight/`. Global configuration is
stored under `${XDG_CONFIG_HOME:-$HOME/.config}/codepreflight/`.
