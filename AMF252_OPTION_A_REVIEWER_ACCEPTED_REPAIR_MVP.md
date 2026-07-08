# AMF-252 Option A — Reviewer-Accepted Repair MVP

**Feature name:** AMF-252 Option A — Reviewer-Accepted Repair MVP  
**Target repo:** `modernizer-solution`  
**Target branch recommendation:** `amf-252-option-a-reviewed-repair-mvp`  
**Mode:** Codex implementation prompt  
**Product decision:** Option A is locked. Only reviewer `accept` creates an applyable repair proposal. `needs_revision`, `reject`, and `needs_more_context` do **not** create candidate diffs for this MVP.

---

## 0. Codex Mission

Implement the clean AMF-252 repair loop on the current stable codebase.

The goal is:

```text
migration build/test/transform failure
  -> backend writes FailureEvidence and RepairContextPack
  -> backend runs proposer LLM
  -> backend runs reviewer LLM
  -> reviewer accept persists one user-review-required proposal
  -> Control Tower shows safe diff + reviewer notes
  -> user approves with proposal_id + diff_checksum + idempotency_key only
  -> backend reloads the exact persisted diff
  -> backend verifies checksum and applyability
  -> backend applies to migrated sandbox only
  -> backend runs validation
  -> validation pass continues migration normally
  -> validation fail keeps patched sandbox and creates next bounded repair attempt
```

The backend is the **safe executor and validator**. It is not a heavy gate decision engine. The user is the approval gate. The frontend must not carry backend gate/verdict/checksum internals.

---

## 1. Hard Product Rules

### 1.1 Option A MVP

Only reviewer `accept` creates an actionable proposal.

```text
reviewer accept
  -> create proposal
  -> allowed_actions includes approve_sandbox_apply

reviewer needs_revision / revise
  -> no applyable proposal
  -> show unavailable/reviewer-requested-revision status only

reviewer reject
  -> no applyable proposal
  -> show unavailable/reviewer-rejected status only

reviewer needs_more_context
  -> no applyable proposal
  -> show unavailable/needs-more-context status only
```

Do **not** implement `direct_candidate_diff` in this feature.

### 1.2 No rollback after successful apply + validation failure

This is critical.

```text
apply fails before patch is applied
  -> mark approve_failed
  -> no validation
  -> no next validation repair from patched state

apply succeeds, then validation fails
  -> keep patched sandbox
  -> create next repair cycle from new validation failure evidence
  -> do not rollback by default
```

Reason: the first patch may fix the original blocker and expose the next blocker. Rolling back will make the next attempt see the old failure again and risks a loop.

### 1.3 One apply path only

Use only:

```python
apply_patch_to_sandbox()
```

Do not add a second direct apply engine. Do not revive or modify the quarantined Copilot loop as part of this feature.

### 1.4 Raw-byte diff checksum is canonical for proposals

At proposal persistence time:

```python
diff_bytes = Path(final_diff_ref).read_bytes()
proposal.diff_checksum = sha256_hex(diff_bytes)
```

At approval time, recompute the same raw-byte checksum and compare it with the stored value.

Do **not** use the chain's `sha256_canonical_json({"unified_diff": diff})` checksum as the proposal approval checksum.

### 1.5 Reviewer is a verdict reviewer in current stable

Current stable `produce_repair_review_chain()` writes the proposer diff as `final_reviewed_repair.diff` when the reviewer accepts. Therefore:

```text
Main/proposer LLM = patch author
Reviewer LLM = accept/reject reviewer
Final applied diff = proposer diff accepted by reviewer
```

Do not describe the reviewer as a final patch author unless you also implement reviewer-edited diffs, which is out of scope for this MVP.

---

## 2. Verified Current Stable Situation

Use this as the starting truth from the uploaded stable zip.

### 2.1 Failure artifacts exist, but refs are not carried into the failure payload

File:

```text
migration_factory/control_tower/application/v2_orchestrator_runner.py
```

Function:

```python
V2OrchestratorRunner._maybe_write_repair_failure_context()
```

Current behavior:

- Writes `{run_dir}/repairs/repair_failure_evidence.json`.
- Writes `{run_dir}/repairs/repair_context_pack.json`.
- Emits `repair_failure_evidence_written`.
- Emits `repair_context_pack_written`.
- Does **not** inject the full internal refs back into `result`.
- `_emit_diagnostic_failure_events()` later builds public failure payloads without these repair refs, so the diagnosis callback cannot run the reviewed chain from persisted context.

### 2.2 Diagnosis callback creates a generic repair gate

File:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Function:

```python
create_repair_gate_diagnosis_callback()
```

Current behavior:

```python
repair_gate_service.create_repair_gate_on_failure(...)
```

This opens a generic `repair_review` gate. It does not call:

```python
produce_repair_review_chain()
```

It does not persist a current repair proposal.

### 2.3 The compact proposer/reviewer chain exists

File:

```text
migration_factory/orchestrator/repair_review_chain.py
```

Function:

```python
produce_repair_review_chain()
```

Current behavior:

```text
deterministic artifact
  -> proposer LLM output
  -> reviewer LLM output
  -> reviewer must accept
  -> write final_reviewed_repair.diff
  -> write review_chain.json
```

Important: current stable writes `proposed_diff` as `final_reviewed_repair.diff` after reviewer accept.

### 2.4 Proposal repository is reusable

File:

```text
migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
```

Class:

```python
V2RepairProposalRecord
```

Reuse existing nullable fields:

```text
job_id
attempt_number
failure_evidence_ref
repair_context_ref
diff_ref
diff_checksum
reviewer_verdict_id
reviewer_verdict_ref
reviewer_output_checksum
gate_id
apply_status
rerun_status
rollback_status
validation_result_ref
remaining_attempts
reviewer_decision
```

Do not add a new proposal table. Do not create a second proposal model.

### 2.5 Current approve endpoint is too gate/verdict dependent

File:

```text
migration_factory/control_tower/adapters/fastapi/app.py
```

Current request model requires:

```python
reviewer_verdict_id
gate_id
```

Current approve endpoint validates reviewer verdict repository state and gate state before apply.

For this feature, those fields must become optional/backward-compatible, not required for the new direct Option A flow.

### 2.6 Frontend currently blocks approve without gate/verdict IDs

File:

```text
web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx
```

Current behavior:

```tsx
const reviewerVerdictId = state.proposal.reviewer_verdict?.reviewer_verdict_id;
const gateId = state.proposal.gate_id;
if (!reviewerVerdictId || !gateId) return;
```

This must be removed for the new flow.

---

## 3. Files To Change

### Backend

```text
migration_factory/control_tower/application/v2_orchestrator_runner.py
migration_factory/control_tower/application/v2_repair_gate_service.py
migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
migration_factory/control_tower/application/v2_repair_projection.py
migration_factory/control_tower/adapters/fastapi/app.py
```

### Frontend

```text
web/control-tower/lib/contracts.ts
web/control-tower/lib/controlTowerApi.ts
web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx
web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx
web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx
web/control-tower/app/migrations/[jobId]/ReviewerVerdictCard.tsx
```

### Tests

```text
tests/control_tower/test_v2_orchestrator_runner.py
tests/control_tower/test_v2_repair_gate_service.py
tests/control_tower/test_v2_repair_review_chain_producer.py
tests/control_tower/test_v2_repair_proposal_api.py
tests/control_tower/test_v2_repair_approve_apply.py
web/control-tower/tests/reviewedDiffProposal.test.tsx
web/control-tower/tests/controlTowerApi.test.ts
```

Do not edit `graphify-out/*` unless explicitly required by the user.

---

## 4. Implementation Plan

## Task 1 — Preserve internal repair refs after failure context write

File:

```text
migration_factory/control_tower/application/v2_orchestrator_runner.py
```

Function:

```python
V2OrchestratorRunner._maybe_write_repair_failure_context()
```

After writing `repair_failure_evidence.json` and `repair_context_pack.json`, inject internal refs/checksums into `result`:

```python
result["_repair_failure_evidence_ref"] = str(evidence_path)
result["_repair_context_pack_ref"] = str(context_path)
result["_repair_run_dir"] = str(run_dir)
result["_repair_failure_evidence_checksum"] = evidence.content_checksum
result["_repair_context_pack_checksum"] = context_pack.context_pack_checksum
result["_repair_base_repo_state_checksum"] = context_pack.base_repo_state_checksum
```

Also preserve sandbox path/H2 flag if available:

```python
sandbox = result.get("sandbox_path") or result.get("sandbox_root") or ""
if sandbox:
    result["_repair_sandbox_path"] = str(sandbox)
result["_repair_h2_required"] = bool(result.get("h2_required") or result.get("h2_startup_required"))
```

Then update `_emit_diagnostic_failure_events()` so `build_failed`, `test_failed`, and `transform_failed` payloads include these internal repair refs when present.

Required payload keys:

```text
_repair_failure_evidence_ref
_repair_context_pack_ref
_repair_run_dir
_repair_sandbox_path
_repair_failure_evidence_checksum
_repair_context_pack_checksum
_repair_base_repo_state_checksum
_repair_h2_required
source_profile
target_profile
changed_files
```

Important: these internal refs may be sent to backend callback/event storage, but they must not appear in primary frontend proposal display.

Acceptance:

- Failed build result contains `_repair_failure_evidence_ref`.
- Failed build result contains `_repair_context_pack_ref`.
- Failed test result contains `_repair_failure_evidence_ref`.
- Failure callback payload contains enough refs to create a reviewed repair proposal.
- Existing failure evidence/context events still emit.
- Successful stages unchanged.

---

## Task 2 — Add a non-gate proposal creation result

File:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Add a small dataclass near existing result dataclasses:

```python
@dataclass(frozen=True)
class ReviewedRepairProposalCreationResult:
    status: str
    proposal_id: str = ""
    reason: str = ""
    event_id: str | None = None
    reviewer_decision: str | None = None
    diff_checksum: str | None = None
    remaining_attempts: int = 0
```

Do **not** return `RepairGateCreationResult` from the new non-gate method. That keeps the old gate mental model alive.

---

## Task 3 — Add `create_reviewed_repair_proposal_on_failure()`

File:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Add method:

```python
def create_reviewed_repair_proposal_on_failure(
    self,
    *,
    job_id: str,
    stage_index: int,
    command_id: str,
    failure_evidence_ref: str,
    repair_context_ref: str,
    run_dir: str,
    sandbox_path: str,
    legacy_path: str = "",
    source_profile: str = "",
    target_profile: str = "",
    h2_required: bool = False,
    model_client: Any | None = None,
    invocation_ledger: Any | None = None,
    uow: Any | None = None,
) -> ReviewedRepairProposalCreationResult:
    ...
```

Implementation rules:

1. Load `failure_evidence_ref` JSON.
2. Load `repair_context_ref` JSON.
3. Deserialize into `FailureEvidence` and `RepairContextPack`.
   - If no existing `from_dict` helpers exist, add private helpers in `v2_repair_gate_service.py`.
   - Preserve checksums from the JSON.
   - Do not recompute checksums in a way that changes persisted identity.
4. Call `produce_repair_review_chain()` with `output_dir=Path(run_dir) / "repair_chain"`.
5. If the chain raises or reviewer decision is not `accept`, emit `reviewed_repair_unavailable` and return `status="skipped"`.
6. On `accept`, read `review_chain["final_diff_ref"]`.
7. Build `SafeDiffPreview` from the final diff file.
8. Reject proposal creation unless:
   - diff file exists
   - diff bytes are non-empty
   - safe preview `checksum_mismatch` is false
   - safe preview parse status is acceptable
   - `evaluate_patch_proposal()` returns `ALLOWED`
   - `apply_patch_to_sandbox(..., check_only/precheck...)` is **not** used if no check-only API exists; instead rely on existing validation inside apply path at approve time and at least ensure safe preview is parseable. If check-only is added, do not mutate sandbox.
9. Compute proposal checksum from raw diff bytes:

```python
diff_checksum = sha256_hex(Path(final_diff_ref).read_bytes())
```

10. Persist exactly one `V2RepairProposalRecord` with:

```text
status = user_review_required
reviewer_decision = accept
diff_ref = final_diff_ref
diff_checksum = raw byte sha256
job_id = job_id
command_id = command_id
attempt_number = current bounded attempt
remaining_attempts = max_repair_attempts - attempt_number
failure_evidence_ref = failure_evidence_ref
repair_context_ref = repair_context_ref
reviewer_output_checksum = review_chain["reviewer_output_checksum"]
gate_id = None
reviewer_verdict_id = None unless existing reviewer repo entry is intentionally created
```

11. Emit one concise event:

```text
repair_proposal_ready
```

Event payload should include:

```text
proposal_id
job_id
stage_index
command_id
diff_checksum
reviewer_decision=accept
attempt_number
remaining_attempts
```

Do not include absolute local paths in event payload unless existing internal event conventions already allow them. Prefer basename/ref-safe data in public events.

Acceptance:

- Reviewer accept creates exactly one proposal.
- Reviewer non-accept creates no applyable proposal.
- Proposal has `status=user_review_required`.
- Proposal has `gate_id=None` or no gate requirement.
- Proposal has `diff_ref` persisted server-side.
- Proposal `diff_checksum` equals `sha256_hex(diff_file_bytes)`.
- Duplicate callback for the same `(job_id, stage_index, command_id)` does not create duplicate proposals.

---

## Task 4 — Wire diagnosis callback to proposal creation when refs exist

File:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Function:

```python
create_repair_gate_diagnosis_callback()
```

Change callback logic:

```python
failure_evidence_ref = str(payload.get("_repair_failure_evidence_ref") or "")
repair_context_ref = str(payload.get("_repair_context_pack_ref") or "")
run_dir = str(payload.get("_repair_run_dir") or "")
sandbox_path = str(payload.get("_repair_sandbox_path") or payload.get("sandbox_path") or "")

if failure_evidence_ref and repair_context_ref and run_dir and sandbox_path:
    repair_gate_service.create_reviewed_repair_proposal_on_failure(...)
else:
    repair_gate_service.create_repair_gate_on_failure(...)
```

The old generic gate path remains fallback only.

Acceptance:

- Failure with repair refs runs reviewed chain.
- Failure without refs keeps existing gate behavior.
- Callback remains best-effort and never breaks orchestrator loop.
- No generic repair gate is created for the same failure when a reviewed proposal was successfully created.

---

## Task 5 — Persist proposal through existing repository only

File:

```text
migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
```

Prefer a small helper:

```python
def save_reviewed_diff_proposal(self, record: V2RepairProposalRecord) -> None:
    self.save_proposal(record)
```

Or construct `V2RepairProposalRecord` in the service and call `save_proposal()` directly.

Do not add a new table. Do not add a new durable model.

Acceptance:

- Existing `get_current_proposal_for_job()` returns the new proposal.
- Existing `get_proposal_for_job()` returns it by ID.
- Attempt history can show it.
- Existing old rows remain readable.

---

## Task 6 — Projection cleanup for Option A

File:

```text
migration_factory/control_tower/application/v2_repair_projection.py
```

Keep:

```python
build_reviewed_diff_proposal_from_record()
```

Make sure projected proposal supports the new direct/no-gate path:

```text
kind/directness may be inferred as reviewed repair proposal with reviewer_decision=accept
allowed_actions includes approve_sandbox_apply only when:
  status == user_review_required
  reviewer_decision == accept
  safe_diff_preview.checksum_mismatch == false
  safe_diff_preview.parse_status is acceptable
```

Do not expose these as primary UI content:

```text
diff_ref
gate_id
diagnosis_ref
repair_plan_ref
reviewer_output_checksum
model invocation IDs
local paths
provider/deployment/env data
```

Backend may still retain compatibility fields internally; frontend must not require or display them.

Acceptance:

- Current proposal API returns safe diff preview.
- Current proposal API returns reviewer notes/reasoning.
- Current proposal API returns `allowed_actions` with `approve_sandbox_apply` only when applyable.
- Proposal response does not display local filesystem paths in the primary UI.

---

## Task 7 — Simplify approve request contract

Files:

```text
migration_factory/control_tower/adapters/fastapi/app.py
web/control-tower/lib/contracts.ts
```

Backend request model:

```python
class RepairProposalApproveRequest(BaseModel):
    proposal_id: str = Field(min_length=1)
    diff_checksum: str = Field(min_length=1)
    idempotency_key: str | None = None

    # Legacy optional compatibility only; not required for new direct flow.
    reviewer_verdict_id: str | None = None
    gate_id: str | None = None
    expected_gate_checksum: str | None = None
```

Frontend type:

```ts
export type RepairProposalApproveRequest = {
  proposal_id: string;
  diff_checksum: string;
  idempotency_key?: string;
  reviewer_verdict_id?: string;
  gate_id?: string;
  expected_gate_checksum?: string;
};
```

For new UI calls, send only:

```json
{
  "proposal_id": "...",
  "diff_checksum": "...",
  "idempotency_key": "..."
}
```

Acceptance:

- Backend accepts minimal payload.
- Backend remains backward-compatible with optional legacy fields.
- UI no longer needs `gate_id` or `reviewer_verdict_id` to approve.

---

## Task 8 — Simplify approve endpoint internals

File:

```text
migration_factory/control_tower/adapters/fastapi/app.py
```

Function:

```python
approve_repair_proposal_sandbox_apply()
```

Required new flow:

```text
1. Validate payload.proposal_id == path proposal_id.
2. Load proposal by job_id + proposal_id.
3. Require status user_review_required / reviewer_accepted compatibility.
4. Require reviewer_decision accept for new Option A direct proposal.
5. Require diff_ref and diff_checksum.
6. Verify request diff_checksum == stored diff_checksum.
7. Read diff bytes from disk.
8. Verify sha256_hex(diff_bytes) == stored diff_checksum.
9. Build SafeDiffPreview with stored_diff_checksum.
10. Reject checksum_mismatch.
11. Reject unparseable/hunk_count_mismatch previews before apply.
12. Resolve runtime context server-side from proposal first.
13. Fall back to gate resolver only for old gate-backed proposals.
14. Run evaluate_patch_proposal().
15. Run apply_patch_to_sandbox() only.
16. If apply fails: mark approve_failed, no validation, no next repair cycle.
17. If apply succeeds: run run_validation_after_patch().
18. If validation passes: mark approved_applied and continue migration.
19. If validation fails: keep patched sandbox, mark approve_failed, create next bounded reviewed repair attempt from validation failure.
```

Remove as hard requirements for new direct proposals:

```text
reviewer verdict repository lookup
frontend-submitted gate_id
frontend-submitted expected_gate_checksum
gate open/current state
```

Keep them only for old gate-backed proposals when `record.gate_id` exists.

Acceptance:

- Approve endpoint reloads diff from `record.diff_ref`.
- Approve endpoint never accepts raw diff.
- Stale checksum returns 409.
- Modified diff file returns 409.
- Malformed safe preview blocks approve before sandbox mutation.
- Apply failure does not run validation.
- Apply success + validation failure does not rollback by default.
- Apply success + validation failure creates next bounded attempt.

---

## Task 9 — Add proposal-first runtime resolver

File:

```text
migration_factory/control_tower/adapters/fastapi/app.py
```

Add:

```python
def _resolve_repair_proposal_runtime_context(
    *,
    uow: Any,
    job_id: str,
    record: V2RepairProposalRecord,
) -> dict[str, Any] | None:
    ...
```

Resolver order:

1. Use `record.repair_context_ref` and `record.failure_evidence_ref`.
2. Load JSON artifacts server-side.
3. Resolve:

```text
sandbox_path
run_dir
legacy_path
command_id
stage_index
source_profile
target_profile
h2_required
risk
deterministic_rule_id
expected_validation
```

4. If proposal has `gate_id`, fallback to existing `_resolve_reviewed_repair_runtime_context()`.
5. Return `None` when sandbox/run context cannot be resolved.

Do not return this resolver output to the frontend.

Acceptance:

- Direct proposal with no `gate_id` can be approved.
- Old gate-backed proposal still works.
- Missing sandbox path blocks safely.
- Missing run dir blocks safely.

---

## Task 10 — Validation failure creates next reviewed proposal without rollback

Files:

```text
migration_factory/control_tower/adapters/fastapi/app.py
migration_factory/control_tower/application/v2_repair_gate_service.py
```

New rule:

```text
APPLIED + validation failed
  -> do not call rollback_patch() for new Option A direct proposal
  -> keep patched sandbox
  -> create next reviewed repair proposal using validation failure evidence
```

Implementation approach:

- For direct proposal with `record.gate_id is None`, do not call `rollback_patch()`.
- Call a new or adjusted next-cycle method that creates another reviewed proposal, not a generic gate.
- Reuse `create_next_repair_cycle_from_rerun_failure()` only if it is changed to create a proposal instead of only a gate for direct flow.
- Otherwise add a small `create_next_reviewed_repair_proposal_from_rerun_failure()` returning `ReviewedRepairProposalCreationResult`.

Do not create infinite loops.

Attempt rule:

```text
attempt_number starts at 1
remaining_attempts = DEFAULT_MAX_REPAIR_ATTEMPTS - attempt_number
next attempt increments attempt_number
stop when remaining_attempts <= 0
```

Acceptance:

- Validation failure after apply does not rollback direct proposal.
- Next attempt sees the new validation failure, not the old original failure.
- Attempts stop at configured max.
- UI attempt history shows prior proposal as `approve_failed`, `apply_status=APPLIED`, `rerun_status=failed`, `rollback_status=None`.

---

## Task 11 — Frontend approve payload cleanup

File:

```text
web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx
```

Replace current approve handler logic.

Remove:

```tsx
const reviewerVerdictId = state.proposal.reviewer_verdict?.reviewer_verdict_id;
const gateId = state.proposal.gate_id;
if (!reviewerVerdictId || !gateId) return;
```

Use:

```tsx
await approveRepairProposal(jobId, state.proposal.proposal_id, {
  proposal_id: state.proposal.proposal_id,
  diff_checksum: state.proposal.diff_checksum,
  idempotency_key: `approve-${state.proposal.proposal_id}-${Date.now()}`,
});
```

Acceptance:

- Apply works without `gate_id`.
- Apply works without `reviewer_verdict_id`.
- Frontend sends no raw diff.
- Frontend sends no artifact refs.
- Frontend sends no local paths.

---

## Task 12 — Frontend display cleanup

Files:

```text
RepairProposalPanel.tsx
ReviewedDiffTabs.tsx
RepairActionsBar.tsx
ReviewerVerdictCard.tsx
```

Main UI should show:

```text
failure summary
stage index
attempt number
remaining attempts
reviewer decision
reviewer notes
safe diff preview
files changed
apply/validation status
```

Main UI should hide:

```text
gate ID
diagnosis ref
repair plan ref
diff ref
reviewer output checksum
model invocation ID
local paths
provider/deployment/env data
```

Tab recommendation:

```text
Diff
Files Changed
Reviewer Notes
Validation
```

Button label:

```text
Apply reviewed diff
```

Disable apply when:

```text
proposal.status is not user_review_required/reviewer_accepted compatibility
allowed_actions does not include approve_sandbox_apply
safe_diff_preview.checksum_mismatch is true
safe_diff_preview.parse_status is unparseable/hunk_count_mismatch
approve is pending
```

Acceptance:

- UI shows the diff and reviewer notes clearly.
- UI does not expose backend internals in the main panel.
- UI does not show request revision/reject actions unless fully implemented and tested.

---

## Task 13 — Events and API states

Add/standardize these event names for the MVP:

```text
repair_proposal_ready
reviewed_repair_unavailable
repair_approve_apply_failed
repair_validation_passed
repair_validation_failed
repair_attempts_exhausted
```

Rules:

```text
repair_proposal_ready
  -> reviewer accepted and one applyable proposal exists

reviewed_repair_unavailable
  -> chain failed or reviewer did not accept; no applyable proposal

repair_approve_apply_failed
  -> patch did not apply; no validation ran

repair_validation_failed
  -> patch applied; validation ran and failed

repair_attempts_exhausted
  -> no next attempt allowed
```

Keep PATCH_APPLY_FAILED distinct from validation failure.

---

## Task 14 — Tests to write/update

Backend tests:

```text
tests/control_tower/test_v2_orchestrator_runner.py
tests/control_tower/test_v2_repair_gate_service.py
tests/control_tower/test_v2_repair_review_chain_producer.py
tests/control_tower/test_v2_repair_proposal_api.py
tests/control_tower/test_v2_repair_approve_apply.py
```

Required cases:

```text
failure writes repair refs into result
failure payload carries repair refs to callback
callback invokes reviewed proposal creation when refs exist
callback falls back to generic gate when refs missing
reviewer accept persists one user_review_required proposal
reviewer needs_revision creates no applyable proposal under Option A
reviewer reject creates no applyable proposal
proposal checksum equals sha256_hex(raw diff bytes)
current proposal API returns safe diff preview and reviewer notes
approve accepts minimal payload
approve does not require gate_id
approve does not require reviewer_verdict_id
approve rejects stale checksum
approve rejects modified diff file
approve rejects malformed safe preview
approve calls apply_patch_to_sandbox only
apply failure does not run validation
validation pass marks approved_applied and continues migration
validation failure keeps patched sandbox and creates next bounded attempt
attempts stop at max attempts
```

Frontend tests:

```text
web/control-tower/tests/reviewedDiffProposal.test.tsx
web/control-tower/tests/controlTowerApi.test.ts
```

Required cases:

```text
approve payload contains only proposal_id, diff_checksum, idempotency_key
apply does not require gate_id
apply does not require reviewer_verdict_id
checksum mismatch disables apply
malformed preview disables apply
main panel hides gate_id and backend refs
main panel hides local paths
reviewer notes render
safe diff renders
validation status renders after approve response
```

---

## 5. Validation Commands

Run targeted checks only first:

```bash
python -m py_compile migration_factory/control_tower/application/v2_orchestrator_runner.py
python -m py_compile migration_factory/control_tower/application/v2_repair_gate_service.py
python -m py_compile migration_factory/control_tower/adapters/fastapi/app.py
python -m py_compile migration_factory/control_tower/application/v2_repair_projection.py
python -m py_compile migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
```

Then targeted backend tests:

```bash
pytest tests/control_tower/test_v2_orchestrator_runner.py
pytest tests/control_tower/test_v2_repair_review_chain_producer.py
pytest tests/control_tower/test_v2_repair_gate_service.py
pytest tests/control_tower/test_v2_repair_proposal_api.py
pytest tests/control_tower/test_v2_repair_approve_apply.py
```

Frontend:

```bash
cd web/control-tower
npm test -- reviewedDiffProposal
npm test -- controlTowerApi
npm run type-check
```

Final checks:

```bash
git diff --check
git status --short
```

Do not run live LLM calls unless explicitly requested by the user.

---

## 6. Final Acceptance Criteria

AMF-252 Option A MVP is complete when:

```text
- migration build/test/transform failure writes FailureEvidence
- migration build/test/transform failure writes RepairContextPack
- failure callback receives internal repair refs
- reviewed repair chain runs from those refs
- proposer LLM produces unified diff
- reviewer LLM reviews it
- reviewer accept creates exactly one current proposal
- reviewer non-accept creates no applyable proposal
- proposal checksum uses sha256_hex(raw diff bytes)
- Control Tower shows safe diff preview
- Control Tower shows reviewer notes
- user can approve with proposal_id + diff_checksum + idempotency_key only
- backend reloads exact stored diff from diff_ref
- backend blocks stale/modified/malformed diffs
- backend applies only to sandbox
- backend uses apply_patch_to_sandbox only
- apply failure does not run validation
- validation pass continues migration normally
- validation failure keeps patched sandbox
- validation failure creates next bounded repair attempt
- attempts stop at DEFAULT_MAX_REPAIR_ATTEMPTS
- UI does not expose raw paths, env, provider info, deployment info, gate internals, or artifact refs in primary display
```

---

## 7. Do Not Do

```text
Do not implement candidate diffs.
Do not recreate direct_reviewed/direct_candidate/materialization state machines.
Do not create a second apply path.
Do not require frontend gate_id for approve.
Do not require frontend reviewer_verdict_id for approve.
Do not rollback after successful apply + validation failure in the new direct flow.
Do not use canonical JSON diff checksum for proposal approval checksum.
Do not expose local paths in primary UI.
Do not revive the old Copilot repair loop.
Do not rewrite normal migration orchestration.
```

