# Full scan approval

Run `preflight scan full` to preview a scan. Planning inspects local Git references,
provider readiness, tracked files, redactions, configured checks, and cached results.
It does not run configured checks or send review requests. All detected readiness and
repository blockers are returned together. Successful provider invocation evidence is
required; authentication alone is insufficient.

The preview prints a fingerprint. Approve that exact preview with
`preflight scan full --yes --plan <fingerprint>`. Repeat any provider override when
approving. The engine rebuilds the read-only preview and rejects changed fingerprints.
Cached results require the same explicit approval. In the TUI the confirmation carries
the fingerprint automatically. Check commands run once, after approval, on a cache miss.

Request counts are estimates: malformed structured output can require repair requests.
Synchronization uses local tracking references, without automatically fetching.
Scan operations never authenticate, log out, change provider settings, or switch branches.

Use `/scanfull` in the workspace. The preview includes source inclusion/exclusion reasons;
PgUp/PgDn lets you inspect long manifests. Files with single lines too large for the selected
batch budget are explicitly excluded rather than silently overflowing it. Check execution
is followed by a repository-state validation before transmission, and state is checked again
before evidence verification. Changed check results cannot reuse old partial batch results.
