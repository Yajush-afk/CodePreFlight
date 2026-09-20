# Resetting CodePreFlight

CodePreFlight state and provider authentication are separate. Clearing local reviews,
preferences, trust, automation grants, or provider health evidence does not sign you out
of Codex, OpenCode, Claude, or another application. CodePreFlight never runs provider logout.

Use `git rev-parse --git-path codepreflight` inside the intended repository to locate its
private state directory. Inspect that exact directory before removing individual cache
or settings files. Do not remove the Git directory itself. Keep a backup if you want to
restore preferences or reviews. Shared `.codepreflight.toml` configuration is separate.

Removing `provider-health.json` forgets successful connection tests, not credentials.
Run a synthetic provider test or a manual review to establish fresh evidence. Full scans
and automated reviews require matching successful invocation evidence. Signing in alone
does not establish it. Global provider sign-out is a separate provider-owned action and
can affect other applications using the same account.
