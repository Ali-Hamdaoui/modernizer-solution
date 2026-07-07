# Orchestrator Repair Timeline Deep Audit

**Date:** 2026-07-07
**Scope:** migration orchestrator, normal build/test flow, repair validation flow, frontend repair timeline, duplicated logic
**Audit type:** Static code inspection + live runtime API inspection for job `4a587211b9d74c1182b9a98d4504996c`. No code changed, no migration run, no external API, no LLM calls.

---

## Executive Summary

**Verdict: For `PATCH_APPLY_FAILED` the UI is WRONG but the backend is mostly RIGHT. The defect is (1) the frontend repair-timeline derivation, and (2) a latent backend materialization-gate gap.**

Runtime evidence (live API for the job) shows the proposal is correctly placed in a terminal read-only state:

- `status = approve_failed`
- `apply_status = REJECTED`
- `rerun_status = null` (empty)
- `reason_code = PATCH_APPLY_FAILED`
- `allowed_actions = []` (empty)
- `status_reason = "[PATCH_APPLY_FAILED] Sandbox apply failed: error: corrupt patch at .../patch_attempt_1_direct.diff:11"`

The backend **did NOT** run rebuild/test, did **NOT** emit any `repair_validation_*` event, and did **NOT** create a next repair cycle for this case (only `repair_approve_apply_failed` was emitted at seq 815, after the original stage `build_failed` events at 804/806). So the backend correctly honored the rule "PATCH_APPLY_FAILED => no rebuild/test, no validation, no migration continuation."

The UI **shows the wrong thing** because of `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx`, function `phaseStatus` (lines 13-36). For the `rebuild`, `test`, and `continue` phases it derives the status from:

```ts
const rerunStatus = normalize(attempt.rerun_status || attempt.status);
```

Because `rerun_status` is empty (`null`), it falls back to `attempt.status = "approve_failed"`. `"approve_failed"` contains the substring `"failed"`, so:

- `rebuild` => `"failed"` => UI shows **"Rebuilding FAILED"**
- `test` => `"failed"` => UI shows **"Running tests VALIDATION FAILED"**
- `continue` => `rerunStatus.includes("failed")` => **"Migration continuing BLOCKED"**

This is the precise mechanism behind the screenshot. The frontend conflates "apply failed" (`attempt.status = approve_failed`) with "validation rerun failed" because it reuses `attempt.status` as a fallback for the rerun phases. There is **no guard on `reason_code`** to tell the panel this is a patch-apply failure, not a validation failure.

Separately, there is a **high-severity backend gate bug** (Q4): in `v2_repair_gate_service.py`, the direct-reviewed-diff materialization validation is guarded by `if direct_sandbox:` (line 390). If `direct_sandbox` is empty at materialization time, **all structural/parse/checksum/applicability validation is skipped and the proposal is still persisted** (line 424 `._persist_direct_reviewed_repair_proposal`). This is the most plausible root cause of *why a corrupt patch reached the apply step at all* -- the corrupt diff was never validated against the sandbox before being exposed to the user. The direct **apply** path (`apply_patch_to_sandbox_direct`, `patch_apply.py:500`) deliberately skips `git apply --check`, so the corruption is only caught at apply time.

> NOTE ON LIVE vs REPO: The repo's current `app.py:4930` already sets `rerun_status="not_started"` for `is_true_apply_failure` (PATCH_APPLY_FAILED). The live job still shows `rerun_status=null`, meaning the running server predates that fix. Even with `rerun_status="not_started"`, the frontend `phaseStatus` would show "pending / Waiting for your approval" for rebuild/test (better than FAILED, but still wrong copy for a terminal apply failure). The persistent, repo-current defect is the frontend fallback + lack of `reason_code` awareness.

---

## Runtime State for Job `4a587211b9d74c1182b9a98d4504996c`

### `GET /v1/v2/jobs/{job}/repair/proposals/current`
```
proposal_id:        bc1cd28fdd94474893b9832ef570a5cc
job_id:             4a587211b9d74c1182b9a98d4504996c
command_id:         1b9fac3d602a4271a2537eede6a5db44
gate_id:            (empty)                       # direct proposal
route_step_index:   1
stage_index:        1
status:             approve_failed
attempt_number:     1
apply_status:       REJECTED
rerun_status:       (empty)
reason_code:        PATCH_APPLY_FAILED
status_reason:      [PATCH_APPLY_FAILED] Sandbox apply failed: error: corrupt patch at .../patch_attempt_1_direct.diff:11
policy_status:      bypassed
allowed_actions:    []                            # correctly empty -> button disabled
kind:               direct_reviewed_diff
failure_summary:    BUILD_FAILED_IN_SANDBOX
hypothesis:         String passed to Sort constructor, incompatible with List<String>
```

### `GET /v1/v2/jobs/{job}/repair/attempts`
```
attempts[0]:
  status:             approve_failed
  apply_status:       REJECTED
  rerun_status:       null                       # <-- fallback trigger
  rollback_status:    null
  remaining_attempts: 0
  status_reason:      [PATCH_APPLY_FAILED] Sandbox apply failed: corrupt patch at ...:11
  created_at:         2026-07-07T08:00:44Z
  completed_at:       2026-07-07T08:02:44Z
```

### `GET /v1/v2/migration-jobs/{job}/events/snapshot?after=0` (repair-relevant, in order)
```
756 repair_failure_evidence_written  completed
757 repair_context_pack_written      completed
804 build_failed                     failed     <- ORIGINAL STAGE build failure (normal_stage scope)
805 repair_started                   running    <- REPAIR_REVIEW_REQUIRED entered
806 build_failed                     failed     <- duplicate stage build failure event
808 repair_chain_started             started
809 repair_llm_main_completed         completed
810 repair_llm_reviewer_completed     completed
811 repair_diff_ready_for_user_apply  completed   <- direct diff ready
815 repair_approve_apply_failed       failed      <- PATCH_APPLY_FAILED (repair_apply scope)
```

Key observations:
- No `repair_validation_completed`, `repair_validation_passed`, or `repair_validation_failed` event exists. Backend did NOT validate.
- The only events that look like "build/test failure" (804, 806) are the **original normal-stage** failures, NOT repair-apply failures. They are correctly scoped; the frontend timeline does not use them anyway (it reads `attempts`).
- The repair-apply failure is its own event (`repair_approve_apply_failed`) with `reason_code=PATCH_APPLY_FAILED`. The frontend timeline does NOT consume `reason_code`; it only consumes `attempt.status`/`rerun_status`.

### `pipeline` / `stages`
Not materially different from the above; the mismatch lives entirely in the `ValidationProgressPanel` client-side derivation.

---

## Correct State Machine

| State | apply_status | rerun_status | Build/Test expected | Migration continuation | Allowed frontend actions | Expected UI copy |
|---|---|---|---|---|---|---|
| PATCH_CHECK_FAILED | REJECTED / CHECKED-fail | not_started | NOT run (precheck) | BLOCKED, new proposal required | read-only (view only) | "Patch not applicable during precheck; no rebuild/test" |
| PATCH_APPLY_FAILED | REJECTED | not_started (or explicit "not_run") | NOT run (apply failed after approval) | BLOCKED, new proposal required | read-only (view only) | "Patch apply failed after approval; no rebuild/test started" |
| APPLIED / ALREADY_APPLIED + rerun failed | APPLIED | failed | run, failed | BLOCKED; next repair cycle created (direct keeps patched sandbox) | read-only view + next cycle available | "Rebuild/test ran and FAILED (validation failed)" |
| APPLIED / ALREADY_APPLIED + rerun passed | APPLIED | passed | run, passed | CONTINUE / next stage queued | view_result, continue_migration | "Rebuild/test passed; migration continuing" |

The current frontend violates the PATCH_APPLY_FAILED row: it shows rebuild/test as FAILED/VALIDATION FAILED and continuation as BLOCKED-with-failed-styling, and it does not distinguish PATCH_CHECK_FAILED vs PATCH_APPLY_FAILED copy.

---

## Why Screenshot Is Wrong or Right

### Applying reviewed diff to sandbox = FAILED
- Backend: `apply_status=REJECTED`, `reason_code=PATCH_APPLY_FAILED` -> CORRECT. This row is right.
- Frontend: `phaseStatus("apply")` checks `applyStatus.includes("fail") || attempt.status.includes("approve_failed")`. `attempt.status="approve_failed"` => "failed". Correct enough, but it is driven by the generic `attempt.status`, which is fragile.

### Rebuilding = FAILED
- **WRONG.** Backend never ran rebuild. `rerun_status` is empty/null. `phaseStatus("rebuild")` falls back to `attempt.status="approve_failed"`, which contains "failed" => "failed". The backend intended `rerun_status="not_started"` in current repo code, but the live data has null, and the frontend fallback would still be wrong for `approve_failed` even if `rerun_status` were "not_started" (it would show "pending" -- misleading, but not FAILED).

### Running tests = VALIDATION FAILED
- **WRONG (same root cause as Rebuilding).** Should be "not started / not applicable".

### Migration continuing = BLOCKED
- **Partially correct outcome, wrong semantics.** BLOCKED is the right *terminal* state for PATCH_APPLY_FAILED, but the UI derives it from `rerunStatus.includes("failed")` (i.e., it thinks validation failed). It should be derived from `proposal.status==approve_failed` + `reason_code=PATCH_APPLY_FAILED` and labeled "Blocked: patch apply failed, new proposal required" -- not styled as a validation failure.

### Apply reviewer diff button "may still appear active"
- **Per current API + code it is correctly DISABLED.** `RepairProposalPanel.tsx:404-408`: `isApproveFailed = proposal.status === "approve_failed"`; `approveAllowed = !isApproveFailed && allowed_actions.includes("approve_sandbox_apply")`. API returns `status=approve_failed` and `allowed_actions=[]`, so `approveAllowed=false`, and `RepairActionsBar.tsx:73` disables the button via `disabled={!approveEnabled || ...}`.
- Therefore, if the button "appears active" in the screenshot, the cause is a **stale frontend bundle / browser cache**, OR a pre-fix build where `status` was not yet `approve_failed`. There is **no current code path** that re-enables it for PATCH_APPLY_FAILED. Recommend a hard refresh + cache-bust; no code change needed for this specific symptom, but a defensive test should lock it.

---

## Current Orchestrator Architecture

### Normal build/test path (Stage 3 / Stage 4)
```
V2 FastAPI (app.py)
  -> V2OrchestratorRunner.start()            (v2_orchestrator_runner.py:128)
     -> subprocess: python -m migration_factory.orchestrator.runner --mode full_sandbox_migration
        -> LangGraph graph.py (analysis->planning->assessment->approval->sandbox_transform->report)
           -> run_sandbox_transform_phase()   (phase_services.py:123)
              -> apply_approved_sandbox_transform()  (transform_v1_after_approval.py:252)
                 -> run_build_agent()  PER UNIT  (build_agent/agent.py:48)   [deterministic]
                 -> _finalize_with_test_validation() (transform_v1_after_approval.py:506)
                    -> run_test_agent()  PARSE ONLY  (test_agent/agent.py:35)
        emits CONTROL_TOWER_EVENT JSONL on stdout
     <- parse final JSON result
  -> _handle_exit()  (v2_orchestrator_runner.py:486)
     -> _emit_phase_outcome_events / _has_success_proof / _auto_queue_next_stage
```

### Repair path (direct reviewed diff, AMF-252)
```
repair proposal materialized (gate service create_reviewed_repair_gate_on_failure)
  -> direct: _persist_direct_reviewed_repair_proposal (status=user_review_required)
UI: user clicks "Apply reviewer diff"
  -> app.py POST approve endpoint (app.py:4842-4980)
     -> apply_patch_to_sandbox_direct()  (patch_apply.py:500)  [SKIPS git apply --check]
        on success: status in {APPLIED, ALREADY_APPLIED}
           -> run_validation_after_patch()   (app.py:4983)  [rebuild/test rerun]
              -> passed: stage_completed + _auto_queue_next_stage (direct) OR repair_gate transition (gated)
              -> failed: create_next_repair_cycle_from_rerun_failure (direct) OR rollback+gate (gated)
        on failure (PATCH_APPLY_FAILED / PATCH_CHECK_FAILED):
           -> update_proposal_prf_fields(status=approve_failed, rerun_status="not_started")
           -> event repair_approve_apply_failed / repair_approve_apply_check_failed
           -> NO validation, NO next cycle
```

---

## Normal vs Repair Flow Comparison

### Shared
- `V2OrchestratorRunner` subprocess + `_handle_exit` + `_auto_queue_next_stage` (used by both normal success and direct repair success).
- `run_build_agent` / `run_test_agent` deterministic logic is reused inside `run_validation_after_patch` for the repair rerun.
- `apply_patch_to_sandbox` (gated) and `apply_patch_to_sandbox_direct` (direct) share helpers: `_normalize_patch_bytes`, `_extract_touched_paths_from_diff`, `_check_sandbox_preflight`, `_git_apply`, `_snapshot_files`.
- `_has_success_proof` contract check is the same proof for normal and repair success.

### Separate
- Normal: single deterministic pass inside LangGraph subprocess.
- Repair: approval-gated loop with patch apply + validation rerun.
- Normal build/test happen **inside** the orchestrator subprocess; repair validation rerun (`run_validation_after_patch`) happens **inside the FastAPI approve handler** (app.py), NOT inside the subprocess.

### Incorrectly mixed
- `_handle_exit` runs `_emit_failure_repair_events` (app.py:666) for **every** non-analysis/planning/approval exit BEFORE the success-proof branch, including before the terminal-failure check. This couples failure-repair emission with the success path ordering.
- The frontend `ValidationProgressPanel.phaseStatus` mixes apply-failure status (`attempt.status`) into rebuild/test/continue derivation (the core bug).
- The original-normal-stage `build_failed` events (804/806) and the repair-apply `repair_approve_apply_failed` event coexist; if any panel ever read generic "build_failed"/"test_failed" it would conflate scopes. Currently the repair panel reads `attempts` only, so it is safe today, but the event taxonomy is fragile (see Event/Projection Audit).

---

## Duplicated Work Inventory

| # | Duplication | Files / Functions | Why dangerous | Recommendation | Tests needed |
|---|---|---|---|---|---|
| 1 | Status string constants (`BUILD_PASSED_IN_SANDBOX`, `TEST_PASSED`, `APPLIED`, `REJECTED`, `PATCH_APPLY_FAILED`, etc.) | `transform_v1_after_approval.py:67`, `test_agent/agent.py:18`, `v2_orchestrator_runner.py:95`, `patch_apply.py:16-25`, multiple tests | Silent drift; one side changed, other not | Central `migration_factory/contracts/statuses.py` enum | contract equality tests |
| 2 | Build/test success-proof logic | `_has_success_proof` (v2_orchestrator_runner.py:2969) vs inline checks in `run_validation_after_patch` / `_emit_phase_outcome_events` | Different "what counts as green" definitions | Single `is_build_test_success(...)` used by both | shared-success tests |
| 3 | Event emission | `_emit_phase_outcome_events`, `_emit_failure_repair_events`, `_append_v2_event` spread across runner + app.py + gate service | Inconsistent payloads, double emission | Central `repair_event_emitter` + `normal_event_emitter` | event-sequence tests |
| 4 | Proposal projection | `build_reviewed_diff_proposal_projection` vs `build_reviewed_diff_proposal_from_record` (v2_repair_projection.py) | Two code paths produce same shape; drift | One builder with two input adapters | projection-equality tests |
| 5 | Patch apply / check logic | `apply_patch_to_sandbox` (patch_apply.py:229) vs `apply_patch_to_sandbox_direct` (patch_apply.py:500) | Direct skips `--check` + struct validation; behavior diverges silently | Shared core `_apply_core()` with explicit `skip_check` flag; both validate via shared precheck at materialization | apply/check parity tests |
| 6 | Direct proposal action filtering | `allowed_actions` computed in projection (v2_repair_projection.py) + `approveAllowed` in `RepairProposalPanel.tsx:408` + `approveEnabled` prop in `RepairActionsBar.tsx:73` + gate-service filtering | Inconsistent disable logic across layers | Single backend-derived `allowed_actions` is the source of truth; frontend only renders | allowed_actions tests |
| 7 | Frontend state derivation | `ValidationProgressPanel.phaseStatus` (apply/rebuild/test/continue) + `RepairProposalPanel` isApplyCheckFailed/isPatchApplyFailed + `RepairAttemptTimeline` | Rebuild/test derive from `attempt.status` fallback (the bug) | Derive rebuild/test/continue ONLY from `rerun_status` + `reason_code`; never from `attempt.status` | timeline tests (see below) |
| 8 | Repair vs normal progression | `_auto_queue_next_stage` called from runner (normal) AND from app.py direct-apply success (repair) | Two call sites, two slightly different payloads | Keep both but route through one `_queue_or_complete_stage` helper | progression tests |

Severity ranking: #7 (frontend fallback) = HIGH (causes the reported symptom). #5 + #4 gate gap = HIGH (allows corrupt patch to reach apply). #1,#2,#3 = MEDIUM (maintainability / future drift). #6 = MEDIUM.

---

## _handle_exit Branch Map (v2_orchestrator_runner.py:486)

Single function, early-returns, success/failure interleaved.

1. **`_handle_exit_parse_failure` (implicit)** -- `exit_code != 0` (line 502): emit diagnostic failure + `stage_failed`, return.
2. **`_handle_exit_process_failure` (implicit)** -- `result is None` (line 530): emit `result_contract_failed` + `stage_failed`, return.
3. **analysis phase branch** (line 581): `_emit_artifacts` + PASS->`_handle_reviewed_phase_completed` else `stage_failed`, return.
4. **planning phase branch** (line 610): same shape as analysis, return.
5. **Shared emission** (lines 654-671): `_emit_artifacts` + `_emit_phase_outcome_events` + `_emit_failure_repair_events` -- runs for ALL remaining paths, INCLUDING before the terminal-failure check. Risk: failure-repair events are emitted on a path that may still be classified success (ordering fragility).
6. **`_handle_exit_approval_required` (implicit)** -- `result.status == "human_approval_required"` (line 673): open approval gate + emit `approval_required` + `stage_blocked_for_approval`, return.
7. **`_handle_exit_failure` (implicit)** -- `_is_terminal_failure_result` (line 752): diagnostic events + `stage_failed`, return.
8. **`_handle_exit_failure` (proof)** -- `not _has_success_proof` (line 786): `stage_failed` with proof detail, return.
9. **approval-card gate** (line 824, stages 1/2): blocked if unapproved, return.
10. **`_handle_exit_success` (implicit)** -- lines 849-904: `proof_updated` + `stage_completed`; stage 4 returns; stage 3 emits extra `stage_completed`; else emits `stage_report_*` then `_auto_queue_next_stage`.

**Report:** success and failure logic are interleaved. The shared `_emit_failure_repair_events` (step 5) sits ABOVE the failure classification (steps 7-8), so repair-context emission is order-coupled to the success branch. No refactor now; splitting into `_handle_exit_parse_failure`, `_handle_exit_process_failure`, `_handle_exit_approval_required`, `_handle_exit_failure`, `_handle_exit_success` is recommended later, behind tests.

---

## Event and Projection Audit

### Event scopes present
- **normal_stage**: `build_failed` (804, 806), `test_failed`, `stage_failed`, `proof_updated`, `stage_completed`.
- **repair_apply**: `repair_approve_apply_failed` (815), `repair_approve_apply_check_failed`, `repair_approve_patch_apply_failed`.
- **repair_validation**: `repair_validation_completed`, `repair_validation_passed`, `repair_validation_failed`.
- **repair_materialization**: `reviewed_repair_materialization_failed`, `repair_diff_ready_for_user_apply`, `repair_chain_started`.

### Does the frontend distinguish scopes?
- `ValidationProgressPanel` does **NOT** use events at all. It uses `RepairAttemptSummary` (`attempts`). The attempt carries `apply_status` and `rerun_status` but **no `reason_code`** in the summary shape consumed here (contracts.ts:1335 `RepairAttemptSummary` has `apply_status`, `rerun_status`, but the panel reads `attempt.rerun_status || attempt.status`). There is no field that tells the panel "this attempt failed at apply, not at validation."
- `RepairProposalPanel` DOES receive `reason_code` (from proposal projection) and has `isPatchApplyFailed`/`isApplyCheckFailed` (lines 405-406, 876) with correct copy at line 474. But the timeline sub-component (`ValidationProgressPanel`) is rendered alongside and ignores `reason_code`.

### Leakage risk
- The original-normal-stage `build_failed` events (804/806) are NOT leaked into the repair panel today (repair panel reads `attempts`). Safe.
- However, the **event taxonomy is too generic**: `build_failed`/`test_failed` do not carry a `scope` field. If a future panel aggregates events by type, it would conflate normal-stage and repair-validation failures. Recommend adding `scope = normal_stage | repair_apply | repair_validation` to these event payloads (non-breaking addition).

### Stage failure summary leaking into repair panel?
- `GET /stages` and `GET /failure-summary` derive from events + proposal. Because the repair proposal is `approve_failed` and the events are correctly scoped, the repair panel itself does not leak. The risk is only in the (incorrect) `phaseStatus` fallback, not in event scope.

---

## Direct Proposal Gate Audit (Q4 / Q5)

### Materialization rules (v2_repair_gate_service.py `create_reviewed_repair_gate_on_failure`)
- `direct_reviewed_diff` persisted via `_persist_direct_reviewed_repair_proposal` (line 1656). Persisted as-is, `status=user_review_required`, `gate_id=None`, `policy_status` later forced to `bypassed` (v2_repair_projection.py:599).
- `direct_candidate_diff` persisted via `_persist_direct_candidate_repair_proposal` (line 1779).
- **Parse:** `build_safe_diff_preview` produces `parse_status`. `_validate_direct_proposal_diff` (line 1612) requires `parse_status in {"parsed","hunk_count_mismatch"}`. If `parse_status` is `unparseable`/`no_content`, returns `(..., False, "parse_status_...")` and the proposal is NOT persisted (good).
- **Checksum:** `preview.checksum_mismatch` (line 1639) => rejected, not persisted (good).
- **Apply-check:** `check_patch_applicability` (git apply --check) runs at line 1642, but **ONLY when `direct_sandbox` is truthy** (guarded at line 390).
- **Direct sandbox required?** NOT effectively. If `direct_sandbox` is empty, the entire validation block (parse/checksum/applicability) is skipped and the proposal is still persisted (line 424). **HIGH-SEVERITY BUG**: a corrupt/unvalidated diff can reach the user. This is the most likely reason the job's corrupt patch (`patch_attempt_1_direct.diff:11`) was materialized.
- **Dangerous case confirmed:** `direct_sandbox` empty => validation skipped => proposal persisted. Mark **HIGH severity**.

### Canonicalization (Q5)
- `canonicalize_with_recount` (safe_diff_preview.py:579) uses `git apply --check --recount` then applies in a temp mirror and regenerates `git diff --binary` as the canonical diff.
- For **reviewed** diffs: on `hunk_count_mismatch`, if recount succeeds, `chain["final_diff_ref"]` is rewritten to `final_reviewed_repair_canonical.diff` (lines 1617-1625) and `chain["final_diff_canonicalized"]=True`. The persisted proposal then references the canonical ref. The safe preview is rebuilt from that ref. **Canonical diff IS persisted and previewed** for reviewed diffs. Consistent.
- For **candidate** diffs: `_validate_direct_candidate_diff` (line 1758) returns `False` immediately on `hunk_count_mismatch` -- candidates are NOT canonicalized, just rejected. Slight inconsistency between reviewed (canonicalize) and candidate (reject) behavior, but acceptable.
- **Gap:** the canonical checksum is stored on the chain (`canonical_checksum`) but the persisted `V2RepairProposalRecord.diff_checksum` is NOT updated to the canonical checksum (it stays the original `public_diff_checksum`, line 1679/1718). So the proposal's `diff_checksum` and the on-disk canonical diff can disagree. Low/medium severity; recommend storing canonical checksum on the record.
- Frontend shows only the diff referenced by `diff_ref`/`safe_diff_preview`; it does not know canonical vs original. Acceptable as long as backend persists canonical as `final_diff_ref`.

---

## Test Coverage Audit

### Existing (relevant)
- `tests/control_tower/test_v2_repair_approve_apply.py::test_apply_failure_persists_approve_failed` (line 1181): asserts `status==approve_failed`, `apply_status==REJECTED`, but does NOT assert `rerun_status`.
- `tests/control_tower/test_v2_repair_approve_apply.py::test_apply_failure_does_not_trigger_validation` (line 1236): asserts validation is NOT called for a failed apply (PATCH_APPLY_FAILED mock). **Backend behavior verified -- good.**
- `tests/control_tower/test_v2_repair_patch_apply.py`: unit tests for `apply_patch_to_sandbox` including `REASON_CODE_PATCH_APPLY_FAILED` (line 262/387). Good.
- `web/control-tower/tests/reviewedDiffProposal.test.tsx`: covers `approve_failed` apply/rerun rendering (lines 1275-1310) and validation passed/failed, but **does NOT cover the `ValidationProgressPanel` timeline for PATCH_APPLY_FAILED with empty `rerun_status`**.

### Missing
- No test asserting the timeline shows rebuild/test as NOT_STARTED (not FAILED) for PATCH_APPLY_FAILED.
- No test asserting no `repair_validation_*` event is emitted for PATCH_APPLY_FAILED.
- No test asserting no next repair cycle is created for PATCH_APPLY_FAILED.
- No test asserting APPLIED + rerun failed DOES create a next repair cycle (direct).
- No test for `ValidationProgressPanel` `phaseStatus` with `reason_code=PATCH_APPLY_FAILED`.
- No test for the direct-materialization `direct_sandbox` empty skip bug (should be rejected, not persisted).
- No test for canonical checksum propagation to `V2RepairProposalRecord.diff_checksum`.

---

## Minimum Safe Fix Plan

### Phase 1: Tests only (no behavior change)
Add backend + frontend tests that LOCK current correct behavior and expose the UI bug:
- `test_patch_apply_failed_timeline_marks_rebuild_not_started`
- `test_patch_apply_failed_timeline_marks_tests_not_started`
- `test_patch_apply_failed_current_proposal_read_only`
- `test_patch_apply_failed_does_not_emit_repair_validation_failed`
- `test_patch_apply_failed_does_not_create_next_java_repair_cycle`
- `test_applied_rerun_failed_creates_next_repair_cycle`
- `test_direct_hunk_count_mismatch_not_actionable_before_approval`
- `test_direct_canonicalized_diff_is_persisted_and_previewed`
- `test_normal_success_does_not_enter_repair_loop`
- `test_normal_build_test_success_emits_correct_event_sequence`
- `test_frontend_repair_panel_distinguishes_patch_apply_failed_from_validation_failed`

### Phase 2: UI state fix for PATCH_APPLY_FAILED (frontend only)
In `ValidationProgressPanel.phaseStatus`:
- Derive `rebuild`/`test`/`continue` phases **only** from `rerun_status` (and `next_gate_status`), never from `attempt.status`.
- Add a `reason_code`/`proposalStatus` parameter; if `reason_code === "PATCH_APPLY_FAILED" || "PATCH_CHECK_FAILED"`, force rebuild/test => "not started" and continue => "blocked (new proposal required)".
- Keep `apply` phase driven by `apply_status`/`attempt.status`.
- This makes the panel match the correct state machine without touching backend.

### Phase 3: Backend projection hardening
- Ensure `rerun_status` is ALWAYS explicitly set for terminal apply failures (already `"not_started"` in current repo; add a test to lock it and backfill live data).
- Add `reason_code` to `RepairAttemptSummary` contract so the timeline can branch without guessing from `status`.

### Phase 4: Direct materialization gate hardening (HIGH severity)
- In `v2_repair_gate_service.py`, require `direct_sandbox` to be non-empty; if empty, emit `reviewed_repair_materialization_failed` with `reason_code="direct_sandbox_missing"` and DO NOT persist the proposal.
- Make the direct apply path (`apply_patch_to_sandbox_direct`) run `git apply --check` (or reuse `check_patch_applicability`) before `git apply`, OR guarantee materialization-time applicability already validated (it is skipped when sandbox empty -- close that gap).
- Persist canonical checksum into `V2RepairProposalRecord.diff_checksum` when canonicalization occurs.

### Phase 5: Optional `_handle_exit` split (after tests)
Split into `_handle_exit_parse_failure`, `_handle_exit_process_failure`, `_handle_exit_approval_required`, `_handle_exit_failure`, `_handle_exit_success`. Low risk once Phase 1 tests exist.

---

## Concrete Test Plan (exact names)

Backend (pytest):
- `test_patch_apply_failed_timeline_marks_rebuild_not_started`
- `test_patch_apply_failed_timeline_marks_tests_not_started`
- `test_patch_apply_failed_current_proposal_read_only`
- `test_patch_apply_failed_does_not_emit_repair_validation_failed`
- `test_patch_apply_failed_does_not_create_next_java_repair_cycle`
- `test_applied_rerun_failed_creates_next_repair_cycle`
- `test_direct_hunk_count_mismatch_not_actionable_before_approval`
- `test_direct_canonicalized_diff_is_persisted_and_previewed`
- `test_normal_success_does_not_enter_repair_loop`
- `test_normal_build_test_success_emits_correct_event_sequence`

Frontend (vitest/react-testing-library):
- `test_frontend_repair_panel_distinguishes_patch_apply_failed_from_validation_failed`

---

## Commands Run

Safe, read-only / verification only:
- `Invoke-RestMethod .../repair/proposals/current` (job 4a587211...) -> captured status/apply_status/rerun_status/reason_code/allowed_actions.
- `Invoke-RestMethod .../repair/attempts` -> attempt status/apply_status/rerun_status.
- `Invoke-RestMethod .../migration-jobs/{job}/events/snapshot?after=0` -> event sequence (repair-relevant filtered).
- py_compile of: v2_repair_flow.py, v2_repair_gate_service.py, v2_repair_projection.py, safe_diff_preview.py, patch_apply.py, app.py, v2_orchestrator_runner.py -> all passed.
- `pytest tests/control_tower/test_v2_repair_approve_apply.py tests/control_tower/test_v2_repair_patch_apply.py --collect-only` -> 58 tests collected, passed collection.
- (npm run type-check in web/control-tower NOT executed in this environment due to time; the defective component is `ValidationProgressPanel.tsx`.)

No destructive commands, no full migration, no external APIs, no LLM calls.

---

## Final Recommendation

**Next concrete coding task:** Implement Phase 1 + Phase 2.

1. Add the 11 tests listed above (backend pytest + 1 frontend vitest). The frontend test `test_frontend_repair_panel_distinguishes_patch_apply_failed_from_validation_failed` will FAIL on current code, documenting the bug.
2. Fix `ValidationProgressPanel.phaseStatus` so rebuild/test/continue are derived from `rerun_status` + a new `reason_code`/`proposalStatus` argument, never from `attempt.status`. For `PATCH_APPLY_FAILED`/`PATCH_CHECK_FAILED`, force rebuild/test = "not started" and continue = "blocked (new proposal required)".
3. Do NOT merge normal and repair flows, do NOT rewrite LangGraph, do NOT change product behavior for APPLIED+rerun states.

Defer Phase 4 (direct sandbox empty skip) as a separate HIGH-severity fix with its own tests, because it changes materialization gating and must be validated independently.

The reported symptom ("Rebuilding FAILED / Running tests VALIDATION FAILED / Migration continuing BLOCKED") is a **frontend timeline-derivation defect**, not a backend validation-red bug. The backend correctly avoided rebuild/test for PATCH_APPLY_FAILED.
