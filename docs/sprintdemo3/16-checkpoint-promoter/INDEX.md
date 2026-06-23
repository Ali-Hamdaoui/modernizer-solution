# Feature 16 — Checkpoint Promoter

## Purpose

Promote validated stage output into an accepted checkpoint.

## Problem solved

Successful sandbox state must become immutable reusable lineage only after proof and human/governance requirements.

## PRD alignment

Completes recovery by producing the next accepted checkpoint.

## Current code reality

Stage progression, gate action, artifact revisions, and validation transitions exist. No checkpoint promoter exists. The requested `v2_artifact_revision_service.py` path was not found and is `needs verification`; current artifact revision repository/service wiring may be elsewhere.

## Expected architecture

Promoter atomically validates terminal attempt/proof, freezes artifact manifest, creates accepted checkpoint, links attempt output, and emits event.

## Likely reuse points

Checkpoint/attempt services, artifact revisions, gate actions, stage progression, checksums, UoW, and events.

## Likely future modified files

`v2_stage_progression.py`, `v2_gate_action_service.py`, artifact revision handling (`needs verification`).

## Likely future new files

`v2_checkpoint_promoter.py`, focused tests.

## Dependencies

Features 03, 04, and 15.

## Blocks

Features 17 and 18.

## Out of scope

Promotion after failed validation, mutable checkpoint content, and cross-job reuse.

## Acceptance criteria

Promotion is atomic, idempotent, lineage-complete, proof-bound, and impossible from failed/stale attempts.

## Focused test strategy

Pass/fail, duplicate promotion, stale input, manifest mismatch, transaction failure, and event emission.

## Risks

Partial persistence or promoting an unreviewed/unapproved repair result.
