# Troubleshooting

Start with `preflight doctor` and `preflight providers`.

- `provider_unavailable`: install or authenticate the selected CLI, start Ollama, or select
  another provider in `.codepreflight.toml`.
- `provider_consent_required`: inspect the provider disclosure and rerun the user-triggered
  command with `--approve` if the destination is acceptable.
- `repository_not_trusted`: review `.codepreflight.toml`, then run `preflight init --write`
  in a repository without a config. If an existing config changed, review it and run
  `preflight init --trust` to refresh local trust state.
- `base_branch_required` or `base_branch_invalid`: pass `--base <branch>` explicitly.
- `provider_output_invalid`: the provider did not return schema-valid JSON. Retry with a
  compatible model or inspect the provider's own authentication and version. Reviews make
  one constrained repair attempt; a second malformed response is preserved locally as a
  failed, non-blocking review.
- stale-looking output: run with `--no-cache` or use `preflight cache clear`.

Hooks deliberately fail open on engine failures by default. Run the corresponding review
command manually to see the complete error. Use `preflight hooks status <hook>` before
reinstalling or removing a managed block.

Operational metadata is available in
`${XDG_STATE_HOME:-$HOME/.local/state}/codepreflight/events.jsonl`. It intentionally omits
repository paths, content, prompts, responses, payloads, and credentials. Removing this file
is safe; it will be recreated when the next command runs.
