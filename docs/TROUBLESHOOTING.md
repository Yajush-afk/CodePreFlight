# Troubleshooting

Start with `preflight doctor` and `preflight providers`.

- `provider_unavailable`: install or authenticate the selected CLI, start Ollama, or select
  another provider with `preflight provider use <id> --write`.
- `provider_consent_required`: inspect the provider disclosure and rerun the user-triggered
  command with `--approve` if the destination is acceptable.
- `repository_not_trusted`: run `preflight init --trust` after reviewing the repository and any
  team `.codepreflight.toml`. The approval is private under `.git`; no team file is required.
- `base_branch_required` or `base_branch_invalid`: pass `--base <branch>` explicitly.
- `provider_output_invalid`: the provider did not return schema-valid JSON. Retry with a
  compatible model or inspect the provider's own authentication and version. Reviews make
  one constrained repair attempt; a second malformed response is preserved locally as a
  failed, non-blocking review.
- stale-looking output: run with `--no-cache` or use `preflight cache clear`.
- `scan_blocked`: inspect all reported blockers. Full scans require a tested ready provider,
  a clean configured base branch, an upstream, and zero ahead/behind against local refs.
  No automatic fetch occurs.
- `scan_plan_stale`: repository, provider, configuration, or check side effects changed the
  preview. Run `/scanfull` again and inspect the new manifest. Old approval is not reused.
- `engine_request_idle_timeout`: no engine progress or provider heartbeat arrived for four
  minutes. The error reports the active scan stage, batch, locally cached completed batches, and
  last observed provider activity. Retry after checking the provider CLI; matching partial batch
  results can resume from the local scan cache.
- `provider_timeout`: one provider invocation exceeded its configured `timeout_seconds`. This is
  separate from the scan inactivity watchdog and from total scan duration.
- `staged_changes_changed`: the index changed during or after review. Review again before committing.
- Missing invocation evidence: use `/providertest`, or complete an ordinary manual review.
  Repeating login is not a substitute for testing the adapter.
- Terminal compatibility: use `preflight --inline`, `NO_COLOR=1`, or
  `PREFLIGHT_NO_ANIMATION=1`. Ctrl+C exits; Escape handles menus/text first, then interruption.

Hooks deliberately fail open on engine failures by default. Run the corresponding review
command manually to see the complete error. Use `preflight hooks status <hook>` before
reinstalling or removing a managed block.

Operational metadata is available in
`${XDG_STATE_HOME:-$HOME/.local/state}/codepreflight/events.jsonl`. It intentionally omits
repository paths, content, prompts, responses, payloads, and credentials. Removing this file
is safe; it will be recreated when the next command runs.
