# AMF-252 Problem B UI/Backend Cleanup Handoff

## Summary
Problem B was cleaned up so the two surfaces stay separate:
- Failure Evidence now stays focused on the original build/transform failure and its historical evidence.
- Reviewed Repair Gate now owns the current reviewed-diff / materialization / approval state.
- Old repair-running leakage was removed from the failure evidence projection and the pipeline projection now stops showing `failure_repair` as running after a materialization blocker.

## Files Changed
- `migration_factory/control_tower/adapters/fastapi/app.py` - split failure evidence from reviewed repair blocker state and blocked the `failure_repair` pipeline row on reviewed repair materialization failures.
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` - separated original failure evidence from reviewed repair blocker rendering and stopped treating repair history as active state.
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` - removed the validation timeline from the materialization-failed no-proposal branch, guarded validation rendering behind real attempts, and passed allowed actions through to the actions bar.
- `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx` - made actions rendering depend on allowed actions, with backwards-compatible fallback behavior for existing callers.
- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx` - made the panel no-op when there are no real apply/validation attempts.
- `web/control-tower/lib/contracts.ts` - added the failure-summary blocker fields needed by the frontend (`reason_code`, `detail`).

## Backend Changes
- `GET /v1/v2/jobs/{job_id}/repair/proposals/current` remains canonical for the reviewed repair gate.
- Materialization failure still returns `proposal = null` with `unavailable.kind = materialization_failed`.
- Allowed actions remain read-only only for materialization failure; no approve action was added.
- `GET /v1/v2/migration-jobs/{job_id}/pipeline` now treats reviewed repair materialization events as a blocker for `failure_repair`, so the row no longer stays `running` after the gate is blocked.
- `GET /v1/v2/migration-jobs/{job_id}/failure-summary` now keeps original stage/build/transform failure evidence separate from the reviewed repair materialization blocker.
- `repair_loop_active` is no longer treated as active just because repair history exists when a materialization blocker is present.
- Unchanged: approval/apply execution paths, rebuild/test execution paths, and the repair proposal canonical read path.

## Frontend Changes
- Failure Evidence in `MigrationCockpit.tsx` now renders:
  - original failure evidence first,
  - a separate `Repair materialization blocker` subsection for reviewed repair materialization failures,
  - repair history as historical evidence instead of active repair state.
- Reviewed Repair Gate in `RepairProposalPanel.tsx` now:
  - renders the materialization-failed branch as read-only,
  - shows the backend diagnostic and allowed actions,
  - does not render `ValidationProgressPanel` for `proposal = null` with `materialization_failed`,
  - only renders validation progress when there are real attempts.
- `RepairActionsBar.tsx` now uses allowed actions as the source of truth when they are provided, and it no longer synthesizes `approve_sandbox_apply` for the reviewed gate branch.
- `ValidationProgressPanel.tsx` now returns `null` when there are no attempts, which prevents timeline synthesis from failure-summary state.

## Old Branches Removed/Bypassed
| File / Function / Component | Old behavior | New behavior | Action |
|---|---|---|---|
| `migration_factory/control_tower/adapters/fastapi/app.py` `_v2_pipeline_projection()` | `failure_repair` could remain `running` after reviewed repair materialization failure | `failure_repair` becomes `blocked` with the blocker message | Bypass |
| `migration_factory/control_tower/adapters/fastapi/app.py` `_v2_failure_summary()` | Repair history could be merged into the original failure card and active repair state implied by repair history alone | Original failure stays original; reviewed repair blocker is emitted separately | Remove / bypass |
| `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` Failure Evidence section | Rendered failure summary as one mixed blob and treated repair history like active repair state | Original evidence and repair blocker are separated; repair history is historical only | Remove / bypass |
| `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` materialization-failed branch | Rendered `ValidationProgressPanel` even with no attempts | No validation timeline for `proposal = null` + `materialization_failed` | Remove |
| `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` proposal branch | Validation timeline rendered regardless of whether attempts existed | Validation timeline renders only with real attempts | Bypass |
| `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx` | Could synthesize approve/revision visibility from local booleans | Uses allowed actions when provided; legacy fallback retained for compatibility | Bypass |
| `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx` | Could render a timeline for empty attempts | Returns `null` for empty attempts | Remove |

## Behavior Matrix
| Scenario | Failure Evidence | Reviewed Repair Gate | Pipeline `failure_repair` | Actions |
|---|---|---|---|---|
| Original build failure only | Shows original build/transform failure evidence and artifacts | No reviewed diff yet | Not running / pending based on normal pipeline state | Historical read actions only |
| Repair chain running | Shows original failure evidence plus repair history as historical evidence | Reviewed gate may exist if proposal is ready | Can still show `running` before materialization blocker arrives | Gate actions depend on proposal state |
| `materialization_failed` / `MALFORMED_DIFF` | Shows original failure evidence and a separate reviewed repair blocker subsection | `proposal = null`, `unavailable.kind = materialization_failed` | `blocked` | Read-only only |
| Proposal exists, no attempt yet | Shows original failure evidence only | Proposal card renders, but no validation timeline | Normal pipeline state | Proposal actions from `allowed_actions` |
| Apply attempt exists | Original failure evidence remains historical | Validation timeline renders from real attempts | Normal pipeline state | Apply/rebuild/test history visible |
| `PATCH_APPLY_FAILED` | Original failure evidence remains historical | Read-only failure state after apply failure | Not rebuilt by this cleanup | No rebuild/test synthesis |
| `APPLIED + rerun failed` | Original failure evidence remains historical | Validation timeline shows real rerun failure | Normal pipeline state | Failure/validation history visible |
| `APPLIED + rerun passed` | Original failure evidence remains historical | Validation timeline shows passed rerun | Normal pipeline state | Approve/apply history visible |

## What Was Not Changed
- No apply/rebuild/test execution path changes.
- No `patch_apply.py` changes.
- No `run_validation_after_patch` changes.
- No `_handle_exit` refactor.
- No LangGraph rewrite.
- No normal migration flow changes.
- No tests added or edited.

## Verification Run
- `py -3 -m py_compile migration_factory/control_tower/adapters/fastapi/app.py` succeeded.
- `npm run type-check` in `web/control-tower` succeeded.
- `git diff --stat` showed the intended backend/frontend edits only in the touched files.
- `git status --short` still showed unrelated pre-existing workspace changes in `migration_factory/control_tower/application/v2_repair_gate_service.py` and `migration_factory/repair_loop/patch_apply.py`; those were not modified by this cleanup.

## Manual API Checks
Commands to run against the local server:

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

Expected results for the current job:
- `/repair/proposals/current`: `proposal = null`, `unavailable.kind = materialization_failed`, `reason_code = MALFORMED_DIFF`, no `approve_sandbox_apply`.
- `/repair/attempts`: `attempts = []`.
- `/pipeline`: `failure_repair.status` is `blocked` or `retry_required`, not `running`.
- `/failure-summary`: original build failure remains visible, reviewed repair materialization failure is scoped as blocker/history rather than original failure.
