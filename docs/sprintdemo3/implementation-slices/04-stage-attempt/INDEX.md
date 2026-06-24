# Feature 04 — StageAttempt

## Purpose

Persist every execution, retry, repair, resume, or fork as an attempt.

## Problem solved

Current command and repair-gate history does not provide the complete DEMO3 execution aggregate or lineage.

## PRD alignment

Preserves failed and successful attempts and binds each execution to an input checkpoint.

## Current code reality

Commands, job events, repair records, and gate-derived attempt limits exist. `v2_repair_gate_service.py` partly derives counts from gate history. No `StageAttempt` aggregate was found.

## Expected architecture

Stage progression creates an attempt before execution; runner updates it through terminal state and stores output/proof refs.

## Likely reuse points

Command repository, orchestrator callbacks, event stream, gates, idempotency patterns, and SQLite UoW.

## Likely future modified files

`domain/`, `v2_stage_progression.py`, `v2_orchestrator_runner.py`, `unit_of_work.py`.

## Likely future new files

`v2_stage_attempt.py`, attempt service/repository/migration, DEMO3 event/audit tests, and focused attempt tests.

## Dependencies

Feature 03.

## Blocks

Features 05 and 06.

## Out of scope

Replacing command records, gate decisions, or repair ledger.

## Acceptance criteria

Every execution has immutable cause, input checkpoint, lineage, status, command/artifact refs, validation refs, and timestamps.

## Focused test strategy

State machine, idempotent creation, terminal immutability, restart durability, and failed-attempt preservation.

## Risks

Double-counting commands/gates as attempts or losing repair-attempt lineage.
