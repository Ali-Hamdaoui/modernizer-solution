# Automatic Failure-to-LLM Diagnosis

## Goal

Automatically create governed LLM diagnosis and repair proposal objects when backend-owned migration execution emits `build_failed`, `test_failed`, or `transform_failed`.

This is the P0 demo feature.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
  - Emits `build_failed`, `test_failed`, `transform_failed`, `stage_failed`, repair events, artifact events, and proof events.
  - `_emit_diagnostic_failure_events()` projects build/test/transform failure payloads.
- `migration_factory/repair_loop/evidence_collector.py`
  - `collect_failure_evidence()` reads artifact refs, log tails, build error contract, H2 report, OpenRewrite diff safety report, POM excerpt, prior repair ledger attempts, and writes `copilot_repair_request.json`.
- `migration_factory/agents/failure_classifier/agent.py`
  - `classify_failure()` maps evidence to typed failure classes.
  - `write_failure_classification()` persists the classification artifact.
- `migration_factory/copilot_repair/request_builder.py`
  - `build_repair_request()` and `COPILOT_RESPONSE_TEMPLATE`.
- `migration_factory/copilot_repair/response_validator.py`
  - `validate_copilot_repair_response()` validates repair response shape and patch safety claims.
- `migration_factory/control_tower/adapters/fastapi/app.py`
  - `_v2_failure_summary()` builds cockpit failure projections.
  - `/v1/v2/migration-jobs/{job_id}/failure-summary` exposes grouped failure state.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Displays Failure & Repair cards from `getV2FailureSummary()`.

What already exists:

- Failure event emission.
- Redacted failure evidence collection.
- Deterministic failure classification.
- Repair request/response schema validation.
- Cockpit failure summary projection.

What must not be duplicated:

- New failure collector.
- New classifier.
- New repair request schema.
- New event stream/projection layer.

## Proposed Implementation

1. Add a backend subscriber/service invoked when `V2OrchestratorRunner` persists `build_failed`, `test_failed`, or `transform_failed`.
2. Resolve the failed command from event payload `command_id`; if missing, use current stage/job command lookup.
3. Call existing `collect_failure_evidence()` with resolved `run_dir`, `sandbox_path`, artifact refs, build/test statuses, and H2 report.
4. Build extended `ContextPack` from the collected request and classification artifact.
5. Route the event through the prompt router:
   - `build_failed` -> `RepairProposal`
   - `test_failed` -> `RepairProposal`
   - `transform_failed` -> `RepairProposal`
6. Validate model output with `validate_model_output("RepairProposal", payload)`.
7. Persist diagnosis/proposal using the existing V2 repair proposal path and a new diagnosis event/record.
8. Emit `ai_diagnosis_created` with pack checksum, proposal id, failure type, reviewer status, and evidence refs.
9. Update cockpit to consume real backend records.

## Data / Schema Changes

Needed additive records/fields:

- `ai_diagnosis_created` V2 event.
- Durable diagnosis/proposal correlation fields:
  - `diagnosis_id`
  - `context_pack_id`
  - `context_pack_checksum`
  - `command_id`
  - `event_type`
  - `failure_type`
  - `repair_proposal_id`
  - `model_invocation_id`
  - `redaction_status`

UNCERTAIN: no durable AI diagnosis table was found. Assumption: start with a V2 event plus repair proposal correlation fields; add an append-only table only if querying event payloads is not enough.

Technical basis: diagnosis/proposal outputs should use strict structured outputs rather than JSON mode because Azure documents JSON mode as valid-JSON-only without schema guarantees, while structured outputs bind responses to a schema: [Azure OpenAI JSON mode](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/json-mode), [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

## Backend Flow

```text
build_failed/test_failed/transform_failed event
-> resolve job/stage/command/sandbox/artifacts
-> collect_failure_evidence()
-> classify_failure()
-> build extended ContextPack
-> prompt router selects RepairProposal schema
-> Azure/OpenAI structured output call
-> validate schema
-> persist diagnosis/proposal
-> emit ai_diagnosis_created
```

## UI / Cockpit Impact

Extend existing Failure & Repair panel:

- AI Diagnosis card.
- Evidence Used by AI list.
- Proposal checksum.
- Link to artifact preview for `copilot_repair_request`, `failure_classification`, `repair_plan`, and POM summary when present.

Existing UI extension points:

- `MigrationCockpit.tsx` Failure & Repair section.
- `V2FailureSummaryItem` and `V2FailureSummaryResponse` in `contracts.ts`.
- `getV2FailureSummary()` and `getV2ArtifactPreview()` in `controlTowerApi.ts`.

## Human Supervision Point

The human sees the diagnosis and proposed repair object before any apply path exists. They can approve, reject, or ask the assistant to revise the proposal.

## Safety / Governance

- Sandbox only: failure diagnosis resolves a sandbox but does not mutate it.
- No legacy mutation: evidence collector reads sandbox/run artifacts and redacted POM excerpt.
- Human approval boundary: LLM proposal status remains draft/proposed until human approval.
- Backend-owned action gate: diagnosis can request proposal/review/approval preparation, but cannot bypass resolver, reviewer, approval, apply, validation, or proof gates.
- Checksum/proof gates: proposal must later pass reviewer, patch gate, approval checksum, and validation rerun.

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_orchestrator_runner.py` for failure event trigger.
- Extend `tests/control_tower/test_v2_repair_flow.py` for automatic proposal creation from failed command.
- Extend `tests/control_tower/test_v2_cockpit_events.py` for `ai_diagnosis_created` projection.
- Add `test_build_failed_creates_ai_diagnosis_event`.
- Add `test_failure_diagnosis_uses_existing_evidence_collector`.
- Add `test_diagnosis_does_not_apply_patch`.

## Risks

- Triggering diagnosis repeatedly for the same failure event.
- Calling the LLM without a bounded/redacted pack.
- Treating diagnosis as proof.
- Creating frontend-only diagnosis cards without persisted backend records.

## Open Questions

- How should idempotency be keyed: event id, command id plus event type, or context pack checksum?
- Should failed model calls create a deterministic fallback diagnosis or only an unavailable state?
- Should `ai_diagnosis_created` be emitted before or after repair proposal persistence?
