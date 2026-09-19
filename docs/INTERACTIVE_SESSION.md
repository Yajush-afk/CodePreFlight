# Interactive repository session

Run `preflight` inside a Git repository. The session is an ephemeral repository workspace: the
transcript, command history, finding selection, and provider consent disappear when it exits.
Structured review and scan caches remain under `.git/codepreflight/`; no conversation is saved.

The header shows the repository, current and base branches, locally known ahead/behind state,
working-tree categories, provider readiness, and review mode. CodePreFlight never fetches merely
to refresh this display. Suggested actions follow the current repository state.

## Commands

```text
/status
/tree
/branches
/switch <local-branch>
/commits
/review staged
/review commit <revision>
/review branch
/review pr
/pr
/provider
/model
/variant
/mode
/jobs
/automation grant
/automation revoke
/scan full
/commit [message]
/help
/clear
/quit
```

Slash commands route deterministically. Plain text is sent only as a repository-scoped question,
such as “What changed on this branch?”, “Explain finding 2”, or “Which tests should I run?”. The
provider receives locally gathered evidence and has no editing or shell capability.

`/model` opens the active provider's discoverable standard-tier models. Fast-tier aliases are not
shown. `/variant` selects provider-supported reasoning effort without changing service speed;
`/varient` is also accepted. Provider login asks for confirmation, clears the Ink frame while the
official CLI owns the terminal, verifies the resulting authentication state, and then restores the
session.

Use Up and Down in the composer for ephemeral command history. Use arrows and Enter in a focused
tree, branch, commit, or provider list. Escape closes an overlay. The first Ctrl+C cancels active
work; with no active request, Ctrl+C exits.

## Review cadence

- Manual runs no automatic AI reviews. Optional pre-commit staged review remains independent.
- Auto detects new or changed open pull requests on session launch, refresh, post-commit, and
  pre-push events.
- Auto+ also queues a fast review for each commit and runs a synchronous branch review before
  push. Post-commit work never blocks or reverses a commit.

Auto and Auto+ state is personal and stored in `.git/codepreflight/automation.json`. Closed-session
provider use requires a credential-free scoped grant. Provider, executable version, model,
destination, repository, rules, or configuration changes invalidate it. Inspect jobs with `/jobs`
and revoke the grant with `/automation revoke`.

## Branch safety

CodePreFlight switches only to an existing local branch and only after confirmation. It refuses
active Git operations, conflicts, tracked-file collisions, and untracked-file collisions. It does
not fetch, create, delete, merge, rebase, or stash branches. A failed `git switch` is reported
without recovery mutations.
