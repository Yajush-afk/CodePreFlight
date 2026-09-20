# Configuration scopes

CodePreFlight separates personal choices from team policy so normal use does not add files to a
repository.

Configuration is applied in this order, with later values overriding earlier ones:

1. The global user configuration at
   `${XDG_CONFIG_HOME:-$HOME/.config}/codepreflight/config.toml` provides machine-wide defaults.
2. The optional `.codepreflight.toml` in the repository contains team-owned rules, approved
   checks, ignores, base-branch settings, and review policy.
3. `.git/codepreflight/preferences.toml` contains the current developer's provider, model, and
   variant choices for that repository.

The private preference lives inside Git's own metadata directory. It is not part of the working
tree, does not appear in `git status`, and cannot be committed accidentally. CodePreFlight limits
this file to provider selection fields; checks, hooks, and repository rules are rejected there.

Use the default private scope for ordinary setup:

```bash
preflight provider use codex --model <model> --write
```

Use `--global` when the same provider should be the default for every repository on the machine.
Use `--team` only when intentionally changing the shareable repository configuration.

Running `preflight init` creates nothing. It explains that personal setup is already available.
`preflight init --team` previews the optional team file, and
`preflight init --team --write` creates and trusts it after review.

Authenticated subscription CLIs run with the repository as their working directory, so their first
use requires explicit repository trust. `preflight init --trust` records that approval under
`.git/codepreflight/trust.json`; it does not require or create a team configuration file.

No scope stores credentials. Subscription CLI authentication remains with the provider CLI, and
API providers refer only to environment-variable names.
