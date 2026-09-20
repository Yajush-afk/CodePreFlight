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

## Recoverable manual reset

Close Preflight and let any background review workers finish first. Remove managed hooks
if you do not want them to queue work after the reset. These commands only operate in the
repository you are currently inside:

```bash
preflight hooks remove pre-commit --write
preflight hooks remove post-commit --write
preflight hooks remove pre-push --write
git rev-parse --show-toplevel
preflight_state="$(git rev-parse --path-format=absolute --git-path codepreflight)"
ls -la "$preflight_state"
```

After verifying the displayed path belongs to the intended repository, move the state
aside instead of deleting it:

```bash
mv -- "$preflight_state" "$preflight_state.backup-$(date +%Y%m%d-%H%M%S)"
preflight
```

If the directory does not exist, there is no repository-local state to reset. This resets
personal preferences, health evidence, trust, review/scan caches, jobs and grants. It does
not change commits, source files, global Preflight preferences, optional team configuration,
or provider authentication. Keep the backup private; it can contain review findings.
To reset only ordinary review cache, use `preflight cache clear` instead.
