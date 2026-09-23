# Interactive repository session

Run `preflight` inside a Git repository. The session is an ephemeral repository workspace: the
transcript, command history, finding selection, and provider consent disappear when it exits.
Structured review and scan caches remain under `.git/codepreflight/`; no conversation is saved.

The fullscreen header shows repository, branch and changed-file counts. A display-only local
commit graph appears on the right at 100 columns or wider. The footer shows reviewer, model,
variant, privacy category and review mode. Detailed tracking/PR/provider information lives in
its dedicated view. CodePreFlight never fetches to refresh the display. One recommended action
follows the current state. Use `preflight --inline` to disable fullscreen.

When setup is needed, choose a provider, resolve authentication/model requirements, optionally
choose reasoning effort and test with synthetic code, then approve repository trust. “Continue
without AI” leaves all local inspection available. Setup is derived from readiness, not a
permanent “onboarding completed” flag.

## Commands

```text
/status
/files
/graph
/branches
/switchbranch <local-branch>
/commits
/review
/reviewstaged
/reviewcommit <revision>
/reviewbranch
/reviewpr
/findings
/pr
/provider
/providerlogin <provider>
/providertest <provider>
/providerswitch <provider>
/model
/variant
/mode
/jobs
/activity
/automationgrant
/automationrevoke
/scanfull
/file <path>
/commit [message]
/help
/clear
/quit
```

Slash commands route deterministically. Plain text is sent only as a repository-scoped question,
such as “What changed on this branch?”, “Explain findings 2, 3 and 4”, or “Which tests should I run?”.
After a review, questions use the active review and selected finding evidence even when the index
is clean. The provider can explain possible fixes but cannot edit files. Changing branches clears
that review context. The provider receives locally gathered evidence; adapters constrain editing
and shell tools.
Preflight reports only tool operations it can actually observe.

`/model` opens the active provider's discoverable standard-tier models. Fast-tier aliases are not
shown. `/variant` selects provider-supported reasoning effort without changing service speed;
`/varient` offers a correction to `/variant`. Provider login asks for confirmation, clears the Ink frame while the
official CLI owns the terminal, verifies the resulting authentication state, and then restores the
session.

Typing `/` opens fuzzy suggestions above the composer; `/mo` ranks model before mode.
Commands requiring an argument offer contextual commits, branches, providers or paths.
Arrows select, Tab completes without execution, Enter selects/runs, and Escape dismisses.
With no suggestion menu and an empty composer, Up/Down scroll the transcript. Ctrl+P/Ctrl+N
navigate ephemeral command history. PgUp/PgDn scroll by page. `/findings` opens a severity-sorted,
scrollable list; select a finding for its evidence, impact, verification and suggested tests,
then ask a follow-up from the composer.

Escape closes suggestions, then overlays, then clears composer text, then cancels a pending
decision. With none of those active it stops local work immediately. During provider work,
press Escape twice within two seconds to stop; the first press shows inline guidance.
Ctrl+C explicitly exits the session. PgUp/PgDn scroll transcript or preview details.

## Review cadence

- Manual runs no automatic AI reviews. Optional pre-commit staged review remains independent.
- Auto detects new or changed open pull requests on session launch, refresh, post-commit, and
  pre-push events.
- Auto+ also queues a fast review for each commit and runs a synchronous branch review before
  push. Post-commit work never blocks or reverses a commit.

Auto and Auto+ state is personal and stored in `.git/codepreflight/automation.json`. Closed-session
provider use requires a credential-free scoped grant. Provider, executable version, model,
destination, repository, rules, or configuration changes invalidate it. Inspect jobs with `/jobs`
and revoke the grant with `/automationrevoke`.

## Branch safety

CodePreFlight switches only to an existing local branch and only after confirmation. It refuses
active Git operations, conflicts, tracked-file collisions, and untracked-file collisions. It does
not fetch, create, delete, merge, rebase, or stash branches. A failed `git switch` is reported
without recovery mutations.
