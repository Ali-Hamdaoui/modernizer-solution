Readiness basis:
- Branch: `DEMO2`
- `git status --short`: dirty before and after analysis; many tracked docs are deleted and `docs/ai_migration_control_tower_v1_issues.md` is untracked.
- Missing required docs from working tree: `docs\PRD_AI_Migration_Control_Tower_v0.3.md`, `docs\M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`, `docs\M2_REPOSITORY_ALIGNMENT.md`, `docs\adr\ADR-M2-*.md`, `docs\Full_AI_Migration_Control_Tower_V1_Implementation_Ready_Plan.md`.
- Graphify used first as required: `graphify --version` returned `graphify 0.8.36`; queries pointed to Control Tower services, schemas, migrations, FastAPI adapter, tests, and web UI.
- Safe checks run:
  - `git diff --check`: passed.
  - `git diff --cached --check`: passed.
  - `py -m pytest -q tests/control_tower -rs --tb=short`: `343 passed, 2 skipped, 2 warnings in 21.03s`.
  - `npm run type-check`: passed.
  - `npm test`: `1 passed`, `7 tests passed`.
  - `npm run build`: not run because Next build writes `.next/`, which violates `ANALYSIS_ONLY = true`.

## V1-01 — Remove local runtime artifacts

### Status
READY

### Current code evidence
- `.gitignore` — lacks `.control-tower-dev/`, `*.sqlite3`, `*.sqlite3-shm`, `*.sqlite3-wal`.
- `.control-tower-dev/control_tower.sqlite3` — currently tracked by `git ls-files`.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Note current `git status --short` already shows unrelated deleted docs and untracked V1 docs; implementer must stage explicit paths only.

### Rules to add
- Do not remove or restore unrelated deleted documentation files.

### Acceptance improvements
- [ ] `git ls-files '.control-tower-dev/control_tower.sqlite3' '*.sqlite3' '*.sqlite3-shm' '*.sqlite3-wal'` returns no tracked runtime DB files.
- [ ] Hygiene test fails on any tracked SQLite file under `.control-tower-dev/`.

### Likely files touched later
- `.gitignore` — add runtime DB ignores.
- `tests/control_tower/test_repository_hygiene.py` — add tracked-artifact guard.
- `.control-tower-dev/control_tower.sqlite3` — remove from git index only if tracked.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_repository_hygiene.py -rs` — proves hygiene guard.
- `git ls-files '.control-tower-dev/control_tower.sqlite3' '*.sqlite3' '*.sqlite3-shm' '*.sqlite3-wal'` — proves no tracked runtime DB artifacts.

### Implementation risk
LOW

### Recommendation
KEEP

### Notes for future implementer
- Use `git rm --cached` for the tracked DB if present; do not delete the user’s local runtime folder from disk unless explicitly requested.

## V1-02 — Lock V1 migration route

### Status
PARTIALLY_DONE

### Current code evidence
- `migration_factory/control_tower/schemas/pipeline_definition.py` — already has stage target metadata, `command_jdk`, previous-stage input, and known continuation policy IDs.
- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` — target is `3.5.6`, but catalog path is still `catalogs/openrewrite/springboot-3.5-java17.yaml`.
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-4-java21-sandbox.yaml` — Boot 4 catalog exists historically.
- `tests/control_tower/_helpers.py` — default test pipeline still targets `3.5.14`.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Existing schema supports `previous_stage`, not the exact V1 term `previous_stage_sandbox`.
- Existing test helpers and M2 defaults still use `pipeline-default` and `3.5.14`.

### Rules to add
- Historical Boot 4 and `3.5.14` assets may remain on disk but must not be selectable through supported V1 APIs.
- Do not break M2 diagnostic tests that use `pipeline-default`.

### Acceptance improvements
- [ ] `GET /v1/pipelines` returns only `springboot-216-to-356-java21-three-stage` for V1-supported route selection.
- [ ] Stage 2 profile references a catalog whose file name and catalog `id` are `springboot-2.7-to-3.5-java17`.
- [ ] V1 pipeline fixtures do not use `3.5.14`.

### Likely files touched later
- `migration_factory/control_tower/schemas/pipeline_definition.py` — add `output_subfolder` or V1 source binding terms.
- `modernizer-solution-ai-hub/profiles/*.yaml` — lock/select V1 route profiles.
- `modernizer-solution-ai-hub/catalogs/openrewrite/*.yaml` — rename/add Stage 2 catalog.
- `tests/control_tower/test_pipeline_definition_schema.py` — add exact three-stage route tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_pipeline_definition_schema.py tests/control_tower/test_pipeline_registration.py -rs` — proves route lock and API exclusion.

### Implementation risk
MEDIUM

### Recommendation
EDIT_BEFORE_WORK

### Notes for future implementer
- Avoid deleting historical Boot 4 files unless the issue is updated to require removal; selection filtering is the safer V1 invariant.

## V1-03 — Persist normalized stage chain

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql` — has `stage_runs`, but no `stage_chain_ledger`.
- `migration_factory/control_tower/application/services.py` — `CreateMigrationJobService.execute` creates `StageRunRecord` rows from pipeline stages.
- `migration_factory/control_tower/domain/entities.py` — no `StageChainLedgerRecord`.
- `migration_factory/control_tower/application/ports.py` — no ledger repository protocol.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define whether `stage_runs` remains mutable operational state and `stage_chain_ledger` becomes immutable route/source/proof binding.
- Specify exact `source_kind` values, especially whether V1 uses `previous_stage_sandbox` instead of current schema’s `previous_stage`.

### Rules to add
- Existing migrations `0001` through `0006` must remain immutable.
- Ledger checksums must be calculated from canonical persisted payloads, not display DTOs.

### Acceptance improvements
- [ ] Migration `0007` is discovered after `0006` and leaves existing M2 tests green.
- [ ] `stage_chain_ledger` has immutable update/delete triggers.
- [ ] Ledger rows link to existing `stage_runs` without replacing them.

### Likely files touched later
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0007_v1_stage_chain.sql` — new tables/triggers.
- `migration_factory/control_tower/application/services.py` — populate ledger at job creation.
- `tests/control_tower/test_v1_stage_chain_ledger.py` — new ledger contract tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_sqlite_migrations.py tests/control_tower/test_v1_stage_chain_ledger.py -rs` — proves migration ordering, immutability, and job-created ledger rows.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Split schema/repository immutability from job-creation integration if possible; the migration creates several future-link tables beyond the first ledger behavior.

## V1-04 — Expose stage chain projections

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/application/queries.py` — has `list_stage_runs`, no ledger-backed stage-chain projection.
- `migration_factory/control_tower/adapters/fastapi/app.py` — has `/v1/jobs`, `/events`, `/commands`, `/artifacts`; no `/v1/jobs/{job_id}/stages`.
- `web/control-tower/lib/contracts.ts` — has diagnostic job/command/artifact/event contracts only.
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx` — renders command/log/artifact/event panels, no stage timeline.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Define exact redacted ref format for run dir and sandbox dir.
- Clarify whether stage detail endpoint returns proof gates now or later.

### Rules to add
- Stage API must read ledger rows, not reconstruct stages from current pipeline YAML at request time.

### Acceptance improvements
- [ ] Unknown job returns existing API error envelope.
- [ ] Unknown stage ID returns deterministic `404`.
- [ ] Absolute paths are rejected in serialized stage DTOs.

### Likely files touched later
- `migration_factory/control_tower/application/dto.py` — add `StageChainLedgerDto`.
- `migration_factory/control_tower/application/queries.py` — ledger read query.
- `migration_factory/control_tower/adapters/fastapi/app.py` — stage endpoints.
- `web/control-tower/lib/contracts.ts` — stage DTO types.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_stage_chain_api.py -rs` — backend API shape/redaction.
- `npm test` — client contract parsing.

### Implementation risk
MEDIUM

### Recommendation
KEEP

### Notes for future implementer
- Keep this read-only; do not introduce execution or worker transitions here.

## V1-05 — Validate runner JDK readiness

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/schemas/runner_profile.py` — current `MavenConfig.executable_path` and `JdkConfig.java_home` are raw paths, not env refs.
- `migration_factory/control_tower/adapters/fastapi/app.py` — only lists runner profiles; no detail or health-check endpoint.
- `tests/control_tower/test_runner_profile_schema.py` — tests raw-path runner profile schema.
- `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx` — only renders runner selector, no readiness badges.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Define env-ref schema shape, e.g. `{kind: "env", name: "JAVA11_HOME"}` versus plain string.
- Define fake command runner interface for tests.

### Rules to add
- Browser/API payloads must not submit or override executable paths, Java homes, Maven paths, or arbitrary env keys.
- Health checks must redact env values and command output paths.

### Acceptance improvements
- [ ] Runner profile schema rejects raw browser-submitted path overrides in health-check request bodies.
- [ ] Missing Java 11/17/21 each produces a separate failed check.
- [ ] Maven readiness is checked through backend-owned configured ref only.

### Likely files touched later
- `migration_factory/control_tower/schemas/runner_profile.py` — env-backed config.
- `migration_factory/control_tower/application/services.py` — readiness service.
- `migration_factory/control_tower/adapters/fastapi/app.py` — runner detail/health endpoints.
- `tests/control_tower/test_v1_runner_readiness.py` — fake command tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_runner_profile_schema.py tests/control_tower/test_v1_runner_readiness.py -rs` — schema and readiness behavior.

### Implementation risk
MEDIUM

### Recommendation
EDIT_BEFORE_WORK

### Notes for future implementer
- This should not mutate `JAVA_HOME`, write toolchains, or depend on the developer’s actual installed JDKs in unit tests.

## V1-06 — Execute worker-owned Stage One

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/application/services.py` — `start_migration_job` queues `foundation_diagnostic`, not `RUN_ORCHESTRATOR_STAGE`.
- `migration_factory/control_tower/infrastructure/worker_launcher.py` — launches inline diagnostic Python source, not `migration_factory.orchestrator.runner`.
- `migration_factory/control_tower/domain/manifests.py` — manifest lacks stage ledger ID, selected JDK ID, profile checksum, catalog checksum, sandbox refs.
- `migration_factory/orchestrator/runner.py` — runner module exists.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define orchestrator runner CLI contract and allowed argv exactly.
- Define how Stage 1 command binds to `stage_chain_ledger` and `stage_runs`.

### Rules to add
- `shell=True` remains forbidden.
- Worker argv and env must be backend-owned and checksum-bound before launch.
- Non-Windows launch must fail closed where Job Object control is required.

### Acceptance improvements
- [ ] Stage 1 command cannot be queued unless runner readiness is `READY`.
- [ ] Manifest checksum covers stage ledger ID, selected JDK ID, profile checksum, catalog checksum, and sandbox refs.
- [ ] Route handler never directly invokes orchestrator execution.

### Likely files touched later
- `migration_factory/control_tower/application/commands.py` — `RunOrchestratorStageCommand`.
- `migration_factory/control_tower/application/services.py` — stage command enqueue.
- `migration_factory/control_tower/infrastructure/worker_launcher.py` — backend-owned orchestrator argv/env.
- `tests/control_tower/test_v1_worker_stage_execution.py` — persistence-before-launch tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_m2_worker_launch.py tests/control_tower/test_v1_worker_stage_execution.py -rs` — preserves M2 launcher and proves Stage 1 command behavior.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- First add command/manifest contracts and tests; then add actual launcher argv/env mapping.

## V1-07 — Resume approvals through Control Tower

### Status
BLOCKED

### Current code evidence
- `migration_factory/orchestrator/approval.py` and `migration_factory/orchestrator/resume.py` — orchestrator approval/resume modules exist.
- `migration_factory/control_tower` — no `approvals` table, `ApprovalRecord`, approval endpoints, or approval UI.
- `migration_factory/control_tower/domain/states.py` — job states include `PAUSED_FOR_PLAN_APPROVAL`.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define the interrupt payload schema that creates approval records.
- Define whether approval is stage-level, plan-level, or both in V1-07.

### Rules to add
- Approval records must be immutable except state transitions through explicit service methods.
- Resume command must require exact candidate checksum and current stage version.

### Acceptance improvements
- [ ] Approval creation is idempotent for the same interrupt/checksum.
- [ ] Approval resume command is queued but not executed in the approval route handler.
- [ ] Rejection cannot be reversed without a new candidate checksum.

### Likely files touched later
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0008_v1_approvals.sql` — approval persistence.
- `migration_factory/control_tower/application/services.py` — approval state machine.
- `migration_factory/control_tower/adapters/fastapi/app.py` — approval endpoints.
- `tests/control_tower/test_v1_approval_resume.py` — approval/resume safety.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_approval_resume.py tests/control_tower/test_m2_event_replay.py -rs` — approval events and replay safety.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Keep approval resume as a queued command; avoid direct orchestrator side effects from FastAPI handlers.

## V1-08 — Continue stages through sandboxes

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/domain/transitions.py` — currently job-level transitions only.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql` — `stage_runs` has status but no proof-gate or sandbox-binding logic.
- `migration_factory/control_tower/infrastructure/worker_launcher.py` — no Java 17/21 stage environment mapping.
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx` — no completed/current/blocked stage timeline.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define proof gate source table from V1-03 and exact gate names.
- Define whether continuation is automatic or developer-triggered.

### Rules to add
- Stage 2 input must be Stage 1 sandbox only; Stage 3 input must be Stage 2 sandbox only.
- Failed stages must not continue automatically.

### Acceptance improvements
- [ ] Continuation service refuses a stage command when prior-stage sandbox ref checksum does not match ledger.
- [ ] Stage continuation emits deterministic `stage.blocked`, `stage.queued`, and `stage.failed` events.
- [ ] No browser request can choose continuation input directory.

### Likely files touched later
- `migration_factory/control_tower/domain/transitions.py` — stage continuation rules.
- `migration_factory/control_tower/application/services.py` — next-stage selection.
- `migration_factory/control_tower/infrastructure/worker_launcher.py` — selected JDK env mapping.
- `tests/control_tower/test_v1_stage_continuation.py` — proof-gated continuation.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_stage_continuation.py -rs` — Stage 2/3 unblock/block rules.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Implement continuation policy as backend domain logic; the UI should only reflect state.

## V1-09 — Register Azure model profiles

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no model profile tables, DTOs, services, or endpoints.
- `migration_factory/control_tower/schemas/runner_profile.py` — only has a simple `ai_profile.profile_id` reference.
- `migration_factory/control_tower/adapters/fastapi/app.py` — no `/v1/model-profiles` or model status in capabilities.
- `web/control-tower` — no model readiness UI.

### Issue quality
- context quality: NEEDS_MORE_CONTEXT
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: WRONG_ORDER

### Missing context to add
- Define whether this truly depends on V1-08; model registry can likely start after V1-04/V1-05.
- Define provider-neutral env-ref schema for deployment IDs and keys.

### Rules to add
- Browser and LLM must never choose deployment IDs.
- Live Azure tests must be opt-in only.

### Acceptance improvements
- [ ] Model deployment names are stored as env refs, not raw values.
- [ ] Health-check request body cannot override provider endpoint, key, API version, or deployment refs.
- [ ] `GET /v1/capabilities` redacts model config and reports disabled fallback.

### Likely files touched later
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0009_v1_model_profiles.sql` — model tables.
- `migration_factory/control_tower/application/services.py` — fake-provider-first health service.
- `migration_factory/control_tower/adapters/fastapi/app.py` — model endpoints/capabilities.
- `tests/control_tower/test_v1_model_registry.py` — fake/live gating tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_model_registry.py -rs` — schema probes, redaction, disabled fallback.

### Implementation risk
MEDIUM

### Recommendation
EDIT_BEFORE_WORK

### Notes for future implementer
- This issue should not make real model calls in normal CI and should not introduce plan/repair behavior.

## V1-10 — Audit model invocations

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no `model_calls` table or model-call audit wrapper.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql` — event types currently cover command/artifact flow, not model call events.
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx` — no model activity list.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Define where redacted request/response artifacts are stored.
- Define model-call purpose enum.

### Rules to add
- Model summaries cannot create or override proof.
- Raw prompts and raw secrets must not enter public events.

### Acceptance improvements
- [ ] `model_calls.context_pack_id` is nullable only for health-check/schema-probe calls.
- [ ] Public model events contain summary metadata only.
- [ ] Failed model calls persist failure classification without raw provider response.

### Likely files touched later
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0010_v1_model_calls.sql` — audit table/events.
- `migration_factory/control_tower/application/services.py` — provider wrapper.
- `tests/control_tower/test_v1_model_call_audit.py` — redaction/replay tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_model_call_audit.py tests/control_tower/test_m2_event_replay.py -rs` — audited calls and event replay.

### Implementation risk
MEDIUM

### Recommendation
KEEP

### Notes for future implementer
- Build audit wrapper around fake provider first; do not add serious LLM workflows here.

## V1-11 — Build bounded context packs

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/application` — no `context_builder.py`, `retrievers.py`, or `redaction.py`.
- `migration_factory/control_tower` — no `context_packs` table.
- `migration_factory/control_tower/application/queries.py` — has bounded command output windows but no bounded evidence packs.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define exact budget accounting method: estimated tokens vs bytes vs chars.
- Define allowed retriever list per purpose.

### Rules to add
- Context Builder must exist before plan, repair, or assistant LLM behavior.
- Full repo dumps and full logs are policy violations.

### Acceptance improvements
- [ ] Each retriever records source evidence refs and byte/window limits.
- [ ] Context pack checksum changes if any evidence manifest changes.
- [ ] Redaction summary is stored and exposed without revealing redacted values.

### Likely files touched later
- `migration_factory/control_tower/application/context_builder.py` — pack builder.
- `migration_factory/control_tower/application/retrievers.py` — bounded retrievers.
- `migration_factory/control_tower/application/redaction.py` — forbidden file and secret redaction.
- `tests/control_tower/test_v1_context_builder.py` — budgets/redaction/immutability.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_context_builder.py -rs` — pack bounds and immutability.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Start with deterministic artifact/log/stage/proof retrievers before any model integration.

## V1-12 — Propose plan amendments

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no `plan_amendments`, `plan_revisions`, or `model_schemas.py`.
- `web/control-tower` — no plan amendment form or preview.
- `migration_factory/control_tower/application/services.py` — no model-driven proposal workflow.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define immutable user instruction schema and allowed instruction size.
- Define exact `PlanProposalV1` schema before implementation.

### Rules to add
- LLM may propose/request only; it must not approve or execute.
- Proposal must reference context pack and model call IDs.

### Acceptance improvements
- [ ] Proposal creation fails if context pack is missing or not `PLAN_AMENDMENT_CONTEXT`.
- [ ] Proposal state transitions are version/checksum guarded.
- [ ] Reject/accept endpoints do not enqueue worker commands.

### Likely files touched later
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0012_v1_plan_amendments.sql` — plan tables.
- `migration_factory/control_tower/application/model_schemas.py` — `PlanProposalV1`.
- `tests/control_tower/test_v1_plan_amendments.py` — immutable instructions and state transitions.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_plan_amendments.py -rs` — proposal workflow without execution.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Persist instruction first, then build context, then fake provider call, then save proposal.

## V1-13 — Gate plans with reviewer

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no reviewer critique persistence or policy gate module.
- `migration_factory/control_tower/domain/states.py` — has pause states but no plan revision states.
- `web/control-tower` — no critique/policy UI.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: OK

### Missing context to add
- Define `ReviewerCritiqueV1` schema and allowed reviewer decisions.
- Define backend policy result schema.

### Rules to add
- Reviewer cannot approve execution.
- Backend policy is the only authority that marks approval-ready.

### Acceptance improvements
- [ ] Disabled or unhealthy reviewer blocks approval readiness.
- [ ] Policy gate rejects proposal if evidence refs are missing from context manifest.
- [ ] Reviewer critique is persisted even when backend policy fails.

### Likely files touched later
- `migration_factory/control_tower/application/policy_gate.py` — backend validation.
- `migration_factory/control_tower/application/model_schemas.py` — reviewer schema.
- `tests/control_tower/test_v1_reviewer_policy_gate.py` — critique and policy failures.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_reviewer_policy_gate.py -rs` — reviewer/policy gating.

### Implementation risk
MEDIUM

### Recommendation
KEEP

### Notes for future implementer
- Make reviewer output advisory; all executable authority stays in Control Tower policy.

## V1-14 — Detect repair opportunities

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/application/services.py` — command finalization exists, but no deterministic repair classifier.
- `migration_factory/control_tower/application` — no `repair_classifier.py` or repair schemas.
- `web/control-tower` — no repair proposal panel.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define failure classification inputs from command result artifacts.
- Define whether repair detection is automatic on failed command finalization or user-triggered.

### Rules to add
- Repair proposal must not apply patches.
- User repair instruction must be immutable and used only in the next proposal context.

### Acceptance improvements
- [ ] Non-repairable failures record deterministic `NOT_REPAIRABLE`/equivalent state.
- [ ] Repair attempt links to failed command result artifact and context pack.
- [ ] Attempt limits are enforced per stage and per failure class.

### Likely files touched later
- `migration_factory/control_tower/application/repair_classifier.py` — deterministic classification.
- `migration_factory/control_tower/application/model_schemas.py` — `RepairProposalV1`, `ValidationPlanV1`.
- `tests/control_tower/test_v1_repair_proposals.py` — classification and limits.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_repair_proposals.py -rs` — repair proposal without mutation.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Implement classification and attempt records before adding GPT repair proposal generation.

## V1-15 — Apply approved repair patches

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower/infrastructure/worker_launcher.py` — no typed patch/Maven/rollback worker commands.
- `migration_factory/control_tower/application` — no `patch_policy.py`.
- `migration_factory/control_tower` — no `patch_artifacts` or snapshot tables.
- `web/control-tower` — no diff/checksum approval controls.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define patch format accepted by backend.
- Define snapshot storage format and rollback guarantees.

### Rules to add
- Legacy source root is never written.
- Arbitrary shell remains disabled.
- Validation runs only typed approved Maven operations under selected stage JDK.

### Acceptance improvements
- [ ] Patch application rejects symlinks/path traversal into legacy source or secrets.
- [ ] Rollback restores exact pre-apply sandbox snapshot checksum.
- [ ] Patch apply and validation commands are separate audited worker commands.

### Likely files touched later
- `migration_factory/control_tower/application/patch_policy.py` — patch validation.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0015_v1_patch_artifacts.sql` — patch/snapshot tables.
- `tests/control_tower/test_v1_patch_apply_rollback.py` — escape/checksum/rollback tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_patch_apply_rollback.py -rs` — patch safety and rollback.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Separate policy validation from filesystem mutation and from Maven validation to keep failures diagnosable.

## V1-16 — Add read-only assistant tools

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no assistant tables, messages, tool calls, or read tools.
- `migration_factory/control_tower/application/queries.py` — has bounded command output windows that can be reused.
- `web/control-tower` — no assistant panel or assistant stream.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: WRONG_ORDER

### Missing context to add
- This should depend on context packs/model audit, not patch application.
- Define read tool names, input schemas, and output caps.

### Rules to add
- Assistant cannot execute, approve, write, run Maven, run shell, or mutate state.
- Tool results must be redacted before model follow-up.

### Acceptance improvements
- [ ] Assistant endpoint rejects any tool outside the read-only allowlist.
- [ ] Assistant stream is separate from migration event stream.
- [ ] Read tools cannot read forbidden files or absolute arbitrary paths.

### Likely files touched later
- `migration_factory/control_tower/application/read_tools.py` — bounded tools.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0016_v1_assistant_tools.sql` — assistant tables.
- `tests/control_tower/test_v1_assistant_tools.py` — no mutation/no execution tests.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_assistant_tools.py -rs` — read-only limits/redaction.
- `npm test` — assistant panel contracts.

### Implementation risk
HIGH

### Recommendation
EDIT_BEFORE_WORK

### Notes for future implementer
- Move this earlier than patch application if the goal is read-only operational help before repair execution exists.

## V1-17 — Request privileged typed actions

### Status
BLOCKED

### Current code evidence
- `migration_factory/control_tower` — no `privileged_actions` table or `action_policy.py`.
- `migration_factory/control_tower/domain/commands.py` — command states exist, but no privileged action states.
- `web/control-tower` — no separate action cards.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define action type schema and checksum canonicalization.
- Define which actions are request-only from assistant versus directly user-created.

### Rules to add
- Shell diagnostic action remains disabled by default.
- No model may execute or approve actions.
- Arbitrary Maven goals and working directories are forbidden.

### Acceptance improvements
- [ ] Action request and action execution are separate service calls and events.
- [ ] Approval requires exact action checksum and current stage version.
- [ ] Disabled shell action cannot be enabled by API payload.

### Likely files touched later
- `migration_factory/control_tower/application/action_policy.py` — allowlist/rejections.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0017_v1_privileged_actions.sql` — action table.
- `tests/control_tower/test_v1_privileged_actions.py` — unsafe rejection/approval checksum.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_privileged_actions.py -rs` — typed action safety.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Start with pending/reject policy only, then add approval, then worker execution for allowed Maven actions.

## V1-18 — Render full V1 cockpit

### Status
NEEDS_SPLIT

### Current code evidence
- `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx` — foundation diagnostic creation only.
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx` — command/log/artifact/event panels only.
- `web/control-tower/lib/contracts.ts` — lacks stages, approvals, model readiness, repairs, actions, assistant, proof contracts.
- `migration_factory/control_tower/adapters/fastapi/app.py` — most required V1 cockpit backend endpoints do not exist yet.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: TOO_BIG
- dependency quality: OK

### Missing context to add
- Define which backend issues must be complete before each cockpit panel.
- Define route split target: keep `app/page.tsx` minimal or build `/jobs/new` and `/jobs/[jobId]`.

### Rules to add
- UI must not invent backend authority or expose raw shell/Maven/model/path editors.
- Migration event stream and assistant stream remain separate.

### Acceptance improvements
- [ ] Cockpit gracefully hides panels whose backend endpoints are unavailable only if the issue explicitly allows progressive rollout.
- [ ] Each panel has contract tests against stable mocked DTOs.
- [ ] UI shows only registered-root refs and backend-owned action summaries.

### Likely files touched later
- `web/control-tower/app/jobs/new/page.tsx` — V1 job creation.
- `web/control-tower/app/jobs/[jobId]/page.tsx` and components — V1 cockpit.
- `web/control-tower/lib/contracts.ts` — consolidated DTOs.
- `web/control-tower/tests/*.test.tsx` — panel/contract tests.

### Test strategy later
- `npm run type-check` — TS contracts.
- `npm test` — component/contract behavior.
- `npm run build` — production build, but only during implementation turns where build artifacts are allowed.

### Implementation risk
HIGH

### Recommendation
SPLIT

### Notes for future implementer
- Split by panels: create job, stage/proof, approvals/actions, repairs, assistant, artifacts/events.

## V1-19 — Generate deterministic proof reports

### Status
NEEDS_REWRITE

### Current code evidence
- `migration_factory/control_tower/domain/states.py` — has `TargetProofLevel`, but no proof gates.
- `migration_factory/control_tower/infrastructure/sqlite/migrations` — no `proof_gates` except proposed in V1-03 and no `final_reports`.
- `migration_factory/control_tower/application/services.py` — command finalization registers terminal artifacts, but no proof computation.
- `web/control-tower` — no proof status or final report link.

### Issue quality
- context quality: GOOD
- acceptance quality: CLEAR
- scope quality: RIGHT_SIZE
- dependency quality: WRONG_ORDER

### Missing context to add
- Backend proof should exist before the full cockpit issue, not after it.
- Define exact required gates per stage and evidence artifact types.

### Rules to add
- Proof gates are created only from deterministic command/artifact evidence.
- Model summaries may appear in reports but cannot create or override proof.

### Acceptance improvements
- [ ] Proof endpoint is implemented before UI cockpit consumes it.
- [ ] Failed or incomplete proof never produces a final report artifact.
- [ ] Final report links to immutable evidence refs and redaction summary.

### Likely files touched later
- `migration_factory/control_tower/application/proof.py` — deterministic proof computation.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0018_v1_final_reports.sql` — final report table/linkage.
- `tests/control_tower/test_v1_proof_reports.py` — proof/report behavior.

### Test strategy later
- `py -m pytest -q tests/control_tower/test_v1_proof_reports.py -rs` — proof from deterministic evidence.
- `npm test` — proof UI contract only after backend endpoint exists.

### Implementation risk
MEDIUM

### Recommendation
EDIT_BEFORE_WORK

### Notes for future implementer
- Move backend proof/report work before full cockpit rendering, or split V1-18 so proof UI waits for V1-19 backend.

# Dependency review

## Correct order
1. `V1-01 Remove local runtime artifacts`
2. `V1-02 Lock V1 migration route`
3. `V1-03 Persist normalized stage chain`
4. `V1-04 Expose stage chain projections`
5. `V1-05 Validate runner JDK readiness`
6. `V1-09 Register Azure model profiles`
7. `V1-10 Audit model invocations`
8. `V1-11 Build bounded context packs`
9. `V1-06 Execute worker-owned Stage One`
10. `V1-07 Resume approvals through Control Tower`
11. `V1-08 Continue stages through sandboxes`
12. `V1-12 Propose plan amendments`
13. `V1-13 Gate plans with reviewer`
14. `V1-14 Detect repair opportunities`
15. `V1-15 Apply approved repair patches`
16. `V1-16 Add read-only assistant tools`
17. `V1-17 Request privileged typed actions`
18. `V1-19 Generate deterministic proof reports`
19. `V1-18 Render full V1 cockpit`

## Issues that can start immediately
- `V1-01` — concrete hygiene issue with direct current evidence.
- `V1-02` — can start after `V1-01`; parts already exist, but issue body needs small edits.
- `V1-09` — technically can be developed in parallel after route/API conventions are stable; it does not need stage continuation.

## Issues blocked by prerequisites
- `V1-03` — blocked by `V1-02`.
- `V1-04` — blocked by `V1-03`.
- `V1-05` — blocked by `V1-04`.
- `V1-06` — blocked by `V1-05`.
- `V1-07` — blocked by `V1-06`.
- `V1-08` — blocked by `V1-07`.
- `V1-10` — blocked by `V1-09`.
- `V1-11` — blocked by `V1-10`.
- `V1-12` — blocked by `V1-11`.
- `V1-13` — blocked by `V1-12`.
- `V1-14` — blocked by `V1-13`.
- `V1-15` — blocked by `V1-14`.
- `V1-16` — should be blocked by `V1-10`/`V1-11`, not patch application.
- `V1-17` — blocked by `V1-16`.
- `V1-18` — blocked by stable backend contracts.
- `V1-19` — should precede proof UI in `V1-18`.

## Issues that need rewrite before implementation
- `V1-02` — add current fixture/catalog context and exact V1 API-selection rule.
- `V1-06` — split manifest/command contract from real worker launch.
- `V1-09` — dependency order should not require stage continuation.
- `V1-16` — dependency should be context/model audit, not patch application.
- `V1-18` — too large; split by cockpit panel.
- `V1-19` — move before full cockpit or split backend proof from UI proof display.

## Suggested issue edits
- `V1-02` — state that historical Boot 4/`3.5.14` files may remain but must be excluded from V1-supported selection.
- `V1-03` — clarify `stage_runs` vs `stage_chain_ledger` ownership.
- `V1-05` — define env-ref schema for Maven/JDKs.
- `V1-06` — specify exact orchestrator runner argv contract.
- `V1-08` — define proof gate persistence and continuation trigger.
- `V1-11` — define retriever caps and token estimation method.
- `V1-16` — move earlier and make it read-only assistant only.
- `V1-19` — make backend proof/report issue precede final cockpit UI.

## Missing issues to add
- `[doc] Restore or reconcile missing planning docs` — required docs are deleted in the working tree while the issue pack is untracked.
- `[chore] Register/seed V1 pipeline and runner fixtures` — current dev/test seed data uses `pipeline-default`, Java 17/21 only, and `3.5.14`.
- `[feat] Define V1 event type registry` — many issues add new events; event types need coordinated migration/testing.
- `[test] V1 contract fixture module` — shared V1 pipeline/runner/job fixtures will prevent each issue from copying setup.
- `[security] Redaction and forbidden-path policy baseline` — context, model audit, assistant, repair, proof, and reports all depend on the same policy.

## Human decisions needed
- Decide whether missing/deleted docs should be restored before V1 work starts; Codex should not restore unrelated deleted files without approval.
- Decide whether Boot 4 YAML files stay as historical assets or are moved out of V1 selection paths.
- Decide whether `V1-09` can move earlier in the order.
- Decide whether read-only assistant should precede patch application.
- Decide whether proof backend should be moved before full cockpit UI.

# Final readiness verdict

## Overall status
NEEDS_ISSUE_REWRITE

## Best first issue
`V1-01` because it is small, has direct current evidence, blocks route cleanup, and reduces repository hygiene risk before larger V1 work.

## Do not implement yet
- Azure/model behavior — model registry/context/audit contracts are not in place.
- Assistant behavior — Context Builder and read-tool policy do not exist.
- Repair/patch application — reviewer gate, patch policy, snapshots, and rollback contracts do not exist.
- Full cockpit UI — required backend contracts are mostly absent.
- Proof reports — should be reordered before final cockpit proof UI.

## Top 10 issue improvements
1. Restore or explicitly supersede the missing required planning docs.
2. Add V1 fixture helpers for the exact three-stage route.
3. Clarify historical Boot 4/`3.5.14` assets versus V1-selectable assets.
4. Split `V1-03` into ledger schema/repository and job-creation integration if needed.
5. Define env-ref schema for Maven, JDKs, Azure endpoints, keys, and deployments.
6. Split `V1-06` into command/manifest contract and real orchestrator worker launch.
7. Move model registry/context/audit before any serious LLM workflows.
8. Move read-only assistant earlier than patch application.
9. Move backend proof/report generation before full cockpit proof UI.
10. Split `V1-18` into route/panel-specific UI issues.