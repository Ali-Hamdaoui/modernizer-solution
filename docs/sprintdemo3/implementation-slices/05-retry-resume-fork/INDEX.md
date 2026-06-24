# Feature 05 — Retry / Resume / Fork

## Purpose

Use accepted checkpoints to avoid restarting from Stage 1.

## Problem solved

Current linear progression does not model checkpoint-based recovery actions.

## PRD alignment

Completes MVP-A and is the prerequisite for intelligent repair execution.

## Current code reality

Backend-owned continuation, idempotent gate actions, and command state exist. Existing “retrying” behavior is command-launch retry, not the full DEMO3 checkpoint action model.

## Expected architecture

One service validates action semantics and creates new attempts against accepted checkpoints. APIs accept IDs/checksums only.

## Likely reuse points

Stage progression, checkpoint/attempt services, command idempotency, gate action service, and event stream.

## Likely future modified files

`v2_stage_progression.py`, FastAPI app, frontend API/contracts.

## Likely future new files

`v2_recovery_action_service.py`, `test_v2_recovery_actions.py`, `test_v2_retry_from_checkpoint.py`.

## Dependencies

Features 02–04.

## Blocks

All MVP-B features.

## Out of scope

Cross-job checkpoint reuse, automatic strategy selection, and LLM repairs.

## Acceptance criteria

Retry reuses input checkpoint; resume continues only valid interrupted state; fork creates explicit branch lineage; restart remains a separate action.

## Focused test strategy

Action semantics, invalid/stale checkpoint, stage/profile compatibility, idempotency, concurrency, and direct-stage blocking.

## Risks

Ambiguous action semantics, duplicate commands, and accidental mutation of accepted checkpoints.
