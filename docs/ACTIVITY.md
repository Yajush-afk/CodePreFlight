# Operation visibility

The interactive `/activity` view contains ephemeral, sanitized operation records:
actor, category, command, mutability, approval state, timing, outcome, and exit code when
available. Routine Git plumbing stays out of the main transcript. Events use protocol
version 3; both source-installed workspaces must be rebuilt together after updating.

Provider records describe the invocation CodePreFlight makes, not hidden tools inside
that provider. Codex runs in an ephemeral temporary directory with a read-only sandbox;
OpenCode disables write, edit, and Bash; Claude disallows Bash and editing tools.
HTTP request bodies and headers are never activity records. Prompts, provider responses,
environment values, and credential values are not captured by this activity channel.

Long-running subscription CLI calls emit a content-free heartbeat containing only the provider
actor and elapsed time. Scan progress adds the current stage, batch counts, selected source-path
names, and cache status. These events drive the working indicator without another model request;
they do not expose prompts, responses, credentials, or chain-of-thought.

Configured check commands are shown with supported credential patterns redacted.
Keep secrets out of command arguments and shareable repository configuration. Activity
is cleared when the session closes and is not a conversation transcript on disk.
