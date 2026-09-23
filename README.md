# CodePreFlight

CodePreFlight is a terminal-based Git workflow and AI code review tool. It helps developers inspect repository changes, understand Git state, review code before it is committed or merged, and move changes through Git with greater confidence.

CodePreFlight sits around the coding process rather than replacing it. A developer or coding agent writes the code; CodePreFlight examines the resulting changes. Reviews combine repository context, deterministic engineering checks, repository-specific rules, and an AI provider selected by the developer.

The tool is local-first, provider-agnostic, and explicit about when repository content is sent to an external provider. It supports local models, compatible AI command-line tools that use an existing subscription, and user-supplied API credentials. CodePreFlight does not operate its own inference service.

Its core responsibilities are:

- presenting repository and branch state clearly;
- reviewing staged, branch, and pull-request changes;
- identifying correctness, security, compatibility, and testing concerns;
- validating AI findings against repository evidence;
- explaining diffs, affected areas, and relevant Git history;
- assisting with safe commit and pull-request workflows;
- keeping every repository mutation under explicit developer control.

CodePreFlight is not a coding agent, code editor, IDE, or autonomous software engineer. It is the quality-control layer between code generation and the Git workflow.

## Install from source

CodePreFlight currently supports macOS and Linux with Node.js 22+, Python 3.12+, Git, npm,
and [`uv`](https://docs.astral.sh/uv/) installed.

```bash
git clone https://github.com/Yajush-afk/CodePreFlight.git
cd CodePreFlight
make install
npm run build
npm link --workspace @codepreflight/cli
preflight doctor
```

The installed command is `preflight`. Run it inside a Git repository to open the interactive
terminal view, or use direct commands:

```bash
preflight status
preflight provider list
preflight provider use codex --write
preflight review --staged
preflight review --commit HEAD
preflight review --branch
preflight workspace tree
preflight automation status
preflight scan full
preflight pr prepare
```

Normal personal use creates no files in the repository. Provider, model, and variant choices
are stored privately under `.git/codepreflight/`, where Git never tracks them. Machine-wide
defaults live in the XDG user configuration. Teams may explicitly run `preflight init --team`
to preview an optional `.codepreflight.toml`, then `preflight init --team --write` to share
review rules, ignore patterns, approved checks, and base-branch settings. API credentials stay
in environment variables. Authenticated provider CLIs require `preflight init --trust`, whose
approval also stays privately under `.git`. Before any remote provider receives code,
CodePreFlight displays the destination, selected-context size, redactions, and context
manifest and requires explicit approval.

## Review workflow

A fast staged review runs deterministic checks, builds a bounded context package, scans it
for credentials, asks the selected provider for structured findings, and verifies the
reported paths and lines locally. Branch review expands the target to the merge base. PR
preparation performs the deep review and drafts a title and description while distinguishing
checks actually run from tests merely recommended.

Each finding includes severity, confidence, evidence, verification state, impact, and a
recommended action. Running `preflight` opens a fullscreen, ephemeral repository session with a
persistent composer, guided setup, and a display-only local commit graph. Use `/files`,
`/branches`, `/commits`, `/review`, `/reviewcommit <revision>`, `/reviewbranch`, `/reviewpr`,
`/mode`, `/scanfull`, `/findings`, and `/help`; plain-language questions stay
scoped to repository, Git, review, and history evidence. After a review, `/findings` opens a
scrollable explorer and follow-up questions can discuss multiple findings without staged changes.
Arrow keys navigate focused lists or scroll the transcript; Ctrl+P/Ctrl+N recall composer history.
Reviews advise by default; only verified severities configured by the
repository can block a managed hook. Operational provider failures are fail-open unless the
repository explicitly opts into fail-closed behavior. Standard `git commit --no-verify` and the
temporary `PREFLIGHT_BYPASS=1` environment variable remain explicit bypass routes.

Provider authentication remains provider-owned. `preflight provider login codex` launches the
Codex login flow, while `preflight provider login opencode` launches OpenCode authentication.
Ollama stays local and requires an installed model; API providers read named environment
variables and CodePreFlight never stores the secret value. Use
`preflight provider test <id> --yes` for a synthetic smoke test that sends no repository content.
Use `/model` and `/variant` in the interactive session to select a provider model and reasoning
effort. CodePreFlight exposes only the standard service tier and filters fast-tier model aliases.
For routine reviews, the picker recommends a capable non-flagship model to reduce credit usage.

Type `/` for fuzzy command suggestions and contextual arguments. Use `/activity` for sanitized
command outcomes and `preflight --inline` for the non-fullscreen fallback.
See the [workspace guide](docs/INTERACTIVE_SESSION.md), [scan approval guide](docs/FULL_SCAN.md),
and [demo walkthrough](docs/DEMO.md).

## Reproducible seeded-defect demonstration

This demonstration creates a temporary repository with working authentication validation,
then stages a regression that removes it. It includes a deterministic failing test; AI review
results can vary by provider and model, so the project makes no detection-rate claim.

```bash
demo_dir="$(mktemp -d)"
cp evaluation/seeded/auth_validation/before.py "$demo_dir/auth.py"
cp evaluation/seeded/auth_validation/check_auth.py "$demo_dir/test_auth.py"
git -C "$demo_dir" init -b main
git -C "$demo_dir" config user.name "Preflight Demo"
git -C "$demo_dir" config user.email "demo@codepreflight.local"
git -C "$demo_dir" add .
git -C "$demo_dir" commit -m "Add validated session creation"
cp evaluation/seeded/auth_validation/after.py "$demo_dir/auth.py"
git -C "$demo_dir" add auth.py
cd "$demo_dir"
preflight provider use ollama --model qwen2.5-coder:7b --write
preflight status
preflight review --staged --provider ollama
```

Replace `ollama` with an available provider shown by `preflight providers`; remote providers
also require `--approve` after reading the disclosure. If `pytest` is configured as an
approved repository check, its actual failure is reported separately from the AI findings.

## Safe Git integration

`preflight hooks install pre-commit` and `preflight hooks install pre-push` preview managed
hook content. Add `--write` to create a hook only when the path is empty or already managed by
CodePreFlight. An unknown existing hook is never changed; the command returns a manual
integration snippet instead. Managed hooks can be enabled, disabled, reinstalled, or removed.
Commits require a reviewed staged fingerprint, an editable message, and explicit final
approval. CodePreFlight does not push, force-push, merge, rebase, or delete branches.

Detailed operational documentation:

- [Installation, upgrade, and uninstall](docs/INSTALL.md)
- [Interactive repository session](docs/INTERACTIVE_SESSION.md)
- [Provider setup and authentication](docs/PROVIDERS.md)
- [Configuration scopes](docs/CONFIGURATION.md)
- [Acceptance demo recording guide](docs/DEMO.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Privacy, local logs, and threat model](docs/PRIVACY_AND_SECURITY.md)
