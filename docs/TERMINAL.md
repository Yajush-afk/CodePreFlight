# Terminal workspace

`preflight` opens fullscreen on a compatible interactive terminal. `preflight --inline`
keeps normal terminal output for recordings and accessibility. Direct commands and JSON
output never enter the alternate screen. CI, non-TTY output, and `TERM=dumb` disable
fullscreen and animation. Set `PREFLIGHT_NO_ANIMATION=1` to disable working animation.

The top shows repository, branch, and change counts. The middle holds conversation,
findings, or a focused picker. Suggestions sit directly above the composer. Reviewer,
model, reasoning effort, privacy category, and mode appear below it. Page Up/Down inspects
long output; `/activity` exposes sanitized operation details.

Escape dismisses suggestions first, then overlays, then composer text, then confirmation.
For local work it stops the operation immediately. For an AI invocation, press Escape
again within two seconds to stop it; the warning stays inline. Idle Escape does nothing.
Ctrl+C exits the session and cancels its requests. During provider-owned login, Preflight
yields terminal ownership and restores its workspace when login returns.
