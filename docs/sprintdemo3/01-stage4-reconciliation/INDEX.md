# Feature 01 — Stage 4 Reconciliation

## Purpose

Bring governed Stage 4 behavior into `chatbot-optimization`.

## Problem solved

The active progression currently ends after Stage 3, while Stage 4 work exists in divergent commits.

## PRD alignment

Satisfies Stage 4 delivery, accepted Stage 3 input, F15 gate preservation, and MVP-A ordering.

## Current code reality

`v2_stage_progression.py`, `v2_job_service.py`, and tests describe three stages. Historical commits `3c11315`, `980c068`, `b48ae40`, and `1e06b32` contain relevant behavior. They are reconciliation inputs, not patches to apply blindly.

## Expected architecture

Extend current progression and runner paths. Stage 4 must resolve accepted Stage 3 artifacts and retain backend-owned command creation and F15 gates.

## Likely reuse points

V2 stage progression, orchestrator runner, job service, artifact revision repository, phase gates, and cockpit timeline.

## Likely future modified files

`migration_factory/control_tower/application/v2_stage_progression.py`, `v2_orchestrator_runner.py`, `v2_job_service.py`, `adapters/fastapi/app.py`, `schemas/`, `web/control-tower/lib/contracts.ts`, `MigrationCockpit.tsx`, and existing progression/runner tests.

## Likely future new files

`tests/control_tower/test_v2_stage4_progression.py`, `tests/control_tower/test_v2_stage4_schema.py`.

## Dependencies

None.

## Blocks

Features 03–05.

## Out of scope

Checkpoint aggregate implementation, intelligent recovery, blind migration reuse, and direct Stage 3→4 bypass.

## Acceptance criteria

- Governed Stage 4 exists on the active branch.
- Only accepted Stage 3 output can feed Stage 4.
- Existing F15 gates and artifact checksums remain authoritative.
- No checkpoint model is added here unless a minimal adapter is required; that decision needs verification.

## Focused test strategy

Stage count/profile tests, Stage 3 binding, output revision persistence, gate ordering, schema, and backend-owned launch.

## Risks

Branch divergence, duplicate migration content, and weakening current gate behavior.
