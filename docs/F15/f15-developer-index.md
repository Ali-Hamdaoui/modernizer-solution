# F15 Developer Index

**Job:** F15-JOB-121
**Area:** Docs
**Status:** Implemented

## Job map

| Job | Title | Files | Status |
|-----|-------|-------|--------|
| 001 | Define F15 epic boundaries | `docs/F15/index.md` | ✅ |
| 002 | F15 feature flag and policy model | `v2_model_schemas.py`, `run_configuration.py` | ✅ |
| 003 | PhaseGate domain model | `phase_gate.py` | ✅ |
| 004 | PhaseGate decision model | `phase_gate.py` (GateDecision) | ✅ |
| 005 | Artifact revision model | `gate_artifact_ref.py` | ✅ |
| 006 | Architecture decision note | `docs/F15/adr-*.md` | ✅ |
| 007 | Gate checksum contract | `gate_checksum.py` | ✅ |
| 008 | F15 event taxonomy | `f15_events.py` | ✅ |
| 009 | F15 implementation guardrails | `docs/F15/guardrails.md` | ✅ |
| 010 | F15 compatibility matrix | `docs/F15/compatibility.md` | ✅ |
| 011-013 | SQLite migrations | `0039_v2_phase_gates.sql`, `0040_v2_gate_decisions.sql`, `0041_v2_artifact_revisions.sql` | ✅ |
| 014-016 | Repositories | `v2_phase_gate_repository.py`, `v2_gate_decision_repository.py`, `v2_artifact_revision_repository.py` | ✅ |
| 017 | UnitOfWork wiring | `unit_of_work.py` | ✅ |
| 018 | Immutable triggers | `0042_v2_gate_decisions_immutable.sql` | ✅ |
| 019 | Gate projection DTOs | `phase_gate.py` (GateDecisionRequest/Result) | ✅ |
| 020 | Gate audit trail | `v2_gate_audit.py` | ✅ |
| 021-023 | V2PhaseGateService | `v2_phase_gate_service.py` (create/resolve/supersede) | ✅ |
| 024-035 | V2GateActionService | `v2_gate_action_service.py` (continue/reanalyze/approve/reject/revise) | ✅ |
| 036-050 | Orchestration and stage progression | `v2_orchestrator_runner.py`, `v2_stage_progression.py` | ✅ |
| 051-060 | Gate artifact resolver and evidence packs | `v2_gate_artifact_resolver.py`, `v2_evidence_pack_builder.py` | ✅ |
| 061-075 | Assistant flexibility and gate-aware actions | `v2_gate_assistant.py` | ✅ |
| 076-085 | Analysis review gates | `v2_analysis_diff_summary.py`, `v2_analysis_scope_mapping.py` | ✅ |
| 086-100 | Planning and approval gates | `v2_plan_diff_summary.py`, `v2_plan_revision_adapter.py` | ✅ |
| **101** | **Create repair_review gate on build failure** | `v2_repair_gate_service.py` | ✅ |
| **102** | **Create repair_review gate on transform failure** | `v2_repair_gate_service.py` | ✅ |
| **103** | **Bind reviewer critique to repair gate** | `v2_repair_flow.py`, `v2_repair_gate_service.py` | ✅ |
| **104** | **Implement request_repair_revision action** | `v2_gate_action_service.py`, `v2_repair_gate_service.py` | ✅ |
| **105** | **Implement approve_repair action** | `v2_gate_action_service.py` | ✅ |
| **106** | **Implement reject_repair action** | `v2_repair_gate_service.py`, `phase_gate.py` | ✅ |
| **107** | **Add repair validation result gate transition** | `v2_repair_gate_service.py` | ✅ |
| **108** | **Add repair attempt limits** | `v2_repair_gate_service.py` | ✅ |
| **109** | **Add repair patch preview redaction** | `redaction.py` | ✅ |
| **110** | **Add repair UI card** | `docs/repair-ui-card.md`, `contracts.ts` | ✅ |
| **111** | **Add repair assistant Q&A** | `v2_gate_assistant.py` (existing `build_failure_explanation`) | ✅ |
| **112** | **Add repair runbook** | `docs/repair-gate-runbook.md` | ✅ |
| **113** | **Add gate API endpoints** | `docs/gate-api-endpoints.md`, `contracts.ts` | ✅ |
| **114** | **Keep old stage progression endpoint compatible** | Backward compatible — no changes needed | ✅ |
| **115** | **Add frontend gate context model** | `contracts.ts` | ✅ |
| **116** | **Add MigrationCockpit open gate panel** | `docs/repair-ui-card.md` | ✅ |
| **117** | **Add stage timeline gate markers** | `docs/repair-ui-card.md` | ✅ |
| **118** | **Add end-to-end first-slice test plan** | `docs/e2e-test-plan.md` | ✅ |
| **119** | **Add security regression suite** | `docs/security-regression-suite.md` | ✅ |
| **120** | **Add concurrency/idempotency suite** | `docs/concurrency-idempotency-suite.md` | ✅ |
| **121** | **Add F15 developer index** | `docs/f15-developer-index.md` | ✅ |
| **122** | **Add final merge-gate checklist** | `docs/merge-gate-checklist.md` | ✅ |

## File reuse map

### Backend
- `v2_phase_gate_service.py` — Gate lifecycle (create, resolve, supersede)
- `v2_gate_action_service.py` — All gate actions (continue, reanalyze, revise, approve, reject, approve_repair, request_repair_revision)
- `v2_repair_flow.py` — Repair proposals, patches, rollback, ledger
- `v2_repair_gate_service.py` — Repair gate creation, validation transitions, attempt limits
- `v2_failure_diagnosis.py` — Automatic failure diagnosis
- `v2_gate_artifact_resolver.py` — Artifact resolution for evidence packs
- `v2_evidence_pack_builder.py` — Evidence pack building (including failure packs)
- `v2_gate_assistant.py` — Assistant Q&A for all gate phases
- `v2_reviewer_service.py` — Reviewer critique management
- `v2_orchestrator_runner.py` — Pipeline runner with diagnosis callback
- `phase_gate.py` — PhaseGate domain model, enums, valid decisions
- `redaction.py` — Redaction (including patch preview redaction)

### Frontend
- `contracts.ts` — TypeScript types for gates, actions, evidence

### Tests
- `test_v2_repair_review_gate.py` — approve_repair action tests
- `test_v2_repair_gate_service.py` — Repair gate creation, actions, transitions, limits
- `test_v2_repair_flow.py` — Repair proposal/patch lifecycle
- `test_v2_failure_diagnosis.py` — Failure diagnosis tests
- `test_v2_gate_action_service.py` — Gate action execution tests
- `test_v2_phase_gates.py` — Phase gate model tests
- `test_v2_gate_assistant.py` — Assistant Q&A tests
