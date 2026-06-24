# Feature 02 — API Hardening

## Purpose

Remove frontend and chatbot control over paths, commands, argv, env, sandboxes, patch targets, model providers, and provider credentials.

## Problem solved

Current stage contracts still contain `sandbox_path` and public continuation responses can include `sandbox_path` and `argv`.

## PRD alignment

Implements ID-only DEMO3 APIs, strict extra-field rejection, and public response redaction.

## Current code reality

FastAPI commonly uses `ConfigDict(extra="forbid")`, but a stage progression request still declares optional `sandbox_path`; frontend contracts also contain path/argv fields.

## Expected architecture

Clients send canonical IDs, decisions, expected checksums, user intent, feedback, and idempotency keys. Backend resolves all execution and model-provider details. The frontend has no Azure AI Foundry client and never receives provider credentials.

## Likely reuse points

Strict schema helpers, backend stage output resolver, existing redaction tests, gate action checksums, and backend command factories.

## Likely future modified files

`adapters/fastapi/app.py`, `control_tower/schemas/`, `web/control-tower/lib/contracts.ts`, `controlTowerApi.ts`, `MigrationCockpit.tsx`.

## Likely future new files

`tests/control_tower/test_v2_recovery_api_security.py`, `web/control-tower/tests/recoveryApiSecurity.test.ts`.

## Dependencies

Feature 01 contract inventory.

## Blocks

Features 05, 13, 14, and 17.

## Out of scope

Internal backend path objects and backend-owned argv needed by execution adapters.

## Acceptance criteria

- DEMO3 requests reject all forbidden execution fields, including unknown extras.
- Public responses omit raw paths, argv, env, commands, secrets, provider credentials/configuration, and unredacted logs.
- No product contract or client flow requires GitHub Copilot, Copilot organization policy, Copilot Chat, Copilot CLI, or Copilot cloud agents.
- Compatibility behavior is explicitly tested.

## Focused test strategy

Request validation, nested extras, response serialization, and frontend payload construction.

## Risks

Unsafe legacy fields or client-facing `copilot_*` naming surviving in shared DTOs, UI, or compatibility endpoints.
