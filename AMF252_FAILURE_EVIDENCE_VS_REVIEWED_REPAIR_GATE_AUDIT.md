# AMF-252 Failure Evidence vs Reviewed Repair Gate Audit

## Executive Summary
The page is currently mixing two different scopes of failure.

`Failure Evidence` should explain why the migration needed repair in the first place. That is the original stage/build failure plus the evidence pack and related events.

`Reviewed Repair Gate` should explain the current repair-chain state after the reviewer accepted a patch. In this job, backend materialization failed before approval because the reviewed diff was malformed, so there is no apply path, no validation timeline, and no approve action.

The current UI mostly has the right separation, but two leaks remain:
1. `MigrationCockpit.tsx` shows repair-loop state and repair events inside `Failure Evidence`, which blurs original failure and repair-blocker state.
2. `RepairProposalPanel.tsx` renders a validation panel even for `materialization_failed`, which makes the gate look more active than it is.

The backend also contributes to the confusion because pipeline projection still treats `failure_repair` like a running phase after `reviewed_repair_materialization_failed`, instead of showing that repair is blocked by an invalid reviewed diff.

## UI Component Map

| Section | Component file | Props/data | Endpoint/API source | Current behavior | Required behavior |
|---|---|---|---|---|---|
| Failure Evidence | `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` | `data.failureSummary`, `data.eventsSnapshot`, `data.repairContextPack`, related failure artifacts | `GET /v1/v2/migration-jobs/{job_id}/failure-summary`, plus supporting snapshot/artifact data | Renders original failure list, but also includes `repair_loop_active` and `repair_events`, so repair-blocker data leaks into the original failure section | Show only original stage/build failure evidence, or clearly separate repair materialization failure into its own sub-block |
| Reviewed Repair Gate | `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` | `proposalState`, `proposal`, `unavailable`, `allowed_actions`, `llm_activity`, attempts | `GET /v1/v2/jobs/{job_id}/repair/proposals/current`, `GET /v1/v2/jobs/{job_id}/llm/activity`, `GET /v1/v2/jobs/{job_id}/repair/attempts` | Correctly shows `Reviewed Repair Diff Invalid` for `materialization_failed`, but still renders a validation panel with `attempts={[]}` | Show unavailable/read-only state only; no validation timeline and no synthetic apply path when no valid reviewed diff exists |

Notes:
- There is no separate `FailureEvidencePanel.tsx` in the current tree; the failure section is inline in `MigrationCockpit.tsx`.
- `page.tsx` is only a thin wrapper that renders `MigrationCockpit`.

## Backend Endpoint Map

| Endpoint | Function/file | Payload fields used | UI consumer | Current issue |
|---|---|---|---|---|
| `GET /v1/v2/migration-jobs/{job_id}/failure-summary` | `migration_factory/control_tower/adapters/fastapi/app.py` | `failures`, `repair_events`, `repair_loop_active` | Failure Evidence | It combines original failure and repair history into one payload, which is useful for evidence but easy to over-render as a single active failure |
| `GET /v1/v2/jobs/{job_id}/repair/proposals/current` | `migration_factory/control_tower/adapters/fastapi/app.py` | `proposal`, `unavailable`, `proposal_created`, `gate_created`, `reason_code`, `allowed_actions` | Reviewed Repair Gate | This is the canonical gate-state source, but the frontend must honor `unavailable.kind=materialization_failed` as final for approval gating |
| `GET /v1/v2/jobs/{job_id}/repair/attempts` | `migration_factory/control_tower/adapters/fastapi/app.py` | attempt list | Reviewed Repair Gate | For this job it is empty, so any validation or apply timeline is invented if shown |
| `GET /v1/v2/jobs/{job_id}/llm/activity` | `migration_factory/control_tower/adapters/fastapi/app.py` | model trace/activity | Reviewed Repair Gate | Useful for showing main/reviewer completion, but not evidence of apply readiness |
| `GET /v1/v2/migration-jobs/{job_id}/pipeline` | `migration_factory/control_tower/adapters/fastapi/app.py` | phase rows and status | Pipeline/status UI inside the page | `failure_repair` can still look `running` because the pipeline projection does not consume `reviewed_repair_materialization_failed` or `retry_required` |

## Evidence From Current Job

- Current proposal is `null`.
- `unavailable.kind = materialization_failed`.
- `unavailable.title = Reviewed Repair Diff Invalid`.
- `reason_code = MALFORMED_DIFF`.
- Detail says `git apply --check --recount failed` with `warning: recount: unexpected line: ?` and `error: corrupt patch`.
- `repair_attempts = []`.
- `proposal_created = false`.
- `gate_created = false`.
- `policy_ran = false`.
- `reviewer_self_repair_attempted = false`.
- `backend_generated_diff = false`.
- Original failure was `BUILD_FAILED_IN_SANDBOX`.
- `failure_summary` contains both original build failure evidence and repair-related events.
- `pipeline` still reports `failure_repair` as running in the current projection shape.
- `events_snapshot` includes the repair materialization failure and retry-required state.
- `stages` show stage 1 failed.
- `llm_activity` shows the main and reviewer model work completed, but that does not mean a valid diff was materialized.

## Canonical State Model

- `original_stage_failure`: the build/transform failure that started repair.
- `repair_chain_completed`: the main model and reviewer finished their reasoning.
- `repair_materialization_failed`: backend could not safely turn reviewed output into a valid diff artifact.
- `repair_retry_required`: backend should retry materialization or reviewer repair, not expose apply.
- `no_apply_path_available`: the gate must stay read-only until a canonical reviewed diff exists and passes validation.

## Current Conflicts

1. Old repair-running state leaks into the failure section.
2. `Failure Evidence` and `Reviewed Repair Gate` both surface repair history, but only the gate should own current approval state.
3. `materialization_failed` still renders a validation component with empty attempts.
4. Pipeline projection still implies the repair phase is active even though materialization failed.
5. Reviewer completion is being visually over-interpreted as apply readiness.

## Frontend Cleanup Plan

- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
  - Keep it as the host shell.
  - Restrict `Failure Evidence` to original stage/build evidence and supporting artifacts.
  - Do not fold `repair_loop_active` or reviewed-diff materialization failure into the same active-failure narrative.

- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`
  - Treat `proposalState.unavailable.kind === "materialization_failed"` as a terminal read-only gate state.
  - Render the unavailable state, model trace, and read-only actions only.
  - Do not render `ValidationProgressPanel` for `materialization_failed`.

- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx`
  - Keep it for real proposal/attempt flows only.
  - Do not let it synthesize a validation timeline when `repair_attempts=[]` and the gate is unavailable.

- `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx`
  - Continue to honor `allowed_actions` only.
  - Never synthesize `approve_sandbox_apply` locally.

- `web/control-tower/lib/contracts.ts`
  - Only change if the UI needs an explicit field for `repair_materialization_failed` or separate scope labeling.

## Backend Projection Cleanup Plan

- `migration_factory/control_tower/adapters/fastapi/app.py`
  - Make `repair/proposals/current` remain the canonical gate-state source.
  - Extend pipeline projection so `failure_repair` no longer looks running once `reviewed_repair_materialization_failed` or `retry_required` is present.
  - Keep `repair/attempts` empty when no apply attempt happened.
  - Keep `events_snapshot` historical, not authoritative for current gate state.

- `migration_factory/control_tower/application/v2_repair_projection.py`
  - If necessary, add explicit scope or retry-status fields so UI can distinguish original failure from repair materialization failure cleanly.

## Old Code / Branches To Remove Or Bypass

| File/component | Old behavior | New canonical behavior | Action | Risk |
|---|---|---|---|---|
| `MigrationCockpit.tsx` failure block | Mixes original failure and repair-loop state | Original failure only, or clearly separated repair blocker section | Bypass for `materialization_failed` | Medium |
| `RepairProposalPanel.tsx` unavailable branch | Shows validation panel with empty attempts | Read-only unavailable state only | Remove from this state path | Medium |
| `pipeline` projection | `failure_repair` may remain running | Mark blocked / retry required when materialization fails | Bypass old running interpretation | Medium |
| `RepairActionsBar.tsx` | Could be reused too broadly if called from wrong branch | Only render on valid proposal state | Keep, but gate its caller | Low |
| `llm/activity` trace | Read as apply-ready proof | Read as model-completion proof only | Keep | Low |

## Files To Change

Only if the cleanup is implemented:
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`
- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/application/v2_repair_projection.py`
- `web/control-tower/lib/contracts.ts` if the contract needs an explicit scope or retry field

## Files Not To Change

- Do not change apply/rebuild/test path.
- Do not change `run_validation_after_patch`.
- Do not duplicate build/test/orchestrator logic.
- Do not refactor `_handle_exit`.
- Do not rewrite LangGraph.
- Do not weaken materialization validation.
- Do not expose `approve_sandbox_apply` for malformed diffs.

## Implementation Plan Without Tests

1. Map the current frontend source of truth for each visible section.
2. Add a clear frontend branch for `materialization_failed` in `RepairProposalPanel`.
3. Remove validation rendering from the unavailable materialization branch.
4. Narrow `Failure Evidence` to original failure evidence, or split out repair materialization as a separate labeled substate.
5. Update backend pipeline projection so repair is blocked/retry-required after materialization failure instead of looking running.
6. Add any minimal contract fields needed for scope or blocker labeling.
7. Keep approval gating strict: no apply action until a canonical reviewed diff passes backend validation.

## Acceptance Criteria

- `Failure Evidence` shows original stage/build evidence only, or clearly groups repair materialization failure separately.
- `Reviewed Repair Gate` shows current gate state, not a synthetic apply path.
- `materialization_failed` renders as reviewed repair unavailable/invalid.
- No apply/rebuild/test timeline appears when `repair_attempts=[]`.
- No approve action is visible.
- Pipeline/status no longer implies repair is running after `materialization_failed`/`retry_required`.
- Original build failure remains visible as evidence.
- Materialization failure is visible as the active repair blocker.
- LLM completion does not imply diff readiness.
- No apply/rebuild/test code is changed.

## Safe Verification Commands

Allowed:
- `git diff`
- `git status`
- `npm run type-check`
- `python -m py_compile` on touched Python files if code changes are later approved

Not allowed:
- `pytest`
- `npm test`
- `vitest`
- full migration
- external APIs
- real LLM calls

## Sources Used For Guidance

- React conditional rendering guidance: https://react.dev/learn/conditional-rendering
- Git `apply` behavior and `--reject`/`--3way` docs: https://git-scm.com/docs/git-apply

