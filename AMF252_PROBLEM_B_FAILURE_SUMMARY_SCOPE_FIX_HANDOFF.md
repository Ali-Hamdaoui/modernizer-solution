# AMF-252 Problem B Failure Summary Scope Fix Handoff

## File Changed
- `migration_factory/control_tower/adapters/fastapi/app.py`

## Fixed Branch
- `_v2_failure_summary()` no longer groups `reviewed_repair_materialization_failed` into the original stage-failure bucket.
- The blocker is only represented by the dedicated repair-materialization row path.

## Before / After
- Before: `reviewed_repair_materialization_failed` could appear as `scope = original_stage_failure` with a stage-failure title/message.
- After: original stage/build/transform failures remain under `scope = original_stage_failure`, while the repair blocker is kept under `scope = repair_materialization_failure`.

## Behavior Now
- Original build failure remains visible as `build_failed` with `scope = original_stage_failure`.
- Repair materialization blocker remains visible as `retry_required` with `scope = repair_materialization_failure`, `reason_code = MALFORMED_DIFF`, `repair_loop_status = blocked`, and `next_operator_action = Backend retry required; no approve action available.`
- `repair_loop_active` stays `false`.
- Top-level `repair_events` stays empty for this blocked materialization state.

## Verification
- `py -3 -m py_compile migration_factory/control_tower/adapters/fastapi/app.py` passed.
- Synthetic reducer validation passed in-process:
  - `build_failed original_stage_failure`
  - `retry_required repair_materialization_failure Reviewed Repair Diff Invalid blocked MALFORMED_DIFF Backend retry required; no approve action available.`
- No frontend files were changed in this follow-up, so `npm run type-check` was not needed.

## Unchanged Paths
- No apply/rebuild/test execution paths were changed.
- No `patch_apply.py` changes.
- No `run_validation_after_patch` changes.
- No `run_build_agent` or `run_test_agent` changes.
- No `_handle_exit` refactor.
- No LangGraph rewrite.
- No soft materialization recovery changes.
