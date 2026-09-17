# Privacy and security model

CodePreFlight performs Git inspection, deterministic checks, context selection, secret
redaction, evidence verification, and cache management locally. It has no telemetry and
does not operate a hosted inference backend.

An AI request contains only the focused Context Package. Before a remote-capable provider
is invoked, the command requires explicit `--approve` consent and reports the provider,
context size, and redaction count. This approval is destination-specific for that command;
it is not a claim that the provider retains no data.

Repository files and diffs are untrusted input. Review prompts tell providers to treat that
content as evidence rather than instructions. CLI adapters run in temporary directories;
editing and shell tools are disabled where the provider supports those controls. Provider
output is schema-validated, and file, line, symbol, and commit references are checked
locally before presentation.

The local review cache lives under `.git/codepreflight/cache`. Cache entries contain the
structured result and Context Manifest, but not repository source or diff content. The
cache fingerprint covers the Context Package, provider identity and version, provider and
review configuration, checks, rules, ignores, target, base revision, and prompt version.
Inspect it with `preflight cache status` and remove it with `preflight cache clear`.

Repository configuration is rejected if a key appears to contain a secret. Credentials
must be supplied through named environment variables or provider-owned authentication.
Secret scanning is defense in depth, not a guarantee that every credential format will be
recognized. Review the Context Manifest and provider destination before approval.

Git reads are automatic. Commits require an unchanged staged fingerprint, an approved
message, and explicit final confirmation. CodePreFlight never modifies an unmanaged hook;
it returns a manual integration snippet when one already exists. Hooks created or already
managed by CodePreFlight use a removable marked block and fail open on operational failures
unless the repository opts into fail-closed behavior. CodePreFlight does not push, reset, rebase, merge, switch
branches, delete branches, or force-push.

## Local operational logs

CodePreFlight writes bounded JSON Lines operational logs to
`${XDG_STATE_HOME:-$HOME/.local/state}/codepreflight/events.jsonl`. A record contains a
timestamp, command name, hashed request identifier, duration, outcome, error code when applicable,
and a one-way truncated hash of the repository path. It never contains prompts, provider
responses, diffs, file contents, configuration values, command payloads, credentials, or
the repository path itself. The file is created with user-only permissions and rotated
locally. These logs are never transmitted; CodePreFlight has no analytics or telemetry.

## Threat model

Assets include repository source, Git state, credentials, provider authentication, and the
integrity of commits and hooks. Trust boundaries are the local repository, approved
repository commands, the TypeScript-Python protocol, local CLI providers, and remote API
providers.

Primary threats and mitigations:

- Prompt injection in source or diffs: repository content is labeled untrusted, context is
  bounded, adapters do not receive repository mutation permission, and findings are checked
  against local evidence.
- Credential disclosure: obvious secrets are scanned before provider invocation, supported
  values are redacted, unsafe content stops review, repository config rejects secret-like
  fields, and every remote destination requires disclosure and approval.
- Malicious repository configuration: executable checks require repository trust; changing
  the configuration digest or remote identity revokes that trust.
- Destructive Git behavior: inspection is read-only; commits require explicit confirmation
  and an unchanged staged fingerprint; push, reset, merge, rebase, checkout, branch deletion,
  and force-push are not implemented.
- Hook takeover: unmanaged hooks are never overwritten. Managed blocks can be previewed,
  disabled, removed, and bypassed through standard Git behavior.
- Hallucinated AI findings: structured output is validated, malformed responses receive only
  one constrained repair attempt, evidence is locally verified, rejected claims are hidden,
  and only verified configured severities may block.
- Local-state leakage: caches omit raw context and credentials; operational logs use only
  allow-listed metadata and a repository-path hash.

Residual risks remain. Pattern-based scanning cannot recognize every secret. Provider and
model retention policies are outside CodePreFlight's control. Read-only CLI sandboxing
depends on the installed provider honoring its documented controls. Static relationship
analysis is strongest for supported Python and JavaScript/TypeScript patterns and labels
text-search fallback as inferred.
