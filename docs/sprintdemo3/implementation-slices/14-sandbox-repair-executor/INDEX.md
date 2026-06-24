# Feature 14 — Sandbox Repair Executor

## Purpose

Apply the exact approved candidate only in a backend-derived sandbox.

## Problem solved

Generic execution needs a single governed adapter that cannot mutate original source or substitute candidate bytes.

## PRD alignment

Backend owns sandbox, paths, commands, application, rollback preparation, and proof.

## Current code reality

`patch_apply.py` writes a patch artifact, snapshots touched files, runs `git apply --check`, applies, hashes results, and can roll back. Existing repair orchestrator uses these capabilities.

## Expected architecture

Executor resolves sandbox from attempt/checkpoint, revalidates policy and checksums, dispatches mode adapter, and records proposed candidate versus actual sandbox diff.

## Likely reuse points

Patch gate/apply, workspace containment, repair flow, ledger, rollback, and backend command construction.

## Likely future modified files

`patch_apply.py`, `validation_runner.py`, `v2_repair_flow.py`.

## Likely future new files

`v2_sandbox_repair_executor.py`, focused executor tests.

## Dependencies

Features 02 and 13, plus pre-execution revalidation task F12-T03.

## Blocks

Feature 15.

## Out of scope

Production/legacy source mutation, client paths, arbitrary commands, and checkpoint promotion.

## Acceptance criteria

Executor applies exact approved bytes in derived sandbox, verifies actual touched paths/diff, never mutates original source, and prepares rollback evidence.

## Focused test strategy

Exact bytes, containment, stale baseline, proposed/actual diff separation, source immutability, adapter selection, and failure cleanup.

## Risks

TOCTOU, symlink escape, unexpected generated changes, and incomplete rollback snapshot.
