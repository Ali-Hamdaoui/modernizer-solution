# AMF-252 Direct Candidate Diff Implementation Handoff

## 1. Summary of Change

Removed the old behavior where `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists` = `proposal=null` / `materialization_failed`. Now the candidate diff is presented to the user for review and decision, with the user as the approval gate.

## 2. Files Changed

| File | Change Type |
|------|-------------|
| `migration_factory/control_tower/application/v2_repair_gate_service.py` | Backend: new routing block in catch (lines 315-381) |
| `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` | Frontend: kicker/title/warning copy, `candidateDiff` prop pass |
| `web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx` | Frontend: dynamic tab labels via `candidateDiff` prop |

**Not changed:**
- `migration_factory/orchestrator/repair_review_chain.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/repair_loop/patch_apply.py`
- `migration_factory/repair_loop/validation_runner.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/application/v2_repair_projection.py`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx`

## 3. Old Behavior Removed

- `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists=True` → catch block emitted `materialization_failed`, returned `status="skipped"`, `proposal=null`
- Frontend showed "Reviewed Repair Materialization Failed" with no diff visible
- User never saw the candidate diff the main LLM had already produced

## 4. New Behavior Implemented

- `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists=True` + `final_diff_exists=False` → catch block routes to existing direct candidate diff persistence, returns `status="created"`, `proposal.kind = "direct_candidate_diff"`
- Frontend renders "Candidate Repair Diff Ready" with candidate diff, reviewer findings, and apply button
- `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists=False` → still returns `materialization_failed` (unchanged)

## 5. Backend Flow After Change

```
1. produce_repair_review_chain() raises RepairReviewChainProductionError
2. Catch block extracts partial_chain, resolves reason_code="REVIEWER_REQUESTED_REVISION"
3. duplicate_main_blocked check (unchanged, line 274)
4. NEW: If proposed_diff_exists=True AND final_diff_exists=False:
   a. Synthesize chain_result = {"review_chain": partial_chain}
   b. Validate with _validate_direct_candidate_diff()
   c. If invalid → fall through to materialization_failed
   d. Persist with _persist_direct_candidate_repair_proposal()
   e. Emit with _emit_repair_candidate_diff_ready_for_user_apply()
   f. Bind invocations with _bind_llm_invocations()
   g. Return status="created", kind="direct_candidate_diff"
5. If condition not met → existing materialization_failed (unchanged)
```

## 6. Frontend Flow After Change

```
1. Backend returns proposal != null with kind="direct_candidate_diff"
2. isCandidateDiff = true (proposal.kind === "direct_candidate_diff")
3. Kicker: "Candidate Repair Diff"
4. Title: "Candidate Repair Diff Ready"
5. Warning banner: "Reviewer requested revision, but the main LLM candidate diff is available for your review and decision."
6. Diff tab: "Proposed Diff (Candidate)"
7. Reviewer tab: "Reviewer Findings"
8. Apply button: "Apply Candidate Diff" (if allowed_actions includes approve_sandbox_apply)
9. "Reviewed Repair Materialization Failed" NOT shown (proposal != null)
10. Revision actions NOT available (direct proposals strip revision from allowed_actions)
```

## 7. Manual API Expectations

For a job where:
- `reviewer_decision = needs_revision`
- `reason_code = REVIEWER_REQUESTED_REVISION`
- `proposed_diff_exists = true`
- `final_diff_exists = false`

Expected `GET /v1/v2/jobs/{job_id}/repair/proposals/current`:

```json
{
  "proposal": {
    "proposal_id": "<non-null>",
    "kind": "direct_candidate_diff",
    "status": "user_review_required",
    "reviewer_decision": "needs_revision",
    "final_diff_exists": false,
    "proposed_diff_exists": true,
    "candidate_diff_source": "main_proposed_diff",
    "allowed_actions": ["view_diff", "view_reviewer_opinion", "view_files_changed", "approve_sandbox_apply"],
    "gate_id": null
  },
  "unavailable": null
}
```

## 8. Manual UI Expectations

- "Candidate Repair Diff" kicker
- "Candidate Repair Diff Ready" title
- Yellow warning banner: "Reviewer requested revision, but the main LLM candidate diff is available for your review and decision."
- "CANDIDATE" status badge
- Diff tab labeled "Proposed Diff (Candidate)"
- Reviewer tab labeled "Reviewer Findings"  
- "Apply Candidate Diff" button visible (if backend allows)
- No "Reviewed Repair Materialization Failed" component
- No revision button

## 9. Unchanged Paths Confirmation

| Path | Status |
|------|--------|
| Accepted reviewer diff (final_diff_exists=True, decision=accept) | Unchanged |
| No diff produced (proposed_diff_exists=False) | Unchanged — materialization_failed |
| MALFORMED_DIFF / structural invalid | Unchanged |
| Patch apply logic (apply_patch_to_sandbox_direct) | Unchanged |
| Rebuild/validation after apply | Unchanged |
| Next repair cycle creation on validation failure | Unchanged |
| duplicate_main_blocked routing | Unchanged |
| Policy banner / gate flow | Unchanged |
| Approve API (POST .../{proposal_id}/approve) | Unchanged |
| Revise API (blocked for direct proposals) | Unchanged |

## 10. Frontend Does Not Send Raw Diff/Path/Env/Argv

Confirmed. The approve request payload only contains:
```typescript
{
  proposal_id: string;
  diff_checksum: string;
  reviewer_verdict_id?: string | null;
  gate_id?: string | null;
  expected_gate_checksum?: string;
  idempotency_key?: string;
}
```
The backend reloads the persisted diff by proposal_id, verifies checksum, applies it to the sandbox.

## 11. Risks / TODOs

- **Other reviewer non-accept decisions** (`REVIEWER_DECLINED_REPAIR`, `REVIEWER_NEEDS_MORE_CONTEXT`) are explicitly NOT included in this change. They still return materialization_failed. If product decides to show candidate diffs for those cases too, a separate change is needed.
- **Type safety**: TypeScript compilation should be verified to ensure `candidateDiff` prop is correctly propagated through all callers of `ReviewedDiffTabs`.
- **End-to-end test**: A full cycle test covering `REVIEWER_REQUESTED_REVISION` → candidate diff → user apply → validation pass would be ideal.
