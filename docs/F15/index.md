# F15 Documentation Pack — Chatbot-Governed Stage Workflow
**Generated:** 2026-06-17  
**Files:** 123 Markdown files: `index.md` plus `job001` through `job122`.  
**Purpose:** Split the F15 proposal into implementation-sized Markdown jobs while avoiding duplicated work and preserving existing V2 behavior.
## Global idea
F15 generalizes the F14 chatbot-to-POM apply pattern to the whole migration lifecycle. For Stage 1, Stage 2, and Stage 3, the Control Tower pauses at analysis, planning, approval, repair, and stage-completion gates. The chatbot can explain evidence and flexibly understand user intent. The backend validates and executes every state-changing action through persisted gates, checksums, and existing services.
## Critical rule
Flexible chatbot does not mean flexible execution. The chatbot may understand many phrases and ask follow-up questions, but backend actions are typed, persisted, checksum-bound, idempotent, sandbox-only, and stage-ordered.
## Existing code to reuse
- **stage:** `migration_factory/control_tower/application/v2_stage_progression.py; migration_factory/control_tower/application/v2_orchestrator_runner.py`
- **assistant:** `migration_factory/control_tower/application/v2_assistant_service.py; migration_factory/control_tower/application/v2_prompt_router.py; migration_factory/control_tower/application/v2_model_schemas.py`
- **repair:** `migration_factory/control_tower/application/v2_repair_flow.py; migration_factory/control_tower/application/v2_failure_diagnosis.py; migration_factory/control_tower/infrastructure/sqlite/migrations/0033_v2_repairs.sql`
- **plan:** `migration_factory/control_tower/application/plan_amendments.py; migration_factory/control_tower/application/plan_proposals.py; migration_factory/control_tower/application/plan_reviews.py`
- **api:** `migration_factory/control_tower/adapters/fastapi/app.py; web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- **persistence:** `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py; migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- **runner:** `migration_factory/orchestrator/graph.py; migration_factory/orchestrator/runner.py; migration_factory/orchestrator/phase_services.py`

## Web/architecture references
- LangGraph interrupts: durable pause/resume with persisted graph state.
- OpenAI function calling / structured outputs: flexible language maps to typed tool/action schemas.
- OWASP LLM Top 10: prompt injection, insecure output handling, excessive agency, sensitive disclosure risks.

## Folder structure

```text
doc/
├── index.md
├── job001-to-implement-define-f15-epic-boundaries.md
├── job002-to-implement-create-f15-feature-flag-and-policy-model.md
├── job003-to-implement-define-phasegate-domain-model.md
├── job004-to-implement-define-phasegate-decision-model.md
├── job005-to-implement-define-artifact-revision-model.md
├── job006-to-implement-create-f15-architecture-decision-note.md
├── job007-to-implement-define-gate-checksum-contract.md
├── job008-to-implement-define-f15-event-taxonomy.md
├── job009-to-implement-create-f15-implementation-guardrails.md
├── job010-to-implement-create-f15-compatibility-matrix.md
├── job011-to-implement-add-sqlite-migration-for-phase-gates.md
├── job012-to-implement-add-sqlite-migration-for-gate-decisions.md
├── job013-to-implement-add-sqlite-migration-for-artifact-revisions.md
├── job014-to-implement-implement-phasegate-repository.md
├── job015-to-implement-implement-gatedecision-repository.md
├── job016-to-implement-implement-artifactrevision-repository.md
├── job017-to-implement-wire-repositories-into-unitofwork.md
├── job018-to-implement-add-immutable-triggers-for-gate-decisions.md
├── job019-to-implement-add-gate-projection-dtos.md
├── job020-to-implement-add-persisted-gate-audit-trail.md
├── job021-to-implement-implement-v2phasegateservice-create-gate.md
├── job022-to-implement-implement-v2phasegateservice-resolve-gate.md
├── job023-to-implement-implement-gate-supersede-flow.md
├── job024-to-implement-implement-v2gateactionservice-shell.md
├── job025-to-implement-implement-continue-from-gate-validation.md
├── ...
├── job113-to-implement-add-gate-api-endpoints.md
├── job114-to-implement-keep-old-stage-progression-endpoint-compatible.md
├── job115-to-implement-add-frontend-gate-context-model.md
├── job116-to-implement-add-migrationcockpit-open-gate-panel.md
├── job117-to-implement-add-stage-timeline-gate-markers.md
├── job118-to-implement-add-end-to-end-first-slice-test-plan.md
├── job119-to-implement-add-security-regression-suite.md
├── job120-to-implement-add-concurrency-idempotency-suite.md
├── job121-to-implement-add-f15-developer-index-docs.md
├── job122-to-implement-add-final-merge-gate-checklist.md
```

## Implementation phases
- **job001-job010:** Foundation and governance
- **job011-job020:** Persistence and repositories
- **job021-job035:** Application services and gate actions
- **job036-job050:** Orchestration and stage progression
- **job051-job060:** Gate artifact resolver and evidence packs
- **job061-job075:** Assistant flexibility and gate-aware actions
- **job076-job085:** Analysis review gates
- **job086-job100:** Planning and approval gates
- **job101-job112:** Repair review gates
- **job113-job120:** API/frontend/tests/docs

## Full job list
- [job001-to-implement-define-f15-epic-boundaries.md](./job001-to-implement-define-f15-epic-boundaries.md) — F15-JOB-001: Define F15 epic boundaries
- [job002-to-implement-create-f15-feature-flag-and-policy-model.md](./job002-to-implement-create-f15-feature-flag-and-policy-model.md) — F15-JOB-002: Create F15 feature flag and policy model
- [job003-to-implement-define-phasegate-domain-model.md](./job003-to-implement-define-phasegate-domain-model.md) — F15-JOB-003: Define PhaseGate domain model
- [job004-to-implement-define-phasegate-decision-model.md](./job004-to-implement-define-phasegate-decision-model.md) — F15-JOB-004: Define PhaseGate decision model
- [job005-to-implement-define-artifact-revision-model.md](./job005-to-implement-define-artifact-revision-model.md) — F15-JOB-005: Define artifact revision model
- [job006-to-implement-create-f15-architecture-decision-note.md](./job006-to-implement-create-f15-architecture-decision-note.md) — F15-JOB-006: Create F15 architecture decision note
- [job007-to-implement-define-gate-checksum-contract.md](./job007-to-implement-define-gate-checksum-contract.md) — F15-JOB-007: Define gate checksum contract
- [job008-to-implement-define-f15-event-taxonomy.md](./job008-to-implement-define-f15-event-taxonomy.md) — F15-JOB-008: Define F15 event taxonomy
- [job009-to-implement-create-f15-implementation-guardrails.md](./job009-to-implement-create-f15-implementation-guardrails.md) — F15-JOB-009: Create F15 implementation guardrails
- [job010-to-implement-create-f15-compatibility-matrix.md](./job010-to-implement-create-f15-compatibility-matrix.md) — F15-JOB-010: Create F15 compatibility matrix
- [job011-to-implement-add-sqlite-migration-for-phase-gates.md](./job011-to-implement-add-sqlite-migration-for-phase-gates.md) — F15-JOB-011: Add SQLite migration for phase gates
- [job012-to-implement-add-sqlite-migration-for-gate-decisions.md](./job012-to-implement-add-sqlite-migration-for-gate-decisions.md) — F15-JOB-012: Add SQLite migration for gate decisions
- [job013-to-implement-add-sqlite-migration-for-artifact-revisions.md](./job013-to-implement-add-sqlite-migration-for-artifact-revisions.md) — F15-JOB-013: Add SQLite migration for artifact revisions
- [job014-to-implement-implement-phasegate-repository.md](./job014-to-implement-implement-phasegate-repository.md) — F15-JOB-014: Implement PhaseGate repository
- [job015-to-implement-implement-gatedecision-repository.md](./job015-to-implement-implement-gatedecision-repository.md) — F15-JOB-015: Implement GateDecision repository
- [job016-to-implement-implement-artifactrevision-repository.md](./job016-to-implement-implement-artifactrevision-repository.md) — F15-JOB-016: Implement ArtifactRevision repository
- [job017-to-implement-wire-repositories-into-unitofwork.md](./job017-to-implement-wire-repositories-into-unitofwork.md) — F15-JOB-017: Wire repositories into UnitOfWork
- [job018-to-implement-add-immutable-triggers-for-gate-decisions.md](./job018-to-implement-add-immutable-triggers-for-gate-decisions.md) — F15-JOB-018: Add immutable triggers for gate decisions
- [job019-to-implement-add-gate-projection-dtos.md](./job019-to-implement-add-gate-projection-dtos.md) — F15-JOB-019: Add gate projection DTOs
- [job020-to-implement-add-persisted-gate-audit-trail.md](./job020-to-implement-add-persisted-gate-audit-trail.md) — F15-JOB-020: Add persisted gate audit trail
- [job021-to-implement-implement-v2phasegateservice-create-gate.md](./job021-to-implement-implement-v2phasegateservice-create-gate.md) — F15-JOB-021: Implement V2PhaseGateService create gate
- [job022-to-implement-implement-v2phasegateservice-resolve-gate.md](./job022-to-implement-implement-v2phasegateservice-resolve-gate.md) — F15-JOB-022: Implement V2PhaseGateService resolve gate
- [job023-to-implement-implement-gate-supersede-flow.md](./job023-to-implement-implement-gate-supersede-flow.md) — F15-JOB-023: Implement gate supersede flow
- [job024-to-implement-implement-v2gateactionservice-shell.md](./job024-to-implement-implement-v2gateactionservice-shell.md) — F15-JOB-024: Implement V2GateActionService shell
- [job025-to-implement-implement-continue-from-gate-validation.md](./job025-to-implement-implement-continue-from-gate-validation.md) — F15-JOB-025: Implement continue_from_gate validation
- [job026-to-implement-implement-request-reanalysis-validation.md](./job026-to-implement-implement-request-reanalysis-validation.md) — F15-JOB-026: Implement request_reanalysis validation
- [job027-to-implement-implement-request-plan-revision-validation.md](./job027-to-implement-implement-request-plan-revision-validation.md) — F15-JOB-027: Implement request_plan_revision validation
- [job028-to-implement-implement-approve-transformation-gate-action.md](./job028-to-implement-implement-approve-transformation-gate-action.md) — F15-JOB-028: Implement approve_transformation gate action
- [job029-to-implement-implement-approve-repair-gate-action.md](./job029-to-implement-implement-approve-repair-gate-action.md) — F15-JOB-029: Implement approve_repair gate action
- [job030-to-implement-implement-reject-gate-action.md](./job030-to-implement-implement-reject-gate-action.md) — F15-JOB-030: Implement reject_gate action
- [job031-to-implement-implement-gate-available-actions-resolver.md](./job031-to-implement-implement-gate-available-actions-resolver.md) — F15-JOB-031: Implement gate available-actions resolver
- [job032-to-implement-implement-conflicting-command-guard.md](./job032-to-implement-implement-conflicting-command-guard.md) — F15-JOB-032: Implement conflicting command guard
- [job033-to-implement-implement-gate-checksum-stale-protection.md](./job033-to-implement-implement-gate-checksum-stale-protection.md) — F15-JOB-033: Implement gate checksum stale protection
- [job034-to-implement-implement-gate-actor-model.md](./job034-to-implement-implement-gate-actor-model.md) — F15-JOB-034: Implement gate actor model
- [job035-to-implement-implement-gate-error-taxonomy.md](./job035-to-implement-implement-gate-error-taxonomy.md) — F15-JOB-035: Implement gate error taxonomy
- [job036-to-implement-refactor-auto-queue-behind-policy.md](./job036-to-implement-refactor-auto-queue-behind-policy.md) — F15-JOB-036: Refactor auto-queue behind policy
- [job037-to-implement-resolve-next-stage-from-persisted-output.md](./job037-to-implement-resolve-next-stage-from-persisted-output.md) — F15-JOB-037: Resolve next stage from persisted output
- [job038-to-implement-add-stage-completion-gate-creation.md](./job038-to-implement-add-stage-completion-gate-creation.md) — F15-JOB-038: Add stage completion gate creation
- [job039-to-implement-add-warning-sensitive-policy-mode.md](./job039-to-implement-add-warning-sensitive-policy-mode.md) — F15-JOB-039: Add warning-sensitive policy mode
- [job040-to-implement-add-phase-split-command-design-support.md](./job040-to-implement-add-phase-split-command-design-support.md) — F15-JOB-040: Add phase-split command design support
- [job041-to-implement-add-analysis-completion-hook.md](./job041-to-implement-add-analysis-completion-hook.md) — F15-JOB-041: Add analysis completion hook
- [job042-to-implement-add-planning-completion-hook.md](./job042-to-implement-add-planning-completion-hook.md) — F15-JOB-042: Add planning completion hook
- [job043-to-implement-add-approval-gate-transition-hook.md](./job043-to-implement-add-approval-gate-transition-hook.md) — F15-JOB-043: Add approval gate transition hook
- [job044-to-implement-add-repair-gate-creation-hook.md](./job044-to-implement-add-repair-gate-creation-hook.md) — F15-JOB-044: Add repair gate creation hook
- [job045-to-implement-add-stage-skip-blocker.md](./job045-to-implement-add-stage-skip-blocker.md) — F15-JOB-045: Add stage skip blocker
- [job046-to-implement-add-gate-driven-command-manifests.md](./job046-to-implement-add-gate-driven-command-manifests.md) — F15-JOB-046: Add gate-driven command manifests
- [job047-to-implement-add-command-idempotency-for-gate-actions.md](./job047-to-implement-add-command-idempotency-for-gate-actions.md) — F15-JOB-047: Add command idempotency for gate actions
- [job048-to-implement-add-gate-aware-event-sink.md](./job048-to-implement-add-gate-aware-event-sink.md) — F15-JOB-048: Add gate-aware event sink
- [job049-to-implement-add-legacy-auto-behavior-regression-tests.md](./job049-to-implement-add-legacy-auto-behavior-regression-tests.md) — F15-JOB-049: Add legacy auto behavior regression tests
- [job050-to-implement-add-manual-mode-end-to-end-fake-runner.md](./job050-to-implement-add-manual-mode-end-to-end-fake-runner.md) — F15-JOB-050: Add manual mode end-to-end fake runner
- [job051-to-implement-implement-gate-artifact-ref-schema.md](./job051-to-implement-implement-gate-artifact-ref-schema.md) — F15-JOB-051: Implement gate artifact ref schema
- [job052-to-implement-implement-v2gateartifactresolver.md](./job052-to-implement-implement-v2gateartifactresolver.md) — F15-JOB-052: Implement V2GateArtifactResolver
- [job053-to-implement-add-analysis-evidence-pack-builder.md](./job053-to-implement-add-analysis-evidence-pack-builder.md) — F15-JOB-053: Add analysis evidence pack builder
- [job054-to-implement-add-planning-evidence-pack-builder.md](./job054-to-implement-add-planning-evidence-pack-builder.md) — F15-JOB-054: Add planning evidence pack builder
- [job055-to-implement-add-approval-evidence-pack-builder.md](./job055-to-implement-add-approval-evidence-pack-builder.md) — F15-JOB-055: Add approval evidence pack builder
- [job056-to-implement-add-failure-evidence-pack-builder.md](./job056-to-implement-add-failure-evidence-pack-builder.md) — F15-JOB-056: Add failure evidence pack builder
- [job057-to-implement-add-artifact-resolver-failure-messages.md](./job057-to-implement-add-artifact-resolver-failure-messages.md) — F15-JOB-057: Add artifact resolver failure messages
- [job058-to-implement-add-redaction-filters-for-gate-packs.md](./job058-to-implement-add-redaction-filters-for-gate-packs.md) — F15-JOB-058: Add redaction filters for gate packs
- [job059-to-implement-add-bounded-context-budget-for-gate-packs.md](./job059-to-implement-add-bounded-context-budget-for-gate-packs.md) — F15-JOB-059: Add bounded context budget for gate packs
- [job060-to-implement-add-artifact-truth-regression-from-f14.md](./job060-to-implement-add-artifact-truth-regression-from-f14.md) — F15-JOB-060: Add artifact truth regression from F14
- [job061-to-implement-extend-actionrequest-with-gate-actions.md](./job061-to-implement-extend-actionrequest-with-gate-actions.md) — F15-JOB-061: Extend ActionRequest with gate actions
- [job062-to-implement-add-gate-aware-assistant-context-loader.md](./job062-to-implement-add-gate-aware-assistant-context-loader.md) — F15-JOB-062: Add gate-aware assistant context loader
- [job063-to-implement-add-flexible-gate-intent-classifier.md](./job063-to-implement-add-flexible-gate-intent-classifier.md) — F15-JOB-063: Add flexible gate intent classifier
- [job064-to-implement-add-analysis-explanation-answer-builder.md](./job064-to-implement-add-analysis-explanation-answer-builder.md) — F15-JOB-064: Add analysis explanation answer builder
- [job065-to-implement-add-planning-explanation-answer-builder.md](./job065-to-implement-add-planning-explanation-answer-builder.md) — F15-JOB-065: Add planning explanation answer builder
- [job066-to-implement-add-approval-summary-answer-builder.md](./job066-to-implement-add-approval-summary-answer-builder.md) — F15-JOB-066: Add approval summary answer builder
- [job067-to-implement-add-failure-explanation-answer-builder.md](./job067-to-implement-add-failure-explanation-answer-builder.md) — F15-JOB-067: Add failure explanation answer builder
- [job068-to-implement-add-assistant-action-preview-for-gates.md](./job068-to-implement-add-assistant-action-preview-for-gates.md) — F15-JOB-068: Add assistant action preview for gates
- [job069-to-implement-add-assistant-execute-via-gate-action-path.md](./job069-to-implement-add-assistant-execute-via-gate-action-path.md) — F15-JOB-069: Add assistant execute-via-gate action path
- [job070-to-implement-add-ambiguity-handling-rules.md](./job070-to-implement-add-ambiguity-handling-rules.md) — F15-JOB-070: Add ambiguity handling rules
- [job071-to-implement-add-model-fallback-behavior.md](./job071-to-implement-add-model-fallback-behavior.md) — F15-JOB-071: Add model fallback behavior
- [job072-to-implement-add-prompt-injection-resistant-evidence-framing.md](./job072-to-implement-add-prompt-injection-resistant-evidence-framing.md) — F15-JOB-072: Add prompt-injection resistant evidence framing
- [job073-to-implement-add-gate-aware-conversation-memory-links.md](./job073-to-implement-add-gate-aware-conversation-memory-links.md) — F15-JOB-073: Add gate-aware conversation memory links
- [job074-to-implement-add-multi-stage-assistant-context-switching.md](./job074-to-implement-add-multi-stage-assistant-context-switching.md) — F15-JOB-074: Add multi-stage assistant context switching
- [job075-to-implement-add-assistant-ux-copy-and-examples.md](./job075-to-implement-add-assistant-ux-copy-and-examples.md) — F15-JOB-075: Add assistant UX copy and examples
- [job076-to-implement-create-analysis-review-gate-after-stage-1-analysis.md](./job076-to-implement-create-analysis-review-gate-after-stage-1-analysis.md) — F15-JOB-076: Create analysis_review gate after Stage 1 analysis
- [job077-to-implement-create-analysis-review-gate-after-stage-2-analysis.md](./job077-to-implement-create-analysis-review-gate-after-stage-2-analysis.md) — F15-JOB-077: Create analysis_review gate after Stage 2 analysis
- [job078-to-implement-create-analysis-review-gate-after-stage-3-analysis.md](./job078-to-implement-create-analysis-review-gate-after-stage-3-analysis.md) — F15-JOB-078: Create analysis_review gate after Stage 3 analysis
- [job079-to-implement-implement-accept-analysis-action.md](./job079-to-implement-implement-accept-analysis-action.md) — F15-JOB-079: Implement accept_analysis action
- [job080-to-implement-implement-request-reanalysis-action.md](./job080-to-implement-implement-request-reanalysis-action.md) — F15-JOB-080: Implement request_reanalysis action
- [job081-to-implement-add-analysis-diff-summary.md](./job081-to-implement-add-analysis-diff-summary.md) — F15-JOB-081: Add analysis diff summary
- [job082-to-implement-add-focused-analyzer-request-mapping.md](./job082-to-implement-add-focused-analyzer-request-mapping.md) — F15-JOB-082: Add focused analyzer request mapping
- [job083-to-implement-block-planning-on-unaccepted-analysis.md](./job083-to-implement-block-planning-on-unaccepted-analysis.md) — F15-JOB-083: Block planning on unaccepted analysis
- [job084-to-implement-add-analysis-review-ui-card.md](./job084-to-implement-add-analysis-review-ui-card.md) — F15-JOB-084: Add analysis review UI card
- [job085-to-implement-add-analysis-gate-runbook.md](./job085-to-implement-add-analysis-gate-runbook.md) — F15-JOB-085: Add analysis gate runbook
- [job086-to-implement-create-planning-review-gate-after-stage-1-planning.md](./job086-to-implement-create-planning-review-gate-after-stage-1-planning.md) — F15-JOB-086: Create planning_review gate after Stage 1 planning
- [job087-to-implement-create-planning-review-gate-after-stage-2-planning.md](./job087-to-implement-create-planning-review-gate-after-stage-2-planning.md) — F15-JOB-087: Create planning_review gate after Stage 2 planning
- [job088-to-implement-create-planning-review-gate-after-stage-3-planning.md](./job088-to-implement-create-planning-review-gate-after-stage-3-planning.md) — F15-JOB-088: Create planning_review gate after Stage 3 planning
- [job089-to-implement-implement-accept-plan-action.md](./job089-to-implement-implement-accept-plan-action.md) — F15-JOB-089: Implement accept_plan action
- [job090-to-implement-implement-request-plan-revision-action.md](./job090-to-implement-implement-request-plan-revision-action.md) — F15-JOB-090: Implement request_plan_revision action
- [job091-to-implement-add-plan-diff-summary.md](./job091-to-implement-add-plan-diff-summary.md) — F15-JOB-091: Add plan diff summary
- [job092-to-implement-block-approval-on-unaccepted-plan.md](./job092-to-implement-block-approval-on-unaccepted-plan.md) — F15-JOB-092: Block approval on unaccepted plan
- [job093-to-implement-create-approval-review-gate.md](./job093-to-implement-create-approval-review-gate.md) — F15-JOB-093: Create approval_review gate
- [job094-to-implement-implement-approve-transformation-action.md](./job094-to-implement-implement-approve-transformation-action.md) — F15-JOB-094: Implement approve_transformation action
- [job095-to-implement-implement-reject-transformation-action.md](./job095-to-implement-implement-reject-transformation-action.md) — F15-JOB-095: Implement reject_transformation action
- [job096-to-implement-add-approval-summary-ui-card.md](./job096-to-implement-add-approval-summary-ui-card.md) — F15-JOB-096: Add approval summary UI card
- [job097-to-implement-add-planning-review-ui-card.md](./job097-to-implement-add-planning-review-ui-card.md) — F15-JOB-097: Add planning review UI card
- [job098-to-implement-add-planning-revision-adapter.md](./job098-to-implement-add-planning-revision-adapter.md) — F15-JOB-098: Add planning revision adapter
- [job099-to-implement-add-plan-reviewer-consistency-gate.md](./job099-to-implement-add-plan-reviewer-consistency-gate.md) — F15-JOB-099: Add plan reviewer consistency gate
- [job100-to-implement-add-approval-runbook.md](./job100-to-implement-add-approval-runbook.md) — F15-JOB-100: Add approval runbook
- [job101-to-implement-create-repair-review-gate-on-build-failure.md](./job101-to-implement-create-repair-review-gate-on-build-failure.md) — F15-JOB-101: Create repair_review gate on build failure
- [job102-to-implement-create-repair-review-gate-on-transform-failure.md](./job102-to-implement-create-repair-review-gate-on-transform-failure.md) — F15-JOB-102: Create repair_review gate on transform failure
- [job103-to-implement-bind-reviewer-critique-to-repair-gate.md](./job103-to-implement-bind-reviewer-critique-to-repair-gate.md) — F15-JOB-103: Bind reviewer critique to repair gate
- [job104-to-implement-implement-request-repair-revision-action.md](./job104-to-implement-implement-request-repair-revision-action.md) — F15-JOB-104: Implement request_repair_revision action
- [job105-to-implement-implement-approve-repair-action.md](./job105-to-implement-implement-approve-repair-action.md) — F15-JOB-105: Implement approve_repair action
- [job106-to-implement-implement-reject-repair-action.md](./job106-to-implement-implement-reject-repair-action.md) — F15-JOB-106: Implement reject_repair action
- [job107-to-implement-add-repair-validation-result-gate-transition.md](./job107-to-implement-add-repair-validation-result-gate-transition.md) — F15-JOB-107: Add repair validation result gate transition
- [job108-to-implement-add-repair-attempt-limits-at-gate-layer.md](./job108-to-implement-add-repair-attempt-limits-at-gate-layer.md) — F15-JOB-108: Add repair attempt limits at gate layer
- [job109-to-implement-add-repair-patch-preview-redaction.md](./job109-to-implement-add-repair-patch-preview-redaction.md) — F15-JOB-109: Add repair patch preview redaction
- [job110-to-implement-add-repair-ui-card.md](./job110-to-implement-add-repair-ui-card.md) — F15-JOB-110: Add repair UI card
- [job111-to-implement-add-repair-assistant-q-a.md](./job111-to-implement-add-repair-assistant-q-a.md) — F15-JOB-111: Add repair assistant Q&A
- [job112-to-implement-add-repair-runbook.md](./job112-to-implement-add-repair-runbook.md) — F15-JOB-112: Add repair runbook
- [job113-to-implement-add-gate-api-endpoints.md](./job113-to-implement-add-gate-api-endpoints.md) — F15-JOB-113: Add gate API endpoints
- [job114-to-implement-keep-old-stage-progression-endpoint-compatible.md](./job114-to-implement-keep-old-stage-progression-endpoint-compatible.md) — F15-JOB-114: Keep old stage progression endpoint compatible
- [job115-to-implement-add-frontend-gate-context-model.md](./job115-to-implement-add-frontend-gate-context-model.md) — F15-JOB-115: Add frontend gate context model
- [job116-to-implement-add-migrationcockpit-open-gate-panel.md](./job116-to-implement-add-migrationcockpit-open-gate-panel.md) — F15-JOB-116: Add MigrationCockpit open gate panel
- [job117-to-implement-add-stage-timeline-gate-markers.md](./job117-to-implement-add-stage-timeline-gate-markers.md) — F15-JOB-117: Add stage timeline gate markers
- [job118-to-implement-add-end-to-end-first-slice-test-plan.md](./job118-to-implement-add-end-to-end-first-slice-test-plan.md) — F15-JOB-118: Add end-to-end first-slice test plan
- [job119-to-implement-add-security-regression-suite.md](./job119-to-implement-add-security-regression-suite.md) — F15-JOB-119: Add security regression suite
- [job120-to-implement-add-concurrency-idempotency-suite.md](./job120-to-implement-add-concurrency-idempotency-suite.md) — F15-JOB-120: Add concurrency/idempotency suite
- [job121-to-implement-add-f15-developer-index-docs.md](./job121-to-implement-add-f15-developer-index-docs.md) — F15-JOB-121: Add F15 developer index docs
- [job122-to-implement-add-final-merge-gate-checklist.md](./job122-to-implement-add-final-merge-gate-checklist.md) — F15-JOB-122: Add final merge-gate checklist

## Recommended first implementation slice
Start with `job001` through `job025`, then `job036`, `job045`, `job051`, `job061`, `job076`, and `job079`. This gives a safe first demo: Stage 1 analysis completes, pipeline stops, chatbot explains gate-bound analysis artifacts, user says continue, backend queues planning.

## Merge-gate principle
Do not call F15 done until old auto behavior still works, F15 manual policy stops at gates, Stage 1/2/3 use sequential accepted outputs, and no new F15 API accepts sandbox paths, commands, env, or raw filesystem targets.
