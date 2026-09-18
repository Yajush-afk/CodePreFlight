# Acceptance demo recording guide

Record in a terminal at least 100 columns wide, then repeat one short view near 60 columns to show
the responsive fallback. Use a clean shell profile and increase terminal font size enough for the
provider disclosure and finding evidence to remain legible.

## Prepare the seeded repository

From the CodePreFlight checkout:

```bash
evaluation/demo/setup.sh
cd <path printed by the script>
preflight init --write
preflight
```

The fixture contains a staged authentication regression and a deterministic failing test. AI
findings may vary by provider and model; do not claim a detection rate. Show the actual provider,
model, revision, check output, context size, and verification state.

## Recording sequence

1. Launch `preflight` and pause on repository, branch, provider, mode, and suggested actions.
2. Open `/provider`; show an unusable missing-model state and its recovery guidance if available.
3. Run `/provider login codex` or `/provider login opencode`, then a synthetic provider test.
4. Open `/tree`, preview the changed authentication file, and close the overlay.
5. Open `/commits`, select a commit, and explain first-parent semantics when relevant.
6. Run `/review staged`; show the pipeline, transmission disclosure, checks, and verification.
7. Open a finding and ask “Explain finding 1” and “Which tests should I run?”.
8. Open `/mode` and explain Manual, Auto, and Auto+ without enabling unwanted hooks in the demo
   repository.
9. In a GitHub-backed branch, run `/pr` and `/review pr` to show detection and deep review.
10. In a separate clean synchronized base-branch repository, run `/scan full`; pause on the dedicated
    manifest and confirmation before approving.
11. Finish with one recoverable failure: missing Ollama model, missing repository trust, or missing
    automation grant.

Keep provider-owned login secrets and browser/device codes out of the recording. Do not claim a
test ran unless the check result says it ran, and do not present recommended tests as completed.
