# AMF-252 Current Repair LLM Diff Flow Deep Handoff

> **Branch:** `amf252-current-repair-flow-handoff`
> **Source branch:** `amf-237-reviewed-repair-gate`
> **Date:** 2026-07-08
> **Status:** Research-only — no implementation, no tests, no code changes
> **Context:** Current-codebase handoff for the F5 reviewed repair chain flow end-to-end

---

## 1. Executive Summary

When a migration stage (build, test, or transform) fails in the orchestrator runner, the system follows this end-to-end flow:

1. **Failure detection** — The orchestrator subprocess exits, and `V2OrchestratorRunner._maybe_write_repair_failure_context()` inspects the result JSON for `build_status` or `test_status` failure. It builds a `FailureEvidence` object and a `RepairContextPack`, then writes both as JSON files (`repair_failure_evidence.json` and `repair_context_pack.json`) into `{run_dir}/repairs/`.

2. **Evidence persistence** — The orchestrator injects reference paths and checksums into the result dict (`_repair_failure_evidence_ref`, `_repair_context_pack_ref`, etc.) and emits `repair_failure_evidence_written` and `repair_context_pack_written` events.

3. **Repair gate entry** — A diagnosis callback fires `V2RepairGateService.create_reviewed_repair_gate_on_failure()`, which deserializes the evidence and context pack, creates an invocation ledger, and calls `produce_repair_review_chain()` from the orchestrator module.

4. **Main/Proposer LLM** — The chain builds a deterministic repair artifact, then calls `V2AssistantModelClient.answer_with_role(role=V2ModelRole.PROPOSER, ...)` with output schema `RepairPrimaryOutput`. The prompt includes the entire repair context pack as JSON, diff generation rules, and a deterministic checksum. The LLM MUST return a JSON object containing `root_cause`, `fix_strategy`, `changed_files`, `proposed_diff`, `risk`, `confidence`, and `rationale`.

5. **Proposer output** — The proposer output is validated (schema, field presence, diff structure), normalized (diff normalization, hunk repair), checksummed (SHA-256 of canonical JSON), and persisted to `primary_repair_llm_output.json`. A checksum of the diff alone is also computed.

6. **Reviewer LLM** — The chain calls `V2AssistantModelClient.answer_with_role(role=V2ModelRole.REVIEWER, ...)` with schema `RepairReviewerOutput`. The reviewer receives the full proposer output, the repair context pack, deterministic checksums, and mechanical diff diagnostics. The reviewer must return a `decision` (accept/reject/needs_more_context/needs_revision), a `reviewed_diff`, and various metadata fields.

7. **Reviewer output** — If reviewer accepts and passes all validations (accept contract, checksum binding, mechanical diff structure, git apply --check), the reviewed diff is finalized as `final_reviewed_repair.diff` and `review_chain.json` is written. If reviewer does not accept, a `RepairReviewChainProductionError` is raised with a `partial_chain`.

8. **Proposal creation** — Back in the gate service, the exception or success determines the proposal path:
   - **`direct_reviewed_diff`**: Reviewer accepted, diff is valid, no gate needed — direct proposal created with `kind="direct_reviewed_diff"`.
   - **`direct_candidate_diff`**: Reviewer requested revision but proposed diff exists — candidate proposal created with `kind="direct_candidate_diff"` and reviewer decision `"needs_revision"`.
   - **`materialization_failed`**: Reviewer rejected, needs more context, or diff was malformed — no proposal created, unavailable diagnostic emitted.
   - **`reviewed_gate`** (legacy path): Full gate-based workflow with policy and applicability checks.

9. **API projection** — `GET /v1/v2/jobs/{job_id}/repair/proposals/current` queries the current proposal record. If a proposal exists and `diff_ref` is valid, it returns a `ReviewedDiffProposal` with `SafeDiffPreview` and `allowed_actions`. If no proposal, it returns `unavailable` diagnostics built from materialization failure events.

10. **Frontend display** — `RepairProposalPanel` fetches the proposal. On `status="available"`, it renders `ReviewedDiffTabs` (showing the diff, validation info, files changed, and reviewer verdict via `ReviewerVerdictCard`) and `RepairActionsBar` (showing the apply button). On `materialization_failed`, it renders `ReviewedRepairMaterializationFailed` or `ReviewedRepairUnavailable`.

11. **User approval** — The frontend sends a `RepairProposalApproveRequest` with `{proposal_id, diff_checksum, idempotency_key, reviewer_verdict_id, gate_id}`. The backend reloads the diff from disk using `diff_ref`, recomputes the checksum, and verifies it matches the stored `diff_checksum` and the request's `diff_checksum`.

12. **Sandbox apply** — `apply_patch_to_sandbox()` or `apply_patch_to_sandbox_direct()` runs: structural validation, sandbox preflight, `git apply --check`, then `git apply`. On success, the diff is applied to the sandbox.

13. **Validation** — `run_validation_after_patch()` rebuilds and runs tests in the sandbox. If validation passes, `_auto_queue_next_stage()` continues the migration to the next stage. If validation fails, a new repair cycle is created via `create_next_repair_cycle_from_rerun_failure()` (direct path) or `handle_repair_validation_result()` (gated path).

14. **Continuation** — On validation pass, the next migration stage is queued. On validation failure, a new repair chain is invoked, creating a fresh proposal with incremented attempt counter. The cycle repeats up to `DEFAULT_MAX_REPAIR_ATTEMPTS = 3`.

---

## 2. System Flow Diagram

```
Stage failure (build/test/transform)
    │
    ▼
V2OrchestratorRunner._maybe_write_repair_failure_context()
    │
    ├── Builds FailureEvidence (compiler errors, test failures, stdout/stderr tails, stage metadata)
    │       → {run_dir}/repairs/repair_failure_evidence.json
    │
    ├── Builds RepairContextPack (source contexts, changed files, normalized evidence, rules)
    │       → {run_dir}/repairs/repair_context_pack.json
    │
    ├── Injects refs into result dict: _repair_failure_evidence_ref, _repair_context_pack_ref, etc.
    │
    └── Emits: repair_failure_evidence_written, repair_context_pack_written
            │
            ▼
    Diagnosis callback → V2RepairGateService.create_reviewed_repair_gate_on_failure()
            │
            ├── Validates required payload fields
            ├── Loads FailureEvidence + RepairContextPack from JSON
            ├── Creates V2LLMInvocationLedger
            ├── Emits: repair_chain_started
            │
            ▼
    produce_repair_review_chain()
            │
            ├── Phase 1: Build deterministic repair artifact
            │       → deterministic_repair_artifact.json
            │
            ├── Phase 2: Main/Proposer LLM (V2ModelRole.PROPOSER)
            │       │   Prompt: context pack JSON + diff rules + deterministic checksum
            │       │   Schema: RepairPrimaryOutput
            │       │   Output: root_cause, fix_strategy, changed_files, proposed_diff, risk, confidence, rationale
            │       │
            │       ├── Validate: schema, field presence, diff structure
            │       ├── Normalize: diff format, hunk repair
            │       ├── Checksum: SHA-256 canonical JSON
            │       │
            │       ▼
            │       primary_repair_llm_output.json
            │       │   ├── proposed_diff → diff_checksum
            │       │   └── output_checksum
            │       │
            │       ├── SUCCESS → Phase 3
            │       └── FAILURE → RepairReviewChainProductionError → Gate Service
            │
            ├── Phase 3: Reviewer LLM (V2ModelRole.REVIEWER)
            │       │   Prompt: proposer output + context pack + diagnostics + checksums
            │       │   Schema: RepairReviewerOutput
            │       │   Output: decision, reviewed_diff, findings, risks, policy_concerns
            │       │
            │       ├── decision = "accept":
            │       │   ├── Validate accept contract
            │       │   ├── Mechanical diff validation
            │       │   ├── If issues: self-repair → re-invoke reviewer
            │       │   ├── If self-repair fails: import replacement fallback
            │       │   ├── If all passes: final_reviewed_repair.diff ✓
            │       │   └── If all fails: RepairReviewChainProductionError
            │       │
            │       ├── decision = "needs_revision"/"revise":
            │       │   └── RepairReviewChainProductionError(REVIEWER_REQUESTED_REVISION)
            │       │
            │       ├── decision = "reject":
            │       │   └── RepairReviewChainProductionError(REVIEWER_DECLINED_REPAIR)
            │       │
            │       └── decision = "needs_more_context":
            │           └── RepairReviewChainProductionError(REVIEWER_NEEDS_MORE_CONTEXT)
            │
            ▼
    V2RepairGateService exception/success handler
            │
            ├── SUCCESS + final_diff_exists + accept:
            │       → Validate + persist as direct_reviewed_diff
            │       → Emit: repair_diff_ready_for_user_apply (kind=direct_reviewed_diff)
            │
            ├── REVIEWER_REQUESTED_REVISION + proposed_diff_exists:
            │       → Validate + persist as direct_candidate_diff
            │       → Emit: repair_candidate_diff_ready_for_user_apply (kind=direct_candidate_diff)
            │
            ├── REVIEWER_DECLINED_REPAIR / REVIEWER_NEEDS_MORE_CONTEXT / malformed:
            │       → materialization_failed
            │       → Emit: reviewed_repair_materialization_failed / reviewed_repair_unavailable
            │
            └── Gate path (legacy):
                    → create_repair_gate_from_reviewed_chain()
                    → Policy + applicability checks → reviewed_gate proposal
                    → Emit: repair_diff_materialized
            │
            ▼
    Proposal record persisted (V2RepairProposalRecord) in SQLite
    status = "user_review_required"
            │
            ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                   API / FRONTEND LAYER                       │
    │                                                              │
    │  GET /v1/v2/jobs/{job_id}/repair/proposals/current           │
    │       → V2RepairProjection.build_reviewed_diff_proposal...    │
    │       → ReviewedDiffProposal + SafeDiffPreview +              │
    │         allowed_actions = ["view_diff", "approve_sandbox_apply", ...] │
    │                                                              │
    │  Frontend: RepairProposalPanel                                │
    │       → ReviewedDiffTabs (diff, validation, files, verdict)   │
    │       → RepairActionsBar ("Apply reviewer diff" button)       │
    │                                                              │
    │  User clicks apply → POST /v1/v2/jobs/{job_id}/repair/       │
    │  proposals/{proposal_id}/approve-sandbox-apply               │
    │       Body: {proposal_id, diff_checksum, idempotency_key}    │
    └─────────────────────────────────────────────────────────────┘
            │
            ▼
    Backend: reload diff from diff_ref on disk
            │
            ├── Verify: request.diff_checksum == stored.diff_checksum
            ├── Verify: recomputed checksum == stored checksum
            ├── Verify: SafeDiffPreview has no checksum_mismatch
            │
            ├── apply_patch_to_sandbox[_direct]()
            │   ├── validate_unified_diff_structure()
            │   ├── sandbox preflight
            │   ├── git apply --check
            │   └── git apply
            │
            ├── APPLIED → run_validation_after_patch()
            │   ├── Build + Test
            │   ├── PASS → _auto_queue_next_stage() → continue migration
            │   │          Emit: repair_validation_passed, stage_completed
            │   │
            │   └── FAIL → Direct: create_next_repair_cycle_from_rerun_failure()
            │              Gated: handle_repair_validation_result(passed=False)
            │              → New repair chain → New proposal (next cycle)
            │              Emit: repair_validation_failed
            │
            └── REJECTED (check/apply failure) → approve_failed
                Emit: repair_approve_apply_check_failed / repair_approve_patch_apply_failed
```

---

## 3. Failure Evidence and Repair Context Flow

> _Deliverable from Sub-Agent 1 — Backend Failure Detection, Evidence Collection, and Repair Context Pack_

### 3.1 Entry Point: Migration Stage Failure

A migration stage failure enters the repair flow through the orchestrator subprocess exit handler.

**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py`

- **Function:** `V2OrchestratorRunner._handle_exit()` — called when the subprocess exits.
- At line 571, `_maybe_write_repair_failure_context()` is called.

### 3.2 Primary Failure Evidence + Context Pack Creation

**Function:** `V2OrchestratorRunner._maybe_write_repair_failure_context()` — Line 1026
**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py`

This function:
1. Checks if `build_status` or `test_status` indicates failure (lines 1036-1043). Returns `None` if neither is a failure.
2. Resolves `run_dir` from `_result_run_dir()` (line 1045). Returns `None` if run_dir is None.
3. Extracts `changed_files`, `failure_summary`, `stdout_tail`, `stderr_tail`, `safe_log_preview` from the result dict.
4. Calls `build_failure_evidence()` to create a `FailureEvidence` object (line 1073).
5. Calls `build_repair_context_pack()` to create a `RepairContextPack` object (line 1113).
6. Creates `{run_dir}/repairs/` directory (line 1127).
7. Writes `repair_failure_evidence.json` (line 1129-1133).
8. Writes `repair_context_pack.json` (line 1135-1137).
9. Injects reference fields into the result dict (lines 1139-1146).
10. Emits `repair_failure_evidence_written` event (line 1148).
11. Emits `repair_context_pack_written` event (line 1162).

**Secondary path (diagnosis):**
- `V2OrchestratorRunner._maybe_diagnose()` at line 1281 calls an injected `diagnosis_callback`
- The callback is created by `create_repair_gate_diagnosis_callback()` in `v2_repair_gate_service.py`, line 3473
- This is the `build_failed`/`test_failed`/`transform_failed` event-triggered path

### 3.3 FailureEvidence Object

**Class:** `FailureEvidence`
**File:** `migration_factory/repair_loop/failure_evidence.py`, Line 47

Fields:

| Field | Type | Description |
|---|---|---|
| `failure_source` | `FailureSource` enum | `BUILD`, `TEST`, `VALIDATION`, `TRANSFORM`, `UNKNOWN` |
| `stage_index` | `int` | Migration stage number |
| `job_id` | `str` | Job identifier |
| `command_id` | `str` | Orchestrator command ID |
| `failure_summary` | `str` | Human-readable summary (truncated to 4000 chars) |
| `compiler_errors` | `tuple[NormalizedCompilerError, ...]` | Parsed Maven compiler errors |
| `test_failures` | `tuple[NormalizedTestFailure, ...]` | Parsed test failures |
| `changed_files` | `tuple[str, ...]` | Files modified in the stage |
| `source_profile` | `str` | Source migration profile ID |
| `target_profile` | `str` | Target migration profile ID |
| `accepted_artifact_checksums` | `tuple[str, ...]` | Checksums of accepted upstream artifacts |
| `artifact_refs` | `dict[str, str]` | Map of artifact kind → artifact file path |
| `stdout_tail` | `str` | Last 4000 chars of stdout |
| `stderr_tail` | `str` | Last 4000 chars of stderr |
| `safe_log_preview` | `str` | Redacted log preview (4000 chars max) |
| `content_checksum` | `str` | SHA-256 of canonical evidence payload |
| `artifact_checksum` | `str` | SHA-256 of full persisted envelope |
| `created_at` | `str` | ISO timestamp |
| `schema_version` | `str` | Always `"1.0.0"` |

Nested types:
- `NormalizedCompilerError` (line 30): `message`, `file_path`, `line`, `column`, `severity`
- `NormalizedTestFailure` (line 39): `test_name`, `test_class`, `message`, `file_path`
- `FailureSource` enum (line 21): `BUILD`, `TEST`, `VALIDATION`, `TRANSFORM`, `UNKNOWN`

### 3.4 RepairContextPack Object

**Class:** `RepairContextPack`
**File:** `migration_factory/repair_loop/repair_context.py`, Line 34

Fields:

| Field | Type | Description |
|---|---|---|
| `job_id` | `str` | Migration job ID |
| `stage_index` | `int` | Stage where failure occurred |
| `command_id` | `str` | Orchestrator command ID |
| `failure_source` | `str` | `"build"` or `"test"` |
| `failure_evidence_checksum` | `str` | Binds to `FailureEvidence.content_checksum` |
| `source_profile` | `str` | Source migration profile |
| `target_profile` | `str` | Target migration profile |
| `accepted_analysis_checksum` | `str` | Checksum of accepted analysis artifacts |
| `accepted_planning_checksum` | `str` | Checksum of accepted planning artifacts |
| `prior_proposal_checksums` | `tuple[str, ...]` | Checksums of previous repair proposals |
| `prior_reviewer_notes` | `tuple[str, ...]` | Reviewer notes from previous attempts |
| `user_comments` | `str` | User feedback |
| `changed_files` | `tuple[str, ...]` | Files modified in the failed stage |
| `normalized_build_evidence` | `tuple[dict[str, Any], ...]` | Compiler errors + build/test/final statuses |
| `source_contexts` | `tuple[dict[str, Any], ...]` | Source file excerpts (up to 8 files) |
| `diff_generation_rules` | `tuple[str, ...]` | Rules for LLM diff generation |
| `safe_log_preview` | `str` | Redacted log preview |
| `base_repo_state_checksum` | `str` | SHA-256 of file checksums + profiles |
| `context_pack_checksum` | `str` | SHA-256 of canonical context pack payload |
| `prior_revision_ids` | `tuple[str, ...]` | Prior revision IDs |
| `cycle_number` | `int` | Current repair cycle (starts at 0) |
| `max_cycles` | `int` | Maximum repair cycles (default 3) |
| `created_at` | `str` | ISO timestamp |
| `schema_version` | `str` | Always `"1.0.0"` |

### 3.5 How Source Contexts Are Built

**Function:** `V2OrchestratorRunner._build_source_contexts()` — Line 2542
**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py`

Selects up to 8 files from:
- Files referenced by compiler errors (`compiler_errors[i].file_path`)
- Changed files from the result
- Candidate files from compiler `location:` annotations (`_source_paths_from_compiler_locations()`, line 2595)

Each source context includes:
- `repo_relative_path` — POSIX-style relative path
- `file_checksum` — SHA-256 of file content
- `package_line` — the `package` declaration
- `import_block` — imports section (truncated to 6000 chars)
- `existing_imports` — list of import statements
- `failing_lines` — error line numbers
- `bounded_source_excerpt` — first 80 lines + surrounding failing lines (max 16000 chars)

### 3.6 Checksum Computation

| Checksum | Function | File | Algorithm |
|---|---|---|---|
| `content_checksum` | `compute_failure_content_checksum()` | `failure_evidence.py:83` | `sha256_canonical_json()` over stable payload (excludes volatile fields) |
| `artifact_checksum` | `compute_failure_artifact_checksum()` | `failure_evidence.py:119` | `sha256_canonical_json()` over `{content_checksum, created_at, schema_version}` |
| `context_pack_checksum` | `compute_context_pack_checksum()` | `repair_context.py:62` | `sha256_canonical_json()` over canonical context pack payload |
| `base_repo_state_checksum` | `compute_base_repo_state_checksum()` | `repair_context.py:89` | `sha256_canonical_json()` over sorted file checksums + profiles |

Checksum primitive: `sha256_canonical_json()` — `migration_factory/control_tower/domain/checksums.py:43`
- SHA-256 of UTF-8 encoded canonical JSON (sorted keys, compact separators: `(,",":")`)

### 3.7 Artifact Paths

| Artifact | Path Pattern |
|---|---|
| Failure evidence | `{run_dir}/repairs/repair_failure_evidence.json` |
| Repair context pack | `{run_dir}/repairs/repair_context_pack.json` |
| Run directory | Typically `{output_root}/.migration/runs/{run_id}` |

### 3.8 Payload Reference Keys (Injected into Result Dict)

| Key | Value |
|---|---|
| `_repair_failure_evidence_ref` | Absolute path to `repair_failure_evidence.json` |
| `_repair_context_pack_ref` | Absolute path to `repair_context_pack.json` |
| `_repair_run_dir` | Run directory path string |
| `_repair_sandbox_path` | Sandbox path string |
| `_repair_failure_evidence_checksum` | `FailureEvidence.content_checksum` |
| `_repair_context_pack_checksum` | `RepairContextPack.context_pack_checksum` |
| `_repair_base_repo_state_checksum` | `RepairContextPack.base_repo_state_checksum` |
| `_repair_h2_required` | Boolean flag for H2 startup requirement |

### 3.9 Error/Fallback Branches

- **Evidence/context building fails (no try/except around builder):** Exception propagates to `_handle_exit()` (line 389), which emits `stage_failed` event.
- **Missing required payload fields in gate service:** Returns `status="skipped"` (line 216-222).
- **JSON deserialization failure in gate service:** Returns `status="skipped"` (line 227-234).
- **Duplicate chain attempt (same job_id, stage_index, command_id):** Returns `status="skipped"` (line 176-184).
- **Existing proposal for same command_id:** Returns `status="skipped"` (line 187-194).
- **Design principle: fail-closed.** If the reviewed repair chain cannot produce a valid materialized diff, it never exposes an untrusted diff. The pipeline is not blocked.

### 3.10 Events Emitted

| Event | File | Line | Status | Payload Keys |
|---|---|---|---|---|
| `repair_failure_evidence_written` | `v2_orchestrator_runner.py` | 1148 | `"completed"` | `command_id`, `failure_source`, `failure_evidence_ref`, `failure_evidence_checksum`, `failure_evidence_artifact_checksum` |
| `repair_context_pack_written` | `v2_orchestrator_runner.py` | 1162 | `"completed"` | `command_id`, `context_pack_ref`, `context_pack_checksum`, `failure_evidence_checksum`, `base_repo_state_checksum` |

### 3.11 Failure Summary API

**Endpoint:** `GET /v1/v2/migration-jobs/{job_id}/failure-summary` — `app.py:2352`
**Handler:** `get_v2_job_failure_summary(job_id)` → `_v2_failure_summary(job_id, events)` at line 13813.

Groups failed events by `(stage_index, primary_key)`. Separates repair events from original stage failures. Returns per-failure dicts with: `type`, `scope`, `stage`, `title`, `message`, `build_status`, `test_status`, diagnostic fields, `stdout_tail`, `stderr_tail`, `repair_events`, `next_operator_action`, `supervision_trace`.

---

## 4. Main LLM / Proposer Flow

> _Deliverable from Sub-Agent 2 — Main/Proposer LLM Selection, Prompting, and Output Flow_

### 4.1 Proposer LLM Call Location

**File:** `migration_factory/orchestrator/repair_review_chain.py`
**Function:** `produce_repair_review_chain()`
**Line:** 1679-1685

```python
primary_result = client.answer_with_role(
    role=V2ModelRole.PROPOSER,
    prompt=_primary_repair_prompt(context_pack, deterministic_checksum),
    fallback="Primary repair model unavailable; reviewed repair cannot be produced.",
    output_schema_name="RepairPrimaryOutput",
    require_schema=True,
)
```

### 4.2 Role Name and Enum

**File:** `migration_factory/control_tower/application/v2_model_role_router.py`
**Enum:** `V2ModelRole.PROPOSER` (line 37), string value `"proposer"`

Mapping in `_role_to_config_role()` (line 66): `V2ModelRole.PROPOSER` → `"main"`
Mapping in `_role_to_env_key()` (line 55): `V2ModelRole.PROPOSER` → `"MAIN"`

### 4.3 Model Selection Logic

**File:** `migration_factory/control_tower/application/v2_model_role_config.py`
**Function:** `ModelRoleConfigLoader._read_role_env()` (line 60)

Resolution chain:
1. `_role_to_config_role(V2ModelRole.PROPOSER)` → `"main"`
2. `_resolve_deployment_for_role(V2ModelRole.PROPOSER)` checks:
   - `AI_MIGRATION_MAIN_MODEL` env var (new style)
   - Fallback: `AZURE_OPENAI_PROPOSER_DEPLOYMENT` (legacy)
3. Config loader reads: `AI_MIGRATION_MAIN_PROVIDER` (default `"azure_openai"`), `AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS` (default 20000), `AI_MIGRATION_MAIN_TIMEOUT_SECONDS` (default 30), `AI_MIGRATION_MAIN_SUPPORTS_JSON_SCHEMA` (default True)

Legacy env var mapping (`v2_model_role_router.py:44-49`):
```python
V2ModelRole.PROPOSER: "AZURE_OPENAI_PROPOSER_DEPLOYMENT"
```

### 4.4 Proposer Prompt

**Function:** `_primary_repair_prompt()` — `repair_review_chain.py:149-202`

The prompt includes:
1. **Role instruction:** "You are a repair proposer. Analyze the build/test failure evidence below and propose an exact unified diff to fix the issue."
2. **Required JSON keys declaration**
3. **Format constraint:** "Output only valid JSON. No markdown. No code fences. No commentary. No prose outside the JSON object."
4. **Constraints:** No commands, no absolute sandbox paths, repo-relative POSIX paths only, strict Git-style unified diff rules
5. **Repair selection rules:** Smallest code-only fix, respect target profile, do not assume Jackson package family, no dependency/POM changes unless proven necessary
6. **Valid JSON example** (lines 189-199)
7. **Deterministic checksum** injected
8. **Context pack** injected as JSON: `json.dumps(context_pack_to_dict(context_pack), sort_keys=True)`

### 4.5 System Messages

**File:** `migration_factory/control_tower/application/v2_assistant_model_client.py`
**Function:** `V2AssistantModelClient._build_messages()` — Line 747

Messages list:
```python
[
    {"role": "system", "content": _assistant_system_prompt()},
    {"role": "user", "content": prompt},
]
```

When `require_schema=True` (always for proposer), a JSON-only instruction is prepended to the system message (line 889-894).

System prompt: `_assistant_system_prompt()` at line 1021 — a long (~80 lines) prompt describing the assistant as "a read-only AI Migration Factory coach" with rules for answering, POM analysis, stage-aware behavior, etc.

### 4.6 Proposer Output Schema

**File:** `migration_factory/control_tower/application/v2_model_schemas.py`
**Schema name:** `RepairPrimaryOutput` (line 82-106)

Required fields:
1. `root_cause` (string)
2. `fix_strategy` (string)
3. `changed_files` (array of strings)
4. `proposed_diff` (string) — **the actual diff**
5. `risk` (string enum: `"LOW"`, `"MEDIUM"`, `"HIGH"`)
6. `confidence` (number, 0.0-1.0)
7. `rationale` (string)

Optional fields:
- `deterministic_rule_id` (string)
- `no_fix_reason` (string)
- `machine_readable_metadata` (object)

### 4.7 Proposer Output Validation and Normalization

Validation happens in multiple layers:

| Layer | Function | File | Line |
|---|---|---|---|
| JSON extraction | `_extract_json_safe()` | `repair_review_chain.py` | 423 |
| Field presence | `_coerce_primary_repair_output()` | `repair_review_chain.py` | 467 |
| Content validation | `_validate_primary_repair_output()` | `repair_review_chain.py` | 1040 |
| Schema validation (router) | `validate_model_output("RepairPrimaryOutput", parsed)` | `v2_model_role_router.py` | 626 |
| Schema diagnostics | `_schema_diagnostics()` | `v2_model_role_router.py` | 706 |

Content validation checks (`_validate_primary_repair_output()`):
- `root_cause`, `fix_strategy`, `proposed_diff` must be non-empty strings (lines 1043-1045)
- `changed_files` must be a list of strings (lines 1047-1049)
- `risk` must be LOW/MEDIUM/HIGH (lines 1051-1053)
- `confidence` must be a float 0.0-1.0 (lines 1055-1057)
- `proposed_diff` must be a valid unified diff (lines 1059-1062)

Normalization steps (line 1724-1738):
- Diff normalization to Git-style (auto-applied, continues with original on failure)
- Bare hunk header repair from sandbox files (auto-applied, continues on failure)

### 4.8 Proposer Artifact Files

| Artifact | Path |
|---|---|
| Primary output | `{run_dir}/repair_chain/primary_repair_llm_output.json` (line 1748) |
| Deterministic artifact | `{run_dir}/repair_chain/deterministic_repair_artifact.json` (line 1632) |

### 4.9 Checksums

| Checksum | Computation | Line |
|---|---|---|
| Diff checksum | `sha256_canonical_json({"unified_diff": proposed_diff})` | 1753 |
| Primary output checksum | `_compute_primary_repair_checksum()` — SHA-256 over all output fields | 635 |

### 4.10 Invocation Ledger

**File:** `migration_factory/control_tower/application/v2_llm_invocation_ledger.py`

At proposer invocation (repair_review_chain.py:1669-1677):
```python
proposer_invocation_id = invocation_ledger.start_invocation(
    job_id=context_pack.job_id,
    role="main",
    responsibility="repair_proposal",
    context_checksum=context_checksum_for_ledger,
    input_checksum=deterministic_checksum,
    schema_name="RepairPrimaryOutput",
)
```
Invocation ID is a UUID4 hex string (no dashes). Persisted to SQLite table `v2_llm_invocations`.

On completion (line 1690-1703): `complete_invocation()` with output, redacted summary, fallback status.
On failure: `fail_invocation()` with redacted error.

### 4.11 LLM Activity API Exposure

**File:** `migration_factory/control_tower/application/v2_llm_invocation_ledger.py`
**Method:** `V2LLMInvocationLedger.record_to_dto()` — Line 221

Returns: `invocation_id`, `job_id`, `role`, `responsibility`, `status`, `proposal_id`, `gate_id`, `provider_alias`, `model_display_name`, `deployment_alias_hash`, `schema_name`, `fallback_used`, tokens, latency, `reason_code`. **No raw prompts, completions, endpoints, or API keys are exposed.**

### 4.12 Proposer Error Branches

| Error | Reason Code | Where Raised | Line |
|---|---|---|---|
| Model unavailable/failed | `primary_result.failure_reason` | `produce_repair_review_chain()` | 1705 |
| Empty response | `main_empty_response` | `_coerce_primary_repair_output()` | 469 |
| Invalid/non-JSON output | `main_schema_invalid` | `_coerce_primary_repair_output()` | 476 |
| Missing required fields | `main_missing_fields` | `_coerce_primary_repair_output()` | 482 |
| Duplicate invocation blocked | `duplicate_main_blocked` | `produce_repair_review_chain()` | 1650 |
| Primary output validation failed | (from validation) | `produce_repair_review_chain()` | 1740 |

All proposer failures raise `RepairReviewChainProductionError` which is caught by the gate service.

### 4.13 Complete Proposer Flow

```
build_deterministic_repair_payload()
    → deterministic_repair_artifact.json
    → deterministic_checksum = sha256_canonical_json(payload)
        │
        ▼
invocation_ledger.start_invocation(role="main", responsibility="repair_proposal", ...)
        │
        ▼
client.answer_with_role(role=V2ModelRole.PROPOSER, prompt=_primary_repair_prompt(...), ...)
    → router.route() → _answer_with_deployment() → Azure/Mistral API call
        │
        ▼
_extract_json_safe(response_text)
    → json.loads() → strip fences → raw_decode scan
        │
        ▼
_coerce_primary_repair_output(parsed)
    → validate JSON keys → extract proposed_diff
        │
        ▼
_validate_primary_repair_output(primary_output)
    → check all required fields non-empty → validate diff structure
        │
        ▼
_diff_normalized → _hunks_repaired (optional auto-fixes)
        │
        ▼
_write_json(primary_path, primary_output) → primary_repair_llm_output.json
        │
        ▼
diff_checksum = sha256_canonical_json({"unified_diff": proposed_diff})
output_checksum = _compute_primary_repair_checksum(primary_output)
        │
        ▼
invocation_ledger.complete_invocation(proposer_invocation_id, ...)
        │
        ▼
→ Pass primary_output + proposed_diff + checksums to Reviewer LLM
```

---

## 5. Reviewer LLM and Diff Decision Flow

> _Deliverable from Sub-Agent 3 — Reviewer LLM Receipt, Decision Logic, and Final Diff States_

### 5.1 Reviewer LLM Call Location

**File:** `migration_factory/orchestrator/repair_review_chain.py`
**Function:** `produce_repair_review_chain()`
**Primary call line:** 1780-1793

```python
reviewer_result = client.answer_with_role(
    role=V2ModelRole.REVIEWER,
    prompt=_reviewer_repair_prompt(context_pack, primary_output, deterministic_checksum),
    fallback="Reviewer repair model unavailable; reviewed repair cannot be produced.",
    output_schema_name="RepairReviewerOutput",
    require_schema=True,
)
```

**Self-repair re-invocation:** `_invoke_reviewer_self_repair()` at line 1411-1418, same role, same schema.

### 5.2 Role Name

**Enum:** `V2ModelRole.REVIEWER` (line 38 in `v2_model_role_router.py`), string value `"reviewer"`

Mapping:
- `_role_to_config_role(V2ModelRole.REVIEWER)` → `"reviewer"` (line 67)
- `_role_to_env_key(V2ModelRole.REVIEWER)` → `"REVIEWER"` (line 57)
- Legacy env: `AZURE_OPENAI_REVIEWER_DEPLOYMENT` (line 46)

### 5.3 Reviewer Prompt

**Function:** `_reviewer_repair_prompt()` — `repair_review_chain.py:205-286`

Contents:
1. **Role instruction:** "You are a repair reviewer and final patch author."
2. **Schema:** `RepairReviewerOutput` with all required fields
3. **Decision guidance:** Instructions for accept/reject/needs_more_context/needs_revision
4. **Deterministic artifact checksum** (line 280)
5. **Context pack checksum** (line 281)
6. **Primary output checksum** (line 282)
7. **Grounded context:** full `context_pack_to_dict(context_pack)` as JSON (line 283)
8. **Primary output:** full primary_output as JSON (line 284) — **includes proposed_diff**
9. **Backend main_diff_diagnostics:** mechanical diagnostics on main's diff (line 285)

### 5.4 Reviewer Output Schema

**Schema name:** `RepairReviewerOutput`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `decision` | `"accept" \| "reject" \| "needs_more_context" \| "needs_revision"` | Required |
| `review_summary` | string | |
| `main_patch_findings` | list of strings | |
| `risks` | list of strings | |
| `policy_concerns` | list of strings | |
| `changed_files_verified` | boolean | |
| `reviewed_diff` | string | Must be non-empty for accept |
| `diff_changed_by_reviewer` | boolean | |
| `main_diff_diagnostics_acknowledged` | boolean | |
| `diff_parseable` | boolean | |
| `reviewed_context_checksum` | string | Must match |
| `reviewed_primary_output_checksum` | string | Must match |
| `reason_for_rejection` | string | Required but nullable |
| `revision_request` | string | Required but nullable |

### 5.5 Valid Decision Values

From `_coerce_reviewer_repair_output()` line 544:
```python
if decision not in {"accept", "revise", "reject", "needs_revision", "needs_more_context"}:
```

- `"accept"` — Reviewer approves the diff
- `"reject"` — `REVIEWER_DECLINED_REPAIR`
- `"needs_more_context"` — `REVIEWER_NEEDS_MORE_CONTEXT`
- `"needs_revision"` — `REVIEWER_REQUESTED_REVISION`
- `"revise"` — Legacy alias for needs_revision, maps to `REVIEWER_REQUESTED_REVISION`

### 5.6 Decision → Exception Mapping

**File:** `repair_review_chain.py:2206-2249`

| Decision | Reason Code | Behavior |
|---|---|---|
| `"accept"` | (no exception) | Proceed to finalize reviewed diff |
| `"reject"` | `REVIEWER_DECLINED_REPAIR` | `RepairReviewChainProductionError` raised |
| `"needs_more_context"` | `REVIEWER_NEEDS_MORE_CONTEXT` | `RepairReviewChainProductionError` raised |
| `"needs_revision"` / `"revise"` | `REVIEWER_REQUESTED_REVISION` | `RepairReviewChainProductionError` raised |

### 5.7 Accept Path: Full Validation Pipeline

After `decision="accept"` in `produce_repair_review_chain()`:

1. **Empty diff check** (line 2010): If `reviewed_diff` is empty → `REVIEWER_ACCEPTED_EMPTY_REVIEWED_DIFF`
2. **Checksum binding** (lines 575-590, 1939-2008): `reviewed_context_checksum` must match context, `reviewed_primary_output_checksum` must match primary
3. **Accept contract validation** (line 2060): `_reviewer_accept_contract_issue()` checks:
   - `reviewed_diff` non-empty
   - `changed_files_verified` is True
   - `main_diff_diagnostics_acknowledged` is True
   - `diff_parseable` is not False
4. **Mechanical validation** (line 2098): `_reviewed_diff_mechanical_issue()` validates diff structure
5. **Self-repair** (lines 2100-2203): If mechanical issues found, re-invokes reviewer to fix the diff
6. **Import replacement fallback** (lines 2288-2461): For `hunk_old_count_mismatch`, attempts `materialize_import_replacement_diff()` from sandbox
7. **Final diff write** (line 2486-2489): `final_reviewed_repair.diff`

### 5.8 Partial Chain Structure

**Function:** `_partial_failed_review_chain()` — `repair_review_chain.py:1232-1295`

```python
{
    "deterministic_artifact_checksum": str,
    "context_pack_checksum": str,
    "primary_output_checksum": str,
    "proposed_diff_checksum": str,
    "reviewed_diff_checksum": str | None,
    "reviewer_output_checksum": str | None,
    "reviewer_decision": str,
    "reviewer_accept_contract_valid": bool,
    "reviewer_accept_contract_issue": str,
    "reviewer_self_repair_attempted": bool,
    "reviewer_self_repair_succeeded": bool,
    "reviewer_self_repair_failure_reason": str,
    "reviewer_mechanical_validation_issue": str,
    "reviewer_self_repair_schema_repair_attempted": bool,
    "reviewer_self_repair_schema_repair_succeeded": bool,
    "reviewer_self_repair_schema_repair_failure_reason": str,
    "reviewer_self_repair_schema_repair_parse_failure_category": str,
    "struct_issue": str,
    "final_diff_exists": False,
    "proposed_diff_exists": bool,
    "candidate_diff_source": "main_proposed_diff" | "",
    "proposal_created": False,
    "gate_created": False,
    "policy_ran": False,
    "proposer_invocation_id": str | None,
    "reviewer_invocation_id": str | None,
    "reviewer_self_repair_invocation_id": str | None,
}
```

### 5.9 Artifact Files Written During Review

| Artifact | Path | When |
|---|---|---|
| Reviewer output | `{run_dir}/repair_chain/reviewer_repair_llm_output.json` | Line 1925, 2469 |
| Reviewer initial output | `{run_dir}/repair_chain/reviewer_initial_repair_llm_output.json` | Line 2111 (self-repair) |
| Final reviewed diff | `{run_dir}/repair_chain/final_reviewed_repair.diff` | Line 2489 (success) |
| Review chain | `{run_dir}/repair_chain/review_chain.json` | Line 1228, 2558 |
| Final reviewed artifact | `{run_dir}/repair_chain/final_reviewed_repair_artifact.json` | Line 2486 |
| Rejected diff | `{run_dir}/repair_chain/reviewed_diff_rejected.diff` | Line 1333 (validation failure) |
| Validation failure | `{run_dir}/repair_chain/reviewed_diff_validation_failure.json` | Line 1359 |

### 5.10 Decision Flow in Gate Service

**File:** `migration_factory/control_tower/application/v2_repair_gate_service.py`
**Function:** `create_reviewed_repair_gate_on_failure()` — Line 159

After `produce_repair_review_chain()` returns or raises:

```
produce_repair_review_chain() result
    │
    ├── SUCCESS (no exception) ──────────────────────────────────────
    │   │
    │   ├── final_diff_exists AND reviewer_decision=="accept"  (line 480)
    │   │       → _validate_direct_proposal_diff() (structural + git apply --check)
    │   │           ├── Valid → _persist_direct_reviewed_repair_proposal()
    │   │           │           kind = "direct_reviewed_diff", status = "created"
    │   │           └── Invalid → _fail_direct_materialization()
    │   │
    │   ├── proposed_diff_exists AND NOT final_diff_exists     (line 550)
    │   │       → _validate_direct_candidate_diff()
    │   │           ├── Valid → _persist_direct_candidate_repair_proposal()
    │   │           │           kind = "direct_candidate_diff", status = "created"
    │   │           └── Invalid → _fail_direct_materialization()
    │   │
    │   └── ELSE → create_repair_gate_from_reviewed_chain()     (line 619)
    │           kind = "reviewed_gate"
    │
    └── EXCEPTION (RepairReviewChainProductionError) ───────────────
        │
        ├── reason_code == "REVIEWER_REQUESTED_REVISION"
        │   AND proposed_diff_exists AND NOT final_diff_exists   (line 318)
        │       → _validate_direct_candidate_diff()
        │           ├── Valid → _persist_direct_candidate_repair_proposal()
        │           │           kind = "direct_candidate_diff"
        │           └── Invalid → materialization_failed
        │
        ├── reason_code == "duplicate_main_blocked"
        │   + prior materialization event found                   (line 280)
        │       → _emit_reviewed_repair_materialization_failed()
        │
        └── ELSE → _emit_reviewed_repair_materialization_failed() (line 375)
                    → materialization_failed
```

### 5.11 Blocking vs. Advisory Components

**BLOCKING (fail-closed):**
- Main LLM unavailable, schema invalid, output validation, empty response
- Reviewer LLM unavailable, schema invalid, checksum mismatch
- Reviewer decision != "accept"
- Accept contract invalid, empty reviewed_diff on accept
- Diff structural validation (after all repair attempts exhausted)
- Semantic drift detection
- Duplicate main invocation
- Git apply --check failure
- Policy rejection
- Required checksum binding missing

**ADVISORY/FALLBACK (attempted, non-blocking if success):**
- Diff normalization to Git-style
- Bare hunk header repair
- Diff parseable field auto-correction (when `skip_self_repair=True`)
- Accept contract auto-correction (when `skip_self_repair=True`)
- Reviewer self-repair
- Import replacement fallback (AMF-250A)
- Reviewer applicability repair

---

## 6. Proposal, API, Frontend, Apply, Validation, and Continuation Flow

> _Deliverable from Sub-Agent 4 — Diff-to-Proposal, API Exposure, Frontend Display, User Approve, Apply, Validation_

### 6.1 Proposal Persistence Functions

| Function | File | Line | Description |
|---|---|---|---|
| `_persist_reviewed_repair_proposal()` | `v2_repair_gate_service.py` | 1549 | Gate-based reviewed repair proposal |
| `_persist_direct_reviewed_repair_proposal()` | `v2_repair_gate_service.py` | 1719 | Direct reviewed repair (no gate, reviewer accepted) |
| `_persist_direct_candidate_repair_proposal()` | `v2_repair_gate_service.py` | 1842 | Direct candidate repair (reviewer requested revision) |

### 6.2 Proposal Record Type

**Class:** `V2RepairProposalRecord`
**File:** `migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py`, Line 12

Fields (`diff_checksum` at line 37, `diff_ref` at line 36):

| Field | Type | Description |
|---|---|---|
| `proposal_id` | `str` | UUID hex |
| `command_id` | `str` | Associated command |
| `failure_summary` | `str` | Failure description |
| `hypothesis` | `str` | Root cause |
| `patch_summary` | `str` | Fix strategy |
| `affected_paths_json` | `str` | JSON list of paths |
| `status` | `str` | `user_review_required`, `approved_applied`, `approve_failed`, etc. |
| `diff_ref` | `str \| None` | **Filesystem path to diff** |
| `diff_checksum` | `str \| None` | **SHA-256 of diff** |
| `kind` (derived) | `str` | Set during projection: `direct_reviewed_diff`, `direct_candidate_diff`, `reviewed_gate` |
| `reviewer_decision` | `str \| None` | Reviewer's verdict |
| `reviewer_output_checksum` | `str \| None` | Reviewer output hash |
| `gate_id` | `str \| None` | Null for direct proposals |
| `safe_diff_preview_ref` | `str \| None` | Preview display name |
| `apply_status` | `str \| None` | Patch apply result |
| `rerun_status` | `str \| None` | Validation result |
| `remaining_attempts` | `int \| None` | Attempts remaining |

### 6.3 Kind Derivation

**File:** `migration_factory/control_tower/application/v2_repair_projection.py`

```python
kind = (
    "direct_candidate_diff"
    if gate_id is None and reviewer_decision and reviewer_decision != "accept"
    else "direct_reviewed_diff" if gate_id is None
    else "reviewed_gate"
)
```
Lines 349-356 and 642-647.

### 6.4 Proposal Status Values

- `"user_review_required"` — proposal ready for human (initial state)
- `"approved_applied"` — apply + validation succeeded
- `"approve_failed"` — apply or validation failed
- `"approved"`, `"rejected"`, `"superseded"`, `"exhausted"` — legacy/finalized states

### 6.5 Events Emitted on Proposal Ready

| Event Type | Function | Line | Includes |
|---|---|---|---|
| `repair_diff_ready_for_user_apply` | `_emit_repair_diff_ready_for_user_apply()` | 1305 | `kind=direct_reviewed_diff`, `proposal_id`, `diff_checksum`, etc. |
| `repair_candidate_diff_ready_for_user_apply` | `_emit_repair_candidate_diff_ready_for_user_apply()` | 1348 | `kind=direct_candidate_diff`, `proposal_id`, `diff_checksum`, etc. |
| `repair_diff_materialized` | `_emit_reviewed_repair_materialized()` | 1247 | Gate-based, `kind=reviewed_gate` |

### 6.6 API Endpoints

**GET `/v1/v2/jobs/{job_id}/repair/proposals/current`**
- **Handler:** `get_current_repair_proposal` — `app.py:4067`
- **Logic:**
  1. Queries `uow.v2_repairs.get_current_proposal_for_job(job_id)` (prioritizes `user_review_required`, then `approve_failed`)
  2. If no record → `{"proposal": null, "unavailable": <diagnostic>}` where diagnostic from `_latest_repair_materialization_unavailable()` (line 783)
  3. If record + valid `diff_ref` → builds `SafeDiffPreview`, resolves gate/evidence context, computes `allowed_actions`, returns projection
  4. If record but `diff_ref` is None → `{"proposal": null, "unavailable": ...}`

**GET `/v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}`**
- **Handler:** `get_repair_proposal` — `app.py:4194`
- Same logic but for specific proposal ID; returns 404 if not found for job.

**GET `/v1/v2/jobs/{job_id}/repair/proposals/current/diff`**
- Returns `safe_diff_preview` from proposal's diff file on disk.

**POST `/v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/approve-sandbox-apply`**
- **Handler:** `approve_repair_proposal_sandbox_apply` — `app.py:4572`
- **See §6.11 for full flow.**

### 6.7 Allowed Actions Computation

For **gate-based proposals** (line 1448):
```python
actions = ("view_diff", "view_reviewer_opinion", "view_files_changed",
           "ask_explanation", "view_attempt_history", "approve_sandbox_apply", "request_revision")
```
Only when `stale_reason` is None (proposal is actionable).

For **direct proposals** (line 4121):
```python
actions = READ_ONLY_REPAIR_ACTIONS + (("approve_sandbox_apply",) if direct_proposal else ("approve_sandbox_apply", "request_revision"))
```

For `approve_failed` or stale: `READ_ONLY_REPAIR_ACTIONS` only.

`approve_sandbox_apply` is **never** included in `unavailable.allowed_actions`.

### 6.8 Frontend Contracts (TypeScript)

**File:** `web/control-tower/lib/contracts.ts`

| Type | Lines | Description |
|---|---|---|
| `SafeDiffPreview` | 1156-1167 | Diff preview with files, hunks, checksum_mismatch |
| `ReviewedDiffProposal` | 1186-1224 | Full proposal with kind, status, allowed_actions |
| `RepairMaterializationUnavailable` | 1258-1318 | Unavailable diagnostic with reason_code, diagnostics |
| `RepairProposalCurrentResponse` | 1320-1324 | API response wrapper: `{proposal, job_id, unavailable}` |
| `RepairProposalApproveRequest` | 1386-1393 | Approve payload: `{proposal_id, diff_checksum, idempotency_key}` |
| `V2LlmInvocationEntry` | 1226-1251 | LLM activity entry |
| `ReviewerVerdictProjection` | 1169-1177 | Reviewer verdict |

### 6.9 Frontend Components

| Component | File | Lines | Purpose |
|---|---|---|---|
| `RepairProposalPanel` | `app/migrations/[jobId]/RepairProposalPanel.tsx` | — | Main orchestration component; fetches proposal, renders branches |
| `ReviewedDiffTabs` | `app/migrations/[jobId]/ReviewedDiffTabs.tsx` | 11 | Diff tabs: Reviewed Diff, Validation, Files Changed, Reviewer Verdict |
| `RepairActionsBar` | `app/migrations/[jobId]/RepairActionsBar.tsx` | 6 | Apply button ("Apply reviewer diff" / "Apply candidate diff") |
| `ValidationProgressPanel` | `app/migrations/[jobId]/ValidationProgressPanel.tsx` | — | Validation progress display |
| `ReviewerVerdictCard` | `app/migrations/[jobId]/ReviewerVerdictCard.tsx` | — | Reviewer opinion/findings card |
| `ReviewedRepairMaterializationFailed` | Within `RepairProposalPanel.tsx` | 834 | Materialization failed state |
| `ReviewedRepairUnavailable` | Within `RepairProposalPanel.tsx` | 598 | Other review chain activity states |
| `MigrationCockpit` | `app/migrations/[jobId]/MigrationCockpit.tsx` | — | Parent orchestrator UI |

### 6.10 Frontend State Machine

**Type:** `ProposalState` (RepairProposalPanel.tsx, line 28):
```typescript
type ProposalState =
  | { status: "loading" }
  | { status: "no-proposal"; unavailable?: RepairMaterializationUnavailable | null }
  | { status: "error"; message: string }
  | { status: "available"; proposal: ReviewedDiffProposal };
```

See §12 for full rendering states.

### 6.11 Approver Flow (Backend)

**Entry:** `POST /v1/v2/jobs/{job_id}/repair/proposals/{proposal_id}/approve-sandbox-apply`

**Request body:** `RepairProposalApproveRequest` — `{proposal_id, diff_checksum, idempotency_key, reviewer_verdict_id?, gate_id?}`

**Flow in `approve_repair_proposal_sandbox_apply()` (app.py:4572):**

```
1. Load proposal record by proposal_id
2. Load diff from disk using record.diff_ref → raw bytes
3. Verify checksums (multiple layers):
   a. request.diff_checksum != stored.diff_checksum → 409 STALE_DIFF_CHECKSUM
   b. sha256_hex(disk_bytes) != stored.diff_checksum → 409 DIFF_CHECKSUM_MISMATCH
   c. preview.checksum_mismatch → 409 SAFE_DIFF_CHECKSUM_MISMATCH
4. Resolve sandbox path:
   - Gate-based: _resolve_reviewed_repair_runtime_context() → _resolve_stage_sandbox_root()
   - Direct: _resolve_direct_repair_runtime_context() → _resolve_stage_sandbox_root()
5. Run apply_patch_to_sandbox[_direct]():
   a. validate_unified_diff_structure()
   b. Sandbox preflight check
   c. git apply --check
   d. git apply (actual application)
6. If REJECTED:
   - Update record: status="approve_failed", apply_status=rejection status
   - Emit: repair_approve_apply_check_failed / repair_approve_patch_apply_failed
   - Return approval response with fail status
   - STOP (no validation)
7. If APPLIED (or ALREADY_APPLIED for direct path):
   - Run run_validation_after_patch():
     a. run_build_agent() → rebuild in sandbox
     b. run_test_agent() → run tests
     c. build_h2_startup_report() → H2 check
   - If PASS: status="approved_applied", _auto_queue_next_stage()
   - If FAIL:
       Direct: create_next_repair_cycle_from_rerun_failure()
       Gated: handle_repair_validation_result(passed=False)
             → rollback_patch() → new repair_review gate
       Record: status="approve_failed"
```

### 6.12 Patch Apply Functions

**File:** `migration_factory/repair_loop/patch_apply.py`

| Function | Line | Description |
|---|---|---|
| `apply_patch_to_sandbox()` | 229 | Gated path: validate → preflight → git apply --check → git apply |
| `apply_patch_to_sandbox_direct()` | 500 | Direct path: validate → check_patch_applicability() → git apply |
| `check_patch_applicability()` | 443 | Runs `git apply --check` and returns CHECKED status |

**Statuses:** `"APPLIED"`, `"REJECTED"`, `"CHECKED"`, `"ALREADY_APPLIED"`

### 6.13 Validation Runner

**File:** `migration_factory/repair_loop/validation_runner.py`
**Function:** `run_validation_after_patch()` — Line 32

Runs: `run_build_agent()` → `run_test_agent()` → `build_h2_startup_report()`
Returns: `ValidationResult` with `passed`, `build_status`, `test_status`, `h2_status`

### 6.14 Continuation Functions

| Function | File | Line | Description |
|---|---|---|---|
| `_auto_queue_next_stage()` | `v2_orchestrator_runner.py` | 1306 | Queues next migration stage after validation pass |
| `create_next_repair_cycle_from_rerun_failure()` | `v2_repair_gate_service.py` | 3071 | Creates new repair chain after validation failure (direct path) |
| `handle_repair_validation_result(passed=False)` | `v2_repair_gate_service.py` | 2955 | Creates new repair gate after validation failure (gated path) |

### 6.15 Events During Approve/Apply/Validate

| Event | When | Status |
|---|---|---|
| `repair_approve_apply_check_failed` | `git apply --check` fails | `"failed"` |
| `repair_approve_patch_apply_failed` | `git apply` fails | `"failed"` |
| `repair_approve_apply_failed` | Other apply failures | `"failed"` |
| `repair_validation_passed` | Validation succeeds | `"completed"` |
| `stage_completed` | Direct: validation passed → auto-queue | `"completed"` |
| `repair_validation_failed` | Validation fails | `"failed"` |
| `build_failed` | Build fails during validation (direct) | `"failed"` |
| `test_failed` | Tests fail during validation (direct) | `"failed"` |
| `h2_startup_failed` | H2 fails during validation (direct) | `"failed"` |

---

## 7. Key Data Structures and Artifacts

### 7.1 FailureEvidence

- **Defined:** `migration_factory/repair_loop/failure_evidence.py:47`
- **Created by:** `build_failure_evidence()` in `v2_orchestrator_runner.py`
- **Persisted as:** `{run_dir}/repairs/repair_failure_evidence.json`
- **Consumed by:** `V2RepairGateService.create_reviewed_repair_gate_on_failure()` (deserialized at line 225)
- **Key fields:** `failure_source`, `failure_summary`, `compiler_errors`, `test_failures`, `changed_files`, `stdout_tail`, `stderr_tail`, `safe_log_preview`, `content_checksum`, `artifact_checksum`

### 7.2 RepairContextPack

- **Defined:** `migration_factory/repair_loop/repair_context.py:34`
- **Created by:** `build_repair_context_pack()` (line 117)
- **Persisted as:** `{run_dir}/repairs/repair_context_pack.json`
- **Consumed by:** Gate service (line 226) and passed to `_primary_repair_prompt()` and `_reviewer_repair_prompt()`
- **Key fields:** `normalized_build_evidence`, `source_contexts`, `diff_generation_rules`, `context_pack_checksum`, `base_repo_state_checksum`, `cycle_number`, `max_cycles`

### 7.3 primary_repair_llm_output.json

- **Created in:** `produce_repair_review_chain()` line 1748
- **Written to:** `{run_dir}/repair_chain/primary_repair_llm_output.json`
- **Contains:** `root_cause`, `fix_strategy`, `changed_files`, `proposed_diff`, `deterministic_rule_id`, `risk`, `confidence`, `rationale`, `output_checksum`, `_diff_normalized`, `_hunks_repaired`
- **Consumed by:** Reviewer LLM, `_persist_direct_candidate_repair_proposal()` (line 1862-1863 for candidate diff source)

### 7.4 reviewer_repair_llm_output.json

- **Created in:** `produce_repair_review_chain()` line 1925, 2469
- **Written to:** `{run_dir}/repair_chain/reviewer_repair_llm_output.json`
- **Contains:** `decision`, `review_summary`, `main_patch_findings`, `risks`, `policy_concerns`, `reviewed_diff`, `changed_files_verified`, `diff_parseable`, etc.
- **Consumed by:** Gate service proposal persistence, `review_chain.json` building

### 7.5 review_chain.json

- **Created in:** `produce_repair_review_chain()` (success: line 2558) or `_persist_failure_review_chain()` (failure: line 1228)
- **Written to:** `{run_dir}/repair_chain/review_chain.json`
- **Contains:** Full chain metadata including checksums, output refs, invocation IDs, decision, `final_diff_exists`, `proposed_diff_exists`, `gate_created`, `proposal_created`, self-repair diagnostics

### 7.6 V2RepairProposalRecord

- **Defined:** `migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py:12`
- **Created by:** `_persist_reviewed_repair_proposal()`, `_persist_direct_reviewed_repair_proposal()`, `_persist_direct_candidate_repair_proposal()`
- **Persisted to:** SQLite table (via `uow.v2_repairs`)
- **Key fields:** `proposal_id`, `diff_ref`, `diff_checksum`, `status`, `reviewer_decision`, `gate_id`, `apply_status`, `rerun_status`

### 7.7 SafeDiffPreview

- **Defined (backend):** Built in `app.py` from diff file on disk
- **Defined (TypeScript):** `web/control-tower/lib/contracts.ts:1156`
- **Contains:** `proposal_id`, `diff_checksum`, `files[]` (`SafeDiffFile` with `SafeDiffHunk[]`), `total_additions`, `total_deletions`, `truncated`, `checksum_mismatch`, `redactions[]`, `parse_status`
- **Consumed by:** Frontend `ReviewedDiffTabs` for diff rendering

### 7.8 ReviewedDiffProposal

- **Defined (backend):** `migration_factory/control_tower/application/v2_repair_projection.py:300`
- **Defined (TypeScript):** `web/control-tower/lib/contracts.ts:1186`
- **Fields:** `proposal_id`, `kind`, `status`, `diff_checksum`, `safe_diff_preview`, `reviewer_verdict`, `files_changed`, `allowed_actions`, `stale_reason`, `apply_status`, `rerun_status`, `status_reason`, `reason_code`, etc.

### 7.9 RepairMaterializationUnavailable

- **Built by:** `_latest_repair_materialization_unavailable()` — `app.py:783`
- **Defined (TypeScript):** `web/control-tower/lib/contracts.ts:1258`
- **Contains:** `kind = "materialization_failed"`, `title`, `reason_code`, `detail`, `main_invocation_id`, `reviewer_invocation_id`, `final_diff_exists`, `policy_ran`, `gate_created`, `proposal_created`, `allowed_actions`, `retry_status`, 30+ diagnostic fields

---

## 8. LLM Role and Model Selection

### 8.1 V2ModelRole Enum

**File:** `migration_factory/control_tower/application/v2_model_role_router.py:35`

```python
class V2ModelRole(str, Enum):
    ASSISTANT = "assistant"
    PROPOSER = "proposer"
    REVIEWER = "reviewer"
    FALLBACK = "fallback"
```

### 8.2 Role-to-Config Mapping

| V2ModelRole | Config Role | Env Key | Legacy Env Var |
|---|---|---|---|
| `PROPOSER` | `"main"` | `"MAIN"` | `AZURE_OPENAI_PROPOSER_DEPLOYMENT` |
| `REVIEWER` | `"reviewer"` | `"REVIEWER"` | `AZURE_OPENAI_REVIEWER_DEPLOYMENT` |
| `ASSISTANT` | `"assistant"` | `"ASSISTANT"` | `AZURE_OPENAI_ASSISTANT_DEPLOYMENT` |
| `FALLBACK` | `"fallback"` | `"FALLBACK"` | `AZURE_OPENAI_FALLBACK_DEPLOYMENT` |

### 8.3 Model Configuration Environment Variables

**File:** `migration_factory/control_tower/application/v2_model_role_config.py`

Pattern: `AI_MIGRATION_{ROLE}_{PROPERTY}`

| Environment Variable | Default | Description |
|---|---|---|
| `AI_MIGRATION_MAIN_MODEL` | (required) | Deployment/model name |
| `AI_MIGRATION_MAIN_PROVIDER` | `"azure_openai"` | Provider alias (`"mistral"` also supported) |
| `AI_MIGRATION_MAIN_RESPONSE_FORMAT` | `"text"` | Response format |
| `AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS` | `20000` | Max output tokens |
| `AI_MIGRATION_MAIN_TIMEOUT_SECONDS` | `30` | Timeout |
| `AI_MIGRATION_MAIN_SUPPORTS_JSON_SCHEMA` | `True` | Structured output support |
| `AI_MIGRATION_REVIEWER_MODEL` | (required) | Reviewer deployment |
| `AI_MIGRATION_REVIEWER_PROVIDER` | `"azure_openai"` | Provider alias |
| `AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS` | (config default) | Max tokens |

### 8.4 Invocation IDs

- Generated by: `V2LLMInvocationLedger.start_invocation()` — `v2_llm_invocation_ledger.py:139`
- Format: `uuid4().hex` (32 hex characters, no dashes)
- Stored in: SQLite table `v2_llm_invocations`
- **Proposer invocation:** role=`"main"`, responsibility=`"repair_proposal"`
- **Reviewer invocation:** role=`"reviewer"`, responsibility=`"review"` or `"review_self_repair"` (self-repair)

### 8.5 LLM Activity API Exposure

**Endpoint (for frontend):** Part of `getCurrentRepairProposal` response chain, invocations exposed via `record_to_dto()`.

**Fields exposed:** `invocation_id`, `job_id`, `role`, `responsibility`, `status`, `provider_alias`, `model_display_name`, `deployment_alias_hash`, `schema_name`, `tokens`, `latency_ms`, `reason_code`, `redacted_error`.
**NOT exposed:** raw prompts, completions, endpoints, API keys.

---

## 9. Diff Lifecycle

### 9.1 proposed_diff

- **Origin:** Main/Proposer LLM output (`RepairPrimaryOutput.proposed_diff`)
- **Stored in:** `primary_repair_llm_output.json`
- **Checksum:** `sha256_canonical_json({"unified_diff": proposed_diff})` — computed at line 1753
- **Scope:** The LLM's initial diff proposal, may be modified by reviewer
- **Used for candidate diff:** If reviewer requests revision, this diff becomes the `candidate_diff.diff` source (line 1862-1863)

### 9.2 reviewed_diff

- **Origin:** Reviewer LLM output (`RepairReviewerOutput.reviewed_diff`)
- **Stored in:** `reviewer_repair_llm_output.json`
- **Checksum:** `sha256_canonical_json({"unified_diff": reviewed_diff})` — computed at line 604
- **Scope:** The reviewer's modified (or approved as-is) diff. Must be a valid unified diff.

### 9.3 final_diff

- **Origin:** After all reviewer validations pass, `reviewed_diff` is finalized
- **Stored in:** `final_reviewed_repair.diff` (line 2489)
- **Meaning:** The canonical final diff from the review chain — ready for proposal persistence
- **Reference:** `review_chain["final_diff_ref"]` = path to this file

### 9.4 candidate_diff

- **Origin:** When reviewer does NOT accept AND `proposed_diff_exists` is True
- **Stored in:** `candidate_diff.diff` (line 1868 in gate service) — contains the **proposer's diff**, not reviewer's
- **Meaning:** The main LLM's proposed diff offered as a candidate for human decision (reviewer didn't accept it)
- **Created by:** `_persist_direct_candidate_repair_proposal()` (line 1842)
- **Kind:** `"direct_candidate_diff"`

### 9.5 Diff Checksums

All use `sha256_canonical_json()` (SHA-256 of sorted, compact JSON):

| Checksum | Computed At | Purpose |
|---|---|---|
| `diff_checksum` (proposed) | line 1753 | Stored in review_chain; used for candidate diff |
| `reviewed_diff_checksum` | line 604 | Stored in review_chain; compared against storage |
| `diff_checksum` on proposal | Persist time | Stored as `V2RepairProposalRecord.diff_checksum` |
| `actual_diff_checksum` (approve time) | `app.py:4648` | Recomputed from disk bytes; must match stored checksum |

### 9.6 diff_ref

- **Stored on:** `V2RepairProposalRecord.diff_ref` — absolute filesystem path to the diff file
- **Set at persist time** (e.g., line 1607, 1780, 1911)
- **Used at approve time** to reload the diff from disk: `Path(diff_ref).read_bytes()` (app.py:4647)

### 9.7 SafeDiffPreview

- **Built at:** API response time in `get_current_repair_proposal()` / `get_repair_proposal()`
- **From:** Diff file loaded from `diff_ref` on disk
- **Parse status:** `"parsed"`, `"unparseable"`, `"no_content"`, `"hunk_count_mismatch"`
- **Critical flag:** `checksum_mismatch` — if True, backend has detected a disk vs record mismatch
- **Redactions:** Redacted file glob patterns applied for security

### 9.8 Apply-Time Checksum Verification (Triple Check)

At approve time (`app.py:4631-4674`):
1. `request.diff_checksum != stored.diff_checksum` → 409 `STALE_DIFF_CHECKSUM`
2. `sha256_hex(disk_bytes) != stored.diff_checksum` → 409 `DIFF_CHECKSUM_MISMATCH`
3. `preview.checksum_mismatch` → 409 `SAFE_DIFF_CHECKSUM_MISMATCH`

---

## 10. Decision Matrix

| Scenario | Backend Behavior | Proposal Kind | User Can See Diff? | User Can Apply? | Notes |
|---|---|---|---|---|---|
| Reviewer accepts + reviewed_diff valid | `direct_reviewed_diff` proposal created | `direct_reviewed_diff` | Yes (reviewer's diff) | Yes (`approve_sandbox_apply`) | Standard happy path |
| Reviewer accepts + reviewed_diff malformed + self-repair succeeds | `direct_reviewed_diff` proposal created | `direct_reviewed_diff` | Yes | Yes | Reviewer re-invoked to fix |
| Reviewer accepts + reviewed_diff malformed + import replacement succeeds | `direct_reviewed_diff` proposal created | `direct_reviewed_diff` | Yes (backend-generated) | Yes | AMF-250A fallback |
| Reviewer accepts + reviewed_diff malformed + all repairs fail | `materialization_failed` (skipped) | N/A | No | No | `MALFORMED_DIFF` reason |
| Reviewer accepts + reviewed_diff empty | `materialization_failed` | N/A | No | No | `REVIEWER_ACCEPTED_EMPTY_REVIEWED_DIFF` |
| Reviewer accepts + contract invalid | `materialization_failed` | N/A | No | No | `REVIEWER_ACCEPT_CONTRACT_INVALID` |
| Reviewer accepts + checksum mismatch | `materialization_failed` | N/A | No | No | `REVIEWER_CHECKSUM_MISMATCH` |
| `needs_revision` + proposed_diff exists | `direct_candidate_diff` proposal created | `direct_candidate_diff` | Yes (proposer's diff) | Yes (candidate apply) | Reviewer decision = `"needs_revision"` |
| `needs_revision` + no proposed_diff | `materialization_failed` | N/A | No | No | No diff to offer |
| `reject` | `materialization_failed` | N/A | No | No | `REVIEWER_DECLINED_REPAIR` |
| `needs_more_context` | `materialization_failed` | N/A | No | No | `REVIEWER_NEEDS_MORE_CONTEXT` |
| Main/proposer invalid JSON | `materialization_failed` | N/A | No | No | `main_schema_invalid` / `main_empty_response` |
| proposed_diff missing from main output | `materialization_failed` | N/A | No | No | `main_missing_fields` |
| `git apply --check` fails (at approve time) | Record → `approve_failed` | (existing) | Yes (stale preview) | No (retrigger required) | `PATCH_CHECK_FAILED` |
| `git apply` fails (at approve time) | Record → `approve_failed` | (existing) | Yes (stale preview) | No (retrigger required) | `PATCH_APPLY_FAILED` |
| Apply succeeds + validation fails (direct) | New repair cycle created; record → `approve_failed` | N/A (new cycle) | Previously yes | No (new repair) | `create_next_repair_cycle_from_rerun_failure()` |
| Apply succeeds + validation fails (gated) | Patch rolled back; new gate created | N/A (new cycle) | Previously yes | No (new repair) | `handle_repair_validation_result(passed=False)` |
| Apply succeeds + validation passes (direct) | `_auto_queue_next_stage()` | (existing, finalized) | Yes (historical) | No (done) | Migration continues |
| Apply succeeds + validation passes (gated) | `stage_completion_review` gate created | (existing, finalized) | Yes (historical) | No (done) | Migration continues |

---

## 11. Backend Events and API States

### 11.1 Complete Event Index

| Event Type | File | Emitted By | Status | Key Payload Fields |
|---|---|---|---|---|
| `repair_failure_evidence_written` | `v2_orchestrator_runner.py:1148` | `_maybe_write_repair_failure_context()` | `"completed"` | `command_id`, `failure_source`, `failure_evidence_ref`, `failure_evidence_checksum`, `failure_evidence_artifact_checksum` |
| `repair_context_pack_written` | `v2_orchestrator_runner.py:1162` | `_maybe_write_repair_failure_context()` | `"completed"` | `command_id`, `context_pack_ref`, `context_pack_checksum`, `failure_evidence_checksum`, `base_repo_state_checksum` |
| `repair_chain_started` | `v2_repair_gate_service.py:1245` | `_emit_repair_chain_started()` | `"started"` | `job_id`, `stage_index`, `command_id`, `context_pack_checksum` |
| `repair_llm_main_completed` | `v2_repair_gate_service.py:1533` | `_emit_llm_role_completed()` | `"completed"` | `invocation_id`, `role`, `responsibility`, `provider_alias`, `deployment_alias_hash`, tokens, latency |
| `repair_llm_reviewer_completed` | `v2_repair_gate_service.py:1533` | `_emit_llm_role_completed()` | `"completed"` | Same as above, `role="reviewer"` |
| `repair_primary_schema_invalid` | `v2_repair_gate_service.py:759` | `_emit_reviewed_repair_unavailable()` | `"failed"` | `reason_code`, `schema_name`, `main_invocation_id` |
| `reviewed_repair_materialization_failed` | `v2_repair_gate_service.py:990` | `_emit_reviewed_repair_materialization_failed()` | `"failed"` | `reason_code`, `detail`, `main_invocation_id`, `reviewer_invocation_id`, `final_diff_exists`, `policy_ran`, `gate_created`, `proposal_created`, 20+ diagnostic fields |
| `reviewed_repair_unavailable` | `v2_repair_gate_service.py:896` | `_emit_reviewed_repair_unavailable()` | `"blocked"` | `reason_code`, `title`, `detail`, `main_invocation_id`, `reviewer_invocation_id`, `allowed_actions` |
| `retry_required` | `v2_repair_gate_service.py:1208` | `_emit_reviewed_repair_materialization_failed()` | `"failed"` | `retry_status`, `retry_reason` |
| `repair_diff_materialized` | `v2_repair_gate_service.py:1298` | `_emit_reviewed_repair_materialized()` | `"completed"` | `gate_checksum`, `gate_id`, `stage_index`, `diff_checksum`, `kind="reviewed_gate"` |
| `repair_diff_ready_for_user_apply` | `v2_repair_gate_service.py:1342` | `_emit_repair_diff_ready_for_user_apply()` | `"completed"` | `proposal_id`, `diff_checksum`, `kind="direct_reviewed_diff"` |
| `repair_candidate_diff_ready_for_user_apply` | `v2_repair_gate_service.py:1384` | `_emit_repair_candidate_diff_ready_for_user_apply()` | `"completed"` | `proposal_id`, `diff_checksum`, `kind="direct_candidate_diff"` |
| `repair_approve_apply_check_failed` | `app.py:4954` | `approve_repair_proposal_sandbox_apply()` | `"failed"` | `proposal_id`, `sandbox_path`, apply result diagnostics |
| `repair_approve_patch_apply_failed` | `app.py:4957` | `approve_repair_proposal_sandbox_apply()` | `"failed"` | Same as above |
| `repair_approve_apply_failed` | `app.py` | `approve_repair_proposal_sandbox_apply()` | `"failed"` | Other apply failures |
| `repair_validation_passed` | `app.py` | `approve_repair_proposal_sandbox_apply()` | `"completed"` | `proposal_id`, `stage_index` |
| `stage_completed` | `app.py:5028` | `approve_repair_proposal_sandbox_apply()` | `"completed"` | Direct path: validation passed, auto-queue triggered |
| `repair_validation_failed` | `app.py` | `approve_repair_proposal_sandbox_apply()` | `"failed"` | `proposal_id`, `validation_result` |

### 11.2 How UI/API Uses Events

- **Pipeline projection:** `_v2_pipeline_projection()` (`app.py:13535`) filters events to `_IMPORTANT_EVENT_TYPES` + active stage
- **Failure summary:** `_v2_failure_summary()` (`app.py:13813`) groups failures and separates repair events from original failures
- **Materialization blocker detection:** `_latest_repair_materialization_blocker()` (`app.py:13523`) scans for `reviewed_repair_materialization_failed`, `reviewed_repair_unavailable`, `retry_required`
- **Unavailable diagnostic:** `_latest_repair_materialization_unavailable()` (`app.py:783`) builds detailed diagnostic from events

---

## 12. Frontend Rendering States

### 12.1 All Major States

| State | Component(s) | Condition |
|---|---|---|
| **Loading** | Spinner/loading text | `proposalState.status === "loading"` |
| **No proposal** | `"No repair proposal"` text (RepairProposalPanel:375) | `proposalState.status === "no-proposal"` with no unavailable diagnostic |
| **materialization_failed** | `ReviewedRepairMaterializationFailed` (RepairProposalPanel:834) | `proposalState.unavailable?.kind === "materialization_failed"` |
| **Review chain activity (non-MF)** | `ReviewedRepairUnavailable` (RepairProposalPanel:598) | Unavailable but not materialization_failed; main completed, reviewer schema invalid, etc. |
| **Direct reviewer diff** | `RepairProposalPanel` + `ReviewedDiffTabs` + `RepairActionsBar` | `proposalState.status === "available"` and `kind === "direct_reviewed_diff"` |
| **Direct candidate diff** | Same components, "Proposed Diff (Candidate)" tab label, "Apply candidate diff" button | `proposalState.status === "available"` and `kind === "direct_candidate_diff"` |
| **Gate-based** | Same components, "Approve sandbox apply" button | `proposalState.status === "available"` and `kind === "reviewed_gate"` |
| **Error** | Error message | `proposalState.status === "error"` |
| **Approve processing** | Loading overlay | After user clicks apply (in-progress) |
| **Apply failed** | Error state in `RepairActionsBar` | `apply_status === "approve_failed"` |
| **Validation running** | `ValidationProgressPanel` | After apply succeeds, during validation |
| **Validation passed** | Success state | `rerun_status === "passed"` |
| **Validation failed** | Failure state with retry options | `rerun_status === "failed"` |
| **Continued** | Migration cockpit moves to next stage | After `_auto_queue_next_stage()` |

### 12.2 Component Responsibilities

| Component | What It Renders |
|---|---|
| `RepairProposalPanel` | Fetches proposal, dispatches to correct sub-view, orchestrates approve flow |
| `ReviewedDiffTabs` | Four tabs: Reviewed Diff (or Proposed Diff), Validation, Files Changed, Reviewer Verdict |
| `RepairActionsBar` | Apply button with status-specific text and error display |
| `ValidationProgressPanel` | Build/test progress during validation |
| `ReviewerVerdictCard` | Reviewer decision, reasoning, findings, risks, missing evidence |
| `ReviewedRepairMaterializationFailed` | Detailed materialization failure with reason, diagnostics, invocation IDs, actions |
| `ReviewedRepairUnavailable` | Review chain activity status with state-specific messaging |

### 12.3 Tab Label Variations

| Kind | Diff Tab Label | Verdict Tab Label | Apply Button Text |
|---|---|---|---|
| `direct_reviewed_diff` | "Reviewed Diff" | "Reviewer Verdict" | "Apply reviewer diff" |
| `direct_candidate_diff` | "Proposed Diff (Candidate)" | "Reviewer Findings" | "Apply candidate diff" |
| `reviewed_gate` | "Reviewed Diff" | "Reviewer Verdict" | "Approve sandbox apply" |

---

## 13. Current Pain Points / Old Behaviors

Documenting known behaviors from code analysis only — not proposing fixes:

### 13.1 Proposal = null hides a diff
In `get_current_repair_proposal()` (app.py:4067), when `diff_ref` is None on the record, the API returns `proposal=null` with an `unavailable` diagnostic — even if a diff was materialized elsewhere. This means a valid diff could exist but never be shown if the ref is lost.

### 13.2 materialization_failed used broadly
The `unavailable.kind = "materialization_failed"` is set unconditionally in `_latest_repair_materialization_unavailable()` (app.py:891). This is used for many distinct failure modes: reviewer non-accept, main schema invalid, malformed diff, duplicate blocked, etc. The frontend renders the same component for all of these.

### 13.3 Reviewer non-accept blocks proposal creation
When reviewer returns `reject`, `needs_more_context`, or the accept contract is invalid, no proposal is created and `materialization_failed` is emitted. The only non-accept path that produces a proposal is `needs_revision` (and only when `proposed_diff_exists` and the candidate diff passes validation). This means reviewers can effectively block the entire flow without a fallback path.

### 13.4 Frontend copy may not match backend state
`ReviewedDiffTabs` label logic switches between "Proposed Diff (Candidate)" / "Reviewed Diff" and "Reviewer Findings" / "Reviewer Verdict" based on `kind`. The `kind` derivation in `build_reviewed_diff_proposal_from_record` (projection:349-356) uses `gate_id is None` + `reviewer_decision != "accept"` to determine `direct_candidate_diff`. There's a gap: if the gate service creates a `direct_candidate_diff` but the reviewer_decision is somehow `"accept"`, the kind would appear as `direct_reviewed_diff`.

### 13.5 Validation failure loop risk
In the direct path, `create_next_repair_cycle_from_rerun_failure()` builds new failure evidence from the rerun output and creates a fresh repair chain. This re-triggers `produce_repair_review_chain()` and potentially creates a new proposal. The max cycle guard is `max_cycles` in `RepairContextPack` (default 3), but the code relies on the cycle_number being incremented correctly between runs.

### 13.6 Event naming inconsistency
- Proposal ready events use `repair_diff_ready_for_user_apply` and `repair_candidate_diff_ready_for_user_apply` but the general event is `repair_diff_materialized`
- Materialization failure events include `reviewed_repair_materialization_failed` and `reviewed_repair_unavailable` which are similar but triggered in different circumstances
- Main LLM events use `repair_llm_main_completed` while the role is "proposer" in the enum

### 13.7 Checksum drift at approve time
The triple-checksum verification at approve time (app.py:4631-4674) is robust but can fail for benign reasons (e.g., disk encoding, filesystem timing). If any checksum check fails, the entire approve flow is aborted with a 409. There is no auto-recovery or re-materialization attempt.

### 13.8 apply_patch_to_sandbox vs apply_patch_to_sandbox_direct
Two different patch apply functions exist with overlapping but different behavior:
- `apply_patch_to_sandbox()` (line 229): used for gated path, returns `"APPLIED"` or `"REJECTED"` only
- `apply_patch_to_sandbox_direct()` (line 500): used for direct path, also returns `"ALREADY_APPLIED"`
- Both perform similar preflight/check/apply steps but with different error handling. This is a maintenance risk.

---

## 14. Safe Future Change Points

For a future engineer modifying the repair/LLM/diff flow:

### 14.1 Adding a New LLM Role

| File | Function/Class | Why | Risk |
|---|---|---|---|
| `v2_model_role_router.py:35` | `V2ModelRole` enum | Add new enum value | Must update `_role_to_config_role()`, `_role_to_env_key()`, `_OLD_ROLE_ENV` |
| `v2_model_role_config.py:60` | `ModelRoleConfigLoader._read_role_env()` | Support new env vars | Must add defaults and env var prefix |
| `v2_model_schemas.py` | Add new schema to `SCHEMA_REGISTRY` | Schema must be registered | Must match validation expectations |

### 14.2 Modifying Reviewer Decision Handling

| File | Function/Class | Why | Risk |
|---|---|---|---|
| `repair_review_chain.py:2206` | `_decision_reason_map` | Add new decision → reason mapping | Must update non-accept handler |
| `repair_review_chain.py:500` | `_coerce_reviewer_repair_output()` | Update valid decisions set | Must keep backward compat |
| `v2_repair_gate_service.py:265` | Exception handler in `create_reviewed_repair_gate_on_failure()` | Add new branch for new decision | Must not break `needs_revision` → `direct_candidate_diff` path |
| `v2_repair_projection.py:349` | Kind derivation | New decision may affect kind | Must not assume gate_id is None means `direct_candidate_diff` |

### 14.3 Changing Proposal Persistence

| File | Function/Class | Why | Risk |
|---|---|---|---|
| `v2_repair_gate_service.py:1549` | `_persist_reviewed_repair_proposal()` | Gate-based proposals | Must preserve `diff_ref`, `diff_checksum`, `gate_id` |
| `v2_repair_gate_service.py:1719` | `_persist_direct_reviewed_repair_proposal()` | Direct reviewer proposals | Must preserve reviewer_decision = "accept" |
| `v2_repair_gate_service.py:1842` | `_persist_direct_candidate_repair_proposal()` | Candidate proposals | Must preserve diff source as proposer's diff |
| `v2_repair_repository.py:12` | `V2RepairProposalRecord` | Record schema | Adding fields requires migration; removing fields may break queries |
| `v2_repair_projection.py:300` | `build_reviewed_diff_proposal_from_record()` | Record → projection | Must update `kind` derivation |

### 14.4 Frontend: Adding New Proposal Kind

| File | Component/Type | Why | Risk |
|---|---|---|---|
| `contracts.ts:1188` | `ReviewedDiffProposal.kind` | Type union | Must add to all checks/sidebars |
| `RepairProposalPanel.tsx:28` | `ProposalState` | State machine | May need new state variants |
| `ReviewedDiffTabs.tsx` | Tab labels | Kind-dependent labels | Must handle new label mapping |
| `RepairActionsBar.tsx` | Apply button text | Kind-dependent text | Must handle new kind |

### 14.5 Changing Apply/Validation Flow

| File | Function/Class | Why | Risk |
|---|---|---|---|
| `patch_apply.py:229` | `apply_patch_to_sandbox()` | Gated apply | Must preserve git apply --check and status returns |
| `patch_apply.py:500` | `apply_patch_to_sandbox_direct()` | Direct apply | Must preserve ALREADY_APPLIED detection |
| `app.py:4572` | `approve_repair_proposal_sandbox_apply()` | Approve handler | Triple checksum verification is security-critical |
| `validation_runner.py:32` | `run_validation_after_patch()` | Post-apply validation | Build and test must run in correct sequence |
| `v2_repair_gate_service.py:3071` | `create_next_repair_cycle_from_rerun_failure()` | Rerun → new cycle | Must increment cycle_number and respect max_cycles |

### 14.6 What NOT to Break

- Triple-checksum verification at approve time (security boundary)
- `diff_ref` filesystem path integrity — if this gets out of sync, diffs cannot be loaded
- `RepairReviewChainProductionError.partial_chain` — relied upon by gate service for diagnostics
- `_repair_failure_evidence_ref` / `_repair_context_pack_ref` payload keys — these are the bridge between orchestrator and gate service
- The idempotency guard `(job_id, stage_index, command_id)` in `_chain_attempted`
- `skip_self_repair=True` parameter — controls whether reviewer self-repair is attempted
- `max_cycles` default of 3 in `RepairContextPack` — infinite loops would block pipelines

---

## 15. Files and Functions Index

### 15.1 Backend: Failure Evidence and Context

| File | Key Functions/Classes |
|---|---|
| `migration_factory/repair_loop/failure_evidence.py` | `FailureEvidence` (line 47), `FailureSource` enum (line 21), `NormalizedCompilerError` (line 30), `NormalizedTestFailure` (line 39), `failure_evidence_to_dict()` (line 211), `compute_failure_content_checksum()` (line 83), `compute_failure_artifact_checksum()` (line 119) |
| `migration_factory/repair_loop/repair_context.py` | `RepairContextPack` (line 34), `build_repair_context_pack()` (line 117), `context_pack_to_dict()` (line 225), `compute_context_pack_checksum()` (line 62), `compute_base_repo_state_checksum()` (line 89) |
| `migration_factory/control_tower/application/v2_orchestrator_runner.py` | `V2OrchestratorRunner._maybe_write_repair_failure_context()` (line 1026), `_handle_exit()` (line ~389), `_build_source_contexts()` (line 2542), `_extract_compiler_errors()` (line 2379), `_maybe_diagnose()` (line 1281), `_emit_diagnostic_failure_events()` (line 1225), `_repair_callback_payload()` (line 2779) |
| `migration_factory/control_tower/domain/checksums.py` | `sha256_canonical_json()` (line 43), `canonical_json_bytes()` (line 35), `canonical_json_text()` (line 22) |

### 15.2 LLM / Proposer

| File | Key Functions/Classes |
|---|---|
| `migration_factory/orchestrator/repair_review_chain.py` | `produce_repair_review_chain()` (line 1596), `_primary_repair_prompt()` (line 149), `_coerce_primary_repair_output()` (line 467), `_validate_primary_repair_output()` (line 1040), `_compute_primary_repair_checksum()` (line 635), `_extract_json_safe()` (line 423), `_build_deterministic_repair_payload()` (line 114), `_compute_main_diff_diagnostics()` (line 1457) |
| `migration_factory/control_tower/application/v2_assistant_model_client.py` | `V2AssistantModelClient.answer_with_role()` (line 222), `_build_messages()` (line 747), `_assistant_system_prompt()` (line 1021), `_answer_with_deployment()` (line 257) |
| `migration_factory/control_tower/application/v2_model_role_router.py` | `V2ModelRole` enum (line 35), `V2ModelRoleRouter.route()` (line ~84), `_role_to_config_role()` (line 63), `_role_to_env_key()` (line 52), `_resolve_deployment_for_role()` (line 74), `_schema_diagnostics()` (line 706), `_schema_failure_reason()` (line 611) |
| `migration_factory/control_tower/application/v2_model_role_config.py` | `ModelRoleConfigLoader._read_role_env()` (line 60), `ModelRoleConfig` (line 20) |
| `migration_factory/control_tower/application/v2_model_schemas.py` | `REPAIR_PRIMARY_OUTPUT_SCHEMA` (line 82), `SCHEMA_REGISTRY` (line ~457) |
| `migration_factory/control_tower/application/v2_llm_invocation_ledger.py` | `V2LLMInvocationLedger.start_invocation()` (line 139), `complete_invocation()` (line ~179), `fail_invocation()` (line ~195), `record_to_dto()` (line 221) |

### 15.3 Reviewer

| File | Key Functions/Classes |
|---|---|
| `migration_factory/orchestrator/repair_review_chain.py` | `_reviewer_repair_prompt()` (line 205), `_coerce_reviewer_repair_output()` (line 500), `_reviewer_accept_contract_issue()` (line 1123), `_reviewed_diff_mechanical_issue()` (line 1139), `_invoke_reviewer_self_repair()` (line 1411), `_partial_failed_review_chain()` (line 1232), `_persist_failure_review_chain()` (line 1177), `_persist_reviewed_diff_validation_failure()` (line 1297), `_strip_reviewed_diff_fences()` (line 1117) |
| `migration_factory/control_tower/application/v2_repair_gate_service.py` | `create_reviewed_repair_gate_on_failure()` (line 159), `produce_reviewer_applicability_repair()` (line ~370), `_reviewed_repair_unavailable_reason()` (line ~3515), `_materialization_reason_code()` (line ~3545) |

### 15.4 Proposal Persistence

| File | Key Functions/Classes |
|---|---|
| `migration_factory/control_tower/application/v2_repair_gate_service.py` | `_persist_reviewed_repair_proposal()` (line 1549), `_persist_direct_reviewed_repair_proposal()` (line 1719), `_persist_direct_candidate_repair_proposal()` (line 1842), `_validate_direct_proposal_diff()` (line 1656), `_validate_direct_candidate_diff()` (line 1794), `_fail_direct_materialization()` (line ~520), `create_repair_gate_from_reviewed_chain()` (line ~2101), `create_next_repair_cycle_from_rerun_failure()` (line 3071), `handle_repair_validation_result()` (line 2955) |
| `migration_factory/control_tower/infrastructure/sqlite/v2_repair_repository.py` | `V2RepairProposalRecord` (line 12), `get_current_proposal_for_job()` (line ~200), `update_proposal_prf_fields()` (line ~140) |
| `migration_factory/control_tower/application/v2_repair_projection.py` | `build_reviewed_diff_proposal_from_record()` (line 300), `build_reviewed_diff_proposal_projection()` (line ~270), `ReviewedDiffProposal` (line ~273), `reviewed_diff_proposal_to_safe_dict()` (line 360), `safe_diff_preview_to_dict()` (line ~50) |

### 15.5 API

| File | Endpoints/Functions |
|---|---|
| `migration_factory/control_tower/adapters/fastapi/app.py` | `get_current_repair_proposal()` (line 4067), `get_repair_proposal()` (line 4194), `get_repair_proposal_diff()` (line ~4430), `approve_repair_proposal_sandbox_apply()` (line 4572), `RepairProposalApproveRequest` (line ~666), `_latest_repair_materialization_unavailable()` (line 783), `_latest_repair_materialization_blocker()` (line 13523), `_v2_failure_summary()` (line 13813), `_v2_pipeline_projection()` (line 13535), `_resolve_reviewed_repair_runtime_context()` (line 13065), `_resolve_direct_repair_runtime_context()` (line 13250), `_auto_queue_next_stage()` (line 1306 in v2_orchestrator_runner.py) |
| `migration_factory/control_tower/application/v2_repair_projection.py` | `reviewed_diff_proposal_to_safe_dict()` (line 360), `build_reviewed_diff_proposal_from_record()` (line ~300), `build_disallowed_info()` (line ~40) |

### 15.6 Frontend

| File | Components/Functions |
|---|---|
| `web/control-tower/lib/contracts.ts` | `SafeDiffPreview` (line 1156), `ReviewedDiffProposal` (line 1186), `RepairMaterializationUnavailable` (line 1258), `RepairProposalCurrentResponse` (line 1320), `RepairProposalApproveRequest` (line 1386), `V2LlmInvocationEntry` (line 1226), `ReviewerVerdictProjection` (line 1169), `RepairAttemptSummary` (line 1337) |
| `web/control-tower/lib/controlTowerApi.ts` | `getCurrentRepairProposal()` (line 721), `getRepairProposal()` (~line 735), `getRepairProposalDiff()` (~line 745), `approveRepairProposal()` (~line 760) |
| `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` | `RepairProposalPanel`, `ProposalState` (line 28), `handleApproveSandboxApply()` (line 274), `ReviewedRepairMaterializationFailed` (line 834), `ReviewedRepairUnavailable` (line 598) |
| `web/control-tower/app/migrations/[jobId]/ReviewedDiffTabs.tsx` | `ReviewedDiffTabs` (line 11), four tabs with kind-dependent labels |
| `web/control-tower/app/migrations/[jobId]/RepairActionsBar.tsx` | `RepairActionsBar` (line 6), apply button with kind-dependent text |
| `web/control-tower/app/migrations/[jobId]/ReviewerVerdictCard.tsx` | `ReviewerVerdictCard` |
| `web/control-tower/app/migrations/[jobId]/ValidationProgressPanel.tsx` | `ValidationProgressPanel` |
| `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx` | `MigrationCockpit` |

### 15.7 Apply / Validation / Continuation

| File | Key Functions/Classes |
|---|---|
| `migration_factory/repair_loop/patch_apply.py` | `apply_patch_to_sandbox()` (line 229), `apply_patch_to_sandbox_direct()` (line 500), `check_patch_applicability()` (line 443), `validate_unified_diff_structure()` (line ~30), `PatchApplyResult` |
| `migration_factory/repair_loop/validation_runner.py` | `run_validation_after_patch()` (line 32), `run_build_agent()` (~line 80), `run_test_agent()` (~line 120), `build_h2_startup_report()` (~line 160), `ValidationResult` |
| `migration_factory/control_tower/application/v2_orchestrator_runner.py` | `_auto_queue_next_stage()` (line 1306) |
| `migration_factory/control_tower/application/v2_repair_gate_service.py` | `create_next_repair_cycle_from_rerun_failure()` (line 3071), `handle_repair_validation_result()` (line 2955), `rollback_patch()` (~line 2910) |
| `migration_factory/control_tower/adapters/fastapi/app.py` | `approve_repair_proposal_sandbox_apply()` (line 4572) |

---

## 16. Open Questions

These are actual unknowns that may need manual confirmation:

1. **`skip_self_repair=True`**: In `create_reviewed_repair_gate_on_failure()`, `produce_repair_review_chain()` is called with `skip_self_repair=True` (line 263). This means reviewer self-repair is disabled in production. The import replacement fallback (`materialize_import_replacement_diff()`) is presumably still active. Which AMF ticket controls enabling self-repair?

2. **Gate path usage**: The `create_repair_gate_from_reviewed_chain()` gate path (line 619) is listed as the ELSE fallback when `final_diff_exists` and `proposed_diff_exists` are both False. Is this path still actively used, or has it been supplanted by the direct paths?

3. **`_validate_direct_proposal_diff()` vs `_validate_direct_candidate_diff()`**: Both run structural validation and `git apply --check` but produce different validation diagnostics. Are their validation criteria identical or do they differ by intent?

4. **`DEFAULT_MAX_REPAIR_ATTEMPTS = 3`**: Is this configurable per job? Per stage? Per profile? Is it exposed anywhere in the UI?

5. **`check_patch_applicability()` return path**: The `CHECKED` status means `git apply --check` passed. Is this status ever used downstream to decide something, or is it informational?

6. **Reviewer applicability repair**: `produce_reviewer_applicability_repair()` (in `v2_repair_gate_service.py`, called around line 2161 for gate path) — is this also used for direct paths? It appears to only be called from the gate-based `create_repair_gate_from_reviewed_chain()`.

7. **Checksum algorithm choice**: SHA-256 of canonical JSON is used throughout. Was there consideration of using the raw diff bytes for diff-level checksums (currently `sha256_canonical_json({"unified_diff": diff_text})`)?

8. **`context_pack_checksum` in prompt**: The context pack checksum is a SHA-256 of the canonical JSON — but the actual context pack JSON is also included in the prompt. If the LLM decides to use the checksum field for validation, does the checksum binding hold after serialization/deserialization round-trip differences?

9. **`reviewed_context_checksum` / `reviewed_primary_output_checksum` binding**: The reviewer must echo back these checksums exactly. What happens if the LLM provider normalizes JSON differently in the prompt vs. what the backend computes?

10. **Frontend `checksum_mismatch` flag**: The `SafeDiffPreview.checksum_mismatch` field is checked at approve time. What scenarios cause this to be True? Disk encoding? Concurrent modification? Filesystem caching?

---

## 17. Final Recommendation

The current codebase implements a full F5 reviewed repair chain with the following architecture:

- **Orchestrator** catches stage failures → builds evidence + context
- **Gate service** triggers the repair review chain
- **Proposer LLM** generates a diff → validated → checksummed
- **Reviewer LLM** evaluates the diff → accepts/rejects/requests revision
- **Reviewer acceptance** (with all validations passing) → `direct_reviewed_diff` proposal
- **Reviewer non-accept + candidate diff** → `direct_candidate_diff` proposal
- **Reviewer rejection / no diff** → `materialization_failed` (no proposal)
- **API** exposes proposal or unavailable diagnostic
- **Frontend** displays diff, reviewer opinion, and apply button
- **User approval** triggers checksum verification, patch apply, build/test validation
- **Validation pass** → continue migration; **failure** → next repair cycle

A future engineer modifying this flow would likely start at:
- `migration_factory/orchestrator/repair_review_chain.py` — the core chain producer
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — the decision logic after chain completion
- `migration_factory/control_tower/application/v2_repair_projection.py` — how proposals map to API responses
- `web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx` — the frontend entry component

The security boundary is the approve endpoint's triple-checksum verification. The fail-closed design ensures an untrusted diff is never applied. The max_cycles guard prevents infinite repair loops.

---

> **End of Handoff.** Branch: `amf252-current-repair-flow-handoff`. File: `AMF252_CURRENT_REPAIR_LLM_DIFF_FLOW_DEEP_HANDOFF.md`.
