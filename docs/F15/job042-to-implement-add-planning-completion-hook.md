# F15-JOB-042 — Add planning completion hook

**Area:** Runner  
**Status:** To implement  
**Epic:** F15 — Chatbot-Governed Stage Workflow  
**Generated:** 2026-06-17

## Goal

Detect planning completion and create planning_review gate.

## Existing repo pieces to inspect/reuse

- `migration_factory/control_tower/application/v2_stage_progression.py; migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/orchestrator/graph.py; migration_factory/orchestrator/runner.py; migration_factory/orchestrator/phase_services.py`

## Do not duplicate

- Do not create a second orchestrator, repair engine, plan revision engine, prompt router, or stage progression service.
- Do not bypass existing SQLite UnitOfWork/repository patterns.
- Do not accept `sandbox_path`, `argv`, `env`, or raw filesystem targets from the frontend/chatbot.
- Do not let the chatbot directly execute, approve, write files, or mutate legacy source.

## Scope

- [ ] Hook planning output event.
- [ ] Bind plan artifacts.
- [ ] Stop before approval.

## Workflow impact

This job contributes to the F15 target workflow:

```text
Stage N -> analysis -> analysis_review gate -> planning -> planning_review gate
        -> approval_review gate -> transformation -> build/test
        -> repair_review gate if failed -> stage_completion_review gate -> next stage/final review
```

The chatbot remains flexible for natural language, but this job must preserve strict backend validation for every state-changing action.

## Acceptance criteria

- [ ] planning_review gate created.
- [ ] Approval not created before plan accepted.
- [ ] Plan artifacts versioned.

## Suggested tests

- `test_v2_planning_review_gate.py`

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
