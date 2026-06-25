# Feature 02 Tasks — API Hardening

## Task F02-T01 — Define strict ID-only recovery contracts

### Goal

Make unsafe execution input impossible in DEMO3 public requests.

### Scope

- Inventory recovery, progression, repair, approval, and checkpoint actions.
- Define canonical IDs, checksums, decisions, feedback, and idempotency fields.
- Reject `sandbox_path`, path, target, command, argv, env, and unknown nested fields.

### Likely future modified files

- `migration_factory/control_tower/adapters/fastapi/app.py` — replace path-bearing request models.
- `migration_factory/control_tower/schemas/` — strict shared request schemas.
- `web/control-tower/lib/contracts.ts` — remove unsafe request properties.
- `web/control-tower/lib/controlTowerApi.ts` — build ID-only payloads.

### Likely future new files

- `tests/control_tower/test_v2_recovery_api_security.py` — backend rejection matrix.
- `web/control-tower/tests/recoveryApiSecurity.test.ts` — frontend payload checks.

### Implementation notes

- Reuse verified strict Pydantic patterns such as `StrictModel`, `StrictRequest`, and `extra="forbid"`.
- Backend derives every path, command, argv, env, and sandbox.
- LLM and human input never supplies execution details.

### Acceptance criteria

- Every forbidden field causes a 4xx validation failure.
- Nested and alias-shaped attempts also fail.

### Focused tests

- Parameterized forbidden-field tests; no execution.

### Out of scope

- Changing internal executor signatures.

### Dependencies

- F01-T01.

## Task F02-T02 — Redact public recovery responses

### Goal

Expose proof and identifiers without leaking execution internals.

### Scope

- Audit response DTOs, events, and cockpit projections.
- Replace paths/commands with artifact IDs, statuses, checksums, and bounded excerpts.
- Preserve internal diagnostics in backend-owned artifacts.

### Likely future modified files

- `migration_factory/control_tower/adapters/fastapi/app.py` — response mapping.
- `web/control-tower/lib/contracts.ts` — safe response types.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — safe rendering.

### Likely future new files

- `tests/control_tower/test_v2_recovery_api_security.py` — recursive leakage assertions.
- `web/control-tower/tests/recoveryApiSecurity.test.ts` — rendered/transport redaction.

### Implementation notes

- Reuse existing POM and repair redaction patterns.
- Do not remove internal backend evidence required for audit.

### Acceptance criteria

- Serialized responses contain no path, argv, env, raw command, secret, or raw-log fields.

### Focused tests

- Recursive key/value scans and representative endpoint snapshots.

### Out of scope

- General repository-wide API redesign.

### Dependencies

- F02-T01.

## Task F02-T03 — Remove Copilot product dependency from documentation and public contracts

### Goal

Remove GitHub Copilot as a product/runtime dependency while preserving legacy internal names until a separate code refactor is approved.

### Scope

- Audit PRD, sprint docs, public API descriptions, cockpit labels, and client configuration requirements.
- State that Azure AI Foundry is the only DEMO3 AI runtime and that all model calls are backend-owned.
- Classify existing `copilot_*` code, schema, artifact, and status names as internal legacy naming where they remain.
- Record follow-up code/API renaming only where legacy names create client-facing ambiguity.

### Likely future modified files

- `migration_factory/control_tower/adapters/fastapi/app.py` — remove legacy provider terminology from public projections if exposed.
- `web/control-tower/lib/contracts.ts` — keep legacy internal transport fields from becoming product requirements.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — replace client-facing Copilot labels if still rendered.

### Likely future new files

- `tests/control_tower/test_v2_provider_contract_security.py` — public contract terminology and leakage checks.
- `web/control-tower/tests/providerBoundary.test.tsx` — no client Copilot/provider dependency.

### Implementation notes

- Do not rename production modules as part of this documentation task.
- GitHub Copilot may be used by developers locally, but it is not a runtime, assistant engine, fallback, execution dependency, or client prerequisite.
- Existing `azure_openai` names may describe legacy Azure-hosted deployment wiring; DEMO3 product documentation and public behavior must identify the supported boundary as Azure AI Foundry.

### Acceptance criteria

- No client-facing document says GitHub Copilot is required.
- No feature task depends on Copilot cloud agents, Copilot Chat, Copilot CLI, licenses, or organization policy.
- Existing code/module names containing `copilot` are marked legacy/internal when mentioned.
- Any code/API naming follow-up is listed separately and is not implemented by this docs task.

### Focused tests

- Documentation consistency search and public response/UI terminology assertions.

### Out of scope

- Renaming Python/TypeScript modules, schemas, persisted fields, or artifacts.

### Dependencies

- F02-T01 and F02-T02.
