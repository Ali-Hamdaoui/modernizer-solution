# AMF-252 Direct Repair Continuation Implementation Plan

## Executive Summary
Recommended implementation order:
1. Fix the frontend timeline contract so `ValidationProgressPanel` derives rebuild/test/continue from `rerun_status` plus the repair reason code, not from `attempt.status`.
2. Harden direct proposal materialization so a missing `direct_sandbox` cannot produce a user-actionable direct proposal.
3. Add approval-time defense in depth to the direct apply helper so the exact persisted diff is checked again against the live sandbox before `git apply`.
4. Verify the direct validation success and failure branches continue to reuse the existing continuation and repair-cycle helpers.
5. Leave canonical diff/checksum handling as-is unless a regression is found; current reviewed-diff canonicalization already persists the canonical file and checksum.

No tests are added or edited in this plan.

## Current Correct Behavior
- Patch apply failure already stops before rebuild/test in the direct approval path.
- `run_validation_after_patch()` already reuses the existing build and test agents instead of reimplementing them.
- Validation failure on the direct path already keeps the patched sandbox and creates the next repair cycle from validation evidence.
- The normal build/test path already exists and remains the source of truth for the non-direct flow.
- Normal stage continuation already exists through the orchestrator runner and stage-progression service.
- Approval-time checksum verification already reloads the persisted diff from disk and rechecks it before apply.
- Reviewed direct diff canonicalization is already handled by the existing recount path: when `hunk_count_mismatch` is repaired, the canonical diff ref is rewritten before persistence and the checksum is recomputed from the canonical file.

## Current Broken / Risky Behavior
- High: `ValidationProgressPanel` currently falls back to `attempt.status` for rebuild/test/continue, which makes `PATCH_APPLY_FAILED` and `PATCH_CHECK_FAILED` look like validation failures.
- High: direct proposal materialization still persists a user-reviewable direct proposal when `direct_sandbox` is empty, because the validation block is skipped instead of failing closed.
- High: `apply_patch_to_sandbox_direct()` skips `git apply --check`, so the approval-time direct apply path is missing defense in depth.
- Medium: the frontend has no explicit reason-code input for the timeline, so it is forced to infer state from a generic attempt summary.
- Medium: continuation state is currently under-specified in the UI for direct apply failures, because the panel is not reason-code aware.
- Low: candidate-vs-reviewed direct proposal behavior is split across two direct-materialization branches, so the safe fix should be scoped to the shared gate helpers rather than duplicated in the approval route.

## Reuse Map

| Existing behavior | Function/file | Should reuse? | Current duplication risk | Recommended action |
|---|---|---:|---|---|
| Repair rerun validation | `migration_factory/repair_loop/validation_runner.py::run_validation_after_patch` | Yes | None if reused as-is | Keep this as the only repair rerun entrypoint. It already owns build + test rerun orchestration. |
| Build rerun | `migration_factory/agents/build_agent/agent.py::run_build_agent` | Yes | High if copied into approval code | Do not duplicate build command construction or result classification. |
| Test rerun | `migration_factory/agents/test_agent/agent.py::run_test_agent` | Yes | High if copied into approval code | Keep test parsing centralized in the test agent. |
| Normal success proof | `migration_factory/control_tower/application/v2_orchestrator_runner.py::_has_success_proof` | Yes | Medium if a second success contract appears | Reuse the existing proof contract for normal success; do not invent a repair-specific proof shape. |
| Normal stage continuation | `migration_factory/control_tower/application/v2_orchestrator_runner.py::_auto_queue_next_stage` | Yes | Medium if direct success gets its own queue logic | Keep direct-success continuation on the same helper. |
| Gate-backed repair continuation | `migration_factory/control_tower/application/v2_repair_gate_service.py::handle_repair_validation_result` | Yes | Medium if a parallel progression path is added | Reuse for non-direct reviewed repair validation outcomes. |
| Next repair cycle from validation failure | `migration_factory/control_tower/application/v2_repair_gate_service.py::create_next_repair_cycle_from_rerun_failure` | Yes | Medium if direct failure gets a bespoke branch | Keep direct validation failure on this existing repair-cycle builder. |
| Applicability precheck | `migration_factory/repair_loop/patch_apply.py::check_patch_applicability` | Yes | High if direct apply bypasses it | Use this as the shared patch-check primitive for materialization and/or approval-time defense. |
| Direct diff preview and parse/checksum state | `migration_factory/control_tower/application/safe_diff_preview.py::build_safe_diff_preview` | Yes | Medium if new parsing logic is added elsewhere | Keep parse/truncation/checksum classification in the preview helper. |
| Canonical recount path | `migration_factory/control_tower/application/safe_diff_preview.py::canonicalize_with_recount` | Yes | Low | Leave this as the only canonicalization path for hunk-count repair. |
| Direct proposal projection | `migration_factory/control_tower/application/v2_repair_projection.py::build_reviewed_diff_proposal_from_record` | Yes | Medium if frontend-specific state is computed in backend | Keep backend projection authoritative; do not duplicate frontend-only derivation there. |
| Direct materialization gate | `migration_factory/control_tower/application/v2_repair_gate_service.py::_validate_direct_proposal_diff` and the direct-proposal branches in `create_reviewed_repair_gate_on_failure` | Yes | High if approval-time logic duplicates gate-time parsing | Fail closed on missing sandbox and reuse the existing materialization helpers. |
| Event emission | `migration_factory/control_tower/application/v2_repair_gate_service.py` and `migration_factory/control_tower/adapters/fastapi/app.py` event helpers | Yes | Medium | Reuse existing event emission; do not add a second event taxonomy. |

## Correct End-to-End Direct Repair Flow
1. Failure evidence is captured by the normal repair/review chain.
2. The reviewer proposes either a reviewed diff or a candidate diff.
3. The materialization gate validates the persisted diff against the sandbox using the existing diff preview and applicability helpers.
4. The user approves the proposal.
5. The backend reloads the persisted diff and verifies the checksum before apply.
6. The backend applies the exact persisted diff to the sandbox.
7. If apply is rejected, stop immediately with `PATCH_APPLY_FAILED` or `PATCH_CHECK_FAILED` and do not rebuild/test.
8. If apply is `APPLIED` or `ALREADY_APPLIED`, call the existing validation rerun helper.
9. If validation passes, continue the normal migration using the existing progression helper.
10. If validation fails, keep the patched sandbox and create the next repair cycle from the validation evidence already produced by the rerun.

## Implementation Phases

### Phase 1: Frontend Timeline Contract Fix
- Update `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` to pass the direct proposal reason code into `ValidationProgressPanel`.
- Update `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx` so rebuild/test/continue are derived from `rerun_status` plus the explicit reason code, not from `attempt.status`.
- For `PATCH_APPLY_FAILED` and `PATCH_CHECK_FAILED`, force:
  - apply = failed
  - rebuild = not started
  - test = not started
  - continue = blocked
- Keep the `APPLIED + rerun_status=passed` and `APPLIED + rerun_status=failed` paths unchanged in principle, but make the text/status mapping reason-code aware.
- Do not expand the repair summary DTO unless a later consumer needs it; the panel already has access to `proposal.reason_code` in the parent component.

### Phase 2: Apply-Success Continuation Audit/Fix
- Verify the direct success path in `migration_factory/control_tower/adapters/fastapi/app.py` continues to use `runner._auto_queue_next_stage(...)` after validation passes.
- Verify the non-direct reviewed-repair success path still uses `V2RepairGateService.handle_repair_validation_result(...)`.
- If any branch uses a one-off queue/progression path, replace it with the existing orchestrator progression helper rather than duplicating stage logic.
- Do not change the normal stage-success path in the orchestrator runner.

### Phase 3: Direct Materialization Gate Hardening
- In `migration_factory/control_tower/application/v2_repair_gate_service.py`, require `direct_sandbox` before any direct reviewed/candidate proposal can be persisted.
- If `direct_sandbox` is missing, emit a materialization failure and an unavailable projection, then return `skipped`.
- Use a stable reason code such as `direct_sandbox_missing`.
- Keep the existing checks in place:
  - `parse_status`
  - `checksum_mismatch`
  - `truncated`
  - `git apply --check`
  - `hunk_count_mismatch` canonicalization via recount for reviewed diffs
- Do not expose `approve_sandbox_apply` for a proposal that did not pass the backend materialization gate.

### Phase 4: Patch Apply Defense-In-Depth
- In `migration_factory/repair_loop/patch_apply.py`, make `apply_patch_to_sandbox_direct()` run `git apply --check` before `git apply`.
- Prefer a small shared internal helper so the direct and gated apply paths do not diverge further.
- Keep the existing direct-path reverse-check behavior for `ALREADY_APPLIED`.
- Do not run rebuild/test when patch apply fails.
- The approval endpoint already reloads the persisted diff and verifies checksum; keep that behavior and harden the apply helper instead of re-implementing request validation.

### Phase 5: Canonical Checksum Fix
- No code change is required for the current reviewed-diff canonicalization path.
- The current code already rewrites the canonical diff ref before persistence and stores the checksum from the canonical file.
- Keep this as a verification point only.
- If a regression is found later, the fix belongs in `migration_factory/control_tower/application/v2_repair_gate_service.py` around `_validate_direct_proposal_diff()` and `_persist_direct_reviewed_repair_proposal()`.

### Phase 6: Optional Cleanup Later
- Split `_handle_exit` only if a later audit proves it is the source of a new bug.
- Do not refactor `_handle_exit` in this implementation.
- Do not rewrite LangGraph or the normal orchestrator control flow.
- Do not create a second build/test or stage-progression system.

## Files To Change
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`
  - Pass the proposal reason code into the timeline component.
- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx`
  - Make the timeline reason-code aware and stop using `attempt.status` as a rebuild/test fallback.
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
  - Fail closed when `direct_sandbox` is missing for direct proposals.
  - Keep direct materialization as the single source of truth for parse/checksum/applicability validation.
- `migration_factory/repair_loop/patch_apply.py`
  - Add `git apply --check` to the direct apply helper and keep the already-applied reverse check.

## Files Not To Change
- Do not refactor `_handle_exit` in this implementation.
- Do not rewrite LangGraph or the normal orchestrator path.
- Do not duplicate `run_build_agent()` or `run_test_agent()`.
- Do not change normal migration success behavior.
- Do not create or edit backend tests.
- Do not create or edit frontend tests.
- Do not add a second stage-progression mechanism.
- Do not change `safe_diff_preview.py` unless a later regression proves the canonical diff path is broken.

## Exact Acceptance Criteria

For `PATCH_APPLY_FAILED`:
- No rebuild/test runs.
- No `repair_validation_*` events are emitted.
- The proposal remains read-only.
- `rerun_status = not_started` for new failures.
- Legacy `null` `rerun_status` is treated as `not_started` when the reason code is `PATCH_APPLY_FAILED`.
- The UI says patch apply failed and rebuild/test not started.

For `PATCH_CHECK_FAILED`:
- No rebuild/test runs.
- No `repair_validation_*` events are emitted.
- The proposal remains read-only.
- The UI says patch precheck failed and rebuild/test not started.

For `APPLIED + rerun passed`:
- Validation runs.
- Migration continues or the next stage queues using the existing progression logic.

For `APPLIED + rerun failed`:
- Validation runs.
- The patched sandbox is kept for the direct path.
- The next repair cycle is created from validation evidence.

For malformed direct diff before approval:
- No `approve_sandbox_apply`.
- `materialization_failed`, `unavailable`, or `skipped` is emitted instead.
- No `user_review_required` direct proposal is exposed unless parse/checksum/applicability validation passed.

For canonicalized diff:
- The canonical diff is persisted.
- The canonical diff is what the frontend shows.
- The proposal `diff_checksum` matches the canonical diff.
- Approval-time checksum validation compares against the canonical diff.

## Safe Verification Commands
Use safe commands only. Do not run tests.

Allowed:
- `python -m py_compile` for touched Python files
- `npm run type-check` in `web/control-tower`
- `git diff`
- `git status`
- manual API calls with `Invoke-RestMethod`

Not allowed:
- `pytest`
- `npm test`
- `vitest`
- full migration runs
- external APIs
- real LLM calls
- destructive commands
