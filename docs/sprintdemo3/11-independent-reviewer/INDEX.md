# Feature 11 — Independent Reviewer

## Purpose

Use a distinct Azure AI Foundry reviewer deployment to review the exact candidate revision.

## Problem solved

Current reviewer records bind proposal/context checksums, but verified repository fields do not persist author and reviewer model identities for equality enforcement.

## PRD alignment

Requires distinct identity, exact revision/context binding, and fail-closed review.

## Current code reality

`v2_reviewer_service.py`, `v2_model_role_router.py`, and `v2_reviewer_repository.py` exist. Repository records include proposal/context checksums and verdict but not verified identity fields.

## Expected architecture

Backend resolves both Foundry deployment/model identities, rejects equality/unverifiable identity, invokes the reviewer through the same backend Azure AI Foundry adapter with exact immutable controlled-context refs, validates strict output, and persists critique.

## Likely reuse points

Reviewer service/repository, role router, model audit, repair gate checks, and artifact checksums.

## Likely future modified files

Reviewer service, role router, reviewer repository, and likely append-only migration (`needs verification`).

## Likely future new files

`v2_review_policy.py`, independence and identity tests.

## Dependencies

Features 08 and 10.

## Blocks

Features 12 and 13.

## Out of scope

Human approval, reviewer execution authority, additional providers, Copilot runtime, and frontend model invocation.

## Acceptance criteria

Review binds exact candidate/evidence/classification/retrieval/mode/checkpoint/attempt; same or unverifiable identity fails closed; reviewer acceptance does not execute.

## Focused test strategy

Identity equality/aliases, stale refs, malformed verdict, mode-specific checklist, and fake reviewer.

## Risks

Different role names resolving to the same deployment or model.
