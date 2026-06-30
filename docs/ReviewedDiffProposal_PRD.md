# ReviewedDiffProposal PRD — Governed LLM Repair UX for AI Migration Control Tower

**Document path to add in repo:** `docs/ReviewedDiffProposal_PRD.md`  
**Project:** AI MIGRATION / `modernizer-solution`  
**Active branch:** `demov3`  
**Feature name:** `LLM Repair Proposal + Reviewed Diff + User Revision Chat + Sandbox Apply + Rebuild/Test`  
**Core domain name:** `ReviewedDiffProposal`  
**Status:** Draft PRD, ready to add before PR-B  
**Last updated:** 2026-06-30 (contract hardening)

---

## 0. Current Status Snapshot

This document is the implementation control document for the `ReviewedDiffProposal` workflow. Every implementation session must update this file before handoff.

Current known branch state from latest reports:

```text
branch: demov3
HEAD:   73ab1fcb3081a83ceee6f08cd41722a8a00c01b9
```

Known dirty files from the active worktree may include:

```text
graphify-out/GRAPH_REPORT.md
graphify-out/graph.json
graphify-out/manifest.json
```

## Current Implementation Status

| Phase | Status | Commit/Branch | Files | Tests | Notes |
|---|---|---|---|---|---|
| Phase 0 / Plan | Done | branch `demov3`, HEAD `3420d429cba3fddd7c547f6e578e0e8d9b666dd4`, commit none | docs only | read-only audit completed | Existing F5 repair engine is reused, not replaced. |
| PR-A / Safe Read-Only Projection | Done | branch `demov3`, PR-A commit `9de9c17f322e646238821c8ee914a3683f9b5a3e`, route-progression fix commit `3420d429cba3fddd7c547f6e578e0e8d9b666dd4` | `migration_factory/control_tower/application/safe_diff_preview.py`; `migration_factory/control_tower/application/v2_model_schemas.py`; `migration_factory/control_tower/application/v2_repair_projection.py`; `tests/control_tower/test_safe_diff_preview.py`; `tests/control_tower/test_reviewed_diff_proposal_projection.py`; `migration_factory/control_tower/application/v2_stage_progression.py`; `tests/control_tower/test_v2_stage_progression.py`; `tests/control_tower/test_v2_orchestrator_runner.py`; `tests/control_tower/test_resume_from_checkpoint_profile.py` | `tests/control_tower/test_safe_diff_preview.py` 13 passed; `tests/control_tower/test_reviewed_diff_proposal_projection.py` 2 passed; `tests/control_tower/test_v2_repair_gate_service.py` 30 passed; `tests/control_tower/test_v2_stage_progression.py` 55 passed; `tests/control_tower/test_v2_worker_stage.py` 26 passed; `tests/control_tower/test_v2_orchestrator_runner.py` 50 passed; `tests/control_tower/test_resume_from_checkpoint_profile.py` 7 passed; `tests/control_tower/test_profile_validation.py` 17 passed; `tests/control_tower/test_profile_pair_validation.py` 5 passed; `tests/control_tower/test_run_configurations.py` 38 passed; `git diff --check` passed | PR-A projection is committed, and the route-progression baseline debt is fixed in the follow-up route-step commit. |
| PR-B / Durable Proposal Persistence + Read APIs | Done (contract hardening) | branch `demov3`, HEAD `cbfbcabf45b6d3d4990c2985f5eb4d4dbcddc407` (+ hardening commit) | `0048_v2_repair_proposals_reviewed_diff_fields.sql`, `v2_repair_repository.py`, `dto.py`, `v2_repair_projection.py`, `app.py`, `tests/control_tower/test_v2_repair_proposal_api.py`, `safe_diff_preview.py`, `docs/ReviewedDiffProposal_PRD.md` | PR-B focused tests 25 passed; all regression suites green; + HTTP contract tests; + checksum mismatch tests | Migration adds 16 nullable fields; 4 read-only GET endpoints added; no raw patch/path/env exposure; old records remain compatible; checksum mismatch flag added to SafeDiffPreview; HTTP route contract tests added. |
| PR-C / Cockpit Read-Only UI | Done | branch `demov3`, HEAD `73ab1fc` (+ PR-C commit) | `contracts.ts`, `controlTowerApi.ts`, `MigrationCockpit.tsx`, `RepairProposalPanel.tsx`, `ReviewedDiffTabs.tsx`, `SafeDiffPreview.tsx`, `ReviewerVerdictCard.tsx`, `RepairAttemptTimeline.tsx`, `RepairActionsBar.tsx`, `controlTowerApi.test.ts`, `migrationCockpit.test.tsx`, `reviewedDiffProposal.test.tsx` | Frontend API tests, component tests, cockpit integration tests, forbidden-field tests all pass; typecheck passes; build passes; backend PR-B/PR-A smoke tests pass | No mutation actions wired; no POST calls; no forbidden fields exposed; diff renders hunks/line numbers/redactions; checksum mismatch warning renders; attempt timeline renders; action bar shows disabled future controls. |
| PR-D / Revision Endpoint | Not Started | | | | Depends on PR-C. |
| PR-E / Approve/Apply Hardening | Not Started | | | | Depends on PR-D. |
| PR-F / Retry/Attempt History | Not Started | | | | Depends on PR-E. |
| PR-G / LLM Invocation Ledger | Not Started | | | | Later hardening phase. |

**Current blocker before PR-C:** none. PR-B contract hardening complete. HTTP route contract tests pass. Checksum mismatch detection added to SafeDiffPreview.

---

## 1. Executive Summary

The AI Migration Control Tower already has most of the repair engine needed for governed LLM-assisted migration repair:

- failure evidence generation,
- repair context packs,
- primary/main LLM repair proposal flow,
- reviewer LLM critique flow,
- repair gates,
- sandbox patch apply,
- validation rerun,
- rollback,
- events,
- artifact storage,
- cockpit traces.

The missing product layer is a first-class, durable, safe, user-facing `ReviewedDiffProposal` workflow.

The goal is not to create a new repair loop. The goal is to wrap and productize the existing F5 repair engine so that when a migration route step fails, the user can see exactly what the system proposes to change, review the final reviewed diff, talk to the LLM about the proposal, request revisions, approve sandbox application, rerun validation, and continue the migration if validation passes.

The core principle is:

```text
LLM proposes.
Reviewer LLM reviews.
Backend validates.
User approves.
Backend applies to sandbox only.
Backend rebuilds/tests.
Migration continues only if evidence is green.
```

---

## 2. Product Problem

Today, the system can generate repair evidence and reviewed repair artifacts, but the cockpit does not yet expose them as a complete product workflow.

When a migration step fails, especially during build/test after OpenRewrite changes, the user needs more than a generic failure message. They need:

1. a clear failure summary,
2. main LLM diagnosis,
3. proposed repair plan,
4. reviewer LLM opinion,
5. exact file-by-file diff,
6. files changed and risk/static analysis,
7. a place to ask questions,
8. a place to request changes to the proposal,
9. an approval action that applies only a reviewed checksum-bound diff to the sandbox,
10. validation results after apply,
11. attempt history if the first repair does not pass.

Example product scenario:

```text
Route Step 2:
springboot-2.7-java11 -> springboot-3.5-java17

OpenRewrite runs.
Maven build fails.
Root cause appears to be an old dependency or javax/jakarta mismatch not fully handled by OpenRewrite.

Main LLM diagnoses the issue and proposes a patch.
Reviewer LLM reviews the patch.
User sees the reviewed final diff.
User can approve or request a smaller/different patch.
Backend applies only the approved reviewed diff to the sandbox.
Backend reruns Maven validation.
If green, route continues.
```

---

## 3. Scope

### 3.1 In Scope

The feature covers:

- `ReviewedDiffProposal` domain model and lifecycle,
- safe unified diff preview,
- reviewed final diff display,
- durable proposal persistence,
- job-scoped proposal APIs,
- user proposal explanation chat,
- user revision request flow,
- reviewer re-review of revised proposal,
- proposal approval hardening,
- sandbox-only apply,
- validation rerun,
- route resume after validation pass,
- next repair attempt after validation fail,
- attempt history and terminal summary,
- later LLM invocation ledger hardening.

### 3.2 Out of Scope

Do not include in this feature unless a later phase explicitly authorizes it:

- new repair engine,
- new route runner,
- LangGraph replacement for route execution,
- direct frontend execution controls,
- raw command/argv/env controls,
- raw patch upload or frontend patch-as-authority,
- editing original legacy source,
- bypassing human/user approval,
- applying reviewer-accepted patches without backend validation,
- exposing Azure endpoints, keys, deployment secrets, raw sandbox paths, DB paths, or local filesystem internals.

---

## 4. Design Principles

### 4.1 Backend Authority

The backend owns:

- route computation,
- route-step status,
- runtime profile selection,
- JDK selection,
- command manifest execution,
- artifact registration,
- gate state,
- checksum validation,
- patch gate validation,
- sandbox apply,
- rollback,
- validation/build/test execution,
- retry budget,
- `migration_completed`.

### 4.2 LLM Advisory Role

The LLM owns:

- explanation,
- diagnosis narrative,
- repair hypothesis,
- repair proposal,
- diff explanation,
- reviewer critique,
- user-facing reasoning,
- missing-context requests.

The LLM does not execute commands, directly edit files, apply patches, approve gates, or bypass backend validation.

### 4.3 User Control

The user must be able to:

- read the proposal,
- inspect the diff,
- ask explanation questions,
- request changes,
- reject the proposal,
- approve sandbox apply.

The user must not be asked to approve blind changes.

### 4.4 Sandbox Boundary

All repair application happens only inside the controlled migration sandbox copy. The original legacy source is never modified.

---

## 5. Existing Systems To Reuse

Do not duplicate these systems.

| Need | Existing system to reuse |
|---|---|
| Route-step authority | `migration_factory/control_tower/application/v2_stage_progression.py` |
| Worker/orchestrator failure visibility | `migration_factory/control_tower/application/v2_orchestrator_runner.py` |
| Failure evidence | `migration_factory/repair_loop/failure_evidence.py` |
| Repair context | `migration_factory/repair_loop/repair_context.py` |
| Redaction | `migration_factory/control_tower/application/context_pack_redaction.py`, `migration_factory/control_tower/application/redaction.py` |
| Primary/reviewer repair chain | `migration_factory/orchestrator/repair_review_chain.py` |
| Reviewer critiques | `migration_factory/control_tower/application/v2_reviewer_service.py`, `migration_factory/control_tower/infrastructure/sqlite/v2_reviewer_repository.py` |
| Repair gates | `migration_factory/control_tower/application/v2_repair_gate_service.py` |
| Repair flow/apply | `migration_factory/control_tower/application/v2_repair_flow.py` |
| Patch policy | `migration_factory/repair_loop/patch_gate.py` |
| Sandbox apply | `migration_factory/repair_loop/patch_apply.py` |
| Validation rerun | `migration_factory/repair_loop/validation_runner.py` |
| Artifacts | `ArtifactRecord`, V2 artifact revisions, `artifact_written` events |
| FastAPI cockpit API | `migration_factory/control_tower/adapters/fastapi/app.py` |
| Migration cockpit | `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` |

---

## 6. Current Persistence Audit

### 6.1 `v2_repair_proposals`

Existing table:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/0033_v2_repairs.sql
```

Existing columns:

```text
proposal_id
command_id
failure_summary
hypothesis
patch_summary
affected_paths_json
status
approval_checksum
created_at
```

Revision metadata added by:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/0045_v2_repair_proposals_revision_metadata.sql
```

Added columns:

```text
source_proposal_id
revision_of
revision_number
context_pack_checksum
allowed_scope
proposal_checksum
```

Repository:

```text
migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
```

Known methods:

```text
save_proposal
get_proposal
list_proposals_by_command
update_proposal_status
```

Gap:

```text
The table is command-scoped, not clearly job/route-step/proposal-review scoped.
It does not persist diff_ref, diff_checksum, reviewer_verdict_ref, gate_id,
attempt_number, safe_diff_preview_ref, or status_reason.
```

### 6.2 `v2_sandbox_actions`

Existing table from `0033_v2_repairs.sql`:

```text
action_id
proposal_id
target_path
patch_content
status
result_summary
created_at
```

Critical warning:

```text
Do not reuse v2_sandbox_actions public projection for ReviewedDiffProposal.
It can expose target_path and patch previews. The ReviewedDiffProposal API must expose safe artifact refs, checksums, and SafeDiffPreview only.
```

### 6.3 `v2_reviewer_critiques`

Existing table:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/0036_v2_reviewer_critiques.sql
```

Columns:

```text
critique_id
proposal_id
proposal_type
proposal_checksum
context_pack_checksum
decision
reasoning
missing_evidence_json
unsafe_assumptions_json
model_invocation_id
created_at
```

Repository:

```text
migration_factory/control_tower/infrastructure/sqlite/v2_reviewer_repository.py
```

Known methods:

```text
save_critique
get_critique
list_critiques_by_proposal
get_latest_accepted
```

Important behavior:

```text
Reviewer accept is not human approval.
Reviewer accept only makes a proposal eligible for a backend/user gate.
```

### 6.4 Gates

Existing table:

```text
v2_phase_gates
```

Migration:

```text
0039_v2_phase_gates.sql
0046_v2_stage4_support.sql
```

Key fields:

```text
gate_id
job_id
gate_phase
stage_index
gate_status
gate_decision
source_artifact_checksum
resolved_artifact_checksum
source_artifact_refs_json
created_at
resolved_at
resolved_by
```

Service:

```text
migration_factory/control_tower/application/v2_repair_gate_service.py
```

Known methods:

```text
create_repair_gate_from_reviewed_chain
request_repair_revision
regenerate_reviewed_repair_chain_on_revision
approve_repair
reject_repair
handle_repair_validation_result
create_next_repair_cycle_from_rerun_failure
```

Gate responsibility:

```text
Gates pause user review and resume/resolve repair flow after approval, rejection, revision, validation pass, or validation failure.
```

### 6.5 Events

Existing table:

```text
v2_job_events
```

Existing relevant events:

```text
repair_failure_evidence_written
repair_context_pack_written
reviewer_critique_created
repair_patch_gate_completed
repair_patch_applied
repair_validation_completed
repair_rollback_completed
artifact_written
model_invocation_started
model_invocation_completed
model_invocation_failed
```

Need product lifecycle events:

```text
repair_failure_detected
repair_evidence_created
llm_repair_diagnosis_started
llm_repair_diagnosis_completed
llm_repair_patch_proposed
repair_diff_materialized
llm_repair_review_started
llm_repair_review_completed
repair_proposal_ready_for_user
repair_revision_requested
repair_proposal_revised
repair_proposal_rejected
repair_proposal_approved
repair_sandbox_apply_started
repair_sandbox_apply_completed
repair_validation_started
repair_validation_passed
repair_validation_failed
repair_retry_scheduled
repair_retry_exhausted
```

### 6.6 Artifacts

Repair review chain currently writes:

```text
primary_repair_llm_output.json
reviewer_repair_llm_output.json
final_reviewed_repair.diff
review_chain.json
```

Important rule:

```text
The cockpit must show final_reviewed_repair.diff / reviewer-reviewed final diff, not an unreviewed primary draft.
```

### 6.7 Model Invocations

Existing table:

```text
v1_model_invocations
```

Migration:

```text
0015_v1_model_invocations.sql
```

Known fields include:

```text
invocation_id
job_id
profile_id
provider_kind
model_name
token counts
redacted_summary
actor/correlation fields
```

Gap:

```text
No durable role, responsibility, context_checksum, output_checksum,
fallback_used, or safe deployment alias/hash.
It cannot robustly prove proposer_invocation_id != reviewer_invocation_id.
```

Later solution:

```text
Add v2_llm_invocations in PR-G or earlier if gate policy requires it.
```

---

## 7. Persistence Decision

Decision: **Hybrid**.

Use the existing persistence spine:

```text
v2_repair_proposals      = proposal identity/status/revision anchor
v2_reviewer_critiques    = reviewer verdict storage
v2_phase_gates           = human approval and pause/resume authority
artifacts/events         = diagnosis, plan, diff, preview, attempt history
```

Do not create a brand-new `v2_reviewed_diff_proposals` table first.

Extend `v2_repair_proposals` later in PR-B.

Planned migration:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/0048_v2_repair_proposals_reviewed_diff_fields.sql
```

Planned fields:

```text
job_id
route_step_index
attempt_number
failure_evidence_ref
repair_context_ref
diagnosis_ref
repair_plan_ref
diff_ref
diff_checksum
safe_diff_preview_ref
reviewer_verdict_id
reviewer_verdict_ref
reviewer_output_checksum
policy_validation_checksum
gate_id
status_reason
```

Planned indexes:

```text
(job_id, created_at)
(job_id, status)
(gate_id)
(source_proposal_id)
```

Compatibility rule:

```text
Existing command-scoped proposals must continue to load.
New fields must be nullable or backfilled safely.
Projection code must tolerate old records with missing reviewed-diff fields.
```

---

## 8. Diff Lifecycle

### 8.1 `main_proposed_diff`

Produced by the main/proposer LLM.

It is useful for reviewer input, but it is not the final user-approvable diff.

### 8.2 `reviewer_reviewed_diff`

Current reviewed final diff artifact:

```text
final_reviewed_repair.diff
```

This is what the UI must show.

### 8.3 `user_approved_diff`

Created conceptually when the user approves:

```text
proposal_id
diff_checksum
reviewer_verdict_id
gate_id
```

The frontend must not submit patch text.

### 8.4 `applied_diff`

Backend reloads the reviewed diff artifact, recomputes checksum, validates proposal/gate/verdict state, runs patch gate, applies to sandbox only, and records validation result.

---

## 9. `SafeDiffPreview` Contract

### 9.1 Purpose

`SafeDiffPreview` converts reviewed unified diff text into a UI-safe structured preview. It is not execution authority. It is a display artifact/projection.

### 9.2 Schema

```ts
type SafeDiffPreview = {
  proposal_id: string
  diff_ref: string | null
  diff_checksum: string
  files: SafeDiffFile[]
  total_additions: number
  total_deletions: number
  truncated: boolean
  redactions: string[]
}

type SafeDiffFile = {
  path: string
  change_type: "added" | "modified" | "deleted" | "renamed" | "binary"
  additions: number
  deletions: number
  hunks: SafeDiffHunk[]
  truncated: boolean
}

type SafeDiffHunk = {
  old_start: number
  old_lines: number
  new_start: number
  new_lines: number
  section_header?: string
  lines: SafeDiffLine[]
}

type SafeDiffLine = {
  kind: "context" | "addition" | "deletion"
  old_line_number?: number
  new_line_number?: number
  text: string
  redacted: boolean
}
```

### 9.3 Parser Requirements

Must parse:

```text
diff --git a/path b/path
--- a/path
+++ b/path
@@ -old_start,old_lines +new_start,new_lines @@ optional section
```

Must support:

```text
modified files
added files
deleted files
renamed files
binary markers
old/new line number tracking
per-file addition/deletion counts
total addition/deletion counts
```

### 9.4 Sanitization Requirements

Expose only normalized safe relative paths.

Block or redact:

```text
absolute Unix paths
Windows drive paths such as C:\...
UNC paths such as \\server\share
/Users/...
/home/...
repo-root-like local paths
..
NUL bytes
control characters
secret-looking values
raw sandbox paths
local checkout paths
```

Secret-like lines include:

```text
api_key=...
password=...
Authorization: Bearer ...
AZURE_OPENAI_API_KEY=...
```

### 9.5 Bounds

```text
max files: 20
max hunks per file: 30
max lines per hunk: 200
max total lines: 3000
max total bytes: 200 KB
max line length: 300 chars
```

When bounds are exceeded:

```text
truncated = true
preserve safe summary/counts where possible
do not expose omitted raw content
```

### 9.6 Checksum

`diff_checksum` must be SHA-256 over exact reviewed diff bytes/string content, not over the sanitized preview.

When a stored `diff_checksum` exists and the recomputed SHA-256 of the loaded diff differs, `SafeDiffPreview.checksum_mismatch` is set to `True`. The diff endpoint returns the preview with the mismatch flag but never exposes the raw filesystem path. A proposal with a checksum mismatch must not be marked approvable (enforced in PR-E).

---

## 10. `ReviewedDiffProposal` Contract

### 10.1 Purpose

`ReviewedDiffProposal` is the safe product projection that ties together:

- failure context,
- diagnosis,
- repair plan,
- reviewed final diff,
- reviewer verdict,
- gate state,
- allowed user actions,
- safe diff preview,
- attempt metadata.

### 10.2 Schema

```ts
type ReviewedDiffProposal = {
  proposal_id: string
  job_id?: string
  command_id?: string
  gate_id?: string
  route_step_index?: number
  stage_index?: number
  status: ReviewedDiffProposalStatus
  attempt_number?: number
  revision_number?: number
  failure_summary?: string
  diagnosis_ref?: string
  repair_plan_ref?: string
  diff_ref: string
  diff_checksum: string
  safe_diff_preview: SafeDiffPreview
  reviewer_verdict: ReviewerVerdictProjection
  files_changed: FilesChangedSummary[]
  risk?: "LOW" | "MEDIUM" | "HIGH" | "UNKNOWN"
  required_validation: string[]
  allowed_actions: ReviewedDiffProposalAction[]
  redactions: string[]
}
```

### 10.3 Status Enum

```text
failure_detected
evidence_created
main_diagnosis_created
patch_proposed
diff_materialized
reviewer_reviewing
reviewer_accepted
reviewer_requested_revision
reviewer_rejected
user_review_required
user_requested_revision
user_rejected
user_approved
sandbox_apply_pending
sandbox_patch_applied
validation_running
validation_passed
validation_failed
retry_scheduled
exhausted
superseded
unknown
```

### 10.4 Allowed Actions

Read-only actions for PR-A/PR-B:

```text
view_diff
view_reviewer_opinion
view_files_changed
ask_explanation
view_attempt_history
```

Mutation actions only after PR-D/PR-E:

```text
request_revision
reject_proposal
approve_sandbox_apply
```

`approve_sandbox_apply` must only appear when backend proves the proposal is approvable.

---

## 11. User Experience

### 11.1 Cockpit Panel

Create a proposal panel under:

```text
web/control-tower/app/migrations/[jobId]/
```

Potential components:

```text
RepairProposalPanel.tsx
ReviewedDiffTabs.tsx
SafeDiffPreview.tsx
ReviewerVerdictCard.tsx
RepairChatRevisionBox.tsx
RepairAttemptTimeline.tsx
RepairActionsBar.tsx
```

### 11.2 Tabs

```text
Diff
Static Analysis
Files Changed
Reviewer Opinion
Chat
```

### 11.3 Diff Display

UI must show:

```text
safe relative file path
change type
additions/deletions
hunks
old/new line numbers
redacted line marker
truncation banner
```

UI must not show:

```text
raw sandbox path
raw local path
raw env
raw argv
raw command
secret values
Azure key/endpoint
raw patch as execution authority
```

### 11.4 Chat Modes

#### Explain Mode

Use when user asks:

```text
Why did this dependency change?
What is this line doing?
Why did the reviewer accept this?
What will happen if I apply it?
```

Explain mode:

```text
no mutation
no new proposal
no file edit
no patch apply
```

#### Revise Mode

Use when user asks:

```text
Do not update all dependencies.
Only update validation.
Do not touch application.properties.
Use version X instead.
Generate a smaller patch.
```

Revision mode:

```text
creates UserRevisionRequest
creates new main LLM proposal
creates new reviewer verdict
creates new SafeDiffPreview
old proposal remains immutable/superseded
```

---

## 12. API Plan

### 12.1 PR-B Read APIs

```http
GET /v1/v2/jobs/{job_id}/repair/proposals/current
GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}
GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/diff
GET /v1/v2/jobs/{job_id}/repair/attempts
```

Rules:

```text
read-only
safe projection only
no raw patch text
no raw sandbox path
no raw command/env/argv
job/proposal ownership validated
server-side checksum recomputed
```

### 12.2 PR-D Chat/Revision APIs

```http
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/chat
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/revise
```

`chat` is explanation-only unless explicitly classified as revision.

`revise` request:

```json
{
  "user_instruction": "Do not update all dependencies. Only update validation.",
  "previous_diff_checksum": "sha256:...",
  "previous_reviewer_verdict_id": "...",
  "idempotency_key": "..."
}
```

### 12.3 PR-E Approval APIs

```http
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/approve
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/reject
```

Approval request:

```json
{
  "proposal_id": "...",
  "diff_checksum": "sha256:...",
  "reviewer_verdict_id": "...",
  "gate_id": "...",
  "expected_gate_checksum": "sha256:...",
  "idempotency_key": "..."
}
```

Backend must reload all state server-side before apply.

---

## 13. Backend Flow

```text
route_step_build_or_test_failed
  -> repair_failure_detected
  -> failure_evidence_created
  -> repair_context_pack_created
  -> main_llm_diagnosis_started
  -> main_llm_repair_proposed
  -> backend_schema_checksum_validation
  -> reviewer_llm_review_started
  -> reviewer_verdict_created
  -> backend_reviewer_validation
  -> reviewed_diff_materialized
  -> repair_proposal_ready_for_user
  -> user reviews diff in cockpit
```

If user requests revision:

```text
user_revision_requested
  -> UserRevisionRequest artifact
  -> main LLM revises proposal
  -> reviewer LLM reviews revised diff
  -> new ReviewedDiffProposal
  -> user_review_required
```

If user approves:

```text
user_approved
  -> backend reloads proposal/diff/verdict/gate
  -> verifies checksums and state
  -> patch gate
  -> sandbox apply
  -> validation rerun
  -> validation_passed => route continues
  -> validation_failed => next attempt or exhausted
```

---

## 14. Security Rules

### 14.1 Forbidden Public Fields

No public API, frontend, event projection, artifact preview, or handoff may expose:

```text
raw sandbox path
absolute local path
raw env
raw argv
raw command
secrets
Azure key
Azure endpoint
DB/cache path
unchecked local filesystem internals
raw provider deployment internals unless explicitly product-approved
raw patch text as execution authority
```

### 14.2 Reviewer Accept Is Not Apply

Reviewer `accept` means:

```text
proposal is eligible for backend/user gate review
```

Reviewer `accept` does not mean:

```text
patch can apply automatically
```

### 14.3 Frontend Is Not Executor

Frontend may send:

```text
proposal_id
diff_checksum
reviewer_verdict_id
gate_id
idempotency_key
user instruction
```

Frontend must not send:

```text
patch text
raw path
command
argv
env
JDK path
sandbox path
```

---

## 15. Test Strategy

### 15.1 Backend Tests

Core tests:

```text
tests/control_tower/test_safe_diff_preview.py
tests/control_tower/test_reviewed_diff_proposal_projection.py
tests/control_tower/test_v2_repair_proposal_api.py
tests/control_tower/test_v2_repair_revision_flow.py
tests/control_tower/test_v2_repair_approve_apply.py
tests/control_tower/test_v2_repair_attempt_history.py
```

Required coverage:

```text
safe diff parses additions/deletions/context
safe diff parses added/deleted/renamed/binary files
safe diff rejects/redacts absolute Unix paths
safe diff rejects/redacts Windows drive paths
safe diff rejects/redacts UNC paths
safe diff rejects/redacts /Users and /home paths
safe diff rejects .. and NUL/control chars
safe diff redacts secret-looking values
safe diff truncates huge diffs
checksum changes when diff changes
projection uses final reviewed diff, not unreviewed draft
projection exposes only safe refs/checksums/relative paths
read APIs expose no forbidden fields
revision creates new proposal and no file mutation
approve requires proposal_id + diff_checksum + reviewer_verdict_id + gate_id
reviewer accept alone does not apply
sandbox-only apply
validation reruns after apply
validation pass continues route
validation fail creates next attempt
retry budget stops attempts
```

Route safety regressions:

```powershell
py -3 -m pytest tests/control_tower/test_v2_stage_progression.py -q
py -3 -m pytest tests/control_tower/test_v2_orchestrator_runner.py -q
py -3 -m pytest tests/control_tower/test_v2_repair_gate_service.py -q
```

Known current issue:

```text
test_v2_stage_progression.py has reported failures. Before PR-B, perform clean baseline comparison at the same HEAD.
```

### 15.2 Frontend Tests

```text
web/control-tower/tests/migrationCockpit.test.tsx
web/control-tower/tests/reviewedDiffProposal.test.tsx
```

Required coverage:

```text
proposal panel renders failure summary
diff tab renders files/additions/deletions/hunks
reviewer verdict renders accept/revise/reject
explanation chat does not revise
revision chat submits user instruction
approve sends only IDs/checksums/gate
no raw path/env/argv/endpoint/key displayed
reject/revise/approve states render correctly
route_steps override legacy stages
validation result after apply updates UI
```

---

## 16. Implementation Phases And Completion Checklist

### 16.1 Phase 0 — Planning Audit

Status: **Done**

Evidence:

```text
Read-only analysis completed.
Hybrid persistence decision chosen.
SafeDiffPreview design defined.
Diff lifecycle defined.
PR split defined.
```

Completion checklist:

- [x] Existing repair persistence audited.
- [x] Diff lifecycle defined.
- [x] SafeDiffPreview schema defined.
- [x] Proposal chat modes defined.
- [x] Pause/resume state defined.
- [x] Model invocation proof gap identified.
- [x] PR split defined.

### 16.2 PR-A — Safe Read-Only Projection

Status: **Done**

Goal:

```text
Add SafeDiffPreview parser/sanitizer and ReviewedDiffProposal read-only projection.
No apply, no revision, no DB migration.
```

Completion record:

```text
Date/time: 2026-06-30 12:47:07 +01:00
Branch: demov3
HEAD: 3420d429cba3fddd7c547f6e578e0e8d9b666dd4
Changed files:
  migration_factory/control_tower/application/safe_diff_preview.py
  migration_factory/control_tower/application/v2_model_schemas.py
  migration_factory/control_tower/application/v2_repair_projection.py
  tests/control_tower/test_safe_diff_preview.py
  tests/control_tower/test_reviewed_diff_proposal_projection.py
Implemented:
  SafeDiffPreview
  safe unified diff parser/sanitizer
  reviewed final diff projection
  reviewer verdict projection
  files-changed summary
  conservative read-only actions
  redaction/truncation/path safety
  checksum from exact reviewed diff bytes
Tests:
  py -3 -m pytest tests/control_tower/test_safe_diff_preview.py -q
  py -3 -m pytest tests/control_tower/test_reviewed_diff_proposal_projection.py -q
  py -3 -m pytest tests/control_tower/test_v2_repair_gate_service.py -q
  py -3 -m pytest tests/control_tower/test_v2_stage_progression.py -q -vv --tb=short
  clean baseline worktree comparison at HEAD 6dec64d726f4932c798f10652c8969be27989012
  git diff --check
Route-progression result: the 13 stage-progression failures were fixed in commit `3420d429cba3fddd7c547f6e578e0e8d9b666dd4`; focused route/projection tests are now green.
```

Files changed in reported PR-A:

```text
migration_factory/control_tower/application/safe_diff_preview.py
migration_factory/control_tower/application/v2_model_schemas.py
migration_factory/control_tower/application/v2_repair_projection.py
tests/control_tower/test_safe_diff_preview.py
tests/control_tower/test_reviewed_diff_proposal_projection.py
```

Reported passing tests:

```powershell
py -3 -m pytest tests/control_tower/test_safe_diff_preview.py -q
py -3 -m pytest tests/control_tower/test_reviewed_diff_proposal_projection.py -q
py -3 -m pytest tests/control_tower/test_v2_repair_gate_service.py -q
```

Reported failing test that was baseline-verified:

```powershell
py -3 -m pytest tests/control_tower/test_v2_stage_progression.py -q
```

Closeout checklist:

- [x] SafeDiffPreview parser/sanitizer added.
- [x] ReviewedDiffProposal projection added.
- [x] Focused PR-A tests pass.
- [x] No DB migration added.
- [x] No apply/revision/LangGraph added.
- [x] Accidental `docs/repair-loop.md` removed.
- [x] Baseline comparison proves `test_v2_stage_progression.py` failures are unrelated to PR-A.
- [ ] PR-A files are staged/committed without Graphify files.
- [ ] This document updated with final PR-A commit hash and test evidence.

PR-A implementation is complete. PR-B remains blocked by unrelated route-progression debt until the user accepts that baseline failure or a separate fix lands.

### 16.3 PR-B — Durable Proposal Persistence + Job-Scoped Read APIs

Status: **Done**

Goal:

```text
Extend v2_repair_proposals for reviewed-diff fields and expose read-only job-scoped APIs.
```

Planned files:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/0048_v2_repair_proposals_reviewed_diff_fields.sql
migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
migration_factory/control_tower/application/dto.py
migration_factory/control_tower/application/v2_repair_projection.py
migration_factory/control_tower/adapters/fastapi/app.py
tests/control_tower/test_v2_repair_proposal_api.py
```

Planned endpoints:

```http
GET /v1/v2/jobs/{job_id}/repair/proposals/current
GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}
GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/diff
GET /v1/v2/jobs/{job_id}/repair/attempts
```

Completion record:

```text
Date/time: 2026-06-30
Branch: demov3
HEAD: cbfbcabf45b6d3d4990c2985f5eb4d4dbcddc407

Committed: cbfbcab feat(control-tower): add reviewed diff proposal read APIs

Changed files:
  migration_factory/control_tower/infrastructure/sqlite/migrations/0048_v2_repair_proposals_reviewed_diff_fields.sql
  migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py
  migration_factory/control_tower/application/dto.py
  migration_factory/control_tower/application/v2_repair_projection.py
  migration_factory/control_tower/adapters/fastapi/app.py
  tests/control_tower/test_v2_repair_proposal_api.py

Migration: 0048_v2_repair_proposals_reviewed_diff_fields.sql — ALTER TABLE ADD COLUMN for 16 nullable fields

Endpoints added:
  GET /v1/v2/jobs/{job_id}/repair/proposals/current
  GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}
  GET /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/diff
  GET /v1/v2/jobs/{job_id}/repair/attempts

Persistence changes:
  V2RepairProposalRecord extended with job_id, route_step_index, attempt_number,
  failure_evidence_ref, repair_context_ref, diagnosis_ref, repair_plan_ref,
  diff_ref, diff_checksum, safe_diff_preview_ref, reviewer_verdict_id,
  reviewer_verdict_ref, reviewer_output_checksum, policy_validation_checksum,
  gate_id, status_reason
  New repository methods: list_proposals_by_job, get_proposal_for_job,
  get_current_proposal_for_job, list_attempts_by_job

Security rules enforced:
  - No raw sandbox path, argv, env, raw_command in API responses
  - No endpoint exposes target_path or patch_content
  - No mutation endpoints (no POST)
  - API validates job/proposal ownership
  - Diff endpoint returns SafeDiffPreview only

Tests:
  tests/control_tower/test_v2_repair_proposal_api.py — 25 passed (unit) + 14 HTTP contract tests added
  tests/control_tower/test_safe_diff_preview.py — 13 passed
  tests/control_tower/test_reviewed_diff_proposal_projection.py — 2 passed
  tests/control_tower/test_v2_repair_gate_service.py — 30 passed
  tests/control_tower/test_v2_stage_progression.py — 55 passed
  tests/control_tower/test_v2_worker_stage.py — 26 passed
  tests/control_tower/test_v2_orchestrator_runner.py — 50 passed
  tests/control_tower/test_resume_from_checkpoint_profile.py — 7 passed
  tests/control_tower/test_profile_validation.py — 17 passed
  tests/control_tower/test_profile_pair_validation.py — 5 passed
  tests/control_tower/test_run_configurations.py — 38 passed
  git diff --check — no whitespace errors

Contract hardening (post-PR-B commit):
  - 14 HTTP route contract tests using FastAPI TestClient
  - Checksum mismatch detection added to SafeDiffPreview
  - checksum_mismatch bool field in SafeDiffPreview dataclass
  - stored_diff_checksum parameter added to build_safe_diff_preview
  - Diff endpoint passes stored checksum; mismatch returns flag
  - Responses verified for forbidden keys/patterns
  - No filesystem paths in error responses
```

Completion checklist:

- [x] Migration adds nullable reviewed-diff fields.
- [x] Repository supports job-scoped current/detail/list retrieval.
- [x] Read APIs return safe projections only.
- [x] Diff endpoint returns `SafeDiffPreview` only.
- [x] No mutation endpoints added.
- [x] No raw patch/path/env/argv exposed.
- [x] Existing old repair proposal records remain compatible.
- [x] Current proposal survives backend restart.
- [x] Tests pass.
- [x] HTTP route contract tests use FastAPI TestClient (14 tests).
- [x] All 4 GET endpoints tested for stable shape.
- [x] Forbidden key/value patterns asserted at HTTP level.
- [x] Checksum mismatch detection added to SafeDiffPreview.
- [x] Diff endpoint passes stored checksum; mismatch flag returned safely.
- [x] Error responses never include filesystem paths.

### 16.4 PR-C — Cockpit Read-Only Proposal/Diff UI

Status: **Done**

Goal:

```text
Render failure, diagnosis, repair plan, reviewer opinion, safe diff, files changed, and attempt timeline.
```

Completion record:

```text
Date/time: 2026-06-30
Branch: demov3
HEAD: 73ab1fcb3081a83ceee6f08cd41722a8a00c01b9 (+ PR-C commit)

Changed files:
  web/control-tower/lib/contracts.ts
  web/control-tower/lib/controlTowerApi.ts
  web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx
  web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx
  web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx
  web/control-tower/app/migrations/[jobId]/SafeDiffPreview.tsx
  web/control-tower/app/migrations/[jobId]/ReviewerVerdictCard.tsx
  web/control-tower/app/migrations/[jobId]/RepairAttemptTimeline.tsx
  web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx
  web/control-tower/tests/controlTowerApi.test.ts
  web/control-tower/tests/migrationCockpit.test.tsx
  web/control-tower/tests/reviewedDiffProposal.test.tsx

New types:
  SafeDiffLine, SafeDiffHunk, SafeDiffFile, SafeDiffPreview,
  ReviewerVerdictProjection, FilesChangedSummary, ReviewedDiffProposal,
  RepairProposalCurrentResponse, RepairProposalDetailResponse,
  RepairProposalDiffResponse, RepairAttemptSummary, RepairAttemptsResponse

API client methods (read-only GET):
  getCurrentRepairProposal(jobId)
  getRepairProposal(jobId, proposalId)
  getRepairProposalDiff(jobId, proposalId)
  getRepairAttempts(jobId)

Components added:
  RepairProposalPanel — fetches current proposal, renders failure summary/status/gate/route step
  ReviewedDiffTabs — 5 tabs: Diff, Static Analysis, Files Changed, Reviewer Opinion, Chat
  SafeDiffPreview — renders hunks with old/new line numbers, truncation/checksum/redaction warnings
  ReviewerVerdictCard — renders decision, reasoning, missing evidence, unsafe assumptions
  RepairAttemptTimeline — renders attempt entries with status/checksums/revisions
  RepairActionsBar — read-only view buttons + disabled future mutation buttons

Security rules enforced:
  - No POST/PUT/PATCH/DELETE methods added
  - No raw target_path, patch_content, sandbox_path, argv, env, raw_command in any component
  - No Azure endpoints, keys, deployment secrets rendered
  - No Bearer tokens, passwords, or authorization headers rendered
  - No C:\ /Users/ /home/ filesystem paths rendered
  - Diff paths are safe relative paths from SafeDiffPreview
  - Redacted lines show [redacted] instead of raw content
  - Checksum mismatch shows clear warning that proposal cannot be approved
  - Mutation buttons are disabled with "Coming in PR-D/PR-E" titles
  - No click handlers for mutation actions

Tests:
  controlTowerApi.test.ts — 11 new tests: URL verification, method GET, null proposal, diff reason, attempts, forbidden fields
  reviewedDiffProposal.test.tsx — 16 component tests across SafeDiffPreview, ReviewerVerdictCard, RepairAttemptTimeline, RepairActionsBar, forbidden-field enforcement
  migrationCockpit.test.tsx — 5 integration tests: component reference, route_step override, no POST, forbidden fields
```

Completion checklist:

- [x] Contracts added for proposal/diff/verdict/attempts.
- [x] API client methods added for read endpoints.
- [x] Proposal panel renders in migration cockpit.
- [x] Diff tab renders additions/deletions/context.
- [x] Reviewer verdict card renders.
- [x] Files changed tab renders.
- [x] Attempt timeline renders.
- [x] Buttons are disabled/read-only unless backend exposes allowed mutation action.
- [x] No forbidden fields display.
- [x] Tests pass.

### 16.5 PR-D — User Revision Lifecycle

Status: **Not started**

Goal:

```text
Let user request proposal changes without direct mutation.
```

Planned endpoint:

```http
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/revise
```

Reuse:

```text
V2RepairGateService.request_repair_revision
regenerate_reviewed_repair_chain_on_revision
v2_repair_flow.create_revision_proposal
```

Completion checklist:

- [ ] Revision request validates job/proposal/gate ownership.
- [ ] Backend loads previous diff/verdict server-side.
- [ ] UserRevisionRequest artifact created.
- [ ] No file mutation occurs on revision request.
- [ ] New proposal created.
- [ ] Reviewer reviews revised diff.
- [ ] Old proposal marked superseded/revised.
- [ ] New proposal becomes user-review-required.
- [ ] Tests pass.

### 16.6 PR-E — Approval / Apply / Validation Hardening

Status: **Not started**

Goal:

```text
Apply only an approved, reviewed, checksum-validated diff to sandbox and rerun validation.
```

Planned endpoint:

```http
POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/approve
```

Required request fields:

```text
proposal_id
diff_checksum
reviewer_verdict_id
gate_id
expected_gate_checksum
idempotency_key
```

Completion checklist:

- [ ] Backend requires proposal/checksum/verdict/gate IDs.
- [ ] Backend rejects raw patch text.
- [ ] Backend reloads all state server-side.
- [ ] Reviewer accepted verdict verified.
- [ ] Patch gate passed.
- [ ] Sandbox scope verified.
- [ ] Human/user approval actor recorded.
- [ ] Sandbox apply executed.
- [ ] Validation rerun executed.
- [ ] Validation pass resumes route.
- [ ] Validation fail creates next repair attempt.
- [ ] Tests pass.

### 16.7 PR-F — Retry / Attempt History / Terminal Summary

Status: **Not started**

Goal:

```text
Persist and display repair attempts, validation results, retry budget, and terminal summaries.
```

Completion checklist:

- [ ] Attempt history API returns proposals/verdicts/validation results.
- [ ] Previous proposal/verdict/validation refs included in next repair context.
- [ ] Retry budget visible.
- [ ] Terminal exhausted state visible.
- [ ] `repair_attempt_summary.md` artifact created.
- [ ] `final_llm_assisted_resolution.md` artifact created when exhausted.
- [ ] UI renders attempt timeline.
- [ ] Tests pass.

### 16.8 PR-G — LLM Invocation Ledger Hardening

Status: **Deferred**

Goal:

```text
Persist governed LLM invocation proof for proposer/reviewer/fallback telemetry.
```

Planned migration:

```text
0049_v2_llm_invocations.sql
```

Planned fields:

```text
invocation_id
job_id
proposal_id
gate_id
role
responsibility
provider_alias
deployment_alias_hash
context_checksum
input_checksum
output_checksum
schema_name
status
fallback_used
redacted_error
redacted_summary
prompt_tokens
completion_tokens
total_tokens
latency_ms
created_at
```

Completion checklist:

- [ ] Proposer invocation persisted.
- [ ] Reviewer invocation persisted.
- [ ] Proposer and reviewer invocation IDs are distinct.
- [ ] Context checksum persisted.
- [ ] Output checksum persisted.
- [ ] Fallback use persisted.
- [ ] Deployment shown as safe alias/hash only.
- [ ] Tests pass.

---

## 17. Route Progression Status

Fixed commit:

```text
3420d429cba3fddd7c547f6e578e0e8d9b666dd4
```

Focused route/projection result:

```text
tests/control_tower/test_v2_stage_progression.py      55 passed
tests/control_tower/test_v2_worker_stage.py           26 passed
tests/control_tower/test_v2_orchestrator_runner.py    50 passed
tests/control_tower/test_resume_from_checkpoint_profile.py 7 passed
tests/control_tower/test_profile_validation.py        17 passed
tests/control_tower/test_profile_pair_validation.py   5 passed
tests/control_tower/test_run_configurations.py        38 passed
tests/control_tower/test_safe_diff_preview.py         13 passed
tests/control_tower/test_reviewed_diff_proposal_projection.py 2 passed
tests/control_tower/test_v2_repair_gate_service.py    30 passed
```

Conclusion:

```text
The route-progression baseline debt is fixed.
PR-B can start.
```

---

## 18. Handoff Update Protocol

Every implementation session must update this document before ending.

### 18.1 Update Required Fields

Update these sections:

```text
0. Current Status Snapshot
16. Implementation Phases And Completion Checklist
19. Completion Log
20. Open Risks And Decisions
```

### 18.2 Completion Evidence Required

For each completed phase, record:

```text
phase name
branch
commit hash or "not committed"
files changed
db migrations added
tests run
test results
known failures
security rules validated
next phase recommendation
```

### 18.3 Do Not Mark Done Unless

A phase cannot be marked done unless:

```text
all phase-specific tests pass
unauthorized dirty files are removed or justified
Graphify files are not staged unless explicitly intended
security exclusions are verified
no forbidden fields are exposed
handoff/doc is updated
```

---

## 19. Completion Log

Append a new row after each implementation step.

| Date | Phase | Status | Branch / Commit | Files Changed | Tests | Notes |
|---|---|---|---|---|---|---|
| 2026-06-30 | Phase 0 | Done | `demov3` / `6dec64d726f4932c798f10652c8969be27989012` | none | read-only audit | Hybrid persistence chosen; PR-A recommended. |
| 2026-06-30 | PR-A | Done | `demov3` / `9de9c17f322e646238821c8ee914a3683f9b5a3e` | `safe_diff_preview.py`, `v2_model_schemas.py`, `v2_repair_projection.py`, PR-A tests | PR-A focused tests pass; route-progression baseline debt fixed in follow-up commit `3420d429cba3fddd7c547f6e578e0e8d9b666dd4` | Read-only projection is committed and the route graph is green. |
| 2026-06-30 | Route progression fix | Done | `demov3` / `3420d429cba3fddd7c547f6e578e0e8d9b666dd4` | `v2_stage_progression.py`, `test_v2_stage_progression.py`, `test_v2_orchestrator_runner.py`, `test_resume_from_checkpoint_profile.py` | Stage progression, orchestrator, resume, validation, and repair-gate focused tests passed | Fixed route-step indexing, target-reached semantics, and one stale metadata expectation. |
| 2026-06-30 | PR-B | Done | `demov3` / `cbfbcabf45b6d3d4990c2985f5eb4d4dbcddc407` | `0048_v2_repair_proposals_reviewed_diff_fields.sql`, `v2_repair_repository.py`, `dto.py`, `v2_repair_projection.py`, `app.py`, `tests/control_tower/test_v2_repair_proposal_api.py` | 25 PR-B tests passed; all 283 regression tests passed across 11 test files | PR-B complete. 4 read-only GET endpoints, 16 nullable columns, no mutation endpoints, all security rules enforced. |
| 2026-06-30 | PR-B contract hardening | Done | `demov3` / `cbfbcabf45b6d3d4990c2985f5eb4d4dbcddc407` + hardening commit | `safe_diff_preview.py`, `app.py`, `tests/control_tower/test_v2_repair_proposal_api.py`, `docs/ReviewedDiffProposal_PRD.md` | 14 HTTP contract tests; checksum mismatch tests; all regression suites green | HTTP route contract tests added; checksum mismatch detection added to SafeDiffPreview; checksum_mismatch flag in diff endpoint; no filesystem paths leaked. |
| 2026-06-30 | PR-C | Done | `demov3` / `73ab1fc` (+ PR-C commit) | `contracts.ts`, `controlTowerApi.ts`, `MigrationCockpit.tsx`, `RepairProposalPanel.tsx`, `ReviewedDiffTabs.tsx`, `SafeDiffPreview.tsx`, `ReviewerVerdictCard.tsx`, `RepairAttemptTimeline.tsx`, `RepairActionsBar.tsx`, `controlTowerApi.test.ts`, `migrationCockpit.test.tsx`, `reviewedDiffProposal.test.tsx` | Frontend API tests, component tests, forbidden-field tests, typecheck, build all pass; backend PR-B/PR-A smoke tests pass | PR-C committed. Read-only proposal/diff UI renders in cockpit. No mutation actions wired. graphify-out remains unstaged. |

Template for next update:

```text
| YYYY-MM-DD | PR-X | Done / Blocked / In progress | branch / commit | files | tests | notes |
```

---

## 20. Open Risks And Decisions

| Risk / Decision | Status | Owner / Next Action |
|---|---|---|
| `graphify-out/*` dirty | Open | Do not stage unless explicitly part of tooling update. |
| Route-progression baseline debt | Closed | Fixed in commit `3420d429cba3fddd7c547f6e578e0e8d9b666dd4`. |
| Graphify outputs dirty | Open | Do not stage unless explicitly part of tooling update. |
| `v2_sandbox_actions` exposes `target_path`/patch preview | Open | Public proposal APIs must avoid this projection. |
| Existing approval endpoint may infer proposal ID from revision/gate ID | Open | Harden in PR-E. |
| Generic `ContextPackBuilder` synthetic checksums | Open | Reviewed repair must use content-derived checksums. |
| Reviewer-edited diffs not currently supported | Open | If required later, add distinct reviewer-reviewed diff artifact contract. |
| Route-step vs legacy stage indexing inconsistency | Open | Bind proposal APIs to actual route-step state, not labels. |
| PR-B diff endpoint reads from filesystem path in diff_ref | Closed for hardening | Diff path sanitized to filename in safe_diff_preview. Remaining artifact-repo migration deferred to future PR. |
| `v1_model_invocations` insufficient for repair proof | Open | Add `v2_llm_invocations` in PR-G or earlier if required. |
| Deployment display policy | Open | Decide admin-only vs alias-only before public LLM activity UI. |
| Checksum mismatch detection | Closed | Implemented in contract hardening. `SafeDiffPreview.checksum_mismatch` flag returned by diff endpoint. Proposal not marked approvable on mismatch (enforced in PR-E). |
| No FastAPI TestClient HTTP contract tests | Closed | 14 HTTP route contract tests added covering all 4 GET endpoints with forbidden key/value assertions. |
| Missing diff file error leaks filesystem path | Closed | Diff endpoint returns "could not load diff" with no filesystem path in error responses. |
| PR-C frontend implementation | Closed | PR-C committed. All frontend tests pass. No mutation actions wired. graphify-out remains unstaged. |

---

## 21. External Design References Considered

The implementation direction aligns with current platform documentation and industry conventions:

- Azure Foundry/OpenAI model access is deployment-name based. Application code should not hardcode deployment names into business logic.
- Structured LLM outputs should be schema-shaped, but backend validation remains mandatory.
- Function/tool calling means the model requests application-provided tools; the backend executes tools.
- Unified diff UI should follow standard addition/deletion/context semantics.
- LangGraph interrupt/human-in-the-loop patterns are useful later for repair/chat state, but route execution and gates stay outside LangGraph.

---

## 22. Final Recommendation

Before PR-B:

1. Add this document to:

   ```text
   docs/ReviewedDiffProposal_PRD.md
   ```

2. Run the baseline comparison for `test_v2_stage_progression.py`.
3. Close PR-A properly:
   - stage/commit only PR-A files,
   - exclude Graphify files,
   - document test evidence,
   - update this PRD with commit hash.
4. Only then start PR-B.

The next phase after PR-A closeout is:

```text
PR-B — Durable Proposal Persistence + Job-Scoped Read APIs
```

Do not start with revision, approval/apply, cockpit mutation controls, LangGraph, or a new repair loop.
