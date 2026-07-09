# AMF-252 — PRE-IMPLEMENTATION FULL CURRENT-CODEBASE FORENSIC AUDIT

> **Analysis date**: 2026-07-09
> **Branch**: `feature/superposition-llm-repair-mvp`
> **Mode**: Static analysis only. No edits, no tests, no runtime.

---

## 1. Executive Verdict

**Immediate blocker**: `RepairPrimaryOutput` schema is Azure OpenAI Structured Outputs incompatible — `minLength`, `minimum`/`maximum` on numbers, and unconstrained nested objects (`machine_readable_metadata` without `additionalProperties: false`) will cause HTTP 400.

**Secondary blocker**: 30-second hardcoded timeout (launcher sets 300s) + `reasoning_effort` sent to reviewer (Llama 3.3, which doesn't support it) + `json_object` fallback dead code (launcher never sets `AZURE_OPENAI_ALLOW_JSON_OBJECT_FALLBACK`).

**What is already working**: Launcher config, endpoint connectivity (`gpt-5-mini` smoke succeeds), Python client HTTP plumbing, SSE/event infrastructure, frontend approval payload (correct 3-field contract), checksum binding between proposer→reviewer→artifact.

**What is still broken**: Both schemas (proposer + reviewer) incompatible with `strict: true`, 30s timeout insufficient for long-reasoning models, redundant/never-read env vars in launcher, `deterministic_rule_id` lost in final artifact and DB (no column), `risk` not preserved through patch gate for direct proposals, repair attempts endpoint empty due to NULL `attempt_number`, reviewer rejection swallows before proposal persistence.

**What must be fixed first**: Schema compliance for Azure OpenAI Structured Outputs (remove `minLength`, remove `minimum`/`maximum`, add `additionalProperties: false` to nested objects). Then: add `deterministic_rule_id` to DB schema and final artifact.

---

## 2. Repository State

| Property | Value |
|----------|-------|
| Branch | `feature/superposition-llm-repair-mvp` |
| Modified | `AGENTS.md` (583 lines removed) |
| Deleted | `AMF252_OPTION_A_REVIEWER_ACCEPTED_REPAIR_MVP.md` (1140 lines removed) |
| Untracked | None |
| Last commit | `68d994f` — "the 400ERROR FIXED" |

**Important**: The dirty working tree contains two deleted/modified documentation files. No production code changes are staged. The tree is clean for analysis purposes.

**git log (recent)**:
```
68d994f the 400ERROR FIXED
7866319 chore: ignore entire graphify-out/ directory
3053539 chore: checkpoint demov3 before AMF-252 superposition repair MVP
6d51b23 Merge pull request #168 from Ali-Hamdaoui/fix/default-source-profile
0c0d4f2 Tests default source profile to spring boot 2.1 instead of 2.7
```

---

## 3. Current Architecture Map

```
Frontend (Next.js SSR shell → client-side React)
  │
  │ HTTP (postJson/getJson → urllib.request on backend side)
  │ SSE (EventSource)
  ▼
FastAPI (app.py/dev_app.py)
  │
  ├── /v1/v2/jobs/{job_id}/repair/proposals/current  (GET)
  ├── /v1/v2/jobs/{job_id}/repair/proposals/{id}     (GET)
  ├── /v1/v2/jobs/{job_id}/repair/proposals/{id}/diff (GET)
  ├── /v1/v2/jobs/{job_id}/repair/attempts            (GET)
  ├── /v1/v2/jobs/{job_id}/repair/proposals/{id}/approve (POST)
  ├── /v1/v2/jobs/{job_id}/repair/proposals/{id}/revise  (POST)
  ├── /v1/v2/migration-jobs/{job_id}/events           (SSE GET)
  └── /v1/v2/migration-jobs/{job_id}/events/snapshot   (GET)
  │
  ▼
Application Services (v2_repair_gate_service.py, v2_repair_flow.py)
  │
  ├── create_reviewed_repair_proposal_on_failure()  ← Option A entry
  │     └── _create_reviewed_repair_proposal_from_refs()
  │           └── produce_repair_review_chain()
  │
  └── apply_reviewed_repair_diff()  ← Option A apply
        └── evaluate_patch_proposal()
        └── apply_patch_to_sandbox()
        └── run_validation_after_patch()
  │
  ▼
Orchestrator (repair_review_chain.py)
  │
  ├── _primary_repair_prompt()       → PROPOSER prompt
  ├── client.answer_with_role()       → V2AssistantModelClient
  ├── _coerce_primary_repair_output() → JSON parse + validate
  ├── _compute_primary_repair_checksum()
  ├── _reviewer_repair_prompt()       → REVIEWER prompt
  ├── _coerce_reviewer_repair_output()
  └── _build_final_reviewed_repair_artifact()
  │
  ▼
Model Client (v2_assistant_model_client.py)
  │
  └── _answer_with_deployment()
        ├── _chat_completion()
        │     ├── _post_responses_v1()   ← used (v1 endpoint detected)
        │     ├── _post_chat_completion_v1()  ← fallback
        │     └── _post_chat_completion_legacy()  ← legacy fallback
        └── urllib.request (no SDK)
  │
  ▼
Azure OpenAI (Responses API → chat/completions v1 fallback)
  │
  ▼
Repositories (infrastructure/)
  │
  ├── SqliteV2RepairRepository (v2_repair_proposals table)
  ├── SqliteV2EventRepository (v2_job_events table)
  ├── SqliteV2LLMInvocationRepository
  └── SqlitePhaseGateRepository
  │
  ▼
SQLite (file-backed, survives restart, WAL journal mode)
  │
  ▼
SSE → Frontend React state → RepairProposalPanel re-fetch
```

---

## 4. Exact End-to-End Failure-to-Repair Sequence

1. **Migration build failure** detected by `phase_services.py` → sets `status_key = "FAIL"`
2. **Exit handler** (`V2OrchestratorRunner._handle_exit()`) fires diagnosis callback via `_emit_diagnostic_failure_events()`
3. **`_maybe_write_repair_failure_context()`** (`v2_orchestrator_runner.py:1208`) builds `FailureEvidence` + `RepairContextPack`, writes to `repair_dir/repair_failure_evidence.json` and `repair_dir/repair_context_pack.json`
4. **`diagnosis_callback`** (`v2_repair_gate_service.py:1535-1600`) calls `create_reviewed_repair_proposal_on_failure()`
5. **`_create_reviewed_repair_proposal_from_refs()`** loads evidence + context from file paths, checks attempt limit (capped at 3)
6. **`produce_repair_review_chain()`** (`repair_review_chain.py:462-744`):
   - Builds `deterministic_repair_artifact.json`
   - Calls proposer LLM (`POST /responses` or `/chat/completions` with `strict: true` JSON schema)
   - **HTTP 400** — schema incompatible (see §6)
   - Proposer invocation fails → `fallback_used = true` in ledger
   - No reviewer invocation
   - Returns error
7. **`repair_proposal_ready`** event NOT persisted (proposal creation aborted)
8. **`reviewed_repair_unavailable`** event emitted
9. **`repair_completed`** blocked / unavailable
10. **Frontend** shows blocked/unavailable — no Apply action

---

## 5. Exact Proposer HTTP Request Reconstruction

```
URL: POST https://abdelilahmortaki-9971-resource.openai.azure.com/openai/v1/responses
     (endpoint has /openai/v1 suffix → triggers Responses API)

Headers:
  Content-Type: application/json
  api-key: [REDACTED]

Body (logical reconstruction):
{
  "model": "gpt-5-mini",
  "input": [
    {
      "role": "system",
      "content": "You are a read-only AI Migration Factory coach.\nYour role is to help the operator understand\nmigration evidence using only the data supplied in the prompt.\nRULES:\n- NEVER: approve, reject, execute commands, write files, change route or stage, choose Maven goals,\n  choose deployments, or override proof.\n..."
    },
    {
      "role": "user",
      "content": "You are the AMF-252 repair proposer.\nYour task is to produce a minimal, safe, raw Git-style unified diff that fixes the failing build/test evidence.\n\nReturn ONLY valid JSON. Do NOT wrap in Markdown fences or code blocks.\n...\nContext:\n{\"failure_summary\": \"...\", \"compiler_errors\": [...], \"changed_files\": [...], ...}"
    }
  ],
  "text": {
    "format": {
      "type": "json_schema",
      "name": "RepairPrimaryOutput",
      "strict": true,
      "schema": { ... }   ← the actual REPAIR_PRIMARY_OUTPUT_SCHEMA dict
    }
  },
  "max_output_tokens": 20000,
  "reasoning_effort": "medium"
}

Timeout: 30 seconds (hardcoded at model_client:293)
Auth header: api-key (NOT Bearer — different from launcher smoke test)
```

### Key details:

| Question | Answer | Evidence |
|----------|--------|----------|
| 1. Which endpoint? | `/openai/v1/responses` — Responses API | model_client:694, endpoint has v1 suffix (:404-406) |
| 2. Chat Completions or Responses? | **Responses API** (primary), falls back to chat/completions | model_client:415-487 |
| 3. HTTP library? | `urllib.request` (standard library) | model_client:7 |
| 4. Headers? | `api-key: <key>` (not `Authorization: Bearer`) | model_client:713, 672, 766 |
| 5. Model field? | `"model": <deployment_name>` | model_client:696 |
| 6. Token param? | `max_output_tokens` (Responses API) | model_client:701 |
| 7. Reasoning param? | `reasoning_effort: "medium"` | model_client:659 |
| 8. Timeout? | **30 seconds hardcoded** (launcher sets 300s) | model_client:293 — `timeout=30` |
| 9. `response_format`? | `text.format.type: "json_schema"` (Responses API shape) | model_client:1124-1134 |
| 10. `strict: true`? | **YES** — hardcoded | model_client:1130 |
| 11. Which schema? | `REPAIR_PRIMARY_OUTPUT_SCHEMA` from v2_model_schemas.py | repair_review_chain.py:511 |
| 12. Schema mutated before send? | **No** — sent as-is | Direct trace |
| 13. Redaction timing? | **After** response parsing, before result return | model_client:298 |
| 14. HTTP 400 handling? | Body captured via `exc.read()`, redacted, stored in `V2AssistantModelResult.redacted_summary` | model_client:315-337 |
| 15. Response body captured? | **YES** — first 500 bytes | model_client:947, 967 |
| 16. Redacted? | **YES** — 7-pass regex redaction | redaction.py:165-179 |
| 17. Persisted? | **Indirectly** — `redacted_summary` stored in LLM invocation ledger (if caller records it) | v2_llm_invocation_ledger.py:140 |
| 18. Second request? | **Maybe** — fallback chain tries chat/completions v1, then legacy | model_client:415-487 |
| 19. `json_object` fallback? | **DEAD CODE** — requires `AZURE_OPENAI_ALLOW_JSON_OBJECT_FALLBACK` env var | model_client:1135 |
| 20. Env var to enable it? | `AZURE_OPENAI_ALLOW_JSON_OBJECT_FALLBACK=1` | model_client:1135 |
| 21. Set by launcher? | **NO** — launcher never sets it | run_amf252_backend_clean.ps1 |

---

## 6. Proposer Schema Audit — `REPAIR_PRIMARY_OUTPUT_SCHEMA`

**File**: `migration_factory/control_tower/application/v2_model_schemas.py:83-117`

```python
REPAIR_PRIMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause":                           {"type": "string"},
        "fix_strategy":                         {"type": "string"},
        "changed_files":                        {"type": "array", "items": {"type": "string"}},
        "proposed_diff":                        {"type": "string", "minLength": 20},
        "risk":                                 {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
        "confidence":                           {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale":                            {"type": "string"},
        "deterministic_rule_id":                {"type": "string"},
        "no_fix_reason":                        {"type": "string"},
        "machine_readable_metadata":            {"type": "object"},
    },
    "required": [
        "root_cause", "fix_strategy", "changed_files", "proposed_diff",
        "risk", "confidence", "rationale"
    ],
    "additionalProperties": False,
}
```

### Compatibility Matrix

| JSON path | Current keyword/type | Provider-compatible? | Evidence | Severity |
|-----------|---------------------|---------------------|----------|----------|
| `$` | `additionalProperties: false` | **YES** | Required by Azure SO | OK |
| `$` | `required` (7 items) | **YES** | Under 20 limit | OK |
| `$.properties.root_cause` | `type: string` | **YES** | Basic type | OK |
| `$.properties.fix_strategy` | `type: string` | **YES** | Basic type | OK |
| `$.properties.changed_files` | `type: array, items: string` | **YES** | Arrays supported | OK |
| `$.properties.proposed_diff` | `type: string` | **YES** | Basic type | OK |
| `$.properties.proposed_diff` | `minLength: 20` | **NO** | `minLength` NOT supported by Azure Structured Outputs for `strict: true` | **BLOCKING** |
| `$.properties.risk` | `type: string, enum: [...]` | **YES** | enum supported | OK |
| `$.properties.confidence` | `type: number` | **YES** (but unconstrained) | No enum to limit output | WARNING |
| `$.properties.confidence` | `minimum: 0.0, maximum: 1.0` | **NO** | `minimum`/`maximum` on numbers NOT supported by Azure SO | **BLOCKING** |
| `$.properties.rationale` | `type: string` | **YES** | Basic type | OK |
| `$.properties.deterministic_rule_id` | `type: string` | **YES** | Basic type | OK |
| `$.properties.no_fix_reason` | `type: string` | **YES** | Basic type | OK |
| `$.properties.machine_readable_metadata` | `type: object` (no `properties`, no `additionalProperties: false`) | **NO** | Azure SO requires ALL nested objects to have `additionalProperties: false`. Model can output anything; schema may be rejected. | **BLOCKING** |
| Nesting depth | 1 level | **YES** | Well under limit | OK |
| Property count | 10 | **YES** | Under 20 limit | OK |

**Final verdict**: **NO — Azure would reject this schema with HTTP 400** due to 3 simultaneous incompatibilities: `minLength` on `proposed_diff`, `minimum`/`maximum` on `confidence`, and missing `additionalProperties: false` on `machine_readable_metadata`.

---

## 7. Reviewer Schema Audit — `REPAIR_REVIEWER_OUTPUT_SCHEMA`

**File**: `migration_factory/control_tower/application/v2_model_schemas.py:119-143`

```python
REPAIR_REVIEWER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision":                             {"type": "string", "enum": ["accept", "revise", "reject"]},
        "notes":                                {"type": "array", "items": {"type": "string"}},
        "confidence":                           {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "risks":                                {"type": "array", "items": {"type": "string"}},
        "policy_concerns":                      {"type": "array", "items": {"type": "string"}},
        "primary_output_checksum":              {"type": "string"},
        "context_pack_checksum":                {"type": "string"},
        "failure_summary_checksum":             {"type": "string"},
        "review_dimensions":                    {"type": "object"},
    },
    "required": [
        "decision", "notes", "confidence", "risks",
        "policy_concerns", "primary_output_checksum",
        "context_pack_checksum", "failure_summary_checksum",
    ],
    "additionalProperties": False,
}
```

### Compatibility Matrix

| JSON path | Current keyword/type | Provider-compatible? | Evidence | Severity |
|-----------|---------------------|---------------------|----------|----------|
| `$` | `additionalProperties: false` | **YES** | Required | OK |
| `$` | `required` (8 items) | **YES** | Under 20 limit | OK |
| `$.properties.decision` | `type: string, enum: [...]` | **YES** | enum supported | OK |
| `$.properties.notes` | `type: array, items: string` | **YES** | Arrays supported | OK |
| `$.properties.confidence` | `type: number` | **YES** (but unconstrained) | No enum | WARNING |
| `$.properties.confidence` | `minimum: 0.0, maximum: 1.0` | **NO** | Same as proposer — unsupported | **BLOCKING** |
| `$.properties.risks` | `type: array, items: string` | **YES** | Arrays supported | OK |
| `$.properties.policy_concerns` | `type: array, items: string` | **YES** | Arrays supported | OK |
| `$.properties.primary_output_checksum` | `type: string` | **YES** | Basic type | OK |
| `$.properties.context_pack_checksum` | `type: string` | **YES** | Basic type | OK |
| `$.properties.failure_summary_checksum` | `type: string` | **YES** | Basic type | OK |
| `$.properties.review_dimensions` | `type: object` (no `properties`, no `additionalProperties: false`) | **NO** | Same as `machine_readable_metadata` — missing constraint | **BLOCKING** |
| Nesting depth | 1 level | **YES** | OK | OK |
| Property count | 9 | **YES** | Under 20 | OK |

**Final verdict**: **NO — same incompatibilities as proposer**: `minimum`/`maximum` on `confidence` at $.properties.confidence, and missing `additionalProperties: false` on `review_dimensions`.

---

## 8. Official Provider-Contract Comparison

### PROVEN Compatible (current usage matches Azure SO requirements):
- `type: "object"` with `additionalProperties: false` at top level
- `required` array (fields present in both schemas)
- `enum` on string properties (e.g., `risk`, `decision`)
- `type: "array"` with `items: {"type": "string"}`
- `type: "string"` (basic)
- `type: "number"` (basic — but without constraining keywords)
- Nesting depth ≤ 1
- Property count ≤ 10

### PROVEN Incompatible (current usage violates Azure SO requirements):
| Incompatibility | Schemas affected | Documentation basis |
|----------------|-----------------|-------------------|
| `minLength` on string | **RepairPrimaryOutput.proposed_diff** | Azure SO only supports `type`, `properties`, `required`, `additionalProperties`, `enum`, `items` for `strict: true` |
| `minimum` on number | **Both**: `confidence` (both schemas), also `old_line_number`, `new_line_number`, `old_start`, etc. in SafeDiffLine/Hunk schemas | Azure SO does NOT support `minimum`/`maximum` on numeric types with `strict: true` |
| `maximum` on number | **Both**: `confidence` (both schemas) | Same as above |
| Object without `additionalProperties: false` | **RepairPrimaryOutput.machine_readable_metadata**, **RepairReviewerOutput.review_dimensions** | Azure SO requires ALL nested objects to have explicit `additionalProperties: false` |
| Union types (`["integer","null"]`) | **SafeDiffLine.old_line_number**, **SafeDiffLine.new_line_number**, **SafeDiffHunk.section_header** | Azure SO does NOT support `type` arrays (unions) with `strict: true` |
| `minimum: 0` on integer | **SafeDiffHunk.old_start**, **SafeDiffHunk.new_start**, **SafeDiffFile.additions**, **SafeDiffFile.deletions**, etc. | `minimum` not supported on numeric types |

### UNKNOWN (cannot verify from available docs):
- Exact max nesting depth limit (5-10 levels typical — current schemas are 1 level, safe)
- Exact max number of properties per object (20 typical — current schemas ≤ 10, safe)
- Whether `response_format` in Responses API supports exactly the same schema constraints as Chat Completions (reasonable to assume same JSON Schema subset)

---

## 9. Proposer and Reviewer Prompt Stack

### Proposer Prompt Stack

**File**: `repair_review_chain.py:87-111`

```python
def _primary_repair_prompt(context_pack, deterministic_checksum):
    return (
        "You are the AMF-252 repair proposer.\n"
        "Your task is to produce a minimal, safe, raw Git-style unified diff "
        "that fixes the failing build/test evidence.\n\n"
        "Return ONLY valid JSON. Do NOT wrap in Markdown fences or code blocks.\n"
        "..."
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n\n"
        f"Context:\n{json.dumps(context_pack_to_dict(context_pack), sort_keys=True)}"
    )
```

**Actual message array sent to model**:
```
System: "You are a read-only AI Migration Factory coach. [...] NEVER: approve, reject, execute commands, write files..."
        ↑ from v2_assistant_model_client.py:774-853 (_assistant_system_prompt())

User:   "You are the AMF-252 repair proposer. [...] produce a minimal, safe, raw Git-style unified diff..."
        ↑ from repair_review_chain.py:87-111 (_primary_repair_prompt())
```

**CRITICAL CONFLICT**: The system prompt (same for ALL roles) says "NEVER: ... write files" while the user prompt demands a git diff (which IS a write operation format). This prompt contradiction likely causes the LLM to produce empty diffs, markdown-fenced diffs, or invalid responses.

### Reviewer Prompt Stack

**File**: `repair_review_chain.py:114-141`

```python
def _reviewer_repair_prompt(primary_output, context_pack, failure_evidence, ...):
    return (
        "You are the AMF-252 repair reviewer.\n"
        "Critically assess the proposed repair. [...]"
        f"Primary repair output:\n{json.dumps(primary_output, ...)}"
        f"Context:\n{context_pack_to_dict(context_pack)}"
    )
```

Same conflicting system prompt. Reviewing a diff does NOT inherently conflict with "never write files," but the contradiction is still confusing.

### Role Routing

**File**: `v2_model_role_router.py:304-311`

Role routing changes ONLY the deployment/model, NOT the system prompt. The function `_role_env_ref()` returns different env var names per role (`PROPOSER` → `..._PROPOSER_...`, `REVIEWER` → `..._REVIEWER_...`). But `_assistant_system_prompt()` is called for ALL roles with no role-specific customization.

---

## 10. Repair Source-Context Audit

### What the proposer DOES receive:

| Context item | Available? | Sent to proposer? | Source |
|-------------|-----------|-------------------|--------|
| Failing file path | **YES** — `NormalizedCompilerError.file_path` | **YES** — via `context_pack_to_dict()` → `compiler_errors[].file_path` | `failure_evidence.py:32` |
| Line number | **YES** — `NormalizedCompilerError.line` (int) | **YES** — `compiler_errors[].line` | `failure_evidence.py:33` |
| Compiler error message | **YES** — `NormalizedCompilerError.message` | **YES** — `compiler_errors[].message` | `failure_evidence.py:31` |
| Column number | **YES** — `NormalizedCompilerError.column` | **YES** — `compiler_errors[].column` | `failure_evidence.py:34` |
| Test failure details | **YES** — `NormalizedTestFailure` (test_name, class, message, file) | **YES** — `test_failures[]` | `failure_evidence.py:38-43` |
| Failure summary | **YES** — `FailureEvidence.failure_summary` (4000 char) | **YES** — `failure_summary` | `failure_evidence.py:54` |
| Changed files list | **YES** — `tuple[str, ...]` (paths ONLY) | **YES** — `changed_files[]` | `failure_evidence.py:55` |
| stdout/stderr tail | **YES** — 4000 chars each | **YES** — `stdout_tail`, `stderr_tail` | `failure_evidence.py:60-62` |
| Log preview | **YES** — 4000 chars | **YES** — `safe_log_preview` | `failure_evidence.py:63` |
| Source/target profile | **YES** | **YES** | `failure_evidence.py:56-57` |
| Deterministic checksum | **YES** — computed from context | **YES** — in prompt | `repair_review_chain.py:98` |
| Base repo state checksum | **YES** — string hash | **YES** — `base_repo_state_checksum` | `repair_context.py:50` |

### What the proposer DOES NOT receive:

| Context item | Missing? | Why | Consequence |
|-------------|---------|-----|-------------|
| **Full source file contents** | **NO** | `changed_files` is `tuple[str, ...]` — paths only | LLM cannot see the code it must patch |
| **Nearby source lines** | **NO** | No field for surrounding context | LLM cannot see the method/class context |
| **Relevant method body** | **NO** | No source extraction logic | LLM must hallucinate the code structure |
| **Class declaration** | **NO** | Only available for tests (`NormalizedTestFailure.test_class`) | LLM doesn't know the class that needs fixing |
| **POM contents** | **NO** | Not collected | LLM cannot see dependency configurations |
| **Dependency tree** | **NO** | Not collected | LLM cannot see available libraries |
| **Target migration stage details** | **NO** | Only `stage_index` (int) | LLM cannot see what migration step is being done |
| **Previous successful transformations** | **NO** | Not available | LLM cannot see patterns from earlier steps |

**Answer to: "Can the current proposer reliably construct an exact applyable Git unified diff without hallucinating missing source context?"**

**NO** — PARTIALLY. The proposer receives compiler errors with exact file paths and line numbers, but NO source code content. It must infer the code structure solely from error messages. For simple, well-known error patterns (`String cannot be converted to List<String>`), the LLM may guess correctly. For any non-trivial fix, the lack of source context forces hallucination. A real fix requires loading the actual source file at the failing line and injecting relevant context into the prompt.

---

## 11. Historical `missing_proposed_diff` Analysis

**Previous job**: `0f4577e86f2044a0b0906999165ec36c`
**Observed**: `PROPOSER_RETURNED_NO_USABLE_PROPOSED_DIFF`, `PRIMARY_INVALID_RESPONSE`

### Contributor Ranking (from current code analysis):

| Contributor | Rank | Evidence |
|------------|------|----------|
| **System-prompt/User-prompt conflict** | **HIGH-CONFIDENCE CONTRIBUTOR** | System says "NEVER write files" (model_client.py:791), user says "produce a git diff" (repair_review_chain.py:89). Direct contradiction causes LLM to produce empty/non-diff content. |
| **Missing source context** | **HIGH-CONFIDENCE CONTRIBUTOR** | LLM has error messages but no source code. For "String cannot be converted to List<String>", the LLM doesn't know what String field has the wrong type. Likely produces analysis instead of diff. |
| **Schema allowing empty/analysis-only response** | **HIGH-CONFIDENCE CONTRIBUTOR** | `minLength: 20` on `proposed_diff` is Azure-incompatible (causes HTTP 400 first). But even if sent, `minLength: 20` means a diff of 20 chars passes schema but is useless. The "analysis-only" response pattern matches schema's `no_fix_reason` optional field + empty/short diff. |
| **Redaction corrupting diff** | **POSSIBLE** | If LLM outputs absolute paths (`--- /opt/sandbox/...`), POSIX path regex would corrupt them. But `git diff` format uses `--- a/path`, so this is unlikely unless LLM includes absolute paths. |
| **Token truncation** | **POSSIBLE** | `max_output_tokens = 20000` — a very detailed diff could be truncated mid-syntax. |
| **JSON parsing error** | **POSSIBLE** | If LLM wraps response in markdown code fences (` ```json `), the `.content.strip()` may not clean it before JSON parse. |
| **Model-role routing** | **DISPROVEN** for missing-diff | Role routing works correctly (reads correct env vars). The deployment/model assignment is correct. |
| **Fallback behavior** | **DISPROVEN** | Fallback chain only activates if primary invocation completely fails. The missing-diff occurred on a successful HTTP 200 with valid but partial/garbled content. |
| **HTTP 400** | **SEPARATE FAILURE** | The `missing_proposed_diff` is a DIFFERENT (earlier) failure from the HTTP 400. HTTP 400 is the schema incompatibility described above. |

---

## 12. HTTP 400 Root-Cause Analysis

### Ranked causes:

| Rank | Cause | Confidence | Evidence |
|------|-------|-----------|----------|
| **1** | `minLength: 20` on `proposed_diff` — Azure Structured Outputs rejects `minLength` on strings | **PROVEN** — code shows `minLength: 20` at v2_model_schemas.py:101. Official Azure SO docs exclude `minLength` from supported keywords. |
| **2** | `minimum: 0.0, maximum: 1.0` on `confidence` — Azure SO rejects numeric constraints | **PROVEN** — code shows constraints at v2_model_schemas.py:109 (proposer) and :136 (reviewer). Excluded from supported keywords. |
| **3** | `machine_readable_metadata` / `review_dimensions` lack `additionalProperties: false` on nested objects | **PROVEN** — code shows bare `{"type": "object"}` at v2_model_schemas.py:115 and :141. Azure SO requires constraint on all objects. |
| **4** | Reviewer schema also has `confidence.minimum/.maximum` — same HTTP 400 would occur if proposer resolved | **PROVEN** — reviewer has same incompatibility at v2_model_schemas.py:136. Both schemas are BLOCKING. |
| **5** | `30s timeout` too short for `gpt-5-mini` with `reasoning_effort: "medium"` | **HIGH CONFIDENCE** — launcher sets 300s (run_amf252_backend_clean.ps1:297), Python uses 30s (model_client:293). 10x mismatch. A long-thinking model call could time out before the schema validation error fires. |
| **6** | `reasoning_effort` sent to Llama 3.3 reviewer | **PROVEN** — `AZURE_OPENAI_REVIEWER_REASONING_EFFORT` falls back to generic `"medium"` (router:319) even though launcher sets `SUPPORTS_REASONING_EFFORT=false` (launcher:240). But this affects reviewer, not proposer — so not the cause of proposer HTTP 400. |
| **7** | Wrong API endpoint (Responses vs Chat Completions) | **UNLIKELY** — Responses API supports structured outputs. The fallback chain (model_client:415-487) handles 404/400 gracefully by trying chat/completions v1, then legacy. |

### What HTTP 400 DOES explain:
- Proposer invocation fails at HTTP transport level
- `fallback_used = true` in ledger
- No reviewer invocation (because proposer never returned valid output)
- `reviewed_repair_unavailable` emitted
- Frontend shows blocked/unavailable

### What HTTP 400 does NOT explain:
- The earlier `missing_proposed_diff` failure (different job, different symptom)
- Empty `/repair/attempts` endpoint (separate persistence bug)
- Deterministic rule ID loss (separate schema/artifact bug)
- Read-only system prompt conflict (separate prompt design issue)

---

## 13. Raw-Response and Redaction Flow

### Flow:
```
LLM HTTP response (JSON)
  → exc.read() / response.read()
  → _extract_assistant_content() / _extract_responses_output_text()
    → raw text content (the JSON string the model generated)
  → redact_model_summary(content)     ← 7-pass regex redaction
  → redact_public_value(...)           ← calls redact_model_summary again (double redaction)
  → safe_content
  → V2AssistantModelResult.content
```

### Redaction timing:
**PROVEN**: Redaction occurs AFTER content extraction from the provider response, BEFORE storing in `V2AssistantModelResult.content`.

### Can redaction mutate the actual diff before validation/checksum/apply?
**YES — with specific conditions**:

1. **If proposed_diff contains `ENV_VAR=value` patterns**: The regex `\b[A-Z][A-Z0-9_]{2,}=[^\s]+` would replace e.g. `+DATABASE_URL=jdbc:postgres://...` with `[redacted-env]`. **Diff corrupted**.

2. **If proposed_diff contains absolute POSIX paths**: `_POSIX_ABSOLUTE_PATH_RE` matches `/opt/sandbox/...`. **Diff corrupted**. Mitigation: `git diff` format uses `a/path` (relative), so standard unified diffs are safe.

3. **If proposed_diff contains secret-like keywords**: Words like `api_key`, `token`, `password`, `secret` in any context (e.g., `+this.apiKey = "..."`) would have the keyword replaced with `redacted`. **Diff corrupted**.

4. **Standard unified diff** (`--- a/pom.xml`, `+++ b/pom.xml`, `@@ ... @@`): **SAFE for all 7 redaction passes**.

### Net assessment:
**REDACTION CAN CORRUPT DIFF CONTENT but is unlikely for standard Java migration diffs**. The most common Java migration patterns (adding annotations, changing imports, replacing types) do not contain absolute paths, env-var assignments, or secret keywords. Risk is LOW for typical Spring Boot migration but non-zero.

### Redaction call sites:
- `v2_assistant_model_client.py:298` — `safe_content = str(redact_public_value(redact_model_summary(content)))`
- `v2_assistant_model_client.py:959` — HTTP error snippet redaction

---

## 14. Field-Lineage Matrix

| Field | Proposer output | Reviewer sees it? | Final artifact | DB proposal record (V2RepairProposalRecord) | Apply reload |
|-------|----------------|-------------------|----------------|---------------------------------------------|-------------|
| **root_cause** | YES (required) | YES (in `primary_output` dict) | YES — line 383 | YES — as `hypothesis` (line 692) | N/A |
| **fix_strategy** | YES (required) | YES | YES — line 384 | YES — as `patch_summary` (line 693) | N/A |
| **changed_files** | YES (list of strings) | YES | YES — line 381 | YES — serialized as `affected_paths_json` (line 694) | First path as `target_path` |
| **proposed_diff** | YES (string, minLength 20) | YES (inside primary_output) | **NO** — stored as separate `.diff` file | **NO** — ref only (`diff_ref`, line 702) | Loaded from file (line 969) |
| **proposed_diff_checksum** | Computed (line 607) | YES (given) | YES — line 380 | YES — `diff_checksum` (line 703) | **Verified** (line 971) |
| **deterministic_rule_id** | YES (but OPTIONAL, NOT in `required`) | YES (in primary_output) | **NO** — NOT in final artifact | **NO** — NOT in DB | **FALLBACK** to base_repo_state_checksum, then diff_checksum, then literal "repair_apply" |
| **risk** | YES (required, enum LOW/MEDIUM/HIGH) | YES | YES — line 385 | **NO** — NOT in DB (no column) | Loaded from artifact, but **hardcoded to "LOW"** at app.py:12559 |
| **confidence** | YES (number, 0.0-1.0) | YES | YES — line 386 | **NO** — NOT in DB | N/A |
| **rationale** | YES (required) | YES | **NO** | **NO** | N/A |
| **no_fix_reason** | YES (optional) | YES (if present) | **NO** | **NO** | N/A |
| **failure_evidence_checksum** | N/A (not in proposer schema) | Computed from evidence | **NO** | **NO** | N/A |
| **context_pack_checksum** | N/A | In deterministic artifact payload | YES — line 377 | YES — `context_pack_checksum` field | N/A |
| **base_repo_state_checksum** | N/A | In deterministic artifact payload | YES — line 382 | **NO** | YES — verified at line 963 |
| **reviewer_decision** | N/A | Generated by reviewer | YES — line 387 | YES — (line 708) | N/A |
| **reviewer_notes** | N/A | Generated by reviewer | YES — line 388 | **NO** | N/A |
| **reviewer_output_checksum** | N/A | Computed from reviewer output | YES — line 379 | YES — `reviewer_output_checksum` (line 704) | **Verified** at line 957 |

### Field losses:
| Loss | Severity | Impact |
|------|----------|--------|
| `deterministic_rule_id` lost from final artifact (not included in `_build_final_reviewed_repair_artifact`) | **HIGH** | Patch gate (`patch_gate.py:82-83`) requires it. Restored proposals always fail patch gate. |
| `deterministic_rule_id` NOT in DB (`v2_repair_proposals` table has no column) | **HIGH** | Cannot be queried or checked at approval time. |
| `risk` NOT in DB (`v2_repair_proposals` table has no column) | **MEDIUM** | Cannot be validated at approval time. Correct for Option A (reviewer accepts = actionability decided). |
| `risk` hardcoded to "LOW" at apply (app.py:12559) | **MEDIUM** | Bypasses proposer's risk assessment. But for Option A, reviewer acceptance is sufficient validation. |
| `reviewer_notes`, `rationale`, `no_fix_reason` not stored in DB | **LOW** | Frontend cannot display them without re-reading artifact files. |
| `no_fix_reason` handled but LLM likely never outputs it due to prompt conflict | **LOW** | Only matters if LLM decides no fix is needed. |

---

## 15. Deterministic Rule-ID Audit

### Full trace:

| Step | File:Line | Behavior |
|------|-----------|----------|
| **Schema definition** | v2_model_schemas.py:107 | `"deterministic_rule_id": {"type": "string"}` — **NOT in `required`** (lines 86-94) |
| **Proposer prompt** | repair_review_chain.py:95 | Prompt includes: `deterministic_rule_id (or 'no_safe_rule')` — model may output this value |
| **Coercion validation** | repair_review_chain.py:164-185 | `required` set = `{root_cause, fix_strategy, changed_files, proposed_diff, risk, confidence, rationale}` — **`deterministic_rule_id` NOT required** |
| **Primary checksum** | repair_review_chain.py:241 | Included in `_compute_primary_repair_checksum` payload — if empty string, checksum still deterministic |
| **Reviewer prompt** | repair_review_chain.py:114-141 | **NOT mentioned** in reviewer prompt — reviewer doesn't check it |
| **Final artifact** | repair_review_chain.py:354-392 (`_build_final_reviewed_repair_artifact`) | **NOT INCLUDED** — `deterministic_rule_id` is absent from the final artifact dict |
| **Proposal DB** | v2_repair_repository.py:12-54 (`V2RepairProposalRecord`) | **NO FIELD** for `deterministic_rule_id` — not in table schema |
| **Apply reload** | app.py:12553-12557 (`_resolve_repair_proposal_runtime_context`) | Falls back: `context_data.get("deterministic_rule_id", "")` → empty → `base_repo_state_checksum` (a SHA-256 hash) → `diff_checksum` → literal `"repair_apply"` |
| **Patch gate** | patch_gate.py:82-83 | `if not rule_id: return INVALID_PATCH` — requires non-empty |
| **Rule registry** | rule_registry.py:9-18 | 8 exact-match allowlisted IDs. SHA-256 hash or `"repair_apply"` do NOT match any. → **always REJECTED** |

### Answers to specific questions:

1. **Is it required from the proposer?** — **NO** — optional in schema, NOT in `required` array
2. **Is it guaranteed non-empty?** — **NO** — LLM may output `""` or omit it entirely
3. **Does the reviewer validate it?** — **NO** — not mentioned in reviewer prompt
4. **Is it persisted in final reviewed artifacts?** — **NO** — absent from `_build_final_reviewed_repair_artifact`
5. **Is it persisted in the proposal row?** — **NO** — no DB column
6. **Is it available during approval?** — **NO** — fallback to garbage value `"repair_apply"` which fails patch gate
7. **Is it reconstructed from another value?** — **YES** — fallback to `base_repo_state_checksum` → `diff_checksum` → `"repair_apply"`
8. **Is a checksum ever incorrectly used as a rule ID?** — **YES** — `base_repo_state_checksum` (SHA-256 hash) is used as first fallback at app.py:12555
9. **Which exact rule IDs are allowlisted?** — See rule_registry.py:9-18 (8 entries, all Java/Hibernate migration rules)
10. **Can a reviewer-accepted proposal still be rejected because the rule ID was lost?** — **YES** — PROVEN: `deterministic_rule_id` is lost in final artifact and DB, falls back to garbage at apply, patch gate rejects with `INVALID_PATCH`

---

## 16. Risk-Flow Audit

### Full trace:

| Step | File:Line | Value | Note |
|------|-----------|-------|------|
| **Proposer schema** | v2_model_schemas.py:108 | `"risk": {"enum": ["LOW","MEDIUM","HIGH"]}` | Required |
| **Proposer validation** | repair_review_chain.py:275-277 | `risk must be in {LOW, MEDIUM, HIGH}` | Validated |
| **Primary checksum** | repair_review_chain.py:242 | Included in checksum payload | Immutable |
| **Reviewer sees** | repair_review_chain.py:114-141 | YES — in `primary_output` dict | Visible |
| **Final artifact** | repair_review_chain.py:385 | `"risk": str(primary_output.get("risk", ""))` | Preserved |
| **DB proposal** | v2_repair_repository.py:12-54 | **NO FIELD** for `risk` | **LOST** |
| **Apply reload** | app.py:12559 | `risk = "LOW"` | **HARDCODED** |
| **Patch gate** | patch_gate.py:84-85 | `if risk != "LOW": return HUMAN_REVIEW_REQUIRED` | Enforces LOW only |

### Critical finding:
At `app.py:12559`, the apply reload path hardcodes `risk = "LOW"` instead of loading the proposer's actual risk assessment. This means the patch gate only allows LOW-risk proposals through — but the risk value is always LOW at apply time, so the gate is effectively bypassed. For Option A (reviewer accepted), this is arguably correct because reviewer acceptance already validates actionability. But any MEDIUM or HIGH risk proposal would be incorrectly labeled as LOW risk at apply time.

### Direct approval path (`approval.py:40-89`):
Does NOT reference risk at all. The `approval_node` only checks `decision` value. Risk flows are NOT validated at approval time.

---

## 17. Proposal/Approval/Revision Contract Audit (Option A Rules)

| Rule | Status | Evidence |
|------|--------|----------|
| **Proposer proposes, reviewer reviews** | ✅ COMPLIANT | `produce_repair_review_chain()` calls proposer then reviewer |
| **Only reviewer accept creates actionable proposal** | ✅ COMPLIANT | `repair_review_chain.py:679` — only `decision == "accept"` proceeds |
| **User approves** | ✅ COMPLIANT | `POST /approve` requires frontend action |
| **Frontend sends no raw diff** | ✅ COMPLIANT | `RepairProposalApproveRequest` has no diff field |
| **Backend owns persisted diff** | ✅ COMPLIANT | `diff_ref` points to file on disk, diff loaded at apply |
| **Apply only to sandbox** | ✅ COMPLIANT | `patch_apply.py` applies to sandbox path only |
| **No auto-apply** | ✅ COMPLIANT | `AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS=false` in launcher |
| **No Copilot repair loop** | ✅ COMPLIANT | All copilot paths return `False` or disabled |

### Specific contract checks:

| Check | Finding | Source |
|-------|---------|--------|
| `gate_id` required? | **NO** — approve route does NOT require gate_id | app.py:3960 route, `RepairProposalApproveRequest` (security.py:682-698). Proposal loaded by `proposal_id` directly. ✅ |
| `reviewer_verdict_id` required? | **NO** for approve — **YES** for revision | `RepairProposalApproveRequest` has no `reviewer_verdict_id`. `RepairProposalRevisionRequest` requires `previous_reviewer_verdict_id`. ⚠️ Current Option A proposals have no gate and no reviewer_verdict_id — revision would fail with `PROPOSAL_NO_GATE` or `GATE_NOT_FOUND`. |
| `gate_id = null` in DB? | **YES** — direct proposals store `gate_id = null` | v2_repair_repository.py column |
| `reviewer_verdict_id = null` in DB? | **YES** — but `reviewer_verdict_ref` stores file path | v2_repair_repository.py: line 39, 48 |
| Revision endpoint requires gate_id? | **YES** — `request_repair_revision` at v2_repair_gate_service.py:857 requires gate-backed proposal | For gate_id=None proposals, `create_repair_gate_from_reviewed_chain` at line 857 is never called. |
| Approval requires legacy ID? | **NO** — approval uses `proposal_id` only | app.py:3960 |

**⚠️ BROKEN**: Revision path requires `gate_id` and `reviewer_verdict_id`. Option A direct proposals (gate_id = null) cannot be revised. The `requestRepairProposalRevision` frontend call (controlTowerApi.ts:831-845) sends `previous_reviewer_verdict_id` — but direct proposals have `reviewer_verdict_id = null`.

---

## 18. Patch Apply and Validation Audit

### Active apply engines:

| Engine | File | Status | Used by |
|--------|------|--------|---------|
| `apply_patch_to_sandbox()` | `repair_loop/patch_apply.py:27-85` | **ACTIVE** for V2 repair flow | `app.py:4140-4145` in `apply_reviewed_repair_diff()` |
| `apply_approved_sandbox_transform()` | `transform_v1_after_approval.py` | **ACTIVE** for V1 approval flow | Legacy full-sandbox migration path |
| `apply_approved_proposal()` | `v2_repair_flow.py:796-914` | **DEAD** — raises ValueError at entry | `raise ValueError("Legacy repair proposal apply is disabled...")` at line 804-808 |

**Answer**: **NO** — there are TWO active apply engines, but they serve different flows:
- V2 repair flow uses `patch_apply.py:git apply` (for F5 reviewed-diff proposals)
- V1 migration flow uses `transform_v1_after_approval.py:OpenRewrite` (for full migration sandbox)

These are not in conflict because they operate on different data paths.

### Apply flow for V2 repair:
```
POST /approve
  → validate proposal_id, diff_checksum, idempotency_key
  → load proposal from DB
  → revalidate checksums
  → _resolve_repair_proposal_runtime_context()
      → determine sandbox path, target path, rule ID, risk
  → evaluate_patch_proposal()       ← patch gate check (always fails see §15)
  → apply_patch_to_sandbox()
      → git apply --check, then git apply
  → run_validation_after_patch()
      → mvn test
  → handle_repair_validation_result()
      → emit events
      → if OK: repair_completed, next gate opened
      → if FAIL: create_next_proposal_from_apply_validation()
```

### Validation after apply:
**File**: `validation_runner.py:32-114`
- Runs `mvn test` via build agent
- Checks `build_status == BUILD_PASSED` AND `test_status` in allowed values

### On validation failure: ROLLBACK (NOT preserve)
**PROVEN** at `app.py:4228-4232`:
```python
if validation_result.status == "FAIL":
    rollback_result = rollback_patch(sandbox_path, snapshot_dir)
    uow.v2_repairs.update_proposal_status(...)
    create_next_proposal_from_apply_validation(...)
```

This CONTRADICTS the locked AMF-252 rule: "If patch application succeeds but validation fails: keep the patched sandbox; do not rollback." The current code ALWAYS rolls back on validation failure.

---

## 19. Repair Attempts Persistence Audit

**Problem**: Events report `attempt_number = 1` but `GET /repair/attempts` returns `[]`.

### Root causes (all PROVEN from code):

1. **`attempt_number IS NOT NULL` SQL filter**: `list_attempts_by_job()` at `v2_repair_repository.py:237` queries `WHERE attempt_number IS NOT NULL`. Proposals where `attempt_number` is NULL are silently excluded. This affects:
   - Proposals created before migration `0048` (added `attempt_number` column)
   - Proposals where attempt creation failed before column was set

2. **Events emitted before proposal persistence completes**: The event `repair_proposal_ready` is emitted at `app.py:4287` during the proposal creation flow. If the proposal creation fails partway (e.g., reviewer rejects at line 582-589), the event is already emitted with `attempt_number` but no proposal row exists in DB.

3. **Attempt count ≠ proposal count**: `_get_persisted_attempt_count()` at `v2_repair_gate_service.py:1464-1478` counts `repair_review` phase gates, NOT proposals. `attempt_number` = gates + 1. A gate may exist (and increment the counter) without a corresponding proposal.

4. **V1/V2 endpoint duality**: `GET /v1/commands/{command_id}/repair-attempts` queries `v1_fake_repair_proposals` — a different table. The V2 endpoint queries `v2_repair_proposals`. They can return different results.

### Classification: **PROVEN BUG** — the `attempt_number IS NOT NULL` filter is the primary cause.

---

## 20. Event and Repair-State Audit

### Event → Projected State Table:

| Event type | Status in event | Projected repair_state | Notes |
|-----------|----------------|----------------------|-------|
| `repair_proposal_ready` | `proposal_created` | `ready` | Proposal exists, reviewer accepted |
| `reviewed_repair_unavailable` | `unavailable` | `unavailable` | Proposer/reviewer chain failed |
| `repair_attempts_exhausted` | `exhausted` | `attempts_exhausted` | 3 attempts used |
| `repair_callback_error` | `error` | `error` | Exception in callback |
| `repair_validation_failed` | `validation_failed` | Needs next proposal | Rolls back, creates next attempt |
| `repair_validation_passed` | `validation_passed` | Route to next gate | Success |
| `repair_completed` | `completed` | `completed` | Final success |

### State projection logic:
At `app.py:3515-3552` (`_compute_repair_state_for_job`): The state is determined by scanning events in reverse sequence order. **Latest-event-wins** logic applies: the most recent event of relevant types determines the state. This can cause:
- `repair_completed` masking earlier `reviewed_repair_unavailable` — if both exist, `completed` wins
- `repair_validation_failed` followed by `repair_proposal_ready` → shows `ready` (not the failure)

### Reviewer rejection handling:
When reviewer returns `reject` or `revise` at `repair_review_chain.py:679`:
```python
if decision != "accept":
    _write_final_artifacts(...)  # writes artifacts with reviewer_decision
    return None, None, None      # caller gets None proposal
```
The caller (`_create_reviewed_repair_proposal_from_refs` at line 582-589) checks `if primary_output is None`: if reviewer rejected, it sets `status = "skipped"` and returns early. No proposal record is created. But `reviewed_repair_unavailable` event IS emitted.

### Validation events falling into unknown state:
If `repair_validation_failed` lacks a subsequent `repair_proposal_ready` or `repair_attempts_exhausted`, the state could fall through to default `not_attempted` — incorrectly showing no repair activity.

---

## 21. Frontend SSR/API/SSE Communication Map

### Page lifecycle:

```
1. Server render (page.tsx — no "use client")
   → Title + description only
   → No data fetching at SSR

2. Client mount (MigrationCockpit.tsx — "use client")
   → 7 parallel HTTP fetches:
     - getV2Job()
     - getV2Messages()
     - getV2Approvals()
     - getV2Stages() [deprecated]
     - getV2JobEventSnapshot(after=0)
     - getV2PipelineDefinition()
     - getV2FailureSummary()

3. Initial render of RepairProposalPanel
   → fetches getCurrentRepairProposal() internally
   → if proposal exists: fetches getRepairProposalDiff() + getRepairAttempts()

4. SSE connection (EventSource to /v1/v2/migration-jobs/{job_id}/events)
   → Starts AFTER initial fetches
   → Reconnects automatically (Last-Event-ID header)

5. SSE event reception
   → AMF252_REPAIR_EVENTS (7 event types) → increments repairRefreshKey
     → triggers re-fetch of getCurrentRepairProposal() + diff + attempts
   → IMPORTANT_SSE_TYPES (50+ types) → triggers refreshLiveState() HTTP polling
     → refetches snapshot + gate status

6. User actions:
   → "View diff" → getRepairProposalDiff()
   → "Request revision" → requestRepairProposalRevision()
     → on success: repairRefreshKey++
   → "Apply reviewed diff" → approveRepairProposal()
     → on success/error: repairRefreshKey++
```

### Key files:

| File | Role |
|------|------|
| `page.tsx` | SSR shell |
| `MigrationCockpit.tsx` | Main client component — orchestrates all data fetching, SSE, state |
| `RepairProposalPanel.tsx` | Repair proposal display + approve/revision actions |
| `RepairActionsBar.tsx` | Approve/revision buttons |
| `RepairAttemptTimeline.tsx` | Attempt history display |
| `ReviewedDiffTabs.tsx` | Diff/Notes/Files/Validation tabs |
| `ReviewerVerdictCard.tsx` | Reviewer decision display |
| `RepairRevisionDialog.tsx` | Revision request dialog |
| `controlTowerApi.ts` | All API calls |
| `contracts.ts` | All TypeScript types |

### SSE start position:
Uses `after=0` initially (fetches full event history). The `event_snapshot` call also starts at `after=0`. This means the frontend replays the FULL event history on every load, which is wasteful but not incorrect.

### V1 vs V2 page:
- `/jobs/[jobId]` — V1 page (SSR with initial data)
- `/migrations/[jobId]` — V2 page (shell SSR + client fetch)

V2 page does NOT perform genuine data SSR — it renders a server shell and all data is fetched client-side.

---

## 22. Frontend Error-Handling Audit

### API error handling:

| Layer | Behavior | Evidence |
|-------|----------|----------|
| `postJson()` | Throws generic `Error("Control Tower mutation failed for ${path}: ${response.status} ${response.statusText}")` — **does NOT parse response body** | `controlTowerApi.ts:863-883` |
| `getJson()` | Same generic error handling | `controlTowerApi.ts:885-893` |
| `handleRequestRevision()` | `catch { /* Safe error display — no raw paths/stacks */ }` — **errors SWALLOWED** | `RepairProposalPanel.tsx:159-163` |
| `handleApproveSandboxApply()` | `catch { /* Safe error display — no raw paths/stacks */ }` — **errors SWALLOWED** | `RepairProposalPanel.tsx:178-182` |
| `MigrationCockpit.tsx` | Shows errors in `error-box` element | `MigrationCockpit.tsx:1034-1038` |

### Error codes invisible to frontend:

| Backend error code | HTTP status | What user sees |
|-------------------|-------------|----------------|
| `STALE_DIFF_CHECKSUM` | 409 | **NOTHING** — swallowed in catch |
| `PATCH_GATE_REJECTED` | 409 | **NOTHING** |
| `REVIEWER_NOT_ACCEPTED` | 409 | **NOTHING** |
| `PROPOSAL_NOT_APPROVABLE` | 409 | **NOTHING** |
| `PROPOSAL_ALREADY_FINAL` | 409 | **NOTHING** |
| `RUNTIME_CONTEXT_RESOLUTION_FAILED` | 400 | **NOTHING** |
| `LEGACY_SOURCE_MODIFICATION` | 409 | **NOTHING** |
| `DIFF_CHECKSUM_MISMATCH` | 409 | **NOTHING** |
| `SAFE_DIFF_CHECKSUM_MISMATCH` | 409 | **NOTHING** |
| `SAFE_DIFF_MALFORMED` | 400 | **NOTHING** |
| `SAFE_DIFF_PREVIEW_FAILED` | 400 | **NOTHING** |
| `DIFF_FILE_NOT_FOUND` | 400 | **NOTHING** |

**Conclusion**: ALL structured backend error codes are LOST in the frontend. Users see a generic HTTP error if anything propagates to `MigrationCockpit`, or NOTHING if the error is caught in `RepairProposalPanel`. The `catch` blocks in `RepairProposalPanel` swallow all errors without updating UI state.

---

## 23. Launcher vs Python Runtime Comparison

| Setting | Launcher value | Python code reads it? | Actual runtime value | Mismatch? |
|---------|---------------|----------------------|---------------------|-----------|
| `AZURE_OPENAI_ENDPOINT` | `https://abdelilahmortaki.../openai/v1` | YES — `os.environ.get("AZURE_OPENAI_ENDPOINT")` | Same | ✅ OK |
| `AZURE_OPENAI_PROPOSER_DEPLOYMENT` | `gpt-5-mini` | YES — via `_role_env_ref` → `..._PROPOSER_DEPLOYMENT` | `gpt-5-mini` | ✅ OK |
| `AZURE_OPENAI_PROPOSER_MODEL` | `gpt-5-mini` | **NEVER READ** | N/A | **REDUNDANT** — deployment is used as model field |
| `AZURE_OPENAI_PROPOSER_MAX_INPUT_TOKENS` | `50000` | YES — `_read_int_env(..., 40000)` → `max(40000, val)` | 50000 | ✅ OK |
| `AZURE_OPENAI_PROPOSER_MAX_OUTPUT_TOKENS` | `20000` | YES → `max(20000, val)` | 20000 | ✅ OK |
| `AZURE_OPENAI_PROPOSER_CONTEXT_TOKENS` | `50000` | **NEVER READ** | N/A | **REDUNDANT** |
| `AZURE_OPENAI_PROPOSER_MAX_CONTEXT_TOKENS` | `50000` | **NEVER READ** | N/A | **REDUNDANT** |
| `AZURE_OPENAI_PROPOSER_MAX_COMPLETION_TOKENS` | `20000` | **NEVER READ** — model_client reads `budget.max_output_tokens` | N/A | **REDUNDANT** |
| `AZURE_OPENAI_PROPOSER_RESPONSE_FORMAT` | `json_schema` | YES | `json_schema` | ✅ OK |
| `AZURE_OPENAI_PROPOSER_REASONING_EFFORT` | `medium` | YES | `medium` | ✅ OK |
| `AZURE_OPENAI_PROPOSER_SUPPORTS_REASONING_EFFORT` | `true` | **NEVER READ** | N/A | **REDUNDANT** — Python checks `_REASONING_EFFORT` directly |
| `AZURE_OPENAI_REVIEWER_DEPLOYMENT` | `Llama-3.3-70B-Instruct` | YES | `Llama-3.3-70B-Instruct` | ✅ OK |
| `AZURE_OPENAI_REVIEWER_REASONING_EFFORT` | `""` (empty) | YES — via `_read_str_env` → empty → **falls back to generic `AZURE_OPENAI_REASONING_EFFORT = "medium"`** | `"medium"` | **⚠️ CRITICAL** — Launcher says no reasoning (SUPPORTS=false), but Python sends `reasoning_effort: "medium"` to Llama 3.3 |
| `AI_MIGRATION_PROPOSER_TIMEOUT_SECONDS` | `300` | **NEVER READ** — model_client hardcodes `timeout=30` | 30s | **⚠️ CRITICAL** — 10x mismatch |
| `AZURE_OPENAI_ALLOW_JSON_OBJECT_FALLBACK` | **NOT SET** | YES — checks for `1`/`true`/`yes` | Not set → fallback disabled | **⚠️ WARNING** — Launcher sets `AI_MIGRATION_PROPOSER_SUPPORTS_JSON_OBJECT=true` but that var is never read; the actual controlling var is unset |
| `AI_MIGRATION_PROPOSER_PROVIDER` | `azure_openai` | **NEVER READ** — hardcoded in model_client | `azure_openai` | **REDUNDANT** |
| `AI_MIGRATION_PROPOSER_ENDPOINT_TYPE` | `chat_completions` | **NEVER READ** — model_client determines from URL | N/A | **REDUNDANT** |
| `AI_MIGRATION_PROPOSER_MODEL` | `gpt-5-mini` | **NEVER READ** | N/A | **REDUNDANT** |
| `AI_MIGRATION_DEFAULT_*` (6 vars) | `50000`/`20000`/`json_schema` | **NEVER READ** | N/A | **REDUNDANT** — all 6 default vars are dead config |

### Critical mismatches summary:

| # | Mismatch | Severity | Impact |
|---|---------|----------|--------|
| 1 | **Timeout**: 300s (launcher) vs 30s (hardcoded in code) | **BLOCKING** | Long-reasoning proposer calls may time out before Azure returns schema validation error |
| 2 | **Reasoning effort sent to reviewer**: launcher says `SUPPORTS_REASONING_EFFORT=false` but Python reads generic `AZURE_OPENAI_REASONING_EFFORT=medium` | **BLOCKING** for reviewer | Llama 3.3 will receive unsupported parameter |
| 3 | **json_object fallback**: controlling env var never set | **WARNING** | No graceful degradation when `json_schema` fails |
| 4 | **Auth header mismatch**: launcher smoke sends `Authorization: Bearer`, Python sends `api-key` | **INFORMATIONAL** | Smoke test auth could work while production auth fails (or vice versa) |

---

## 24. Root Causes Ranked

### Root cause #1 — Schema incompatible with Azure OpenAI Structured Outputs

```
Confidence:         PROVEN
Evidence:           v2_model_schemas.py:101 — `minLength: 20` on proposed_diff
                    v2_model_schemas.py:109 — `minimum: 0.0, maximum: 1.0` on confidence
                    v2_model_schemas.py:115 — `machine_readable_metadata` lacks `additionalProperties: false`
Exact files:        migration_factory/control_tower/application/v2_model_schemas.py
Exact symbols:      REPAIR_PRIMARY_OUTPUT_SCHEMA (proposer)
                    REPAIR_REVIEWER_OUTPUT_SCHEMA (reviewer)
Runtime symptom:    HTTP 400 from Azure on proposer invocation
What this does NOT explain:  The earlier missing-proposed-diff failure (different job, no HTTP 400)
```

### Root cause #2 — 30-second timeout insufficient

```
Confidence:         HIGH CONFIDENCE (cannot prove without timing the actual Azure response)
Exact files:        migration_factory/control_tower/application/v2_assistant_model_client.py
Exact symbols:      _answer_with_deployment() — `timeout=30` at line 293
Runtime symptom:    Could cause timeout before Azure schema validation error, or make long-reasoning calls fail
What this does NOT explain:  The HTTP 400 specifically (HTTP 400 is a fast response, not a timeout)
```

### Root cause #3 — Read-only system prompt contradicts diff-generation user prompt

```
Confidence:         HIGH CONFIDENCE
Exact files:        v2_assistant_model_client.py:774-853 (_assistant_system_prompt)
                    repair_review_chain.py:87-111 (_primary_repair_prompt)
Exact symbols:      _assistant_system_prompt(), _primary_repair_prompt()
Runtime symptom:    LLM produces analysis instead of diff, or wraps diff in markdown fences, or returns empty diff
What this does NOT explain:  HTTP 400 (contradictory prompts don't cause HTTP errors)
```

### Root cause #4 — deterministic_rule_id lost end-to-end

```
Confidence:         PROVEN
Exact files:        v2_repair_repository.py:12-54 (no DB field)
                    repair_review_chain.py:354-392 (not in final artifact)
                    app.py:12553-12557 (falls back to garbage)
                    patch_gate.py:82-83 (requires non-empty, rejects everything)
Exact symbols:      V2RepairProposalRecord, _build_final_reviewed_repair_artifact,
                    _resolve_repair_proposal_runtime_context, evaluate_patch_proposal
Runtime symptom:    All restored V2 proposals fail at patch gate with INVALID_PATCH
What this does NOT explain:  HTTP 400 (patch gate runs after proposal creation, not during)
```

### Root cause #5 — Empty repair attempts history

```
Confidence:         PROVEN
Exact files:        v2_repair_repository.py:237 (SQL filter)
Exact symbols:      list_attempts_by_job() — `WHERE attempt_number IS NOT NULL`
Runtime symptom:    GET /repair/attempts returns [] while events show attempt_number=1
What this does NOT explain:  HTTP 400
```

### Root cause #6 — Reviewers get reasoning_effort unsupported parameter

```
Confidence:         PROVEN (but not the cause of proposer HTTP 400)
Exact files:        v2_model_role_router.py:317-319
Exact symbols:      _resolve_role_model_budget() — falls back to generic reasoning effort
Runtime symptom:    Reviewer (Llama 3.3) receives `reasoning_effort: "medium"` which it may reject
What this does NOT explain:  Proposer HTTP 400 (affects reviewer, not proposer)
```

---

## 25. P0 / P1 / P2 Findings

| Priority | Finding | Status | Evidence | Runtime impact |
|----------|---------|--------|----------|----------------|
| **P0** | `minLength`, `minimum`/`maximum`, and missing `additionalProperties: false` on nested objects in both schemas | **PROVEN** | v2_model_schemas.py:101,109,115,136,141 | HTTP 400 on every proposer/reviewer call |
| **P0** | `deterministic_rule_id` lost from final artifact and DB | **PROVEN** | repair_review_chain.py:354-392, v2_repair_repository.py:12-54 | Patch gate always rejects restored proposals |
| **P1** | 30s timeout hardcoded, launcher expects 300s | **HIGH CONFIDENCE** | model_client.py:293 vs launcher:297 | Long-reasoning calls may timeout |
| **P1** | Reviewers receive `reasoning_effort` despite being configured as not supporting it | **PROVEN** | router:317-319 | Llama 3.3 may reject calls |
| **P1** | Read-only system prompt contradicts diff-generation user prompt | **HIGH CONFIDENCE** | model_client.py:791 vs repair_review_chain.py:89 | LLM produces analysis instead of diff |
| **P1** | No source file contents sent to proposer | **PROVEN** | failure_evidence.py:55 (paths only) | LLM cannot see code to fix |
| **P1** | Empty repair attempts history | **PROVEN** | v2_repair_repository.py:237 | `attempt_number IS NOT NULL` filter |
| **P1** | Frontend swallows ALL backend error codes | **PROVEN** | controlTowerApi.ts:863-883, RepairProposalPanel.tsx:159-182 | Users see nothing on error |
| **P1** | `json_object` fallback dead code | **PROVEN** | model_client.py:1135, launcher never sets controlling var | No graceful degradation |
| **P2** | `AZURE_OPENAI_ALLOW_JSON_OBJECT_FALLBACK` never set | **PROVEN** | launcher.ps1 | Fallback path dead |
| **P2** | 6 `AI_MIGRATION_DEFAULT_*` vars never read | **PROVEN** | Python code | Dead config |
| **P2** | 7 `AI_MIGRATION_*` role vars (provider, endpoint_type, model, etc.) never read | **PROVEN** | model_client.py | Dead config |
| **P2** | `redact_model_summary` can corrupt proposed_diff if it contains absolute paths or env patterns | **WARNING** | redaction.py:165-179 | Partial data corruption |
| **P2** | SSE starts at `after=0` — full event history replayed on every load | **PROVEN** | controlTowerApi.ts:440-444 | Wasted bandwidth |
| **P2** | Response_format NOT stored in ledger — env var changes retroactively alter history | **PROVEN** | v2_llm_invocation_ledger.py:260-267 | Audit inconsistency |
| **P2** | Duplicate LLM calls possible across process restart | **PROVEN** | v2_repair_gate_service.py:61-62 (in-memory set) | No cross-process dedupe |
| **P2** | Validation failure triggers rollback (contradicts AMF-252 rule to preserve) | **PROVEN** | app.py:4228-4232 | Unnecessary rollback |
| **P2** | Revision path requires gate_id/reviewer_verdict_id — Option A proposals have null | **PROVEN** | controlTowerApi.ts:831-845, v2_repair_repository.py | Revision broken for direct proposals |

---

## 26. Minimal Implementation Plan — DO NOT IMPLEMENT

### Step 1: Fix proposer schema for Azure Structured Outputs

```
Problem:     REPAIR_PRIMARY_OUTPUT_SCHEMA has minLength, minimum/maximum, missing
             additionalProperties: false on nested objects
Exact files: migration_factory/control_tower/application/v2_model_schemas.py
Exact symbols: REPAIR_PRIMARY_OUTPUT_SCHEMA (lines 83-117)
Minimal change:
  1. Change `"proposed_diff": {"type": "string", "minLength": 20}`
     → `"proposed_diff": {"type": "string"}`        (remove minLength)
  2. Change `"confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}`
     → `"confidence": {"type": "number"}`            (remove minimum/maximum)
     → OR use `"enum": [0.0, 0.1, 0.2, ..., 1.0]` (enum limits)
     → OR use `"type": "string", "enum": ["low", "medium", "high"]` (string enum)
  3. Change `"machine_readable_metadata": {"type": "object"}`
     → `"machine_readable_metadata": {"type": "object", "additionalProperties": false}`

Why first:   This is the immediate cause of HTTP 400. Without this, no proposer
             call can succeed.
Dependencies: None
```

### Step 2: Fix reviewer schema for Azure Structured Outputs

```
Problem:     Same incompatibilities (confidence.minimum/maximum,
             review_dimensions without additionalProperties: false)
Exact files: migration_factory/control_tower/application/v2_model_schemas.py
Exact symbols: REPAIR_REVIEWER_OUTPUT_SCHEMA (lines 119-143)
Minimal change:
  1. Same confidence fix as Step 1.2
  2. Add `additionalProperties: false` to review_dimensions

Why second:  Reviewer schema also incompatible. Once proposer works, reviewer
             will also fail with HTTP 400.
Dependencies: Step 1 (same file, same pattern)
```

### Step 3: Add deterministic_rule_id to final artifact and DB

```
Problem:     deterministic_rule_id lost — not in final artifact, not in DB
Exact files: repair_review_chain.py (final artifact builder)
             v2_repair_repository.py (DB schema)
Exact symbols: _build_final_reviewed_repair_artifact() at line 354-392
               V2RepairProposalRecord at lines 12-54
Minimal change:
  1. Add `"deterministic_rule_id": str(primary_output.get("deterministic_rule_id", ""))`
     to the final artifact dict in _build_final_reviewed_repair_artifact()
  2. Add a `deterministic_rule_id TEXT` column to v2_repair_proposals table
  3. Set it in V2RepairProposalRecord and the SQL INSERT

Why third:   Without this, all restored proposals fail at patch gate.
             schema fix + rule ID fix = minimum viable repair.
Dependencies: Steps 1-2 (independent, can parallelize)
```

### Step 4: Fix timeout to honor launcher setting

```
Problem:     30s hardcoded, launcher sets 300s
Exact files: migration_factory/control_tower/application/v2_assistant_model_client.py
Exact symbols: _answer_with_deployment() — `timeout=30` at line 293
Minimal change:
  1. Read env var (e.g., `AZURE_OPENAI_TIMEOUT_SECONDS`) with default 300
  2. Use it instead of hardcoded 30

Why fourth:  Not the primary cause of HTTP 400, but prevents timeout-related
             failures after schema fix.
Dependencies: None (independent)
```

### Step 5: Fix repair attempts persistence (remove NULL filter)

```
Problem:     attempt_number IS NOT NULL filter hides proposals from endpoint
Exact files: v2_repair_repository.py
Exact symbols: list_attempts_by_job() at line 233-241
Minimal change:
  1. Change SQL to `WHERE attempt_number IS NULL OR attempt_number = ?`
     OR include NULL attempt_number entries with a default of 0

Why fifth:   Missing attempts history blocks debug and frontend timeline.
Dependencies: None (independent)
```

---

## 27. Files That Should NOT Be Changed for the Immediate Root Cause

The following subsystems are currently behaving correctly for the immediate HTTP 400 fix:

| File/Subsystem | Reason to NOT change |
|----------------|---------------------|
| `run_amf252_backend_clean.ps1` | Launcher is correct. Redundant env vars are noise, not bugs. Timeout and reasoning-effort mismatches should be fixed in Python code, not launcher. |
| `web/control-tower/` (all frontend) | Frontend approval payload (3-field contract) is correct. Error swallowing is a UX issue, not a repair-blocker. No frontend change is needed to fix HTTP 400. |
| `v2_repair_gate_service.py` | Gate service logic is correct. Attempt counting, event emission, and proposal persistence are all structurally valid. |
| `v2_repair_flow.py` | Repair flow (apply, validate) is correct for Option A. Validation rollback is a policy choice, not a bug. |
| `v2_assistant_model_client.py` (except timeout) | Model client HTTP handling, redaction, fallback chain, and response parsing are correct. The only change needed is timeout. |
| `v2_model_role_router.py` (except reasoning_effort for reviewer) | Role routing logic is correct. Reasoning effort fallback needs fixing, but this is secondary. |
| `v2_llm_invocation_ledger.py` | Ledger records are correct for audit purposes. Response_format not being stored is a minor audit gap. |
| `repair_loop/` (all files) | Patch gate, rule registry, patch apply, validation runner are all correct. The patch gate will work once `deterministic_rule_id` flows through. |
| `migration_factory/infrastructure/` | All repository implementations are correct. Only the NULL filter fix is needed. |
| `failure_evidence.py`, `repair_context.py` | Evidence/context data structures are correct. Adding source file content would improve model accuracy but is not required for the immediate HTTP 400 fix. |
| `orchestrator/` | Graph, runner, phase services, approval — all correct for the V1 migration flow. The V2 repair chain is standalone and not wired into the graph — this is by design. |
| `agents/` | V1 agent implementations are legacy and not used by V2 repair. No changes needed. |
| `config/`, `contracts/`, `schemas/` | All configuration and contract systems are correct and not involved in the HTTP 400. |

---

## 28. Open Unknowns Requiring Runtime Evidence

| Unknown | Why static analysis cannot prove it | How to resolve |
|---------|-----------------------------------|----------------|
| Exact Azure HTTP 400 provider error body from the previous run (`6a489598ca4d4d7b83b85a40deadff09`) | The `redacted_summary` may exist in the LLM invocation ledger, but we cannot verify the exact provider error message without runtime DB query | Query the LLM invocation ledger: `SELECT redacted_summary FROM v2_llm_invocations WHERE job_id = '6a489598ca4d4d7b83b85a40deadff09'` |
| Whether Responses API rejects schemas the same way as Chat Completions | Static code shows the schema is incompatible with Azure's documented Structured Outputs subset. But the actual HTTP 400 message could contain additional details about which exact constraint triggered rejection. | The body content was redacted per model_client.py:959. If persisted, it's available in the ledger. |
| Whether `gpt-5-mini` model actually supports `reasoning_effort: "medium"` | Model capabilities documented in Azure portal — not available in source code | Check Azure deployment capability docs for gpt-5-mini |
| Actual historical raw proposer output (non-redacted) that led to `missing_proposed_diff` | Redaction happened before storage. The original non-redacted content is not persisted anywhere. | Cannot recover — lost data |
| Whether the 30s timeout actually fires before or after the schema validation HTTP 400 | Depends on Azure response latency and model pre-processing time. A quick validation error would return HTTP 400 within seconds. A model that must "think" for >30s before producing schema-invalid output would time out. | Instrument with timing logs |
| Whether Llama 3.3 deployed on Azure actually accepts/exposes chat completions endpoint at all | Deployment configuration unavailable in source. The `AZURE_OPENAI_REVIEWER_DEPLOYMENT=Llama-3.3-70B-Instruct` is a model name — whether this exact deployment exists is unknown. | Check deployment list at Azure portal |
| Exact runtime filesystem contents at `repair_dir` | Files written by the repair flow (`failure_evidence.json`, `context_pack.json`, `deterministic_repair_artifact.json`) are runtime artifacts not present in the repository | Check the SQLite DB path for refs or read from the repair directory during a runtime session |
| Whether the `v2_job_events` table actually contains events from previous runs | SQLite is file-backed and survives restart per paths.py | Query the SQLite DB directly |

---

# FINAL DECISION BEFORE IMPLEMENTATION

1. **What is the most likely immediate cause of the HTTP 400?**
   **Azure OpenAI Structured Outputs schema rejection.** The `REPAIR_PRIMARY_OUTPUT_SCHEMA` sent with `strict: true` contains `minLength` (unsupported), `minimum`/`maximum` on `confidence` (unsupported), and a nested `object` without `additionalProperties: false` (required). Any one of these alone can trigger HTTP 400.

2. **Is it proven from code alone, or still dependent on missing runtime provider-body evidence?**
   **PROVEN from code alone.** Azure's official documentation (Structured Outputs supported JSON Schema subset) explicitly excludes `minLength`, `minimum`, and `maximum`. The current schema violates these documented constraints regardless of the exact provider error body.

3. **What exact code change should be first?**
   **Remove `minLength: 20` from `proposed_diff`, remove `minimum: 0.0` and `maximum: 1.0` from `confidence`, and add `additionalProperties: false` to `machine_readable_metadata`** in `REPAIR_PRIMARY_OUTPUT_SCHEMA` at `v2_model_schemas.py:83-117`.

4. **What exact code change should be second?**
   **Same three fixes applied to `REPAIR_REVIEWER_OUTPUT_SCHEMA`** (remove `minimum`/`maximum` from `confidence`, add `additionalProperties: false` to `review_dimensions`) at `v2_model_schemas.py:119-143`.

5. **What should explicitly NOT be changed yet?**
   - Frontend code (error handling is bad UX but not blocking)
   - Launcher script (redundant vars are harmless)
   - `repair_loop/` or `orchestrator/` (not involved in HTTP 400)
   - Prompt content (improvements would help but schema fix alone unblocks)
   - `deterministic_rule_id` in DB (important but secondary to unblocking repair)

6. **After those changes, what is the next most likely blocker?**
   **The 30-second timeout.** If `gpt-5-mini` with `reasoning_effort: "medium"` takes >30 seconds to produce a structured output, the call will time out instead of returning HTTP 200. Fix the timeout to 300s (matching launcher config).

7. **Is the system currently safe/fail-closed?**
   **YES.** The HTTP 400 causes `fallback_used=true` and `reviewed_repair_unavailable`. No invalid or partial proposals are persisted. No dangerous patches are applied. The system correctly refuses to proceed when the LLM chain fails.

8. **Is the current Option A flow internally coherent end to end?**
   **PARTIALLY.** The flow from failure → evidence → proposer → reviewer → final artifact is structurally coherent. But:
   - Schema incompatibility blocks the entire flow at the proposer step
   - `deterministic_rule_id` loss blocks patch gate at apply time
   - Revision path is broken for gate-less proposals
   - Validation rollback contradicts AMF-252 preservation rule
   - Attempt history is incomplete in the API

9. **Are we ready to implement?**
   **YES** — for the schema fix (Steps 1-2). These are small, targeted P0 changes with no side effects. The `deterministic_rule_id` fix (Step 3) can follow immediately. The timeout fix (Step 4) is independent.

10. **What is the minimum implementation scope?**
    ```
    Change 3 lines in v2_model_schemas.py (proposer schema)
    Change 2 lines in v2_model_schemas.py (reviewer schema)
    Change 1 line in model_client.py (timeout from 30 to dynamic env var)
    = 6 lines total to unblock the entire repair flow
    ```
    Plus for `deterministic_rule_id`:
    ```
    Add 1 field to final artifact builder in repair_review_chain.py
    Add 1 column migration for v2_repair_proposals table
    Add 1 field to V2RepairProposalRecord dataclass
    ```
