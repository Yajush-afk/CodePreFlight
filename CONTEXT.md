# CodePreFlight

CodePreFlight is the quality-control context between code creation and the Git workflow. This glossary defines the product language used to describe repository inspection, review, evidence, and developer decisions.

## Repository state

**Repository Snapshot**:
A read-only description of the repository at a specific moment, including its branch, changes, conflicts, remotes, and relevant project structure.
_Avoid_: Repo state dump, Git output

**Change Set**:
The exact collection of repository changes selected for one review, such as staged changes or the difference between a branch and its base.
_Avoid_: Patch bundle, changed code

**Review Target**:
The Git scope that defines a Change Set: staged changes, a branch, or a pull request.
_Avoid_: Review mode, diff type

**Base Branch**:
The branch against which a branch or pull-request Change Set is determined.
_Avoid_: Parent branch, target line

## Review

**Review**:
An inspection of a Change Set using repository evidence, deterministic checks, Repository Rules, and a selected Provider.
_Avoid_: Scan, audit

**Finding**:
A single review concern that states what happened, where the evidence exists, why it matters, and what deserves inspection or change.
_Avoid_: Comment, issue, alert

**Evidence**:
Repository information that supports or contradicts a Finding, such as changed lines, related symbols, tests, configuration, or Git history.
_Avoid_: Model reasoning, proof

**Verification State**:
The degree to which a Finding's claims correspond to available repository Evidence.
_Avoid_: Truth score, accuracy percentage

**Severity**:
The engineering consequence assigned to a Finding: Critical, Warning, Suggestion, or Informational.
_Avoid_: Priority, risk score

**Review Depth**:
The intended breadth of a Review: Fast for staged changes, Standard for a branch, or Deep for a pull request.
_Avoid_: Quality level, model strength

**Review Policy**:
The repository or user decision that determines whether Findings are informational, warning-only, or blocking.
_Avoid_: Enforcement mode, AI authority

## Context and checks

**Context Package**:
The focused repository information selected for a Provider to analyze during one Review.
_Avoid_: Prompt dump, repository upload

**Context Manifest**:
The record of what a Context Package includes, excludes, redacts, or truncates.
_Avoid_: Token report, file list

**Review Fingerprint**:
A deterministic identity for the complete inputs to a Review, used to detect changed work and safely reuse a prior result.
_Avoid_: Cache key, diff hash

**Check**:
A deterministic repository command whose observed result may inform a Review, such as a test, linter, type check, or build validation.
_Avoid_: Tool call, validation step

**Repository Rule**:
A shared project expectation that guides Reviews, such as requiring tests for public interfaces or migrations for schema changes.
_Avoid_: Prompt instruction, lint rule

**Attention Signal**:
A concrete reason a Change Set deserves additional human inspection, without presenting arbitrary numerical risk.
_Avoid_: Risk score, danger percentage

**Blast Radius**:
The set of repository behavior and related code that may be affected by a Change Set.
_Avoid_: Impact score, dependency list

## Providers and safety

**Provider**:
The configured AI capability that analyzes a Context Package, whether reached through a local model, authenticated CLI, or user-supplied API credential.
_Avoid_: Agent, backend, model vendor

**Repository Trust**:
The developer's approval for CodePreFlight to use a repository's configured Checks and review settings.
_Avoid_: Safe repository, allowlist
