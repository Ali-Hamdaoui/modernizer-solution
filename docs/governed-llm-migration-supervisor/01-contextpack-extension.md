# ContextPack Extension

## Goal

Extend the existing context-pack primitives so every LLM diagnosis/proposal/review is tied to the migration event, stage, command, artifact refs, POM summary, sandbox binding, and redaction status that produced it.

This is metadata enrichment, not a new context-pack system.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_model_schemas.py`
  - `ContextPack` dataclass: `pack_id`, `pack_type`, `title`, `description`, `evidence_refs`, token budgets, checksum, created time.
  - `ContextPackBuilder.build_context_pack()`, `pack_to_dict()`, `schema_to_dict()`.
  - `TOKEN_BUDGETS` and strict schema registry for `RepairProposal`, `ReviewerCritique`, `ActionRequest`, and `AssistantAnswer`.
- `migration_factory/control_tower/application/context_packs.py`
  - `ContextPackManifestService.persist_manifest()`, `get_manifest()`, `list_manifests_for_job()`, `to_dto()`.
  - Persists checksummed context-pack manifests and audit records.
- `migration_factory/control_tower/application/context_pack_redaction.py`
  - `filter_evidence_refs()`, `redact_evidence_ref()`, `redact_manifest_field()`, `redact_bounds_json()`, `redact_evidence_refs_json()`.
- `migration_factory/final_report/context_builder.py`
  - `build_report_context()` already builds a deterministic final-report context from artifact refs and provenance.
- `migration_factory/repair_loop/evidence_collector.py`
  - `collect_failure_evidence()` already builds redacted failure evidence and a Copilot repair request.

What already exists:

- Bounded pack construction.
- Persisted manifest records.
- Redaction for evidence refs and manifest fields.
- Token budgets and strict schema names.
- Report context provenance.
- Failure evidence collector.

What must not be duplicated:

- Context-pack manifest persistence.
- Redaction pipeline.
- Artifact store.
- Failure evidence collector.
- Final-report context builder.

## Proposed Implementation

1. Add optional metadata fields to the existing V2 `ContextPack` dataclass and `ContextPackBuilder.pack_to_dict()`.
2. Add compatible persisted metadata to `ContextPackManifestService.persist_manifest()`, preferably through `bounds_json` or a new append-only `metadata_json` column if explicit querying is required.
3. Reuse `context_pack_redaction.py` before persistence and before model-call prompt construction.
4. Build metadata from existing backend records:
   - `agent_name` from prompt router/model role.
   - `event_type` from V2 event type such as `build_failed`.
   - `stage_index` from V2 event/command.
   - `profile_id` from setup/job/model profile.
   - `command_id` from failed event payload.
   - `failure_type` from `failure_classifier/agent.py`.
   - `artifact_refs_used` from `artifact_written` events and failure evidence request.
   - `pom_summary_ref` from the new `PomContextSummary` artifact.
   - `sandbox_binding_ref` from backend-resolved sandbox binding.
   - `redaction_status` from the redaction pass.
5. Keep old context packs readable by treating missing metadata as `null`/empty.

## Data / Schema Changes

Add metadata fields:

```text
agent_name
event_type
stage_index
profile_id
command_id
failure_type
artifact_refs_used
pom_summary_ref
sandbox_binding_ref
redaction_status
```

Backward compatibility:

- Existing `ContextPack` callers should continue to work with default empty metadata.
- Existing manifests without metadata remain valid.
- Any structured-output schema change must keep `additionalProperties: false`, following OpenAI and Azure structured-output requirements: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Azure Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).

## Backend Flow

```text
V2 event/command
-> resolve evidence refs
-> redact refs/content using existing redaction
-> build ContextPack with metadata
-> persist manifest/checksum/audit
-> pass pack checksum and refs to prompt router
```

## UI / Cockpit Impact

Extend cockpit displays only after backend records exist:

- Context pack checksum.
- Event/stage/command binding.
- Evidence refs used.
- Redaction status.

Likely consumers:

- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/controlTowerApi.ts`

## Human Supervision Point

The human does not approve a context pack directly in the first slice. The context pack is visible as evidence for diagnosis/proposal/reviewer cards so the operator can see what evidence the LLM used before approving a repair.

## Safety / Governance

- Sandbox only: pack metadata carries `sandbox_binding_ref`; it does not grant write authority.
- No legacy mutation: context packs provide evidence for actionable migration objects, not source edits.
- Human approval boundary: context packs support diagnosis/proposal/review objects, while human approval stays separate.
- Backend-owned action gate: pack metadata can inform an action request, but cannot bypass resolver, reviewer, approval, apply, or validation gates.
- Checksum/proof gates: pack checksum is persisted and cited by downstream proposal/review records.

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_model_schemas.py` for pack metadata defaults and serialization.
- Extend `tests/control_tower/test_v1_11a_context_pack_manifests.py` for metadata persistence if manifest schema changes.
- Extend `tests/control_tower/test_v1_11c_context_pack_redaction.py` for metadata redaction.
- Add `test_context_pack_metadata_is_backward_compatible`.
- Add `test_context_pack_metadata_redacts_paths_and_model_refs`.

## Risks

- Duplicating V2 `ContextPack` and V1 persisted manifests instead of harmonizing them.
- Storing raw absolute paths or model deployment names in metadata.
- Adding required metadata fields that break older tests/records.

## Open Questions

- Should metadata live as explicit DB columns or a single `metadata_json` field?
- Should `redaction_status` be a string, enum, or a structured report with dropped refs?
- UNCERTAIN: the repo has both V2 dataclass packs and V1 context-pack manifests; assumption is to extend both only where needed.
