# AMF-252 Direct Repair Fix Handoff

## Summary
- Fixed the frontend repair timeline so rebuild/test/continue are reason-code aware and no longer infer validation failure from `attempt.status`.
- Hardened direct repair materialization so missing `direct_sandbox` fails closed for both reviewed and candidate direct diffs.
- Added direct-apply defense in depth by running a precheck before `git apply`, while preserving the existing `ALREADY_APPLIED` reverse-check path.
- Verified the continuation path and canonical checksum path; no code change was needed there.

## Files Changed
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`
  - Passes `proposal.reason_code` into `ValidationProgressPanel`.
- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx`
  - Accepts `reasonCode` and derives rebuild/test/continue from `reasonCode` + `rerun_status`, not `attempt.status`.
  - Shows the AMF-252 copy for patch-apply and patch-precheck failures.
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
  - Fails closed when `direct_sandbox` is missing before persisting either direct reviewed or direct candidate proposals.
- `migration_factory/repair_loop/patch_apply.py`
  - Runs `check_patch_applicability()` before direct `git apply`.
  - Preserves `ALREADY_APPLIED` via the existing reverse-check classification.
- `AMF252_DIRECT_REPAIR_CONTINUATION_IMPLEMENTATION_PLAN.md`
  - The implementation plan created earlier in this session.

## Behavior Matrix

### PATCH_CHECK_FAILED
- Apply: failed
- Rebuild: not started
- Test: not started
- Continue: blocked
- Read-only proposal: yes

### PATCH_APPLY_FAILED
- Apply: failed
- Rebuild: not started
- Test: not started
- Continue: blocked
- Read-only proposal: yes

### APPLIED + rerun failed
- Apply: passed
- Rebuild: failed
- Test: failed
- Continue: blocked
- Patched sandbox kept for the direct path: yes

### APPLIED + rerun passed
- Apply: passed
- Rebuild: passed
- Test: passed
- Continue: continuing / next stage queued

### Malformed direct diff before approval
- No `approve_sandbox_apply`
- Materialization fails closed
- No user-actionable direct proposal unless parse/checksum/applicability passed

### Canonicalized reviewed diff
- Canonical diff ref is the persisted source of truth
- Canonical checksum remains aligned with the persisted diff

## What Was Not Changed
- `_handle_exit`
- LangGraph/orchestrator
- `run_build_agent()` / `run_test_agent()`
- normal migration success path
- tests

## Verification Run
- `py -3 -m py_compile migration_factory/control_tower/application/v2_repair_gate_service.py migration_factory/repair_loop/patch_apply.py`
  - Passed.
- `npm run type-check` in `web/control-tower`
  - Failed due existing `RepairProposalPanel.tsx` type errors unrelated to the timeline fix:
    - `app/migrations/[jobId]/RepairProposalPanel.tsx:131`
    - `app/migrations/[jobId]/RepairProposalPanel.tsx:199`
    - `app/migrations/[jobId]/RepairProposalPanel.tsx:290`
- `git diff --stat`
  - Confirmed only the intended files changed.
- `git status --short`
  - Confirmed the working tree contains only the intended edits plus this handoff file and the implementation plan.

## Manual Runtime Checks To Run Later
```powershell
$Job = "4a587211b9d74c1182b9a98d4504996c"
$Port = "8000"

(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/proposals/current") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/attempts") | ConvertTo-Json -Depth 80
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/events/snapshot?after=0") | ConvertTo-Json -Depth 80
```

Expected manual API behavior for `PATCH_APPLY_FAILED`:
- `proposal.status = approve_failed`
- `apply_status = REJECTED`
- `reason_code = PATCH_APPLY_FAILED`
- `allowed_actions` does not include `approve_sandbox_apply`
- `rerun_status = not_started` for new failures, or `null` accepted for legacy data
- no `repair_validation_*` events
- frontend shows rebuild/test not started

Expected behavior for fresh malformed direct diff:
- no `approve_sandbox_apply`
- materialization fails closed
- no user-reviewable direct proposal unless parse/checksum/apply-check passed

## Risks / Follow-up
- `npm run type-check` still fails because of unrelated existing errors in `RepairProposalPanel.tsx`.
- Legacy rows with `null` `rerun_status` still depend on the new reason-code-aware frontend path to display correctly.
- Stale frontend bundles or cached API responses could still show the old timeline until refreshed.
- Canonical checksum behavior was verified by inspection, not runtime mutation.
