# AMF-252 Problem B Backend Projection Audit

## Executive Summary
Problem B is a backend projection mismatch across two UI sections:

1. `Failure Evidence` should represent the original stage/build/transform failure that caused repair to start.
2. `Reviewed Repair Gate` should represent the current repair gate state, including whether a reviewed diff exists and can be approved.

The canonical backend sources are already mostly split correctly:
- `GET /v1/v2/migration-jobs/{job_id}/failure-summary` is the evidence/history surface.
- `GET /v1/v2/jobs/{job_id}/repair/proposals/current` is the current gate-state surface.

The confusion comes from two backend projections:
- `failure-summary` mixes original failure evidence with repair-loop events and has no scope separation.
- `pipeline` still reduces `failure_repair` as if it is running, because it only knows about `repair_started` / `repair_fallback_generated` / `repair_completed`, not `reviewed_repair_materialization_failed` or `retry_required`.

For job `c929857bcd0142e89898a4cf43cbe464`, the backend gate state is already canonical:
- `proposal = null`
- `unavailable.kind = materialization_failed`
- `reason_code = MALFORMED_DIFF`
- `allowed_actions` are read-only only
- `repair_attempts = []`

The backend should keep that gate source authoritative, then make the surrounding evidence and pipeline projections stop implying that a valid apply path still exists.

## Backend Endpoint Map

| Endpoint | Route/function | File | Response fields used | Frontend section | Current issue | Recommended action |
|---|---|---|---|---|---|---|
| `GET /v1/v2/migration-jobs/{job_id}/failure-summary` | `get_v2_job_failure_summary()` -> `_v2_failure_summary()` | `migration_factory/control_tower/adapters/fastapi/app.py` | `failures`, `repair_loop_active`, `repair_events`, `artifact_kinds`; per-failure `repair_loop_status`, `repair_fallback`, `event_types`, `repair_events`, `supervision_trace` | `Failure Evidence` | It merges original failure and repair history into one payload with no scope metadata, so repair-blocker data can be rendered like original failure evidence | Keep as evidence/history, but add scope/blocker metadata if needed and stop the frontend from treating repair-loop data as the original failure |
| `GET /v1/v2/jobs/{job_id}/repair/proposals/current` | `get_current_repair_proposal()` | `migration_factory/control_tower/adapters/fastapi/app.py` | `proposal`, `unavailable`, `job_id`; `unavailable` includes `kind`, `title`, `reason_code`, `allowed_actions`, `retry_status`, `retry_reason`, `next_action`, `proposal_created`, `gate_created`, `reviewer_*`, `backend_*` | `Reviewed Repair Gate` | This endpoint is already the canonical gate source, but the UI must treat `materialization_failed` as final read-only state | Keep canonical; do not synthesize approve/apply locally |
| `GET /v1/v2/jobs/{job_id}/repair/attempts` | `list_repair_attempts()` -> `record_to_attempt_summary()` | `migration_factory/control_tower/adapters/fastapi/app.py` and `migration_factory/control_tower/application/v2_repair_projection.py` | `attempts[]` with safe attempt summaries | `Reviewed Repair Gate` / validation timeline | For this job it is empty, which is correct because no apply happened; any timeline rendered from this would be invented | Keep empty when no apply attempt exists |
| `GET /v1/v2/jobs/{job_id}/llm/activity` | `list_v2_llm_activity()` | `migration_factory/control_tower/adapters/fastapi/app.py` | `invocations`, `job_id` | `Reviewed Repair Gate` model trace | Model completion is not a proxy for materialization success or apply readiness | Keep as trace only; do not infer apply readiness |
| `GET /v1/v2/migration-jobs/{job_id}/pipeline` | `get_v2_job_pipeline()` -> `_v2_pipeline_projection()` -> `_pipeline_row_status()` | `migration_factory/control_tower/adapters/fastapi/app.py` | `rows`, `evidence`, `raw_logs`, `active_stage_index` | Pipeline/status rows | `failure_repair` can still appear `running` because the reducer does not consume reviewed materialization failure or retry-required state | Update projection so the row becomes blocked/retry-required after `materialization_failed` |
| `GET /v1/v2/migration-jobs/{job_id}/events/snapshot` | `get_v2_job_event_snapshot()` | `migration_factory/control_tower/adapters/fastapi/app.py` | `events`, `after`, `latest_sequence` | Historical debug/fallback data | It is raw history, not current gate truth; the UI should not derive current approval state from it | Keep historical only |

## Current Job Evidence

For `c929857bcd0142e89898a4cf43cbe464`:
- Original stage/build failure was `BUILD_FAILED_IN_SANDBOX`.
- Repair chain started.
- Main model completed.
- Reviewer completed and accepted the repair.
- Backend rejected the reviewed diff before approval.
- `proposal = null`.
- `unavailable.kind = materialization_failed`.
- `unavailable.title = Reviewed Repair Diff Invalid`.
- `reason_code = MALFORMED_DIFF`.
- `detail` reports `git apply --check --recount` failed with `warning: recount: unexpected line: ?` and `error: corrupt patch`.
- `proposal_created = false`.
- `gate_created = false`.
- `policy_ran = false`.
- `repair_attempts = []`.
- Allowed actions are read/view only.
- No approve action exists.
- No apply happened.
- No rebuild/test validation happened.
- Pipeline may still show `failure_repair.status = running`.
- `failure_summary` includes both the original build failure and `reviewed_repair_materialization_failed`.
- `events` include `reviewed_repair_materialization_failed`, `retry_required`, and `stage_failed`.
- Stage 1 is failed.

## Failure Evidence Backend Analysis

### Route and function
- Route: `GET /v1/v2/migration-jobs/{job_id}/failure-summary`
- Function: `get_v2_job_failure_summary()` at `app.py:2353`
- Builder: `_v2_failure_summary()` at `app.py:13789`

### Response shape
`get_v2_job_failure_summary()` returns:
- `job_id`
- `has_failures`
- `failures`
- `repair_loop_active`
- `repair_events`
- `artifact_kinds`

Each failure item includes:
- `type`
- `stage`
- `title`
- `message`
- `build_status`
- `test_status`
- `final_status`
- `final_proof_level`
- `repair_loop_status`
- `repair_fallback`
- diagnostics like `matched_line`, `command`, `build_tool`, `result_kind`, `stdout_tail`, `stderr_tail`
- `event_types`
- `repair_events`
- `next_operator_action`
- `supervision_trace`

### How failures are collected
`_v2_failure_summary()`:
- Collects terminal failed events that are not repair events.
- Groups them by `(stage, primary_key)`.
- Merges repair events for the same stage into the failure payload.

### How repair events are collected
- `repair_events_typed` is every event whose type is in `_REPAIR_EVENT_TYPES`.
- Stage repair events are attached both to per-failure payloads and to the top-level `repair_events` list when ungrouped.

### How `repair_loop_active` is computed
- It is `len(repair_events_typed) > 0`.
- That means any repair history turns the summary into "repair loop active" even when the active blocker is actually a terminal materialization failure.

### Scope problem
There is no scope field distinguishing:
- original stage/build failure
- repair materialization failure

That is the core reason the frontend can over-read the summary as one active failure state.

### Audit conclusion
`failure-summary` is correct as an evidence/history payload, but it is too coarse for a UI that wants to separate "why repair started" from "why reviewed repair is unavailable".

## Reviewed Repair Gate Backend Analysis

### Route and function
- Route: `GET /v1/v2/jobs/{job_id}/repair/proposals/current`
- Function: `get_current_repair_proposal()` at `app.py:4068`

### Canonical behavior
The route does the right high-level thing:
- If there is no current proposal record, it returns:
  - `proposal = None`
  - `job_id`
  - `unavailable = _latest_repair_materialization_unavailable(uow, job_id)`
- If there is a proposal record, it builds a safe reviewed-diff proposal from the persisted record and safe preview logic.

### Unavailable projection source
The unavailable object comes from `_latest_repair_materialization_unavailable()` at `app.py:783`.

That helper:
- Scans events for `reviewed_repair_materialization_failed`, `reviewed_repair_unavailable`, and `repair_primary_schema_invalid`.
- Chooses the best candidate by reason/detail score.
- Builds a `kind = "materialization_failed"` payload.

### Key unavailable fields
The payload already includes:
- `kind`
- `title`
- `reason_code`
- `detail`
- `message`
- `final_diff_exists`
- `policy_ran`
- `gate_created`
- `proposal_created`
- `allowed_actions`
- `retry_status`
- `retry_reason`
- `next_action`
- `reviewer_*`
- `reviewer_self_repair_*`
- `reviewer_applicability_repair_*`
- `backend_import_replacement_fallback_*`
- `backend_generated_diff_*`

### Approval gating
`_unavailable_allowed_actions()` only returns read/view actions:
- `view_diff` if `final_diff_exists`
- `view_reviewer_opinion`
- `view_files_changed`
- `ask_explanation`
- `view_attempt_history`

It does not add `approve_sandbox_apply`.

### Retry signaling
- `_retry_status()` returns `retry_required` when `reason_code == "MALFORMED_DIFF"`.
- `_next_action_for_unavailable()` returns "Backend retry required; no approve action available." for `MALFORMED_DIFF`.

### Audit conclusion
`/repair/proposals/current` is already the canonical backend source of truth for the Reviewed Repair Gate. The backend bug is not here; it is in adjacent projections that still imply a running repair path or mix repair blocker state into evidence/history.

## Repair Attempts Backend Analysis

### Route and function
- Route: `GET /v1/v2/jobs/{job_id}/repair/attempts`
- Function: `list_repair_attempts()` at `app.py:4339`
- Serializer: `record_to_attempt_summary()` at `v2_repair_projection.py:653`

### Data source
The route returns:
- `attempts: [record_to_attempt_summary(r) for r in uow.v2_repairs.list_attempts_by_job(job_id)]`

### Why `attempts = []` here
For this job, the reviewed diff never became an approved/applied attempt.
That is correct because:
- the diff was malformed during backend materialization
- no apply happened
- no rebuild/test happened

### Audit conclusion
The backend should not invent attempt history from failed review or materialization events. Empty attempts is the correct payload for this class of failure.

## LLM Activity Backend Analysis

### Route and function
- Route: `GET /v1/v2/jobs/{job_id}/llm/activity`
- Function: `list_v2_llm_activity()` at `app.py:5669`

### Response shape
Returns:
- `invocations`
- `job_id`

### Meaning
This is a trace of model activity only.
It can show:
- main model completed
- reviewer completed

It cannot be used as evidence that a reviewed diff exists or is apply-ready.

### Audit conclusion
Keep this endpoint as a trace. Do not couple it to materialization success.

## Pipeline Backend Analysis

### Route and function
- Route: `GET /v1/v2/migration-jobs/{job_id}/pipeline`
- Function: `get_v2_job_pipeline()` at `app.py:2340`
- Projection builder: `_v2_pipeline_projection()` at `app.py:13518`
- Row reducer: `_pipeline_row_status()` at `app.py:13593`

### Current row logic
The phase list includes:
- `failure_repair` with only:
  - `repair_started`
  - `repair_fallback_generated`
  - `repair_completed`

The row reducer is generic:
- `failed` if any matching event is failed
- `blocked` if latest status is blocked
- `running` if latest status is running or latest type ends with `_started`
- `pass` if any matching event completed

### Why `failure_repair` can still say `running`
Because `reviewed_repair_materialization_failed` and `retry_required` are not part of the `failure_repair` phase list.

So if the phase has a prior `repair_started` event and no later event in that same phase, the row stays `running` even though the reviewed diff is already invalid.

### Why the reducer ignores the actual blocker
The pipeline projection reads event types, not the current gate projection.
It does not consult:
- `reviewed_repair_materialization_failed`
- `retry_required`
- `repair/proposals/current`

### Safest backend fix
The safest backend fix is to keep the pipeline projection event-based, but teach it to treat materialization failure as a blocker for the `failure_repair` row.

Recommended logic:
```text
if latest reviewed repair state indicates materialization_failed:
    failure_repair.status = blocked
    failure_repair.latest_message = unavailable.next_action or
        "Reviewed repair diff invalid; backend retry required."
    failure_repair.blocker_reason_code = unavailable.reason_code
```

If staying strictly event-based:
```text
if latest event type is reviewed_repair_materialization_failed or retry_required:
    failure_repair.status = blocked or retry_required
```

### Preferred choice
Prefer the current repair-gate projection as the source of truth if a lightweight helper can read it without duplicating apply logic. If not, the event-based blocker check is still safer than leaving the row as `running`.

## Event Snapshot Backend Analysis

### Route and function
- Route: `GET /v1/v2/migration-jobs/{job_id}/events/snapshot`
- Function: `get_v2_job_event_snapshot()` at `app.py:2319`

### Response shape
- `job_id`
- `after`
- `events`
- `latest_sequence`

### Meaning
This is historical event data only.
It can include:
- `reviewed_repair_materialization_failed`
- `retry_required`
- `stage_failed`

But it is not the canonical current gate source.

### Audit conclusion
Leave this endpoint as raw history. If scope metadata is needed, add it to the event payloads or a projection, not by redefining the snapshot as current state.

## v2_repair_projection.py Analysis

### Relevant types and functions
- `READ_ONLY_REPAIR_ACTIONS` at `v2_repair_projection.py:198`
- `ReviewedDiffProposal` at `v2_repair_projection.py:227`
- `build_reviewed_diff_proposal_projection()` at `v2_repair_projection.py:269`
- `build_reviewed_diff_proposal_from_record()` at `v2_repair_projection.py:518`
- `record_to_attempt_summary()` at `v2_repair_projection.py:653`

### What this file does
This module builds safe reviewed-proposal projections and attempt summaries.
It is not where unavailable/materialization-failed state is constructed.

### Current behavior relevant to Problem B
- Reviewed proposal projections include `allowed_actions` and `reason_code`.
- `build_reviewed_diff_proposal_from_record()` uses `build_safe_diff_preview()`.
- `allowed_actions` defaults to `READ_ONLY_REPAIR_ACTIONS`.
- `record_to_attempt_summary()` serializes attempt records safely.

### What it does not do
- It does not add scope metadata to failure-summary.
- It does not define `materialization_failed` unavailable payloads.
- It does not own the pipeline row logic.

### Audit conclusion
This file is mostly fine for the Reviewed Repair Gate projection. The missing state needed for Problem B is in `app.py` projections and, if needed, a small extension to the safe projection shape.

## Backend Conflicts Found

| Conflict | Backend source | Frontend impact | Severity | Recommended fix |
|---|---|---|---|---|
| `failure-summary` mixes original failure and repair-loop history | `_v2_failure_summary()` | `Failure Evidence` can look like the active repair blocker | Medium | Add scope/blocker labeling, or split rendering by scope |
| `failure_repair` still looks running | `_v2_pipeline_projection()` / `_PIPELINE_PHASES` / `_pipeline_row_status()` | Pipeline/status row contradicts `materialization_failed` gate state | High | Mark as blocked/retry-required when reviewed materialization failed |
| Canonical gate state is correct but other projections ignore it | `get_current_repair_proposal()` vs pipeline/failure-summary | UI shows inconsistent active state | High | Keep `/repair/proposals/current` canonical and update projections around it |
| `repair_attempts` is empty but the UI could still show a timeline | `list_repair_attempts()` + frontend consumers | Invented apply/rebuild/test path | Medium | Keep attempts empty and condition UI on attempts data |
| LLM completion is over-read as apply readiness | `list_v2_llm_activity()` | Gate feels ready when it is not | Low | Keep trace wording separate from materialization state |

## Recommended Backend Changes

Priority order:
1. Fix `/pipeline` so `failure_repair` is blocked or retry-required after `reviewed_repair_materialization_failed` / `retry_required`.
2. Optionally add scope metadata to `failure-summary` so original failure and repair materialization failure do not look like the same active failure.
3. Keep `/repair/proposals/current` canonical.
4. Keep `/repair/attempts` empty when no apply attempt exists.
5. Add only minimal fields if the UI needs explicit blocker labeling.

### Proposed pipeline pseudo-code
Preferred event-based version:
```text
if any event type in {"reviewed_repair_materialization_failed", "retry_required"}:
    failure_repair.status = "blocked"
    failure_repair.latest_message = "Reviewed repair diff invalid; backend retry required."
    failure_repair.blocker_reason_code = "MALFORMED_DIFF"
```

If you can safely read the current gate projection without duplicating logic:
```text
if current.unavailable.kind == "materialization_failed":
    failure_repair.status = "blocked"
    failure_repair.latest_message = current.unavailable.next_action or "Reviewed repair diff invalid; backend retry required."
    failure_repair.blocker_reason_code = current.unavailable.reason_code
```

### Safer choice
The event-based check is safer for a minimal backend change because it stays within the current pipeline projection model and does not pull approval/apply logic into the row reducer.

## Files To Change

Likely:
- `migration_factory/control_tower/adapters/fastapi/app.py`

Possibly:
- `migration_factory/control_tower/application/v2_repair_projection.py`
- `web/control-tower/lib/contracts.ts` only if the backend contract needs new fields for scope or blocker labeling

## Files Not To Change

- `migration_factory/repair_loop/patch_apply.py`
- `migration_factory/repair_loop/validation_runner.py`
- `migration_factory/agents/build_agent/agent.py`
- `migration_factory/agents/test_agent/agent.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` unless only reading
- `_handle_exit`
- LangGraph/orchestrator code
- normal migration flow
- any apply/rebuild/test execution path

## Implementation Plan Without Tests

1. Map the backend route/functions and confirm the current data flow.
2. Update pipeline projection so `failure_repair` becomes blocked or retry-required once the reviewed diff is materialization-failed.
3. Optionally add failure scope metadata to `failure-summary`.
4. Keep `/repair/proposals/current` as the canonical gate source.
5. Keep `/repair/attempts` empty when no apply attempt exists.
6. Keep `/llm/activity` as trace only.
7. Verify with safe reads only.

## Acceptance Criteria

- `/repair/proposals/current` remains canonical for Reviewed Repair Gate.
- `/failure-summary` remains evidence/history, not current gate state.
- `/repair/attempts` remains `[]` when no apply attempt happened.
- `/llm/activity` does not imply apply-ready.
- `/pipeline` no longer shows `failure_repair` running after `materialization_failed` / `retry_required`.
- No approve action is exposed for malformed diff.
- No apply/rebuild/test path is changed.
- No normal migration flow is changed.

## Safe Verification Commands

Allowed:
- `python -m py_compile` on touched Python files
- `git diff`
- `git status`
- manual API calls with `Invoke-RestMethod`

Example manual checks:
```powershell
$Job = "c929857bcd0142e89898a4cf43cbe464"
$Port = "8000"

(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/failure-summary") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/proposals/current") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/attempts") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/llm/activity") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/pipeline") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/events/snapshot?after=0") | ConvertTo-Json -Depth 80
```

Not allowed:
- `pytest`
- `npm test`
- `vitest`
- full migration
- external APIs
- real LLM calls

