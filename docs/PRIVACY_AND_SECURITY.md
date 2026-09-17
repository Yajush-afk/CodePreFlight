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
message, and explicit final confirmation. Managed hooks preserve existing content inside
a removable marked block and fail open on operational failures unless the repository opts
into fail-closed behavior. CodePreFlight does not push, reset, rebase, merge, switch
branches, delete branches, or force-push.
