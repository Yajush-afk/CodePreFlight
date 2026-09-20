# ADR 0003: Separate private preferences from team configuration

## Status

Accepted

## Context

Provider selection originally wrote `.codepreflight.toml` at the repository root. This made a
personal subscription, model, or reasoning choice look like team policy and left an untracked file
in repositories that did not otherwise need CodePreFlight configuration.

CodePreFlight also needs a legitimate shareable configuration surface for repository rules,
approved commands, ignores, base-branch selection, and review policy.

## Decision

Load configuration through one engine interface in increasing precedence order:

1. XDG global user configuration.
2. Optional repository `.codepreflight.toml` team configuration.
3. Private `.git/codepreflight/preferences.toml` repository preference.

The private schema permits only provider, model, and variant selection. Repository rules,
commands, hooks, and policy remain global or team configuration. Provider setup defaults to the
private scope; global and team writes require explicit command flags. Repository initialization is
an explicit team action and never captures whichever provider happens to be available locally.
Repository trust is also private Git metadata and can be granted without creating a team file.

## Consequences

Normal personal use produces no working-tree files and cannot accidentally commit personal model
choices. Teams can still version a deterministic policy file when they choose to. Existing team
files remain compatible and continue to load. Trust digests cover only the executable team
configuration, so changing a private provider choice does not invalidate repository trust.
