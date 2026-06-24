# Feature 12 — Backend Policy Validator

## Purpose

Judge safety and applicability generically without knowing the exact fix in advance.

## Problem solved

Existing patch gates provide strong path checks but current rule evaluation is often repair-specific and DEMO3 needs unified lineage/review/approval/dependency/config controls.

## PRD alignment

Keeps backend fixed around generic safety, execution, and proof rather than exact repair knowledge.

## Current code reality

`patch_gate.py` checks traversal, absolute paths, forbidden prefixes, legacy/run-root containment, symlink parents, and security changes. `patch_apply.py` snapshots and applies. Existing reviewer and gate checksum checks can be reused.

## Expected architecture

Compose lineage, checksum, patch, dependency, config, review, and approval validators under the selected safety envelope.

## Likely reuse points

Patch gate/apply, POM dependency policy, workspace containment, reviewer repository, gate decisions, checksums, and repair flow.

## Likely future modified files

`patch_gate.py`, `patch_apply.py`, `v2_repair_gate_service.py`, `v2_repair_flow.py`.

## Likely future new files

Backend/patch/dependency/config validators, pre-execution revalidation tests, and focused policy tests.

## Dependencies

Features 09–11.

## Blocks

Features 13 and 14.

## Out of scope

Authoring exact fixes, deriving human approval, or running validation commands.

## Acceptance criteria

Pre-approval validation rejects stale checksums, traversal, symlink escape, forbidden paths, excessive files/diff, policy violations, and unreviewed candidates. The same validator is called again before execution to reject stale or unapproved state.

## Focused test strategy

One focused family per validator plus composed fail-closed behavior.

## Risks

TOCTOU between validation/apply and mismatch between proposed and actual touched paths.
