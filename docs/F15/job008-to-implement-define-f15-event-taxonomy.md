# F15-JOB-008 — Define F15 event taxonomy

**Area:** Events  
**Status:** To implement  
**Epic:** F15 — Chatbot-Governed Stage Workflow  
**Generated:** 2026-06-17

## Goal

Add event names for gates and decisions without breaking existing event consumers.

## Existing repo pieces to inspect/reuse

- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py; migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `migration_factory/control_tower/application/v2_assistant_service.py; migration_factory/control_tower/application/v2_prompt_router.py; migration_factory/control_tower/application/v2_model_schemas.py`

## Do not duplicate

- Do not create a second orchestrator, repair engine, plan revision engine, prompt router, or stage progression service.
- Do not bypass existing SQLite UnitOfWork/repository patterns.
- Do not accept `sandbox_path`, `argv`, `env`, or raw filesystem targets from the frontend/chatbot.
- Do not let the chatbot directly execute, approve, write files, or mutate legacy source.

## Scope

- [ ] Define gate_opened, gate_resolved, gate_superseded, gate_action_rejected, gate_action_accepted.
- [ ] Define analysis_review_required and planning_review_required events.
- [ ] Document payload schema.

## Workflow impact

This job contributes to the F15 target workflow:

```text
Stage N -> analysis -> analysis_review gate -> planning -> planning_review gate
        -> approval_review gate -> transformation -> build/test
        -> repair_review gate if failed -> stage_completion_review gate -> next stage/final review
```

The chatbot remains flexible for natural language, but this job must preserve strict backend validation for every state-changing action.

## Acceptance criteria

- [ ] Events contain no raw absolute paths.
- [ ] Existing SSE clients ignore unknown events safely.
- [ ] Events include job_id/stage/gate_id.

## Suggested tests

- `test_v2_gate_events.py`

## Dependencies

Previous foundation jobs

## Out of scope

Do not expand beyond this job. Do not implement later F15 slices early.

## Shared F15 Invariants

- F15 is a new epic, not an F14 extension.
- F14 is closed as "core chatbot-to-POM apply delivered" with follow-up debt for read/propose/raw-POM consistency.
- The chatbot must be flexible in language, explanation, and intent mapping.
- The backend must remain strict in state, paths, checksums, commands, approvals, and writes.
- No new F15 endpoint may accept `sandbox_path`, `argv`, `env`, or raw filesystem targets from the frontend/chatbot.
- All stage-changing work must go through persisted gates and backend-owned services.
- Reuse existing stage progression, prompt router, action schema, repair flow, and plan amendment/revision code.
- Artifact explanation must read gate-bound artifact refs/checksums, not stale previews.
- Legacy source remains read-only; source-changing work remains sandbox-only.
