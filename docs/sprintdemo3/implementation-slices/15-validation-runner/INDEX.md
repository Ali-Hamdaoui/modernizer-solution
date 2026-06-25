# Feature 15 — Validation Runner

## Purpose

Use compile, focused tests, or configured validation to prove success.

## Problem solved

Repair application is not proof; DEMO3 needs policy-bound validation artifacts before promotion.

## PRD alignment

Sandbox plus deterministic validation is truth, and failed validation triggers rollback/no promotion.

## Current code reality

`repair_loop/validation_runner.py` runs build/test/H2 checks and returns artifact refs. Repair flow and orchestrator already coordinate validation/rollback.

## Expected architecture

A versioned validation policy selects backend-built operations by profile/mode and records immutable results/checksums.

## Likely reuse points

Current validation runner, orchestrator runner, repair flow, command launcher, rollback, artifact store, and ledger.

## Likely future modified files

`validation_runner.py`, `v2_repair_flow.py`, `v2_orchestrator_runner.py`.

## Likely future new files

`v2_validation_policy.py`, focused policy tests.

## Dependencies

Features 09 and 14.

## Blocks

Feature 16.

## Out of scope

Model-declared success and arbitrary model/client validation commands.

## Acceptance criteria

Configured checks are backend-owned and immutable; failure rolls back where required and cannot promote; pass yields exact proof refs.

## Focused test strategy

Compile, focused tests, configured alternatives, timeout, partial failure, rollback, redaction, and artifact checksums.

## Risks

Overbroad test scope, nondeterministic fixtures, or treating command launch as success.
