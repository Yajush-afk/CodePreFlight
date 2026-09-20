# Acceptance demo recording guide

Record in a terminal at least 100 columns wide, then repeat one short view near 60 columns to show
the responsive fallback. Use a clean shell profile and increase terminal font size enough for the
provider disclosure and finding evidence to remain legible.

## Prepare the seeded repository

From the CodePreFlight checkout:

```bash
evaluation/demo/setup.sh
cd <path printed by the script>
preflight init --team --write
preflight
```

The fixture contains a staged authentication regression and a deterministic failing test. AI
findings may vary by provider and model; do not claim a detection rate. Show the actual provider,
model, revision, check output, context size, and verification state.

## Recording sequence

1. Launch `preflight` and pause on repository, branch, provider, mode, and suggested actions.
2. Open `/provider`; show an unusable missing-model state and its recovery guidance if available.
3. Use the guided setup or `/providerlogin codex`, then `/providertest codex`. Do not
   repeat login if authentication is already valid. Pause recording during provider-owned login.
4. Open `/files`, preview the changed authentication file, and close the overlay.
5. Open `/commits`, select a commit, and explain first-parent semantics when relevant.
6. Type `/mo` to show model suggestions; use `/reviewstaged` and show the pipeline,
   transmission disclosure, checks, and verification. Open `/activity` for sanitized command outcomes.
7. Open a finding and ask “Explain finding 1” and “Which tests should I run?”.
8. Open `/mode` and explain Manual, Auto, and Auto+ without enabling unwanted hooks in the demo
   repository.
9. In a GitHub-backed branch, run `/pr` and `/reviewpr` to show detection and deep review.
10. In a separate clean synchronized base-branch repository, run `/scanfull`; pause on the dedicated
    manifest and confirmation before approving.
11. Finish with one recoverable failure: missing Ollama model, missing repository trust, or missing
    automation grant.

Show the right-side local commit graph and the reviewer/model/variant footer. Resize below
100 columns and open `/graph` to demonstrate the full-width fallback. During a local operation,
Esc cancels immediately; during a provider request it displays an inline second-Esc confirmation
with a two-second window. Ctrl+C exits. Use `preflight --inline` if your recorder does not handle
the alternate screen, or `PREFLIGHT_NO_ANIMATION=1 preflight` for static output.

For the full-scan segment, use a disposable local remote rather than changing your project:

```bash
scan_demo=$(mktemp -d)
git init --bare "$scan_demo/remote.git"
git clone "$scan_demo/remote.git" "$scan_demo/work"
cd "$scan_demo/work"
git switch -c main
printf 'def add(a, b):\n    return a + b\n' > arithmetic.py
git add arithmetic.py
git commit -m "Add arithmetic example"
git push -u origin main
preflight
```

Complete setup and a synthetic test, then `/scanfull`. This shell setup intentionally creates
and pushes only to the disposable local remote; CodePreFlight does not push or fetch.
Delete neither your account credentials nor your real repository to manufacture a failure.

Keep provider-owned login secrets and browser/device codes out of the recording. Do not claim a
test ran unless the check result says it ran, and do not present recommended tests as completed.
