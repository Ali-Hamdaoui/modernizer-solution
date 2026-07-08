# AMF-252 Full Codebase Discovery and Old Behavior Removal Plan

## 1. Executive Summary

**The real issue:** When the reviewer LLM returns `decision = needs_revision` (reason_code = `REVIEWER_REQUESTED_REVISION`), `repair_review_chain.py` raises `RepairReviewChainProductionError`. The catch block in `v2_repair_gate_service.py` treats ALL such exceptions as fatal materialization failures and returns `status = "skipped"` early — before ever reaching the existing `direct_candidate_diff` persistence path at line 482.

This turns `proposal = null` / `unavailable.kind = materialization_failed` even when a valid main-LLM `proposed_diff` exists. The user is blocked from seeing or applying the candidate diff.

**Root cause:** `repair_review_chain.py:2243` raises instead of returning a structured non-accept result. `v2_repair_gate_service.py:265-350` has no fallback logic for `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists`.

**The fix is minimal:** The existing `direct_candidate_diff` code path already exists at `v2_repair_gate_service.py:482-547`. It is fully functional — validation, persistence, event emission, and approval/apply infrastructure all work. The only thing missing is the flow reaching it for the `needs_revision` case.

---

## 2. Desired New Product Flow

```
1. Migration/build/transform failure happens
2. Backend collects failure evidence and context pack
3. Main LLM (PROPOSER) receives context, produces proposed_diff
4. Reviewer LLM (REVIEWER) reviews the main output
5. If reviewer ACCEPTS and produces reviewed_diff → direct_reviewed_diff proposal
6. If reviewer says NEEDS_REVISION but proposed_diff exists → direct_candidate_diff proposal
7. If no diff exists at all → materialization_failed (unchanged terminal state)
8. User sees diff displayed (reviewed or candidate) with reviewer findings
9. User decides whether to accept/apply the displayed diff
10. If user accepts, backend reloads persisted diff, verifies checksum, applies to sandbox
11. Backend rebuilds/revalidates
12. If validation passes → continue migration via existing stage progression
13. If validation fails → keep patched sandbox, create next repair cycle
```

**Key product rules (unchanged):**
- User is the approval gate
- Backend is executor
- Frontend must never send raw diff/path/env/argv
- Frontend sends proposal_id, checksum/idempotency fields only
- Backend reloads persisted diff, verifies checksum, applies to sandbox
- Backend rebuilds/tests, then continues migration or creates next repair cycle

---

## 3. Current Backend Flow

### 3.1 repair_review_chain.py — Main LLM output

**File:** `migration_factory/orchestrator/repair_review_chain.py`

| Step | Function | Lines | Description |
|------|----------|-------|-------------|
| Proposer call | `produce_repair_review_chain` | 1679 | `client.answer_with_role(role=V2ModelRole.PROPOSER, ...)` |
| Parse primary output | `_coerce_primary_repair_output` | 1721 | Parses JSON, validates `proposed_diff` required field |
| Write primary JSON | `produce_repair_review_chain` | 1749 | Persists `primary_repair_llm_output.json` |
| Compute checksum | `produce_repair_review_chain` | 1753 | `sha256_canonical_json({"unified_diff": proposed_diff})` |
| Persist proposed diff | — | 1749 | As string field inside `primary_repair_llm_output.json` |

### 3.2 repair_review_chain.py — Reviewer LLM call and decision handling

| Step | Function | Lines | Description |
|------|----------|-------|-------------|
| Reviewer call | `produce_repair_review_chain` | 1779-1793 | `client.answer_with_role(role=V2ModelRole.REVIEWER, ...)` |
| Coerce reviewer output | `_coerce_reviewer_repair_output` | 1857 | Parses and validates reviewer JSON |
| **RAISE on non-accept** | `produce_repair_review_chain` | **2205-2250** | **`if reviewer_output["decision"] != "accept"` → raises `RepairReviewChainProductionError`** |
| Map decision → reason_code | `produce_repair_review_chain` | 2207-2212 | `{"reject": "REVIEWER_DECLINED_REPAIR", "needs_revision": "REVIEWER_REQUESTED_REVISION", ...}` |
| Build partial_chain | `_persist_failure_review_chain` → `_partial_failed_review_chain` | 1177-1262 | Builds review_chain dict with metadata |
| Write review_chain.json | `_persist_failure_review_chain` | 1177 | Persists even for non-accept cases |

**Key excerpt (lines 2205-2250):**
```python
if reviewer_output["decision"] != "accept":
    _decision_reason_map = {
        "reject": "REVIEWER_DECLINED_REPAIR",
        "needs_more_context": "REVIEWER_NEEDS_MORE_CONTEXT",
        "needs_revision": "REVIEWER_REQUESTED_REVISION",
        "revise": "REVIEWER_REQUESTED_REVISION",
    }
    non_accept_reason = _decision_reason_map.get(reviewer_output["decision"], ...)
    raise RepairReviewChainProductionError(
        f"reviewer decision not accept: {reviewer_output['decision']}",
        reason_code=non_accept_reason,  # "REVIEWER_REQUESTED_REVISION"
        partial_chain=non_accept_chain,
    )
```

### 3.3 What partial_chain contains for needs_revision

Built by `_partial_failed_review_chain` (line 1232) + `_persist_failure_review_chain` (line 1177):

```python
{
    # From _partial_failed_review_chain:
    "proposed_diff_checksum": "<sha256>",          # SHA256 of proposed_diff
    "reviewed_diff_checksum": "",                   # Empty (reviewer had no diff)
    "reviewer_output_checksum": "<sha256>",
    "reviewer_decision": "needs_revision",
    "reviewer_accept_contract_valid": True,
    "final_diff_exists": False,                     # ALWAYS False for needs_revision
    "proposed_diff_exists": True,                   # True when diff_checksum non-empty
    "candidate_diff_source": "main_proposed_diff",  # Available candidate source
    "proposal_created": False,
    "gate_created": False,
    "policy_ran": False,
    "proposer_invocation_id": "<id>",
    "reviewer_invocation_id": "<id>",
    # + self-repair fields (all False for skip_self_repair)
    
    # From _persist_failure_review_chain:
    "job_id": "<job_id>",
    "stage_index": <n>,
    "reason_code": "REVIEWER_REQUESTED_REVISION",
    "detail": "decision=needs_revision",
    "reviewer_output_ref": "path/to/reviewer_repair_llm_output.json",
    "primary_output_ref": "path/to/primary_repair_llm_output.json",  # ← Can reload proposed_diff
    "deterministic_artifact_ref": "path/to/deterministic_artifact.json",
}
```

**Confirmed: `partial_chain` includes all fields needed to reload the proposed_diff and route to the direct_candidate_diff path.**

### 3.4 v2_repair_gate_service.py — The catch block that blocks everything

**File:** `migration_factory/control_tower/application/v2_repair_gate_service.py`

**Flow:**

```
Line 253: try:
Line 254:   chain_result = produce_repair_review_chain(...)
           ↓
           RepairReviewChainProductionError raised (needs_revision)
           ↓
Line 265: except Exception as exc:
Line 268:   if isinstance(exc, RepairReviewChainProductionError):
Line 269:     partial_chain = dict(getattr(exc, "partial_chain", {}) or {})
Line 271:     reason_code = _reviewed_repair_unavailable_reason(exc)  # → "REVIEWER_REQUESTED_REVISION"
Line 272:     materialization_reason = _materialization_reason_code(reason_code)
Lines 274-313:   (duplicate_main_blocked check — skipped)
Lines 315-350:   Emit materialization failure events, log, RETURN EARLY:

                return RepairGateCreationResult(
                    gate_id="",
                    status="skipped",
                    reason=f"reviewed repair materialization failed: {materialization_reason}",
                )

                ↑ THIS EARLY RETURN PREVENTS EVER REACHING:
Line 412:       if final_diff_exists and reviewer_decision == "accept"     ← direct proposal path
Line 482:       if proposed_diff_exists and not final_diff_exists         ← direct candidate path  **NEVER REACHED**
Line 549:       create_repair_gate_from_reviewed_chain(...)               ← gate path
```

### 3.5 The existing direct_candidate_diff path (never reached)

**File:** `migration_factory/control_tower/application/v2_repair_gate_service.py`, lines 481-547

This code is fully functional and would work correctly if reached:

```python
# Line 482:
if proposed_diff_exists and not final_diff_exists:
    # Validate candidate diff
    _cand_valid, _cand_reason = self._validate_direct_candidate_diff(...)     # Line 1726
    # Persist proposal
    proposal_id, proposal_diff_checksum = self._persist_direct_candidate_repair_proposal(...)  # Line 1774
    # Emit event for UI
    self._emit_repair_candidate_diff_ready_for_user_apply(...)                # Line 1280
    # Bind LLM invocations
    self._bind_llm_invocations(...)                                          # Line 1857
```

The same pattern exists in:
- `regenerate_reviewed_repair_chain_on_revision` (lines 2690-2739)
- `create_next_repair_cycle_from_rerun_failure` (lines 3269-3318)

### 3.6 Existing reusable functions (no new engine needed)

| Function | File:Line | Purpose |
|----------|-----------|---------|
| `_validate_direct_candidate_diff` | `v2_repair_gate_service.py:1726` | Validates proposed_diff → `(bool, str)` |
| `_persist_direct_candidate_repair_proposal` | `v2_repair_gate_service.py:1774` | Writes `candidate_diff.diff`, saves `V2RepairProposalRecord`, returns `(proposal_id, checksum)` |
| `_emit_repair_candidate_diff_ready_for_user_apply` | `v2_repair_gate_service.py:1280` | Emits event for UI |
| `_bind_llm_invocations` | `v2_repair_gate_service.py:1857` | Binds invocation IDs to proposal |
| `_partial_failed_review_chain` | `repair_review_chain.py:1232` | Already computes `proposed_diff_exists=True, final_diff_exists=False` |
| `_persist_failure_review_chain` | `repair_review_chain.py:1177` | Writes `review_chain.json` |

---

## 4. Current API / Apply / Continuation Flow

### 4.1 GET /repair/proposals/current

**File:** `migration_factory/control_tower/adapters/fastapi/app.py:4068`

```python
# Line 4075: Load current proposal record
record = uow.v2_repairs.get_current_proposal_for_job(job_id)

# Line 4077-4081: No record → unavailable
if record is None:
    return {"proposal": None, "unavailable": _latest_repair_materialization_unavailable(...)}

# Line 4082-4166: Record with diff_ref → build proposal projection
if record has diff_ref:
    proposal = build_reviewed_diff_proposal_from_record(...)
    return {"proposal": proposal, "unavailable": None}

# Line 4188-4192: Record but no diff_ref → unavailable
return {"proposal": None, "unavailable": _latest_repair_materialization_unavailable(...)}
```

**Key insight:** When `_persist_direct_candidate_repair_proposal` persists a record with `diff_ref`, the next call to `get_current_repair_proposal` will return the proposal (not unavailable). The transition works automatically.

### 4.2 GET /repair/proposals/{proposal_id}

**File:** `app.py:4194`

Same projection logic. Returns 404 if proposal not found.

### 4.3 allowed_actions for direct proposals

**File:** `app.py:4121`

When `gate_id is None` (direct proposal):
```python
actions = READ_ONLY_REPAIR_ACTIONS + (("approve_sandbox_apply",) if direct_proposal else ("approve_sandbox_apply", "request_revision"))
```

`approve_sandbox_apply` is **always** added for direct proposals. For direct_candidate_diff:
- `request_revision` is stripped (line 4125-4126)
- `approve_sandbox_apply` stays

### 4.4 POST /repair/proposals/{proposal_id}/approve

**File:** `app.py:4573-5325`

| Step | Lines | Action |
|------|-------|--------|
| Validate proposal_id | 4601-4606 | Matches path |
| Load record | 4608-4618 | Validate belongs to job |
| Verify checksum | 4620-4680 | `payload.diff_checksum` vs stored, disk reload + SHA256, SafeDiffPreview |
| Detect direct vs gated | 4684 | `proposal_is_direct = stored_gate_id is None` |
| Direct: skip gate | 4686-4703 | No gate/evidence/policy validation |
| Direct: apply | 4843-4849 | `apply_patch_to_sandbox_direct()` |
| Apply fails | 4913-4980 | Mark `approve_failed`, return error |
| Apply succeeds | 4982-4990 | `run_validation_after_patch()` |
| Validation passes | 5024-5067 | `runner._auto_queue_next_stage()` — auto queue next stage |
| Validation fails | 5096-5270 | `create_next_repair_cycle_from_rerun_failure()` — next repair cycle |

**No blocker exists for direct_candidate_diff approval.** The `proposal_is_direct` check treats all direct proposals identically, regardless of `kind`.

### 4.5 Backend diff reload and checksum verification

**File:** `app.py:4638-4660`

```python
diff_path = Path(diff_ref)
raw_diff = diff_path.read_bytes()
actual_diff_checksum = sha256_hex(raw_diff)
if actual_diff_checksum != stored_diff_checksum:
    raise error
```

**This works for both reviewed and candidate diffs.**

### 4.6 Direct patch apply

**File:** `migration_factory/repair_loop/patch_apply.py:500-657`

```python
def apply_patch_to_sandbox_direct(sandbox_path, patch_path, ...):
    # Step 1: git apply --check (dry-run)
    applicability_check = check_patch_applicability(...)
    if applicability_check.status != "CHECKED":
        # Step 2: Try reverse --check (detect already-applied)
        reverse_check = _git_apply(["git", "apply", "--reverse", "--check", str(patch_path)], ...)
        if reverse_check.returncode == 0:
            return PatchApplyResult(status="ALREADY_APPLIED", ...)
        return PatchApplyResult(status="REJECTED", ...)
    # Step 3: git apply
    applied = _git_apply(["git", "apply", str(patch_path)], ...)
```

### 4.7 Validation rerun and continuation

**File:** `migration_factory/repair_loop/validation_runner.py`

`run_validation_after_patch()` reuses existing build agent and test agent — no duplication.

**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py:1306`

`_auto_queue_next_stage()` handles stage progression after validation passes.

### 4.8 Next repair cycle from rerun failure

**File:** `v2_repair_gate_service.py:3003`

`create_next_repair_cycle_from_rerun_failure()`:
1. Checks remaining attempts — if exhausted, writes terminal failure
2. Builds new `FailureEvidence` from rerun failure data
3. Builds new `RepairContextPack` including full prior cycle context
4. Calls `produce_repair_review_chain()` with proposer/reviewer
5. Policy-validates and opens next repair_review gate

### 4.9 Old API behavior to remove/change

**File:** `app.py:783-1027` — `_latest_repair_materialization_unavailable`

The unavailable projection still scans for `reviewed_repair_materialization_failed` events. Once a candidate diff proposal is persisted, the `get_current_proposal_for_job` returns the record (line 4075), bypassing the unavailable path entirely. **The unavailable code is not reached when a proposal exists — no change needed here.**

**What must change:**
- `_unavailable_allowed_actions` (line 739): Only returns read-only actions. If a candidate diff exists, the proposal path handles this — so this function doesn't need changes.

---

## 5. Current Frontend Flow

### 5.1 How frontend loads proposal state

**File:** `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx:119-181`

```ts
const response = await getCurrentRepairProposal(jobId);
if (response.proposal) {
    setProposalState({ status: "available", proposal: response.proposal });
} else {
    setProposalState({ status: "no-proposal", unavailable: response.unavailable ?? null });
}
```

**Binary check only.** When `proposal === null`, the entire component switches to "no-proposal" mode. There is no third path for candidate-diff proposals that might need a different UI treatment.

### 5.2 Normal proposal branch

**File:** `RepairProposalPanel.tsx:127`

Renders when `proposalState.status === "available"`. All non-null proposals (including `direct_candidate_diff`) go through this path.

### 5.3 materialization_failed branch

**File:** `RepairProposalPanel.tsx:316-329`

Two triggers:
1. `proposalState.status === "no-proposal"` AND `unavailable?.kind === "materialization_failed"`
2. `proposalState.status === "no-proposal"` AND reviewer + main LLM both completed

### 5.4 Diff display

**File:** `RepairProposalPanel.tsx:542-546` → delegates to `ReviewedDiffTabs.tsx:53-65`

```tsx
{activeTab === "diff" && (
    <div>
        {diff ? <SafeDiffPreview diff={diff} /> : <p>No diff preview available.</p>}
    </div>
)}
```

### 5.5 ReviewedDiffTabs — no candidate vs reviewed differentiation

**File:** `web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx:11-16`

Tab labels are hardcoded:
```ts
const TABS = [
    { id: "diff", label: "Reviewed Diff" },          // Always says "Reviewed Diff"
    { id: "validation", label: "Validation" },
    { id: "files-changed", label: "Files Changed" },
    { id: "reviewer-opinion", label: "Reviewer Verdict" },
];
```

**No `diff_kind` or `proposal.kind` awareness.** The "Reviewed Diff" label appears even for candidate diffs.

### 5.6 RepairActionsBar — approve button

**File:** `RepairActionsBar.tsx:42-49, 108-131`

```ts
const showApprove = usingAllowedActions ? allowed.has("approve_sandbox_apply") : true;
```

Button label varies based on `candidateDiff` and `directProposal` booleans:
```tsx
{candidateDiff ? "Apply candidate diff" : directProposal ? "Apply reviewer diff" : "Approve sandbox apply"}
```

When `approve_sandbox_apply` is in `allowed_actions`, the approve button renders. **This already supports candidate diffs.**

### 5.7 Current UI state labels

**File:** `RepairProposalPanel.tsx:452-453`
```tsx
<div className="repair-panel-kicker">
    {isCandidateDiff ? "Candidate Diff" : isDirectProposal ? "Direct Reviewer Diff" : "Backend-governed repair gate"}
</div>
<h2>
    {isCandidateDiff ? "Candidate Diff Ready" : isDirectProposal ? "Reviewer Diff Ready" : "Reviewed Repair Proposal"}
</h2>
```

The `isCandidateDiff` check is `proposal.kind === "direct_candidate_diff"` (line 189-190). **This is already present** — the label "Candidate Diff Ready" exists but is never shown because the proposal never reaches the "available" state for `REVIEWER_REQUESTED_REVISION`.

### 5.8 materialization_failed copy

**File:** `RepairProposalPanel.tsx:878-879`
```ts
const title = diagnostic?.title?.trim() || "Reviewed Repair Materialization Failed";
const summary = diagnostic?.message?.trim() || "Backend could not materialize a reviewed diff for user approval.";
```

### 5.9 Post-apply UI states

**File:** `RepairProposalPanel.tsx:462-485`

| State | Condition | Copy |
|-------|-----------|------|
| Apply-check failed | `PATCH_CHECK_FAILED` | "Backend apply-check failed; new proposal required. No build/test rerun was started." |
| Patch apply failed | `PATCH_APPLY_FAILED` | "Backend patch apply failed after review approval. No build/test rerun was started." |
| Validation failed | Other approve-failed | "Reviewer accepted and backend applied the diff, but validation failed after apply." |

---

## 6. Old Behavior To Fully Remove

When a main-LLM `proposed_diff` exists but the reviewer says `needs_revision`:

| # | Old Behavior | Why Wrong | What Should Happen |
|---|--------------|-----------|--------------------|
| 1 | `proposal = null` | Blocks user from seeing candidate diff | `proposal` should be non-null with `kind = "direct_candidate_diff"` |
| 2 | `unavailable.kind = "materialization_failed"` | Misleading — diff exists, just not reviewed-accepted | No `unavailable` field; replace with proposal |
| 3 | UI shows "Reviewed Repair Materialization Failed" | User thinks repair broke entirely | UI should show "Candidate Repair Diff Ready" with reviewer findings |
| 4 | Candidate diff hidden from user | User is the approval gate and should decide | Show candidate diff with reviewer's revision notes |
| 5 | No `approve_sandbox_apply` action | User cannot approve candidate diff | `allowed_actions` must include `approve_sandbox_apply` |
| 6 | Treating reviewer non-accept as terminal materialization failure | Reviewer may have valid concerns but diff is still actionable | Reviewer non-accept with existing proposed_diff should route to candidate diff, not terminal failure |

**Important: Do NOT remove true materialization_failed behavior when NO diff exists.**
If `proposed_diff` is genuinely empty/missing AND `reviewed_diff` is empty/missing, `materialization_failed` remains correct.

---

## 7. New Backend Behavior To Implement

### Recommended approach: Fix in `v2_repair_gate_service.py` catch block (lines 265-350)

**Option A (minimal, safer):** Enhance the catch block to check `partial_chain` for `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists` and fall through to the existing `direct_candidate_diff` path.

**Option B (requires changing `repair_review_chain.py`):** Change `produce_repair_review_chain` to return a structured result instead of raising for non-accept decisions. The result would include `final_diff_exists=False, proposed_diff_exists=True`, and the caller would naturally flow into `direct_candidate_diff`.

**Recommendation: Option A** — it's a smaller change, doesn't touch the orchestrator, and reuses the existing catch-branch infrastructure.

### Desired behavior after fix:

```
1. produce_repair_review_chain() raises RepairReviewChainProductionError(reason_code="REVIEWER_REQUESTED_REVISION")
2. catch block extracts partial_chain
3. Check: if reason_code in {"REVIEWER_REQUESTED_REVISION", "REVIEWER_DECLINED_REPAIR", "REVIEWER_NEEDS_MORE_CONTEXT"}
   AND partial_chain["proposed_diff_exists"] is True:
   → Load proposed_diff from primary_output_ref (re-read primary_repair_llm_output.json)
   → Call _validate_direct_candidate_diff(...)
   → Call _persist_direct_candidate_repair_proposal(...)
   → Call _emit_repair_candidate_diff_ready_for_user_apply(...)
   → Call _bind_llm_invocations(...)
   → Return success with proposal_id
4. If proposed_diff_exists is False:
   → Keep existing materialization_failed behavior (unchanged)
5. If reason_code is not a non-accept decision (e.g., MALFORMED_DIFF, main_schema_invalid):
   → Keep existing materialization_failed behavior (unchanged)
```

### Exact functions to reuse (no new code needed):

| Function | File:Line | Already Works For |
|----------|-----------|-------------------|
| `_validate_direct_candidate_diff` | `v2_repair_gate_service.py:1726` | Validates proposed_diff |
| `_persist_direct_candidate_repair_proposal` | `v2_repair_gate_service.py:1774` | Persists candidate diff + proposal record |
| `_emit_repair_candidate_diff_ready_for_user_apply` | `v2_repair_gate_service.py:1280` | Emits event for UI |
| `_bind_llm_invocations` | `v2_repair_gate_service.py:1857` | Binds LLM invocations to proposal |

---

## 8. New API Behavior To Implement

For `REVIEWER_REQUESTED_REVISION` with candidate diff, after backend fix:

| Field | Old Value | New Value |
|-------|-----------|-----------|
| `proposal` | `null` | `ReviewedDiffProposal` with `kind = "direct_candidate_diff"` |
| `unavailable` | `{ kind: "materialization_failed", ... }` | Absent / null |
| `proposal.status` | — | `"user_review_required"` |
| `proposal.reviewer_decision` | — | `"needs_revision"` |
| `proposal.final_diff_exists` | — | `false` |
| `proposal.proposed_diff_exists` | — | `true` |
| `proposal.diff` | — | Main LLM's `proposed_diff` (safe-previewed) |
| `proposal.allowed_actions` | — | Includes `"approve_sandbox_apply"` |
| `proposal.candidate_diff_source` | — | `"main_proposed_diff"` |

**API endpoints that need no change:**
- `GET /repair/proposals/current` — will automatically return proposal once record exists
- `GET /repair/proposals/{proposal_id}` — same auto-behavior
- `POST /repair/proposals/{proposal_id}/approve` — existing direct proposal logic handles it
- Apply, validation, continuation endpoints — unchanged

---

## 9. New Frontend Behavior To Implement

### 9.1 When backend fix is in place, frontend already works

Because the backend will return `proposal: { kind: "direct_candidate_diff", ... }` instead of `proposal: null`, the existing `RepairProposalPanel.tsx:127` check:
```ts
if (response.proposal) {
    setProposalState({ status: "available", proposal: response.proposal });
```
will route to the "available" branch automatically.

### 9.2 Desired UI state (changes needed)

| Element | Current (needs_revision) | New Desired |
|---------|--------------------------|-------------|
| Kicker text | "Candidate Diff" (already coded but never shown) | "Candidate Repair Diff" |
| Title | "Candidate Diff Ready" (already coded) | "Candidate Repair Diff Ready" |
| Warning | None | "Reviewer requested revision, but the main LLM proposed diff is available for your review and decision." |
| Diff tab | "Reviewed Diff" (hardcoded) | "Proposed Diff (Candidate)" |
| Reviewer Verdict tab | Always shown | Show, but label as "Reviewer Findings" with revision reasoning |
| Apply button | Not shown (no `approve_sandbox_apply`) | "Apply Candidate Diff" (already coded, needs `approve_sandbox_apply` in `allowed_actions`) |

### 9.3 Frontend changes needed

| # | File | Line(s) | Change |
|---|------|---------|--------|
| 1 | `RepairProposalPanel.tsx` | 452-453 | Add distinct kicker/title for candidate diffs with reviewer findings |
| 2 | `RepairProposalPanel.tsx` | 487 | Consider showing `PolicyBannerSection` for candidate diffs too |
| 3 | `RepairProposalPanel.tsx` | 316-329 | Add comment that `materialization_failed` now only fires when no candidate diff exists |
| 4 | `ReviewedDiffTabs.tsx` | 12 | Make "Reviewed Diff" label dynamic: `proposal.kind === "direct_candidate_diff" ? "Proposed Diff (Candidate)" : "Reviewed Diff"` |
| 5 | `ReviewedDiffTabs.tsx` | 15 | Make "Reviewer Verdict" tab label dynamic: `proposal.kind === "direct_candidate_diff" ? "Reviewer Findings" : "Reviewer Verdict"` |
| 6 | `RepairActionsBar.tsx` | 16-17, 32-33 | Remove dead `approveEnabled`/`revisionEnabled` props |

### 9.4 What should NOT change

- `SafeDiffPreview` — generic diff rendering, no changes needed
- `RepairAttemptTimeline` — separate concern
- `ModelRoleActivity` — pure LLM invocation display
- `ValidationProgressPanel` — validation phases derive from attempts, which are empty until apply
- `RepairRevisionDialog` — revision form is generic
- `MigrationCockpit.tsx` — just renders `RepairProposalPanel`, no changes needed
- `controlTowerApi.ts` — pure HTTP wrappers, no changes needed

---

## 10. Files To Change

### Backend (2 files)

| File | Reason | Complexity |
|------|--------|------------|
| `migration_factory/control_tower/application/v2_repair_gate_service.py` | Add fallback in catch block (lines 265-350) to route `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists` into existing `direct_candidate_diff` path | Low |
| `migration_factory/control_tower/application/v2_repair_projection.py` | If `build_reviewed_diff_proposal_from_record` needs metadata about candidate diff source (already has `kind` field at line 642) | None (already ready) |

### Frontend (3 files)

| File | Reason | Complexity |
|------|--------|------------|
| `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` | Ensure candidate diff proposals render with appropriate warning copy and reviewer findings | Low |
| `web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx` | Make diff tab label and reviewer tab label dynamic based on `proposal.kind` | Low |
| `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx` | Remove dead `approveEnabled`/`revisionEnabled` props | Trivial |

### Contracts (1 file, likely no change)

| File | Reason | Complexity |
|------|--------|------------|
| `web/control-tower/lib/contracts.ts` | `kind: "direct_candidate_diff"` already exists in `ReviewedDiffProposal` at line 1188. `final_diff_exists`, `reviewer_decision`, `allowed_actions` already exist. | None (already ready) |

---

## 11. Files Not To Change

- `migration_factory/orchestrator/repair_review_chain.py` — if using Option A (catch-block fix). Only change if using Option B.
- `migration_factory/control_tower/adapters/fastapi/app.py` — API already handles direct proposals correctly
- `migration_factory/repair_loop/patch_apply.py` — apply logic already correct
- `migration_factory/repair_loop/validation_runner.py` — validation already correct
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — continuation already correct
- `migration_factory/agents/build_agent/agent.py` — build logic unchanged
- `migration_factory/agents/test_agent/agent.py` — test logic unchanged
- LangGraph/orchestrator code — no rewrite needed
- `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx` — already reason-code aware
- `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` — just renders child component
- `web/control-tower/lib/controlTowerApi.ts` — pure HTTP wrapper

**Critical: Do not:**
- Make frontend send raw diff/path/env/argv
- Bypass backend checksum/sandbox/apply/validation
- Remove materialization_failed for cases where no diff exists
- Duplicate build/test logic
- Create a second patch apply engine
- Add or run tests

---

## 12. Implementation Plan

### Phase 1: Backend Gate Service Fix (one file, one location)

**File:** `migration_factory/control_tower/application/v2_repair_gate_service.py`

**Location:** Lines 265-350 (the catch block in `create_reviewed_repair_gate_on_failure`)

**Step 1:** After extracting `partial_chain` and `reason_code` (line 271), add a new check:

```python
# After line 272: materialization_reason = _materialization_reason_code(reason_code)
# NEW: Check if reviewer non-accept with existing proposed diff

_reviewer_non_accept_reasons = {"REVIEWER_REQUESTED_REVISION", "REVIEWER_DECLINED_REPAIR", "REVIEWER_NEEDS_MORE_CONTEXT"}
if reason_code in _reviewer_non_accept_reasons and partial_chain.get("proposed_diff_exists"):
    # Route to direct_candidate_diff path
    _cand_valid, _cand_reason = self._validate_direct_candidate_diff(
        job_id=job_id,
        stage_index=stage_index,
        partial_chain=partial_chain,
        ...
    )
    if _cand_valid:
        proposal_id, proposal_diff_checksum = self._persist_direct_candidate_repair_proposal(...)
        self._emit_repair_candidate_diff_ready_for_user_apply(...)
        self._bind_llm_invocations(...)
        return RepairGateCreationResult(
            gate_id="",
            status="direct_candidate_proposed",
            reason="reviewer requested revision; candidate proposed diff persisted",
        )
```

**Step 2:** Keep existing materialization_failed behavior for all other cases (no-diff, malformed-diff, etc.)

### Phase 2: Frontend Polish (3 files)

**Step 1:** `ReviewedDiffTabs.tsx:11-16` — Make tab labels dynamic:
```tsx
const diffLabel = proposal.kind === "direct_candidate_diff" ? "Proposed Diff (Candidate)" : "Reviewed Diff";
const reviewerLabel = proposal.kind === "direct_candidate_diff" ? "Reviewer Findings" : "Reviewer Verdict";
```

**Step 2:** `RepairProposalPanel.tsx:452-453` — Add candidate-diff-specific warning banner above the proposal card when `kind === "direct_candidate_diff"`:
```tsx
{isCandidateDiff && (
    <div className="warning-banner">
        Reviewer requested revision, but a candidate diff from the main LLM is available for your review.
    </div>
)}
```

**Step 3:** `RepairActionsBar.tsx:16-17, 32-33` — Remove dead props.

### Phase 3: Verification (manual only, no pytest/npm test)

After implementing Phase 1, verify:
1. For a job with `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists=True`:
   - `GET /repair/proposals/current` returns `proposal != null`
   - `proposal.kind === "direct_candidate_diff"`
   - `proposal.allowed_actions` includes `"approve_sandbox_apply"`
   - `unavailable` is absent
2. For a job with no diff whatsoever:
   - `GET /repair/proposals/current` still returns `proposal = null`
   - `unavailable.kind === "materialization_failed"` (unchanged)
3. For a job with `reviewer_decision === "accept"` and valid reviewed diff:
   - Existing flow unchanged

---

## 13. Manual Verification Plan Only

No `pytest`. No `npm test`. No `vitest`. No `py_compile`. Manual API/UI checks only.

### Backend API checks (run against local server)

```powershell
$Job = "<job_id>"
$Port = "8000"

# 1. Check proposal state
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/proposals/current") | ConvertTo-Json -Depth 80

# 2. Check failure summary
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/failure-summary") | ConvertTo-Json -Depth 80

# 3. Check attempts (should be [] before apply)
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/repair/attempts") | ConvertTo-Json -Depth 80

# 4. Check LLM activity
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/jobs/$Job/llm/activity") | ConvertTo-Json -Depth 80

# 5. Check pipeline
(Invoke-RestMethod "http://127.0.0.1:$Port/v1/v2/migration-jobs/$Job/pipeline") | ConvertTo-Json -Depth 80
```

### Expected results after fix (candidate diff case)

- `/repair/proposals/current`: `proposal != null`, `proposal.kind = "direct_candidate_diff"`, `unavailable` absent
- `/failure-summary`: Original build failure still visible; repair blocker scoped separately
- `/repair/attempts`: `attempts = []` (no apply yet)
- `/llm/activity`: Shows proposer completed, reviewer completed (needs_revision)
- `/pipeline`: `failure_repair` reflects candidate-diff-ready state, not `running`

### UI checks

After backend returns candidate diff proposal:
1. Proposal panel shows `title = "Candidate Repair Diff Ready"` (or similar)
2. Warning text about reviewer revision is visible
3. Diff tab shows candidate `proposed_diff` from main LLM
4. Reviewer Verdict/Finding tab shows reviewer's revision reasoning
5. "Apply Candidate Diff" button is visible and enabled
6. After user clicks apply:
   - Patch check/applied status updates
   - Validation progress panel appears with real attempts
   - On pass: migration continues; on fail: next repair cycle created

---

## 14. Open Questions / Risks

| # | Question | Status | Risk |
|---|----------|--------|------|
| 1 | Does `partial_chain` always contain `primary_output_ref`? | Confirmed YES (set by `_persist_failure_review_chain` at line 1220-1221) | Low |
| 2 | Can `proposed_diff` artifact always be reloaded from `primary_output_ref` after reviewer needs_revision? | Yes — `primary_repair_llm_output.json` is written at line 1749 before reviewer is called. It persists regardless of reviewer outcome. | Low |
| 3 | Should candidate diff be shown with stronger warning copy? | Recommended — add a warning banner stating reviewer requested revision | Low |
| 4 | Should reviewer requested revision require extra explicit risk confirmation before apply? | Design decision — not a code blocker. Current apply flow already requires user button click. | Low |
| 5 | Does `_persist_direct_candidate_repair_proposal` support all metadata needed by frontend? | Yes — persists `V2RepairProposalRecord` with `diff_ref`, `diff_checksum`, `kind`, `reviewer_decision`, `allowed_actions`, etc. | Low |
| 6 | Should `REVIEWER_DECLINED_REPAIR` also get candidate diff treatment? | If `proposed_diff_exists=True`, yes — same logic applies. The user may still want to apply the main diff even if reviewer declined. | Medium |
| 7 | Should `REVIEWER_NEEDS_MORE_CONTEXT` also get candidate diff treatment? | Possibly — but the diff may be lower quality. Could show with stronger warning or restrict to read-only. | Medium |

---

## 15. Final Recommendation

### Backend-first approach (minimal, safe):

1. **Change `v2_repair_gate_service.py` catch block** (lines 315-350) to route `REVIEWER_REQUESTED_REVISION` + `proposed_diff_exists` into the existing `direct_candidate_diff` persistence path at line 482.
2. **Keep old materialization_failed only for no-diff cases** (unchanged behavior when `proposed_diff_exists=False`).
3. **Keep apply/rebuild/continue flow unchanged** — it already works for direct proposals.
4. **Keep API projection unchanged** — `get_current_proposal_for_job` returns the record once persisted.

### Frontend-second approach (polish only):

1. **Remove old materialization_failed UI** for candidate-diff cases — this happens automatically because the proposal branch renders when `proposal != null`.
2. **Polish diff tab labels** in `ReviewedDiffTabs.tsx` to reflect candidate vs reviewed.
3. **Add warning banner** for candidate diffs with reviewer revision context.
4. **Remove dead props** from `RepairActionsBar.tsx`.

### Estimated change surface:

- **Backend:** ~30 lines added/modified in 1 file
- **Frontend:** ~15 lines added/modified across 2-3 files
- **Contracts:** 0 changes needed
- **API routes:** 0 changes needed
- **Apply/validation/continuation:** 0 changes needed

### No new repair engine. No duplicated logic. No test creation. No test running.
