# Guided reviewer setup

An unavailable reviewer opens a guided setup screen. Choose a provider, authenticate
through its own CLI if needed, select an available model, optionally choose reasoning
effort, and optionally run a confirmed synthetic test. Review and approve repository
trust separately. Each screen reflects current capabilities; expired authentication
returns to login without erasing the selected model or variant.

Choose **Continue without AI** to use local status, files, branches, and history. Use
`/provider` to resume setup. Provider selection only saves a private preference; it does
not claim that authentication, model access, or real invocation has succeeded.

Synthetic tests contain no repository source but can consume subscription credits.
Manual review can establish invocation evidence without a prior test. Full scans and
automation require matching evidence. API providers use named environment variables;
do not paste keys into Preflight. Claude CLI integration is experimental: confirm provider
policy and billing before activation. Preflight never performs provider logout.
