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
Review batches group related source and test files by subsystem. Common lockfiles are excluded
from provider context and recorded in the manifest. The preview shows the exact selected file
paths and line ranges for each batch. Codex CLI defaults to at most two concurrent batch requests;
other providers default to one. Set `scan.max_parallel_requests` to 1 or 2 to override. A rate-limit
response reduces the remaining work to one request at a time. Completed batches can be reused
from the matching local cache. The final summary is assembled locally from verified findings and
check results, without an additional provider synthesis request.
Synchronization uses local tracking references, without automatically fetching.
Scan operations never authenticate, log out, change provider settings, or switch branches.

Use `/scanfull` in the workspace. The preview includes source inclusion/exclusion reasons;
PgUp/PgDn lets you inspect long manifests. Files with single lines too large for the selected
batch budget are explicitly excluded rather than silently overflowing it. Check execution
is followed by a repository-state validation before transmission, and state is checked again
before evidence verification. Changed check results cannot reuse old partial batch results.

Full scans do not inherit the ordinary five-minute engine-request deadline. Each provider call
still uses its configured `timeout_seconds`. While a subscription CLI is running, CodePreFlight
emits a content-free heartbeat every five seconds. The terminal applies a four-minute inactivity
watchdog that resets on real engine progress or a provider heartbeat; it is not an overall scan
duration limit. Escape cancellation still terminates the engine process group.

Progress text reports what Preflight actually did: scan stages, active batch numbers, exact selected
source paths, cache reuse, and evidence verification. A locally updated one-second timer is shown
without generating provider requests. `/activity` shows sanitized Preflight-run commands; provider-
internal file reads or commands cannot be observed and are not claimed. There are no invented model
thoughts or provider-personality messages.
