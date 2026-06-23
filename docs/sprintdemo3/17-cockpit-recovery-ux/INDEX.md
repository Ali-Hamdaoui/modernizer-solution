# Feature 17 — Cockpit Recovery UX

## Purpose

Show lineage, recovery actions, candidate, review, approval, validation, and proof.

## Problem solved

The cockpit shows existing gates/failures/repairs but not checkpoint lineage or retry/resume/fork as first-class actions.

## PRD alignment

Gives humans the information and controls needed to remain decision owners.

## Current code reality

`MigrationCockpit.tsx` already renders stage/failure supervision, reviewer verdict, validation, and rollback details. Contracts/API exist but include some internal path/argv fields elsewhere.

## Expected architecture

UI renders backend projections and submits user intent plus ID/checksum actions. It never derives authority, paths, commands, provider configuration, or success. It has no Azure AI Foundry SDK/client and never calls a model endpoint directly.

## Likely reuse points

Migration cockpit, event replay, existing gate/repair panels, contracts, API client, and frontend tests.

## Likely future modified files

`MigrationCockpit.tsx`, `contracts.ts`, `controlTowerApi.ts`.

## Likely future new files

Checkpoint, attempt timeline, repair review, recovery action components, and `recoveryCockpit.test.tsx`.

## Dependencies

Features 02, 05, 13, and 16.

## Blocks

Feature 18 demo coverage.

## Out of scope

Advanced fork comparison and any frontend execution logic.

## Acceptance criteria

UI shows exact lineage and safe evidence; available actions come from backend; paths, argv, env, commands, secrets, provider credentials/configuration, and raw logs remain hidden. No UI feature requires GitHub Copilot.

## Focused test strategy

Rendering, action payloads, stale refresh, redaction, disabled states, event updates, and accessibility.

## Risks

Frontend state becoming authority or leaking internal data through generic JSON rendering.
