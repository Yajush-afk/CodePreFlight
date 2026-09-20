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

No repository initialization is required for personal use. Select a provider with
`preflight provider use <id> --write`; CodePreFlight stores that choice privately under
`.git/codepreflight/`, so it does not appear in Git status.
Before first use of an authenticated provider CLI, run `preflight init --trust` to record private
repository approval under the same Git metadata directory.

Teams that want shared rules and approved deterministic checks can run `preflight init --team`
to preview an optional `.codepreflight.toml`, then `preflight init --team --write` to create
and trust it. Credentials must stay in environment variables or provider-owned authentication.

## Provider configuration

Run `preflight providers` before selecting a provider. Ollama keeps the request on the local
machine. CLI providers reuse their own installed authentication.
An OpenAI-compatible endpoint reads its API key from an environment variable.

```toml
rules = ["Public API changes require tests"]

[review]
policy = "warning"
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
stored under `${XDG_CONFIG_HOME:-$HOME/.config}/codepreflight/`. Bounded local operational
logs are stored under `${XDG_STATE_HOME:-$HOME/.local/state}/codepreflight/`; deleting that
directory is optional and does not affect repositories.

## Future bundled packaging boundary

The stable source distribution has two artifacts: the compiled `@codepreflight/cli`
workspace and the locked `codepreflight-engine` Python environment. A future macOS/Linux
bundle must preserve the versioned NDJSON protocol between them, run `preflight doctor`
after installation, install no Git hooks automatically, and keep global configuration and
state in the same XDG locations. Bundling must not add telemetry, embedded credentials, or a
persistent local server. Source installation remains the reference behavior until clean
macOS and Linux CI stays stable.
