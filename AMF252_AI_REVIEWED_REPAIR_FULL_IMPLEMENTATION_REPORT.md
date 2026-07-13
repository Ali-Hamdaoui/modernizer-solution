# AMF-252 AI Reviewed Repair — Full Implementation Report

## Executive verdict

The AMF-252 reviewed-repair implementation is statically implemented across the V2 backend, persistence, validation boundary, continuation bridge, frontend actions, and state-bearing events.

The implementation is not runtime-proven or end-to-end proven. No migration, model call, patch Apply, build/test execution, or test suite was run for this mission.

## Files changed

- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `migration_factory/control_tower/application/v2_repair_projection.py`
- `migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0053_v2_repair_lineage_claims.sql`
- `migration_factory/repair_loop/validation_runner.py`
- `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx`
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`
- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/lib/contracts.ts`

Tests were not added or modified. The authoritative plan file and pre-existing Graphify outputs remain outside the implementation scope.

## Implementation by phase

### Phase 0 — projection truth

All three persisted-proposal projections now pass `reviewer_decision`, `risk`, reviewer reasoning, and validation proof status into the projection builder. Omitted arguments no longer manufacture `unknown` or omit persisted risk.

### Phase 1 — lifecycle

Reviewer `accept` remains the only actionable reviewer outcome. `revise` and `reject` are persisted as truthful non-actionable outcomes with reviewer decision, reason, risk, and lineage references where available. A human rejection endpoint now persists a terminal rejection and emits `repair_outcome_persisted`.

Human Apply remains gated by backend `allowed_actions`, deterministic rule allowlisting, LOW risk, diff checksum, safe-diff parsing, and reviewer acceptance.

### Phase 2 — transaction and idempotency safety

Apply now starts with a short, job-scoped persisted claim keyed by `idempotency_key` and diff checksum. Duplicate terminal requests replay the persisted terminal response; concurrent/in-flight claims fail closed. Apply work is moved onto a read-mode UoW after the claim so it does not hold `BEGIN IMMEDIATE` while patch/build/test work runs.

The claim and terminal state are persisted in the repair proposal record. Revision/rejection action idempotency remains compatible with existing V2 gate idempotency; direct revision requires controlled runtime validation before being considered fully equivalent to gate-backed regeneration.

### Phase 3 — ValidationExecutionContext

`ValidationExecutionContext` is immutable and server-owned. It carries job/command/stage identity, sandbox identity, original validation command, validation unit, module/class, JDK environment, timeout/startup behavior, report policy, H2 flags, and source/target/runtime profiles.

The original failure boundary writes `validation_execution_context.json` and its checksum. Repair validation reuses `run_build_agent()` for command execution and `run_test_agent()` only for Surefire evidence parsing. Missing commands fail closed; a string command is normalized as one command rather than split character-by-character.

`TEST_PASSED` is distinguished from `TESTS_NOT_FOUND` through `validation_proof_status`, including `BUILD_AND_TEST_VERIFIED` and `BUILD_VERIFIED_TEST_EVIDENCE_NOT_FOUND`.

### Phase 4 — complete lifecycle and lineage

New proposals receive an immutable lineage manifest containing failure/context/diff/reviewer/policy/rule/risk bindings and checksum. SQLite stores only minimal indexed lineage, claim, validation, and continuation fields. Apply reloads and verifies the manifest and validation-context checksums and proposal/diff bindings.

Invalid or missing deterministic rule IDs now fail closed. The former checksum/`repair_apply` fallback behavior is removed.

Attempt limits continue to use the existing bounded V2 policy (`DEFAULT_MAX_REPAIR_ATTEMPTS = 3`). No automatic hidden reviewer loop was added.

### Phase 5 — continuation bridge

After a successful repair validation, the existing `stage_completion_review` gate remains authoritative. A human `CONTINUE` action now reloads the persisted repair proposal and server-owned sandbox reference, calls `V2StageProgressionService.queue_next_stage()` with the patched sandbox, persists the returned command identity, commits, and launches the existing `V2OrchestratorRunner` outside the persistence transaction.

Idempotent gate decisions do not queue the next stage a second time.

### Phase 6 — frontend and events

The existing V2 repair UI was reused. It now exposes validation proof status, reviewer state, rejection, revision availability, Apply errors, and safe public data. Apply is enabled only from the current proposal’s authoritative `allowed_actions`; a stale event-derived action cannot enable it.

The public projection no longer returns the raw `diff_ref` filesystem path. Safe preview and the dedicated diff endpoint remain the public diff boundary.

State-bearing `repair_outcome_persisted` was added and generic `repair_completed` is not emitted after that precise outcome. Existing V2 SSE and refresh mechanisms remain in use.

## Existing code reused

- `run_build_agent()` for all build/validation command execution.
- `run_test_agent()` for generated Surefire evidence parsing only.
- `evaluate_patch_proposal()` and `apply_patch_to_sandbox()` for patch policy and sandbox application.
- Existing V2 repair repositories, phase gates, event repository, SSE, safe diff projection, frontend panels, stage progression service, and orchestrator runner.
- Existing bounded repair attempt policy.

No repair LangGraph node/subgraph, duplicate Maven/Gradle executor, duplicate test executor, second patch gate, second sandbox implementation, or second frontend repair state model was added.

## DB/schema changes

Migration `0053_v2_repair_lineage_claims.sql` adds nullable legacy-compatible fields for lineage manifest references/checksums, validation-context references/checksums, Apply idempotency/claim state, continuation command identity, and validation proof status. A partial unique index prevents reuse of an Apply idempotency key for multiple proposals.

## Static validations performed

- `py -3 -m py_compile` on all changed Python files: passed.
- `git diff --check`: passed; only normal CRLF conversion warnings were reported.
- `npm run typecheck -- --pretty false` in `web/control-tower`: passed.
- Targeted `rg` audits for hardcoded Maven repair commands, fabricated rule-ID fallbacks, projection call sites, claim state, and continuation wiring.

## Tests and runtime

- Tests added: none.
- Tests modified: none.
- Python tests/pytest: not run.
- Frontend test suites: not run.
- Live migration: not performed.
- Live model call: not performed.
- Live repair Apply: not performed.
- Runtime/E2E execution: not performed.

## Remaining unproven items and known risks

- Static compilation cannot prove SQLite migration ordering, multi-connection locking behavior, or concurrent request behavior.
- Direct human revision now records an explicit request without silently looping; the gate-backed regeneration path remains the authoritative fully wired regeneration path. A controlled runtime proof is required before treating direct revision as equivalent.
- Continuation depends on persisted stage metadata and route configuration. The bridge fails closed when server-owned sandbox/proposal context is missing.
- No proof exists yet that every historical legacy proposal has sufficient validation context or lineage data; legacy records intentionally remain nullable and fail closed where required safety metadata is absent.
- The implementation has not proven that all externally emitted event reducers and deployed frontend bundles consume the new fields exactly as intended.

## Exact next runtime proof procedure

1. Apply SQLite migration `0053` in an isolated disposable database.
2. Run a controlled failing migration with a deterministic, allowlisted LOW-risk reviewer result.
3. Verify failure evidence, context, validation-context checksum, lineage manifest, reviewer decision, risk, and safe projection.
4. Exercise human reject and gate-backed human revision; verify no Apply action is exposed for reject/revise.
5. Exercise two concurrent Apply requests with the same proposal and idempotency key; verify one claim, one patch, one validation, and replay of the terminal response.
6. Exercise accepted Apply with the original Maven/Gradle validation profile and inspect build/test artifacts, specifically distinguishing `TEST_PASSED` from `TESTS_NOT_FOUND`.
7. Continue the resulting stage-completion gate and verify the patched sandbox is preserved, one next command is queued, the command identity is persisted, and the existing runner starts it.
8. Exercise bounded validation failure until the configured terminal state and inspect attempt lineage/events.
9. Only after this controlled runtime flow succeeds should the feature be called runtime-proven; only a full real migration path establishes end-to-end proof.

## Final distinction

This report establishes **STATICALLY IMPLEMENTED** status based on source inspection, compilation, type checking, and targeted audits.

It does not establish **RUNTIME-PROVEN** or **END-TO-END PROVEN** status.
