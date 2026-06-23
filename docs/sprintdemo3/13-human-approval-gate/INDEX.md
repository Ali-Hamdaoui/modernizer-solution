# Feature 13 — Human Approval Gate

## Purpose

Require a human to approve the exact reviewed candidate revision.

## Problem solved

Existing repair approval and gate actions are reusable, but DEMO3 approval must bind all new candidate/review lineage and cannot be inferred from reviewer acceptance.

## PRD alignment

Human remains the decision owner; backend validates exact checksums and actor authority.

## Current code reality

F15 gate action service supports approve/reject/revise, checksum stale protection, idempotency, and repair reviewer checks.

## Expected architecture

An approval service adapts existing gates to exact DEMO3 candidate/review records. API accepts IDs, decision, checksum, feedback, and idempotency only.

## Likely reuse points

Gate action/phase services, gate decisions, repair gate service, actor model, checksums, and idempotency.

## Likely future modified files

`v2_gate_action_service.py`, `v2_repair_gate_service.py`, FastAPI app, frontend API/contracts.

## Likely future new files

`v2_repair_approval_service.py`, `test_v2_human_repair_approval.py`.

## Dependencies

Features 02, 10, and 11, plus Feature 12 pre-approval tasks F12-T01 and F12-T02.

## Blocks

Feature 14.

## Out of scope

Automatic/model approval and execution.

## Acceptance criteria

Human approve/reject/revise binds exact candidate and accepted review checksums; stale or non-human actions fail; approval alone does not bypass policy.

## Focused test strategy

Actor authority, exact checksums, stale revision, idempotency, conflicting decisions, and redacted API.

## Risks

Reviewer acceptance treated as approval or broad approval reused after revision.
