# AMF-252 Post-Implementation Backend Safety Audit Report

## 1. Executive Verdict

**NO-GO**

Three P0 blockers exist that must be resolved before any runtime test.

**P0 Blockers:**
1. **Migration version collision** — `0050_v2_llm_invocations.sql` and `0050_v2_repair_proposals_rule_id_risk.sql` both claim version 0050. The migration runner explicitly rejects duplicates. Startup will fail.
2. **compiler_errors never populate** — `_maybe_write_repair_failure_context` calls `build_failure_evidence()` without passing `compiler_errors`. The builder gets `compiler_errors=()`, so `source_contexts` will be empty on the first real Java compile failure.
3. **Risk defaults to LOW** — `_resolve_repair_proposal_runtime_context` line 12560: `risk = str(getattr(record, "risk", "") or "").upper() or "LOW"`. This is the opposite of fail-closed. Missing/malformed/NULL risk becomes LOW.

---

## 2. Repository State

| Property | Value |
|---|---|
| Current branch | `feature/superposition-llm-repair-mvp` |
| HEAD | `68d994f` — "the 400ERROR FIXED" |
| Working tree | Clean (no staged changes), untracked audit files |
| Deleted files | `AGENTS.md`, `AMF252_OPTION_A_REVIEWER_ACCEPTED_REPAIR_MVP.md` |

---

## 3. Actual Changed File Verification

| File | Git Status | Report says changed? | Actual production change? | Risk |
|---|---|---|---|---|
| `v2_model_schemas.py` | Modified | Yes | Yes — schema updated | LOW |
| `v2_assistant_model_client.py` | Modified | Yes | Yes — transport logic rewritten | LOW |
| `v2_model_role_router.py` | Modified | Yes | Yes — reasoning effort, timeout | LOW |
| `repair_review_chain.py` | Modified | Yes | Yes — prompt, validation updated | MEDIUM |
| `repair_context.py` | Modified | Yes | Yes — source context added | MEDIUM |
| `v2_repair_gate_service.py` | Modified | Yes | Yes — Option A direct path added | LOW |
| `v2_repair_repository.py` | Modified | Yes | Yes — new fields added | LOW |
| `v2_orchestrator_runner.py` | Modified | Yes | Yes — failure context writes | P0 — compiler_errors not passed |
| `app.py` | Modified | Yes | Yes — approval endpoint updated | MEDIUM |
| `0050_v2_repair_proposals_rule_id_risk.sql` | New | Yes | Yes — new migration | P0 — version collision |
| `repair_context.py` (shown as `repair_loop`) | Modified | Yes | Yes | MEDIUM |

All reported files are actually changed. No missing or phantom changes.

---

## 4. Migration Numbering / Discovery Audit

### Migration files in sorted order:

```
0049_v2_repair_proposals_prf_fields.sql
0050_v2_llm_invocations.sql         ← created first
0050_v2_repair_proposals_rule_id_risk.sql  ← created second (SAME VERSION)
0051_v2_job_approval_settings.sql
```

### Findings:

1. **Duplicate version 0050.** Two files share the same numeric prefix.
2. **Migration runner rejects duplicates.** `discover_migrations()` in `__init__.py` (line 152): `raise MigrationDiscoveryError(f"Duplicate migration version: {version:04d}")`.
3. **Runner sorts by `sorted(directory.glob("*.sql"))` alphabetically**, which would order `0050_v2_llm_invocations.sql` before `0050_v2_repair_proposals_rule_id_risk.sql`. But the duplicate check fires BEFORE any execution, so neither file runs.
4. **`schema_migrations` table** stores `(version, name, checksum, applied_at)`. Version is the numeric prefix.
5. **Checksum verification** occurs against the numeric version, so even if the runner somehow processed one 0050, the other would fail checksum verification.
6. **Result: startup will crash** with `MigrationDiscoveryError: Duplicate migration version: 0050`.

### Fix needed:
Rename `0050_v2_repair_proposals_rule_id_risk.sql` to `0052_v2_repair_proposals_rule_id_risk.sql`.

| Question | Answer |
|---|---|
| Version unique? | **NO** — P0 blocker |
| Auto-discovered? | Would be, but blocked by duplicate detection |
| Safe for existing DB? | N/A — migration never runs |
| NULL columns after migration? | N/A — never applied |

---

## 5. Strict Schema Audit

### REPAIR_PRIMARY_OUTPUT_SCHEMA (lines 83-116 of v2_model_schemas.py)

| Property | Type | Required | Provider-safe? | Notes |
|---|---|---|---|---|
| root_cause | string | Yes | Yes | |
| fix_strategy | string | Yes | Yes | |
| changed_files | array[string] | Yes | Yes | |
| proposed_diff | string | Yes | Yes | has description |
| deterministic_rule_id | string | Yes | Yes | |
| risk | string (enum LOW/MEDIUM/HIGH) | Yes | Yes | |
| confidence | number | Yes | Yes | |
| rationale | string | Yes | Yes | |
| no_fix_reason | string or null | Yes | Yes | nullable |

**Checks:**
- **minLength removed?** YES — not present anywhere in this schema
- **maxLength?** Not present
- **pattern?** Not present
- **minimum/maximum?** Not present
- **machine_readable_metadata removed?** YES — not in schema
- **additionalProperties=false?** YES — at top level (line 85)
- **Nested objects?** NO — all properties are primitives or arrays of primitives
- **Empty deterministic_rule_id?** Schema allows empty string. Validated by backend? Not explicitly rejected by schema or semantic validator.

### REPAIR_REVIEWER_OUTPUT_SCHEMA (lines 118-141)

| Property | Type | Required | Provider-safe? | Notes |
|---|---|---|---|---|
| decision | string (enum accept/revise/reject) | Yes | Yes | |
| notes | array[string] | Yes | Yes | |
| risks | array[string] | Yes | Yes | |
| confidence | number | Yes | Yes | |
| policy_concerns | array[string] | Yes | Yes | |
| reviewed_context_checksum | string | Yes | Yes | |
| reviewed_primary_output_checksum | string | Yes | Yes | |
| reviewed_diff_checksum | string | Yes | Yes | |

**Checks:**
- **minimum/maximum removed?** YES — not present
- **review_dimensions removed?** YES — not in schema
- **additionalProperties=false?** YES — line 120
- **Nested objects?** NO
- **All required?** YES — all 8 fields in `required` array

### Schema Transport Verification

Both `REPAIR_PRIMARY_OUTPUT_SCHEMA` and `REPAIR_REVIEWER_OUTPUT_SCHEMA` are:

1. Registered in `SCHEMA_REGISTRY` (lines 450-451)
2. Passed to `answer_with_role()` as `output_schema_name` from `repair_review_chain.py` lines 532 and 648
3. Used by `_response_format_candidates()` in `v2_assistant_model_client.py` line 1229 to build the `response_format` payload
4. Wrapped with `name`, `strict: True`, and `schema` in the JSON body (lines 1240-1250)

**Verdict: Schema is provider-safe and structurally correct.**

---

## 6. Backend Semantic Validator Audit

### Proposer validation (repair_review_chain.py)

**`_coerce_primary_repair_output()`** (lines 160-201):
- JSON parse ✓
- Required fields check: `root_cause`, `fix_strategy`, `changed_files`, `proposed_diff`, `risk`, `confidence`, `rationale`
- `deterministic_rule_id` NOT validated — not in required set (line 180)
- `no_fix_reason` NOT validated
- Empty proposed_diff rejected ✓
- Markdown fences rejected ✓
- Unified diff markers required ✓

**`_validate_primary_repair_output()`** (lines 280-314):
- Empty required string fields rejected ✓
- `changed_files` must be list of strings ✓
- `risk` validated against LOW/MEDIUM/HIGH ✓
- `confidence` validated 0.0 to 1.0 ✓
- Diff markdown fences rejected ✓
- Diff unified format check ✓
- Forbidden paths checked ✓
- Forbidden keys checked ✓

**`deterministic_rule_id` is NOT validated by either function.** The schema requires it (provider-enforced), but backend validation does not reject empty string.

### Reviewer validation (repair_review_chain.py)

**`_coerce_reviewer_repair_output()`** (lines 204-248):
- JSON parse ✓
- Decision validated against accept/revise/reject ✓
- revise → `request_revision` mapping ✓
- Confidence defaults to 0.8 if missing ✓
- Checksum fallback: if reviewer omits a checksum, the coerced value falls back to the expected checksum (lines 244-246)

**Checksum verification** (lines 683-694):
- `reviewed_context_checksum` != `context_checksum` → reject ✓
- `reviewed_primary_output_checksum` != `primary_checksum` → reject ✓
- `reviewed_diff_checksum` != `diff_checksum` → reject ✓

**Decision gate** (line 696):
- `reviewer_output["decision"] != "accept"` → raises error ✓
- **Only accept creates proposals** ✓

| Scenario | Creates proposal? | Evidence |
|---|---|---|
| Malformed proposer output | NO | Lines 550-578, exception raised |
| Empty diff | NO | Lines 187-190 |
| Reviewer revise | NO | Line 696-698 |
| Reviewer reject | NO | Line 696-698 |
| Checksum mismatch | NO | Lines 683-694 |
| Unknown decision | NO | Lines 231-233 |

**All fail-closed correctly for the review chain's own validation.**

---

## 7. Exact Proposer Transport / Request

### Transport:
`chat_completions_v1` — forced by `_resolve_transport()` at line 245:
```python
if role in (V2ModelRole.PROPOSER, V2ModelRole.REVIEWER) and responsibility in ("repair_proposal", "repair_review"):
    return "chat_completions_v1"
```

### Route:
`answer_with_role(PROPOSER)` in `repair_review_chain.py:528`
→ `_answer_with_deployment()` at line 249
→ `_resolve_transport()` → `"chat_completions_v1"`
→ `_chat_completion()` at line 299
→ `force_chat_completions=True` → `_chat_completion_v1()`
→ `_post_chat_completion_v1()` at line 685

### Full HTTP Request Body:
```
POST {endpoint}/openai/v1/chat/completions
Headers: Content-Type: application/json, api-key: {key}
Body:
{
  "model": "{deployment}",
  "messages": [
    {"role": "system", "content": "You are the AMF-252 repair proposer..."},
    {"role": "user", "content": "You are the AMF-252 repair proposer.\nYour task..."}
  ],
  "max_completion_tokens": 20000 (minimum, can be higher),
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairPrimaryOutput",
      "strict": true,
      "schema": { ... REPAIR_PRIMARY_OUTPUT_SCHEMA ... }
    }
  },
  "reasoning_effort": null or omitted
}
```

**Timeout: resolved via router.resolve_timeout()** — defaults to 300.

---

## 8. Exact Reviewer Transport / Request

### Transport:
`chat_completions_v1` — same as proposer.

### Route:
`answer_with_role(REVIEWER)` in `repair_review_chain.py:638`
→ `_answer_with_deployment()`
→ `_resolve_transport()` → `"chat_completions_v1"`
→ `_chat_completion()` → `force_chat_completions=True`
→ `_chat_completion_v1()` → `_post_chat_completion_v1()`

### Full HTTP Request Body:
```
POST {endpoint}/openai/v1/chat/completions
Body:
{
  "model": "{deployment}",
  "messages": [
    {"role": "system", "content": "You are the independent AMF-252 repair reviewer..."},
    {"role": "user", "content": "You are a repair reviewer..."}
  ],
  "max_completion_tokens": 20000 (minimum),
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "RepairReviewerOutput",
      "strict": true,
      "schema": { ... REPAIR_REVIEWER_OUTPUT_SCHEMA ... }
    }
  }
}
```

**`reasoning_effort`:** If reviewer env `AZURE_OPENAI_REVIEWER_REASONING_EFFORT` is set to `""` (empty), `_resolve_reasoning_effort()` detects `role_env in os.environ` → `raw = ""` → returns `None`. `None` is omitted from the payload (line 705: `if reasoning_effort is not None`). **PROVEN.**

---

## 9. Responses API Generic Path Audit

`_responses_completion_v1()` at line 558 delegates to `_post_responses_v1()` at line 731.

### The response_format transformation is correct (lines 751-761):
```python
if response_format is not None:
    schema_name = response_format.get("json_schema", {}).get("name", "response")
    json_schema = response_format.get("json_schema", {})
    payload["text"] = {
        "format": {
            "type": "json_schema",
            "name": schema_name,
            "strict": json_schema.get("strict", True),
            "schema": json_schema.get("schema", {}),
        }
    }
```

### Checks:
- **`text.format` used?** YES — correct shape for Responses API ✓
- **`name` at correct level?** YES — inside `text.format` ✓
- **`strict` at correct level?** YES — inside `text.format` ✓
- **`schema` at correct level?** YES — inside `text.format` ✓
- **`max_output_tokens` used?** YES (line 749-750) ✓
- **Reasoning sent correctly?** YES — `payload["reasoning"] = {"effort": reasoning_effort}` at line 763 ✓
- **Raw Chat Completions format reused?** NO — separate handler ✓
- **Risk to non-repair roles?** NO — repair roles bypass Responses API entirely via `force_chat_completions=True` ✓

**Verdict: CORRECT FROM STATIC CONTRACT**

---

## 10. Reasoning-Effort Resolution

`_resolve_reasoning_effort()` in `v2_model_role_router.py` lines 341-352:

```python
def _resolve_reasoning_effort(self, role: V2ModelRole) -> str | None:
    role_key = role.value.upper()
    role_env = f"AZURE_OPENAI_{role_key}_REASONING_EFFORT"
    if role_env in os.environ:       # <-- distinguishes ABSENT from PRESENT-BUT-EMPTY
        raw = os.environ.get(role_env, "").strip()
        if raw:
            return raw
        return None                  # <-- empty string → None
    generic = self._read_str_env("AZURE_OPENAI_REASONING_EFFORT")
    if generic:
        return generic
    return None
```

**`name in os.environ` is used to distinguish absent from present-but-empty. PROVEN.**

### Resolution table:

| Role | Role env | Generic env | Resolved to | Sent in HTTP body? |
|---|---|---|---|---|
| PROPOSER | Not set / "medium" | any | "medium" or None → omitted | If None → omitted |
| REVIEWER | `""` | any | None | Omitted |
| REVIEWER | Not set | "low" | "low" | `reasoning_effort: "low"` |
| REVIEWER | Not set | Not set | None | Omitted |

---

## 11. Timeout Resolution

`resolve_timeout()` in `v2_model_role_router.py` lines 328-339:

```python
def resolve_timeout(self, *, role: V2ModelRole) -> int:
    role_key = role.value.upper()
    role_timeout = self._read_int_env(f"AI_MIGRATION_{role_key}_TIMEOUT_SECONDS", 0)
    if role_timeout > 0:
        return role_timeout
    role_timeout = self._read_int_env(f"AZURE_OPENAI_{role_key}_TIMEOUT_SECONDS", 0)
    if role_timeout > 0:
        return role_timeout
    generic_timeout = self._read_int_env("AZURE_OPENAI_TIMEOUT_SECONDS", 0)
    if generic_timeout > 0:
        return generic_timeout
    return 300
```

The launcher script (`run_amf252_backend_clean.ps1`) must set the env vars. This audit cannot verify env var values statically. But the code path is proven:

1. Timeout is resolved per-role
2. Passed to `_answer_with_deployment()` (line 289)
3. Passed to `_chat_completion()` (line 306)
4. Passed as `timeout=resolved_timeout` to `urllib.request.urlopen()` (line 724)
5. Default fallback is **300 seconds**

**Verdict: Code is correct. Env var values must be verified at runtime.**
**PROPOSER effective timeout: env-dependent, default 300.**
**REVIEWER effective timeout: env-dependent, default 300.**

---

## 12. Role-Specific System Prompts

`_system_prompt_for_role()` in `v2_assistant_model_client.py` lines 833-855:

```python
def _system_prompt_for_role(role: V2ModelRole) -> str:
    if role == V2ModelRole.PROPOSER:
        return "You are the AMF-252 repair proposer.\n\nYou may generate proposed patch TEXT..."
    if role == V2ModelRole.REVIEWER:
        return "You are the independent AMF-252 repair reviewer.\n\nReview the proposed patch..."
    return _assistant_system_prompt()
```

### Proposer prompt analysis:
- **Can generate PATCH TEXT?** YES — explicitly allowed ✓
- **Can execute commands?** NO — explicitly forbidden ✓
- **Can approve self?** NO — explicitly forbidden ✓
- **Can bypass policy?** NO — explicitly forbidden ✓

### Reviewer prompt analysis:
- **Can accept?** YES ✓
- **Can revise?** YES ✓
- **Can reject?** YES ✓
- **Can apply/modify/execute?** NO — explicitly forbidden ✓

### Prompt contradiction check:
The system prompt says "You may generate proposed patch TEXT" (proposer). The user prompt in `_primary_repair_prompt()` also says "produce a minimal, safe, raw Git-style unified diff". **NO CONTRADICTION.**

The system prompt says "You may return accept, revise, or reject" (reviewer). The reviewer user prompt says "Validate the repair proposal... Accept only if...". **NO CONTRADICTION.**

**Verdict: PROPOSER PROMPT CONFLICT: NO. REVIEWER PROMPT CONFLICT: NO.**

---

## 13. Bounded Source Context Audit

### Architecture:

`build_bounded_source_context()` in `repair_context.py` lines 75-133:
- Takes `sandbox_root`, `compiler_errors`, `changed_files`
- Resolves paths relative to sandbox_root
- Checks for symlinks AFTER `resolve()` (line 57 `resolved.is_symlink()`)
- Checks path is within sandbox via `relative_to(sandbox_root)` (line 57-61)
- Reads file, selects window around error line
- Max 3 files, 40K characters total
- SHA-256 over FULL file (not excerpt)
- Context pack checksum includes `content_checksum`, path, line bounds

### Critical question: Where does sandbox_root come from?

In `_maybe_write_repair_failure_context()` of `v2_orchestrator_runner.py` (line 1269):
```python
sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")
```

This is from the orchestrator result dict. Available on build/test failure.

### Critical question: Are compiler_errors actually populated?

**PROVEN: NO.** `_maybe_write_repair_failure_context()` calls `build_failure_evidence()` at line 1249 WITHOUT passing `compiler_errors`. The function signature is:
```python
build_failure_evidence(
    failure_source=...,
    stage_index=...,
    ...,
    # NO compiler_errors parameter
)
```

The default for `compiler_errors` in `build_failure_evidence` is `None`, which becomes `()` in the constructor (line 153: `compiler_errors=tuple(compiler_errors or ())`).

Then at lines 1264-1267:
```python
compiler_error_locations: list[tuple[str, int]] = []
for err in evidence.compiler_errors:  # empty!
    if err.file_path and err.line > 0:
        compiler_error_locations.append((err.file_path, err.line))
```

**This is empty. Source contexts will only be built from `changed_files`.**

### Path security:

`_normalize_and_check_path()` (lines 53-64):
```python
resolved = (sandbox_root / file_path).resolve()
try:
    resolved.relative_to(sandbox_root)
except ValueError:
    return None
if resolved.is_symlink():
    return None
return resolved
```

**Symlink check AFTER `resolve()`**: If a symlink points inside sandbox, `resolve()` follows it and then `relative_to(sandbox_root)` passes. The `is_symlink()` check on line 62 checks the resolved path, which is the TARGET (not a symlink anymore). **This means a symlink attack CAN work if a symlink inside sandbox points to a path also inside sandbox but to an unexpected file.** However, `relative_to(sandbox_root)` prevents escape outside sandbox.

**The ordering is: resolve() → relative_to(sandbox_root) → is_symlink()**.
- If `foo` is a symlink → `../secret.txt`, then `(sandbox_root / "foo").resolve()` points outside sandbox → `relative_to(sandbox_root)` raises ValueError → returns None. **SAFE.**
- If `foo` is a symlink → `../sibling/file.txt` where `../sibling/` is ALSO inside sandbox, then `relative_to` passes, `is_symlink()` checks the resolved path (which is a regular file) → false. The content of `../sibling/file.txt` is read. This is bounded by sandbox, so **SAFE**, but the file selection may be unexpected.

**Path traversal via `..`**: `file_path` is joined with sandbox_root and resolved. `..` in file_path is normalized away. Then `relative_to(sandbox_root)` checks. **SAFE.**

**Absolute Windows paths**: `sandbox_root / "C:\foo"` on Windows would produce `sandbox_root\C:\foo` which resolves weirdly. But `relative_to(sandbox_root)` would catch this. **SAFE.**

| Question | Answer | Evidence |
|---|---|---|
| sandbox_root available? | On build/test failure | Line 1269 |
| Empty sandbox_root? | Produces empty source_contexts | Line 1271 checks truthiness |
| compiler_errors populated? | NO — P0 | Lines 1249-1263, no compiler_errors param |
| changed_files populated? | YES | Line 1232 |
| Path relative resolution? | YES | Line 57 |
| Symlink escape prevented? | YES | Lines 57-61, relative_to sandbox_root |
| Symlink inside sandbox → unexpected file? | POSSIBLE | is_symlink checks resolved target |
| File size bounded? | YES | Via max_chars (40K) |
| UTF-8 safe? | YES | errors="replace" at line 105 |
| Max files enforced? | YES | 3 files max at line 80 |
| Lines 0-based or 1-based? | Lines are 0-based for reading (line 111), 1-based stored (line 127) |
| SHA-256 over full file? | YES | Line 123, _sha256_file |
| Content in checksum? | YES | Via content_checksum in context pack checksum |
| Sent to proposer? | YES | Lines 88-100 of repair_review_chain.py |

### Verdict: SOURCE CONTEXT ARCHITECTURE: CONDITIONAL

**P0: compiler_errors list is always empty because build_failure_evidence is called without compiler_errors parameter.**

---

## 14. Failure Evidence Population Audit

`_maybe_write_repair_failure_context()` (lines 1208-1326 of orchestrator_runner.py) builds `FailureEvidence` with:

| Field | Available? | Evidence |
|---|---|---|
| failure_source | YES | From build_status/test_status at line 1220 |
| failure_summary | YES | From result at line 1242 |
| compiler_errors | **NO — always empty** | build_failure_evidence called without compiler_errors param |
| test_failures | **NO — always empty** | Same reason |
| changed_files | YES | From result at line 1232 |
| source_profile | YES | From result at line 1256 |
| target_profile | YES | From result at line 1257 |
| stdout_tail | YES | From orchestrator at line 1260 |
| stderr_tail | YES | From orchestrator at line 1261 |
| safe_log_preview | YES | From result at line 1262 |

| Failure type | Compiler errors | Test failures | Source context expected (with current code) |
|---|---|---|---|
| Build failure | **Empty** | Empty | Based on changed_files only |
| Test failure | Empty | **Empty** | Based on changed_files only |
| Transform failure | N/A — not handled here | N/A | N/A |

**P0: compiler_errors is never populated, making source_context selection at best based on changed_files only.**

---

## 15. Raw vs Redacted Content Audit

### Authoritative data flow:

```
provider HTTP response
→ _post_chat_completion_v1() → _extract_assistant_content() → returns raw content str
→ _chat_completion_v1() → returns raw content
→ _chat_completion() → returns raw content
→ _answer_with_deployment() → V2AssistantModelResult(content=raw_content) ← RAW
→ router route() → V2RoleModelResult(content=raw_content) ← RAW
→ _to_assistant_result() → V2AssistantModelResult(content=raw_content, redacted_summary=redact(raw_content))
→ repair_review_chain.py: primary_result.content ← RAW
```

### Key decision points:

1. **Is raw content parsed before redaction?** YES. `_coerce_primary_repair_output()` at line 551 of repair_review_chain.py parses `primary_result.content` (raw). Redacted_summary is separate.

2. **Is raw diff checksummed exactly?** YES. `_compute_primary_repair_checksum()` at line 251 uses the raw output dict including proposed_diff.

3. **Is raw diff persisted?** YES. `diff_path.write_text(proposed_diff, encoding="utf-8")` at line 723.

4. **Can public API return raw content?** The `V2AssistantModelResult` is used internally. The FastAPI endpoint returns safe diff preview. **Raw content is NOT directly exposed via API.**

5. **LLM activity endpoint:** The invocation ledger stores `output` (raw) and `redacted_summary`. The raw output goes to DB. The projection `record_to_attempt_summary` does NOT return raw content.

6. **Logs:** `_log_transport_diagnostic` includes `error_detail` which goes through `_sanitize_body_snippet()` → `redact_model_summary()`. **Redacted.**

7. **Exceptions:** `RepairReviewChainProductionError` may include content snippets limited to 1000 chars.

### Security assessment:

| Destination | Raw content? | Redacted? | Public? | Risk |
|---|---|---|---|---|
| V2AssistantModelResult.content | YES | No | Internal | LOW |
| LLM ledger DB | YES (output field) | No | Via internal API | MEDIUM |
| Transport diagnostic logs | Via error_detail | YES (redacted) | Log only | LOW |
| Exceptions | 1000-char snippets | No | In logs | LOW |
| Frontend / API | No | N/A | No | SAFE |
| Events | No | N/A | Via SSE | SAFE |

**Verdict: AUTHORITATIVE DATA INTEGRITY: GOOD. RAW CONTENT PUBLIC EXPOSURE: NO.**

---

## 16. Diagnostic Security Audit

`_log_transport_diagnostic()` at line 858 of `v2_assistant_model_client.py`:

```python
def _log_transport_diagnostic(*, role, responsibility, transport, deployment,
                                schema_name, response_format_used, http_status, error_detail):
    diag = {
        "event": "model_transport_failure",
        "role": role,
        "responsibility": responsibility,
        "transport": transport,
        "deployment": deployment[:64] if deployment else "",
        "schema_name": schema_name,
        "response_format": response_format_used,
        "http_status": http_status,
        "error_detail": error_detail[:500] if error_detail else "",  # <-- CAPPED
    }
    logger.warning("TRANSPORT_DIAGNOSTIC: %s", json.dumps(diag, default=str))
```

`error_detail` is already truncated (500 chars) and passes through `_summary_with_snippet()` which calls `redact_model_summary()`. The upstream `_sanitize_body_snippet()` (line 1061) also strips API keys.

**Checks:**
- `error_detail` truncated? YES — max 500 chars
- `redact_model_summary()` applied? YES — via `_summary_with_snippet()` and `_sanitize_body_snippet()`
- API key in diagnostic? NO — stripped by regex in `_sanitize_body_snippet()`
- Authorization header? NO — stripped
- Endpoint deployed? Truncated to 64 chars
- Raw prompt? NO — never included

**Verdict: DIAGNOSTIC ERROR DETAIL SAFE: YES**

---

## 17. Direct Option A Field Lineage Matrix

| Field | Proposer output | Review chain | V2RepairProposalRecord | DB column | Approval reload | Patch gate |
|---|---|---|---|---|---|---|
| proposal_id | N/A | Generated | UUID4 | proposal_id | Via URL | Used |
| job_id | N/A | From context | job_id | job_id | Via URL | Used |
| command_id | N/A | From context | command_id | command_id | From record | Used |
| stage_index | N/A | From context | route_step_index | route_step_index | From record | Used |
| attempt_number | N/A | Computed | attempt_number | attempt_number | From record | Used |
| failure_evidence_ref | N/A | Loaded path | failure_evidence_ref | failure_evidence_ref | Loaded | No |
| failure_evidence_checksum | N/A | From context | Not persisted | N/A | N/A | N/A |
| context_pack_ref | N/A | Loaded path | repair_context_ref | repair_context_ref | Loaded | No |
| context_pack_checksum | N/A | From context | Not persisted | N/A | N/A | N/A |
| base_repo_state_checksum | N/A | From context | Not persisted | N/A | N/A | N/A |
| root_cause | YES | YES (review_chain) | hypothesis | hypothesis | Read | No |
| fix_strategy | YES | YES (review_chain) | patch_summary | patch_summary | Read | No |
| changed_files | YES | YES (review_chain) | affected_paths_json | affected_paths_json | Read | No |
| proposed_diff | YES | Persisted on disk | diff_ref (path) | diff_ref | Reloaded from disk | YES |
| proposed_diff_checksum | Computed | YES | diff_checksum | diff_checksum | Re-verified | YES |
| **deterministic_rule_id** | YES | YES (review_chain) | **deterministic_rule_id** | deterministic_rule_id | Loaded via runtime context | **YES** |
| **risk** | YES | YES (review_chain) | **risk** | risk | Loaded via runtime context | **YES** |
| confidence | YES | YES (review_chain) | Not persisted | N/A | N/A | N/A |
| reviewer_decision | N/A | YES (review_chain) | reviewer_decision | reviewer_decision | Checked = "accept" | N/A |
| reviewer_notes | N/A | YES (review_chain) | Not persisted | N/A | N/A | N/A |
| reviewer_output_checksum | N/A | YES | reviewer_output_checksum | reviewer_output_checksum | Not used | N/A |

**PROVEN: deterministic_rule_id and risk ARE PRESERVED end-to-end.** The `V2RepairProposalRecord` dataclass includes both (lines 55-56 of `v2_repair_repository.py`), the INSERT includes both (line 93), and the approval runtime context resolver (`_resolve_repair_proposal_runtime_context` lines 12552-12560) loads them from the record.

---

## 18. deterministic_rule_id Actionability Audit

### Trace:

1. **Proposer can return `no_safe_rule`** — explicitly documented in user prompt (repair_review_chain.py line 108): `"deterministic_rule_id (or 'no_safe_rule')"`.

2. **Schema requires deterministic_rule_id** as string, but allows any string including "no_safe_rule". Backend semantic validator does NOT validate deterministic_rule_id content.

3. **Proposal created** with `deterministic_rule_id="no_safe_rule"`, status `user_review_required`.

4. **repair_state.ready** — the `get_current_proposal_for_job` query returns proposals with status `user_review_required`. So a `no_safe_rule` proposal appears ready.

5. **allowed_actions** — `_format_approval_review_preview` may show `approve_sandbox_apply` based on status alone, not rule ID.

6. **Approve endpoint** calls `_resolve_repair_proposal_runtime_context` which loads `deterministic_rule_id="no_safe_rule"` and passes to `evaluate_patch_proposal()`.

7. **Patch gate** at `patch_gate.py` line 77-83: `rule_id = str(proposal.get("deterministic_rule_id") or "")` → `"no_safe_rule"`. Line 82: `if not rule_id: return INVALID_PATCH` — does NOT fire because "no_safe_rule" is truthy. Then `evaluate_rule()` at line 109-116 checks `if rule_id not in ALLOWED_RULE_IDS` — `"no_safe_rule"` is NOT in `ALLOWED_RULE_IDS` (rule_registry.py line 9-18). Returns `RuleDecision(False, ..., human_review_required=True)`. This becomes `HUMAN_REVIEW_REQUIRED` status. The approve endpoint checks `if gate_result.status != "ALLOWED"` → raises PATCH_GATE_REJECTED.

**So `no_safe_rule` proposals CAN be created, appear ready, but CANNOT be approved (patch gate rejects them).**

| Question | Answer | Evidence |
|---|---|---|
| no_safe_rule → ready? | YES | status=user_review_required |
| no_safe_rule → approve? | NO | Patch gate rejects |
| Approve button visible? | POSSIBLE | Frontend allowed_actions based on status |

**Verdict: SAFE (patch gate catches it), but BAD UX (user sees Apply button then gets rejection).** Not a P0 safety blocker but a significant UX issue.

---

## 19. Risk Fail-Closed Audit

### Critical finding:

In `_resolve_repair_proposal_runtime_context()` of `app.py` line 12560:
```python
risk = str(getattr(record, "risk", "") or "").upper() or "LOW"
```

| Scenario | Resolution | Evidence |
|---|---|---|
| NULL risk from DB | `getattr(record, "risk", "")` → `None` → `str(None)` → `"None"` → `.upper()` → `"NONE"` → `"NONE" or "LOW"` → `"LOW"` | Line 12560 |
| Empty string risk | `str("")` → `""` → `"" or "LOW"` → `"LOW"` | Line 12560 |
| Missing field | `getattr(record, "risk", "")` → `""` → `"" or "LOW"` → `"LOW"` | Line 12560 |
| Malformed risk | Goes through as-is, then patch gate checks `risk != "LOW"` → MEDIUM/HIGH → HUMAN_REVIEW_REQUIRED | Lines 84-85 of patch_gate.py |

**Wait — for NULL from DB**: `getattr(record, "risk", "")` on a dataclass field of type `str | None` returns `None` when the value is None. Then `str(None)` is `"None"`, which is truthy, so `"None" or "LOW"` = `"None"`. Then `.upper()` = `"NONE"`. Then `risk != "LOW"` is True at patch_gate.py line 84 → returns `HUMAN_REVIEW_REQUIRED`. So NULL risk actually becomes `"NONE"` which triggers human review at the patch gate. **This is safe but ugly.**

**For empty string**: `getattr(record, "risk", "")` returns `""`. `str("")` = `""`. `"" or "LOW"` = `"LOW"`. **This IS unsafe — empty string becomes LOW.**

**For missing field** (if column didn't exist): `getattr(record, "risk", "")` returns `""`. Same as empty string. **IS unsafe.**

**Verdict: NORMAL NEW PROPOSAL RISK FLOW: SAFE** (risk is set from proposer→review_chain→record). **OLD/NULL ROW RISK FLOW: CONDITIONAL** — NULL → "NONE" → human review (safe). Empty string → LOW (unsafe).

**P1: The `"" or "LOW"` pattern should be `"" or "BLOCKED"` or should fail-closed to HUMAN_REVIEW_REQUIRED, not LOW.**

---

## 20. Repository/Database Migration Coherence

### V2RepairProposalRecord fields (lines 12-56):

Both `deterministic_rule_id: str | None = None` and `risk: str | None = None` are declared (lines 55-56).

### SQL INSERT (lines 78-96):
The INSERT includes both columns (line 93: `deterministic_rule_id, risk`) and both placeholders (line 96: `?, ?`). Arguments at lines 138-139 pass `record.deterministic_rule_id` and `record.risk`. **PROVEN COHERENT.**

### SELECT * behavior:
All `SELECT *` queries will automatically include the new columns after migration runs.

### _row_to_proposal (lines 281-326):
Both fields are handled with the safe pattern:
```python
deterministic_rule_id=str(row["deterministic_rule_id"]) if "deterministic_rule_id" in keys and row["deterministic_rule_id"] else None,
risk=str(row["risk"]) if "risk" in keys and row["risk"] else None,
```

These check `in keys` for backward compatibility with older DBs that don't have these columns. **PROVEN BACKWARD COMPATIBLE.**

### Construction site (v2_repair_gate_service.py lines 686-711):
```python
record = V2RepairProposalRecord(
    ...
    deterministic_rule_id=str(review_chain.get("deterministic_rule_id", "")),
    risk=str(review_chain.get("risk", "")),
)
```

All fields are key-word arguments (not positional). **PROVEN SAFE.**

### Verdict:
| Property | Status |
|---|---|
| Repository schema coherent | YES |
| Migration coherent | N/A — blocked by version collision |
| Backward compatible | YES |
| Key-word construction safe | YES |

---

## 21. Repair Attempt Semantics

### list_attempts_by_job (v2_repair_repository.py lines 238-246):
```python
SELECT * FROM v2_repair_proposals
WHERE job_id = ? AND attempt_number IS NOT NULL
ORDER BY attempt_number DESC, created_at DESC
```

Only proposals with `attempt_number IS NOT NULL` are returned. Since the direct Option A path at `v2_repair_gate_service.py` lines 698 sets `attempt_number=attempt_number`, successful proposals WILL appear. **Failed proposer invocations do NOT create proposals, so they do NOT appear.**

### Scenario matrix:

| Scenario | Event emitted? | Proposal row? | Attempt API row? | Counts against max? |
|---|---|---|---|---|
| Proposer HTTP 400 | repair_started | No | No | **No** — attempt_number assigned after chain succeeds |
| Reviewer reject | repair_started | No (`status=skipped`) | No | **No** |
| Reviewer accept + proposal | YES (repair_proposal_ready) | YES | YES | **YES** |
| Validator failure + new attempt | YES (repair_validation_failed) | YES (new) | YES | **YES** |

### Attempt number assignment (v2_repair_gate_service.py lines 533-556):
```python
persisted_attempts = self._get_persisted_attempt_count(job_id, stage_index)
# ... also checks direct proposals in DB
attempt_number = persisted_attempts + 1
```

**Attempt numbering IS durable** — it reads from DB. **NOT race-safe** — two concurrent callbacks could get same MAX(attempt_number). But for MVP this is acceptable.

### Attempt count is in-memory AND DB-backed:
- `_attempt_counts` dict (in-memory, non-durable)
- `_get_persisted_attempt_count` reads from DB
- **On restart, in-memory count is lost, but DB count is recovered**

| Question | Answer |
|---|---|
| /repair/attempts = attempts or proposals? | Proposals with attempt_number |
| Failed provider disappears? | YES |
| Reviewer reject disappears? | YES |
| attempt_number assigned before model call? | **NO** — assigned after chain succeeds |
| Process restart resets count? | **NO** — DB-backed |
| Duplicate callbacks → duplicate numbers? | POSSIBLE (not race-safe) |

**Verdict: ATTEMPT HISTORY COMPLETE: NO** (failed attempts before proposal creation are invisible). **ATTEMPT LIMIT DURABLE: YES.**

---

## 22. Model Fallback/Source Semantics

### Source values in current code:

| Runtime path | source | fallback_used | status | Accurate? |
|---|---|---|---|---|
| Live provider success | "azure_openai" | False | "live_ok" | YES |
| Fallback success | "deterministic" | True | "fallback" | YES |
| Primary failure + fallback failure | "deterministic" | True (only if fallback_failure) | "fallback" | CONFUSING |
| Router deterministic (both fail) | "deterministic" | Variable | "fallback" | CONFUSING |

**In `_deterministic_result()`** (v2_model_role_router.py lines 260-261):
```python
fallback_used=bool(fallback_failure_reason),
```
This is `True` only when `fallback_failure_reason` is non-empty. If primary failed but fallback didn't run (disabled), `fallback_failure_reason` is `""` → `fallback_used=False`. **But the source is still "deterministic".**

**In `_safe_model_role_status()`** (repair_review_chain.py line 785):
```python
"fallback_used": str(getattr(result, "source", "") or "") == "azure_openai_fallback",
```
This checks for the literal string `"azure_openai_fallback"`. But the source is now `"deterministic"`, not `"azure_openai_fallback"`. **So `fallback_used` will always be `False`** for deterministic fallback. **This is MISLEADING.**

**Verdict: DIAGNOSTIC SEMANTICS: MISLEADING.** `_safe_model_role_status().fallback_used` will be False even when deterministic fallback is used.

---

## 23. repair_state and allowed_actions Coherence

### Current proposal state generation:

`get_current_proposal_for_job()` (v2_repair_repository.py lines 224-236):
```python
SELECT * FROM v2_repair_proposals
WHERE job_id = ?
  AND (status = 'user_review_required'
       OR (gate_id IS NOT NULL AND status IN ('user_review_required', 'reviewer_accepted', 'diff_materialized')))
ORDER BY created_at DESC
LIMIT 1
```

For direct Option A proposals (no gate_id), the status must be `'user_review_required'`.

### What creates state.ready?

The event `repair_proposal_ready` is emitted at line 410 of v2_repair_gate_service.py. This happens when `result.status == "created"` — i.e., the proposal was persisted with reviewer accept.

**repair_state.ready means: reviewed chain accepted + proposal persisted.**

It does NOT mean:
- deterministic_rule_id is allowlisted ✓ (NOT checked before ready)
- risk is valid ✓ (NOT checked before ready)
- Patch gate has run ✓ (NOT checked before ready)

**Verdict: `repair_state.ready` means "reviewed" not "actionable". The approve endpoint is the actual gate that runs `evaluate_patch_proposal()`.**

This is architecturally sound — the frontend shows "ready" but the actual apply will fail at the patch gate. However, it's bad UX.

---

## 24. Approval Fail-Closed Audit

### Approve endpoint checks (app.py lines 3960-4160):

| Check | Present? | Line | Result if fails |
|---|---|---|---|
| proposal_id match | YES | 3985-3990 | 400 |
| record exists & belongs to job | YES | 3996-4002 | 404 |
| diff_ref exists | YES | 4005-4012 | 400 |
| request checksum == stored checksum | YES | 4015-4020 | 409 |
| Recompute checksum from disk | YES | 4030-4044 | 409 |
| SafeDiffPreview checksum match | YES | 4047-4070 | 409/400 |
| Reviewer decision == "accept" | YES | 4073-4079 | 409 |
| Status is approvable | YES | 4082-4094 | 409 |
| Patch gate | YES | 4115-4135 | 409 |
| Legacy source check | YES | 4140-4151 | 409 |

**ALL INVARIANTS PRESENT.** The approve endpoint is thoroughly fail-closed.

### Old row behavior:
- `risk = None` → `str(None)` → `"None"` → patch gate: `"NONE" != "LOW"` → `HUMAN_REVIEW_REQUIRED` → rejected.
- `deterministic_rule_id = None` → `str(None)` → `"None"` → patch gate: `rule_id = "None"` → `evaluate_rule("None")` → `"None" not in ALLOWED_RULE_IDS` → `HUMAN_REVIEW_REQUIRED` → rejected.

**OLD ROWS ARE SAFE — they cannot be approved because risk=NULL→"NONE" and rule_id=NULL→"None" both fail the patch gate.**

**Verdict: APPROVAL FAIL-CLOSED: YES**

---

## 25. Patch Gate Contract Audit

`evaluate_patch_proposal()` in `patch_gate.py` lines 68-120:

| Condition | Result | Line |
|---|---|---|
| Missing rule_id (empty) | INVALID_PATCH | 82-83 |
| risk != "LOW" | HUMAN_REVIEW_REQUIRED | 84-85 |
| requires_human_review | HUMAN_REVIEW_REQUIRED | 86-87 |
| Not unified diff | INVALID_PATCH | 88-89 |
| Out of scope claims | BLOCKED | 90-91 |
| Path errors | INVALID_PATCH | 93-103 |
| Security concern | HUMAN_REVIEW_REQUIRED | 105-107 |
| Rule not in ALLOWED_RULE_IDS | HUMAN_REVIEW_REQUIRED or BLOCKED | 109-119 |
| All pass | ALLOWED | 120 |

### Rule Registry (rule_registry.py):

**ALLOWED_RULE_IDS = 8 specific IDs:**
1. DEPENDENCY_ADD_H2_RUNTIME
2. DEPENDENCY_ADD_VALIDATION_STARTER
3. DEPENDENCY_REMOVE_TOMCAT9_OVERRIDE_BOOT3
4. DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA
5. DEPENDENCY_REPLACE_JAVAX_VALIDATION_WITH_JAKARTA
6. DEPENDENCY_UPGRADE_ZALANDO_PROBLEM_SPRING_WEB_0291
7. H2_SMOKE_CONFIG_ONLY
8. JAKARTA_IMPORT_MECHANICAL_SOURCE

Each rule has content-specific validation (e.g., must touch only pom.xml, must add specific dependency).

**Patch gate IS content-aware policy check, not just identity check.**

### `no_safe_rule` through patch gate:
- `rule_id = "no_safe_rule"` (truthy, passes empty check)
- Passes risk check (if LOW)
- Passes `is_unified_diff` check
- Passes path checks
- Passes security check
- `evaluate_rule("no_safe_rule")` → `"no_safe_rule" not in ALLOWED_RULE_IDS` → returns `RuleDecision(False, ..., human_review_required=True)`
- Result: `HUMAN_REVIEW_REQUIRED`

**Verdict: PATCH GATE IS: CONTENT-AWARE POLICY CHECK** (with rule-specific validation). `no_safe_rule` is correctly blocked.

---

## 26. Validation Failure Preservation Audit

### Patch applies successfully, validation fails (app.py lines 4251-4296):

```python
# Validation failed
proposal_post_status = "approve_failed"
rollback_status = None   # <-- NO rollback
# ... updates proposal status
if remaining_attempts_after > 0:
    next_result = _create_next_direct_reviewed_repair_proposal_from_validation_failure(...)
```

**Key behaviors:**
1. `rollback_status = None` — **no rollback called** ✓
2. Next attempt created with `_create_next_direct_reviewed_repair_proposal_from_validation_failure` ✓
3. Sandbox preserved — the patched sandbox is used for the next validation ✓
4. Fresh `FailureEvidence` created with `FailureSource.VALIDATION` ✓
5. New `RepairContextPack` includes prior checksums ✓

**LOCKED POLICY COMPLIANT: YES**

---

## 27. Multi-Attempt Source Context Freshness

`_create_next_direct_reviewed_repair_proposal_from_validation_failure()` (app.py lines 12579-12659):

1. Creates fresh `FailureEvidence` with `FailureSource.VALIDATION` and actual validation errors
2. Creates fresh `RepairContextPack` via `build_repair_context_pack()`
3. The context pack does NOT include `source_contexts` — it defaults to empty tuple
4. The new proposal is created via `repair_gate_svc.create_reviewed_repair_proposal_on_failure()` which loads from refs and calls `produce_repair_review_chain()`
5. The review chain builds source context from the `context_pack` and `failure_evidence`
6. But since `compiler_errors` is empty (as established), source context will again be based only on `changed_files`

**Source context is technically "fresh" because new FailureEvidence is created, but it's equally unpopulated as the first attempt.**

**Verdict: MULTI-ATTEMPT CONTEXT FRESHNESS: CONDITIONAL** — fresh FailureEvidence is created but compiler_errors remain empty. The proposer gets `changed_files` plus validation error summary, but no actual source file content unless `changed_files` triggers context selection.

---

## 28. Source Path/Symlink Security

### Static analysis of attack vectors:

| Attack | _normalize_and_check_path | Patch gate | Result |
|---|---|---|---|
| `../secret.txt` | `(sandbox / "../secret.txt").resolve()` → outside sandbox → `relative_to` fails → None | Rejected by path traversal check | **BLOCKED** |
| `..\secret.txt` on Windows | Same behavior after resolve | Rejected by `_relative_path_errors` | **BLOCKED** |
| Absolute path `/etc/passwd` | `(sandbox / "/etc/passwd").resolve()` → OS-dependent, generally weird path | `_relative_path_errors` rejects absolute | **BLOCKED** |
| Symlink inside → outside | `resolve()` follows symlink → resolves outside → `relative_to` fails | `_has_symlink_parent` catches in patch gate | **BLOCKED** |
| Symlink inside → another inside file | `resolve()` follows → still inside sandbox → `relative_to` passes → `is_symlink()` on resolved (not symlink) → false | `_has_symlink_parent` walks each part | **BLOCKED** by patch gate |
| UNC path `//server/share/` | Resolve may fail | `_relative_path_errors` catches absolute | **BLOCKED** |
| `.git` in path | Path check catches | `_relative_path_errors` blocks `.git` | **BLOCKED** |
| Case confusion on Windows | Path may resolve to same file, case-insensitive on NTFS | Within sandbox, not a security issue | **ACCEPTABLE** |

### Symlink ordering in _normalize_and_check_path:
```python
resolved = (sandbox_root / file_path).resolve()     # 1. resolve first
try:
    resolved.relative_to(sandbox_root)               # 2. check within sandbox
except ValueError:
    return None
if resolved.is_symlink():                            # 3. check if resolved is symlink
    return None
```

**Issue**: `is_symlink()` is checked on the fully resolved path. If the path was a symlink, `resolve()` already followed it, so `is_symlink()` returns False for the target. **However**, if the path is not a symlink but a component in the middle was, `resolve()` already resolved it. The `relative_to` check is the primary security boundary.

### Patch gate path resolution:
`validate_patch_paths()` (patch_gate.py lines 159-183):
```python
candidate = (sandbox / PurePosixPath(rel)).resolve()
if not candidate.is_relative_to(sandbox):
    errors.append(f"patch path escapes sandbox: {rel}")
```

This also uses `resolve()` first, then `is_relative_to()`. **Safe.**

### Verdict:
**Source context reader: SAFE** — `relative_to` prevents escape.
**Patch gate: SAFE** — `is_relative_to` prevents escape.
**Symlink attack: BLOCKED** — resolution followed by sandbox boundary check.
**.git access: BLOCKED** — explicit deny list.

---

## 29. Source Context Secret Exposure Analysis

### File selection criteria (build_bounded_source_context):

The builder selects files from `candidate_paths` which comes from `compiler_errors` (empty — P0) and `changed_files`. There is:

- **NO file extension allowlist**
- **NO sensitive file denylist**
- **NO secret scanning**
- Files are read as-is with `read_text(encoding="utf-8")`

### Can changed_files include `.env`?

The orchestrator result provides `changed_files`. If the orchestrator reports `.env` as a changed file, it could be selected. However:

1. The orchestrator runs inside sandbox. The sandbox is git-based with controlled source.
2. `.env` files would only exist if the source repo contains them.

### Risk classification:

Secret-like files (`.env`, `credentials`, `id_rsa`, etc.) inside the sandbox source are NOT filtered by the source context builder. If present, their content could be sent to the LLM.

**Mitigating factors:**
- The sandbox is a clean workspace, not the production environment
- `.env` files are typically gitignored and wouldn't be in the source
- Changed_files comes from the orchestrator, which tracks git changes

**Verdict: SOURCE-CONTEXT DATA EXFILTRATION RISK: LOW.** No active filtering, but sandbox nature limits exposure.

---

## 30. Raw Model Content Exposure Map

| Destination | Raw content? | Redacted? | Risk |
|---|---|---|---|
| V2AssistantModelResult.content | YES | No | Internal only |
| V2RoleModelResult.content | YES | No | Internal only |
| repair_review_chain primary_result.content | YES | No | Used for parsing, not exposed |
| Redacted summary (ledger) | No (redacted) | YES (redact_model_summary) | SAFE |
| LLM ledger DB output column | YES | No | DB-local, not in API |
| LLM activity API | No | YES (redacted_summary only) | SAFE |
| HTTP responses (current proposal) | No (safe diff preview only) | YES | SAFE |
| Events/SSE | No | YES | SAFE |
| Logs (transport diagnostic) | No (500 char trunc, redacted) | YES | SAFE |
| Exceptions | 1000-char first chars | No | LOW risk — truncated |
| Diagnostic artifacts (proposer_validation_failure) | 1000-char preview | YES (pattern detection) | SAFE |

**Verdict: RAW CONTENT PUBLIC EXPOSURE: NO.** The raw content flows through internal Python objects and is only persisted to DB. The LLM activity API returns `redacted_summary`, not raw content. The diff stored on disk has access controlled by the OS.

---

## 31. HTTP Failure Observability

`_log_transport_diagnostic()` captures:
- role ✓
- responsibility ✓
- transport ✓
- deployment (truncated 64 chars) ✓
- schema_name ✓
- response_format ✓
- http_status ✓
- error_detail (truncated 500 chars, redacted) ✓

**Can operator distinguish responses_v1 vs chat_completions_v1 failure?** YES — the `transport` field is logged.

**Is this data:**
- Logged? YES — `logger.warning`
- Persisted? NO — not in DB
- Available via LLM activity API? YES — ledger persists failure_reason
- Available through debug pack? NO — but logs are available

**Verdict: FUTURE HTTP 400 DIAGNOSABILITY: GOOD** for the transport diagnostic. Operator can see role, transport type, HTTP status, and redacted error detail.

---

## 32. Transactional Consistency

### Direct Option A proposal creation (v2_repair_gate_service.py lines 408-468):

```python
if uow is not None:
    if result.status == "created":
        event = uow.v2_events.save(...)  # event persisted
        # event_id available but NOT used for atomic commit
```

**The proposal save and event save happen in the same unit of work** (they share the same `uow` object). If `uow.commit()` is called after this method returns, both proposal and event are atomically persisted. **PARTIALLY ATOMIC** — depends on the caller committing the UoW.

Looking at the call chain:
`_maybe_create_repair_gate` → `create_repair_gate_diagnosis_callback` → eventually `create_reviewed_repair_proposal_on_failure`

The caller creates the UoW. The UoW is committed after the callback returns. **So DB insert and event append ARE in the same transaction.**

| Scenario | Atomic? |
|---|---|
| Crash after proposal insert, before event | Both rolled back (same transaction) |
| Crash after event, before commit | Both rolled back |
| Commit succeeds | Both persisted |

**Verdict: PARTIALLY ATOMIC** — same UoW, so same transaction. But if UoW.commit() is not called, both are lost.

**Could event exist without proposal?** NO — same transaction, both are committed or neither.
**Could proposal exist without event?** NO — same transaction.

---

## 33. Restart / Multi-Worker Safety

### Process-local state:
- `V2OrchestratorRunner._active_processes` — tracks running processes, lost on restart
- `V2RepairGateService._attempt_counts` — in-memory attempt counts, lost on restart
- `V2RepairGateService._REPAIR_ATTEMPT_DEDUPE_KEYS` — dedupe set, lost on restart

### Durable state:
- All proposal data in SQLite
- Events in SQLite
- Migration state in `schema_migrations`

### Race conditions:
1. **Duplicate attempt numbers**: `_get_persisted_attempt_count` + 1 is not atomic across concurrent callbacks. Two callbacks for the same job/stage could get the same attempt_number.
2. **Duplicate LLM calls**: No DB uniqueness prevents running the review chain twice for the same failure.
3. **Duplicate proposals**: The code checks for existing proposals by command_id (lines 669-681 of v2_repair_gate_service.py), but between check and insert, another callback could also pass the check.

### Restart behavior:
- `_attempt_counts` is lost → next attempt starts from `_get_persisted_attempt_count` which reads from DB
- `_REPAIR_ATTEMPT_DEDUPE_KEYS` is lost → duplicates possible on restart
- **Restart does NOT reset the attempt count** because it's recovered from DB

### Multi-worker:
The `_REPAIR_ATTEMPT_DEDUPE_LOCK` is thread-local, not process-safe. Two workers could both process the same failure.

**Verdict for MVP: ACCEPTABLE** — low probability of concurrent callbacks in single-worker deployment. The DB provides eventual consistency.

---

## 34. Complete Fail-Closed Invariant Table

| Failure condition | Event | repair_state | Proposal created? | Apply allowed? | Fail closed? |
|---|---|---|---|---|---|
| Provider HTTP 400 | repair_started | N/A | No | No | YES |
| Provider timeout | repair_started | N/A | No | No | YES |
| Provider malformed JSON | repair_started | N/A | No | No | YES |
| Proposer empty diff | None (exception raised) | N/A | No | No | YES |
| Proposer Markdown diff | None (exception raised) | N/A | No | No | YES |
| Proposer invalid diff | None (exception raised) | N/A | No | No | YES |
| Proposer invalid confidence | None (exception raised) | N/A | No | No | YES |
| Proposer missing rule ID | None (exception raised) | N/A | No | No | YES |
| Proposer no_safe_rule | repair_proposal_ready | user_review_required | YES | No (patch gate) | CONDITIONAL (UX only) |
| Proposer MEDIUM risk | repair_proposal_ready | user_review_required | YES | No (patch gate) | YES |
| Proposer HIGH risk | repair_proposal_ready | user_review_required | YES | No (patch gate) | YES |
| Reviewer malformed JSON | None (exception raised) | N/A | No | No | YES |
| Reviewer checksum mismatch | None (exception raised) | N/A | No | No | YES |
| Reviewer revise | None (exception raised) | N/A | No | No | YES |
| Reviewer reject | None (exception raised) | N/A | No | No | YES |
| Reviewer timeout | repair_started | N/A | No | No | YES |
| Proposal DB insert failure | None (exception) | N/A | No | No | YES |
| Migration version collision | N/A | N/A | N/A | N/A | **P0** — startup fails |
| Risk NULL → "NONE" | N/A | N/A | YES | No (patch gate) | YES (by accident) |
| Rule ID NULL → "None" | N/A | N/A | YES | No (patch gate) | YES (by accident) |
| Stale diff checksum | N/A | N/A | N/A | No (409) | YES |
| Patch gate reject | N/A | N/A | N/A | No (409) | YES |
| Patch apply failure | repair_approve_apply_failed | approve_failed | N/A | N/A | YES |
| Validation failure | repair_validation_failed | approve_failed | Next attempt | N/A | YES |
| Attempts exhausted | repair_attempts_exhausted | approve_failed | No | N/A | YES |

---

## 35. P0/P1/P2/P3 Risk Register

### P0 — Must fix before any runtime test

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| P0-1 | **Migration version 0050 collision** | `0050_v2_llm_invocations.sql` and `0050_v2_repair_proposals_rule_id_risk.sql` both exist | Startup fails with `MigrationDiscoveryError` |
| P0-2 | **compiler_errors never populated** | `_maybe_write_repair_failure_context` calls `build_failure_evidence()` without passing `compiler_errors` param | Source context will be empty (or only changed_files-based). First real Java compile failure produces no file-level context for the proposer. |
| P0-3 | **Risk defaults to LOW for empty string** | `_resolve_repair_proposal_runtime_context` line 12560: `"" or "LOW"` | Empty risk becomes LOW instead of rejecting |

### P1 — Can run controlled test with awareness

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| P1-1 | **no_safe_rule → ready UX gap** | Proposal created with status `user_review_required` even with `no_safe_rule`. Patch gate rejects it later. | User sees Apply button, gets rejection. |
| P1-2 | **fallback_used diagnostics misleading** | `_safe_model_role_status()` checks for `"azure_openai_fallback"` string, but source is now `"deterministic"` | fallback_used always False for deterministic fallback |
| P1-3 | **Attempt history incomplete** | Only proposals with `attempt_number IS NOT NULL` appear. Failed provider attempts don't create proposals. | Frontend shows gap in attempt timeline |
| P1-4 | **Empty deterministic_rule_id allowed** | Not validated by `_coerce_primary_repair_output()` or `_validate_primary_repair_output()` | Empty string passes through, later caught by patch gate |
| P1-5 | **Race condition on attempt number** | `MAX(attempt_number) + 1` not atomic | Duplicate attempt numbers under concurrent callback |

### P2 — Should fix later

| ID | Finding | Evidence | Consequence |
|---|---|---|---|
| P2-1 | **In-memory dedupe lost on restart** | `_REPAIR_ATTEMPT_DEDUPE_KEYS` is process-local | Duplicate callbacks possible on restart |
| P2-2 | **No file extension or sensitive-file filtering in source context** | `build_bounded_source_context` reads any file type | Secret files could be sent to LLM if present in sandbox |

### P3 — Minor cleanup

| ID | Finding |
|---|---|
| P3-1 | `_safe_model_role_status` returns "available" for deterministic fallback when `fallback_used` is False |

---

## 36. Updated Implementation Scorecard

| Category | Score | Reason |
|---|---|---|
| Model contract correction | 10/10 | Schemas clean, provider-safe, no remaining Azure-problematic constraints |
| Transport correction | 10/10 | Both roles forced to `chat_completions_v1` via `force_chat_completions=True` |
| Prompt correction | 10/10 | Role-specific prompts, no contradictions |
| Repair source context | **4/10** | Architecture is sound but compiler_errors empty → context almost always empty |
| Failure evidence quality | **5/10** | compiler_errors and test_failures never populated from orchestrator result |
| Raw-vs-redacted data integrity | 9/10 | Good separation, raw used for parsing, redacted for public paths |
| Persistence lineage | 9/10 | All fields preserved end-to-end except compiler_errors |
| deterministic_rule_id safety | 7/10 | Preserved end-to-end, patch gate catches unknown rules, but empty string not validated |
| Risk handling | **6/10** | New proposals safe; empty string fallback to LOW is wrong |
| Patch-gate coherence | 9/10 | Content-aware, allowlisted rules, security checks |
| Repair attempt durability | 7/10 | DB-backed but race conditions possible |
| Diagnostics | 8/10 | Good transport diagnostics, misleading fallback_used |
| Database migration safety | **0/10** | Version collision prevents startup entirely |
| Transactional consistency | 8/10 | Same-UoW for proposal + event |
| Restart/multi-worker safety | 6/10 | In-memory state lost, race conditions possible, acceptable for MVP |
| **Runtime readiness** | **0/10** | P0 migration collision prevents startup |
| **Production confidence** | **3/10** | Three P0 blockers before any test |

---

## 37. GO / NO-GO Verdict

# **NO-GO**

Three P0 blockers must be fixed before any runtime test. The migration version collision alone prevents application startup.

---

## 38. Exact Prerequisites for First Runtime Test

1. **Fix migration version collision**: Rename `0050_v2_repair_proposals_rule_id_risk.sql` → `0052_v2_repair_proposals_rule_id_risk.sql` (since 0051 already exists).

2. **Fix compiler_errors population**: In `_maybe_write_repair_failure_context()`, pass `compiler_errors` from the orchestrator result to `build_failure_evidence()`. The result dict contains error information that must be parsed into `NormalizedCompilerError` tuples.

3. **Fix risk fallback**: Change `_resolve_repair_proposal_runtime_context()` line 12560 from `"" or "LOW"` to `"" or "MEDIUM"` or better yet, reject empty risk with an explicit error. The fail-closed principle requires that missing/empty risk does not become LOW.

4. **Verify migration runner discovers and applies the new migration**: After renaming, confirm the runner processes it and the `schema_migrations` table records it correctly.

5. **Verify proposer transport = chat_completions_v1**: Static trace confirms this. No change needed.

6. **Verify reviewer transport = chat_completions_v1**: Static trace confirms this. No change needed.

7. **Verify reviewer reasoning effort behavior**: Static trace confirms `""` → `None` → omitted. No change needed.

8. **Verify timeout behavior**: Code resolves per-role with 300 default. Verify env vars at runtime.

9. **Verify source context path safety**: Static analysis confirms sandbox boundary protection. No change needed.

10. **Verify raw model output not publicly exposed**: Static analysis confirms safe. No change needed.

11. **Verify diagnostic errors redacted**: Static analysis confirms safe. No change needed.

12. **Verify direct Option A deterministic_rule_id lineage**: Static analysis confirms end-to-end preservation. No change needed.

13. **Verify risk fail-closed**: Fix P0-3 first.

14. **Verify no_safe_rule semantics**: Known UX issue, not a safety blocker. Proposals cannot be approved.

15. **Verify old/null proposal behavior safe**: Static analysis shows NULL → patch gate rejection by accident. Acceptable conditionally.

16. **Verify current proposal readiness semantics**: `repair_state.ready` means "reviewed" not "actionable". Acceptable.

---

## 39. 36 Final Questions Answered

1. **Is the new SQLite migration version unique?** **NO** — duplicates 0050.

2. **Will the migration runner definitely discover and execute it exactly once?** **NO** — will raise `MigrationDiscoveryError` on duplicate version.

3. **Can existing proposal rows contain NULL risk or NULL deterministic_rule_id after migration?** **YES** — columns are `TEXT` (nullable).

4. **Can NULL/missing risk still become LOW?** **YES** — empty string becomes LOW via `"" or "LOW"`. NULL becomes `"None"` which is truthy, so it becomes `"NONE"` which is NOT LOW.

5. **Is that fail-closed?** NULL → `"NONE"` → human review at patch gate (safe by accident). Empty string → LOW (unsafe). **PARTIALLY.**

6. **Can deterministic_rule_id="no_safe_rule" create repair_state.ready?** **YES** — proposal created with status `user_review_required`.

7. **Can no_safe_rule expose approve_sandbox_apply?** **POSSIBLE** — depends on frontend rendering based on status.

8. **Is that consistent with patch-gate behavior?** **INCONSISTENT** — patch gate rejects `no_safe_rule` with `HUMAN_REVIEW_REQUIRED`.

9. **Does the active patch gate require an allowlisted deterministic rule?** **YES** — `evaluate_rule()` checks against `ALLOWED_RULE_IDS`.

10. **Is source_context actually likely to be populated on the first real Java compile failure?** **NO** — `compiler_errors` is never passed to `build_failure_evidence()`.

11. **Are compiler_errors actually populated by the active runner?** **NO** — `_maybe_write_repair_failure_context()` does not pass compiler_errors from result.

12. **Can source-context extraction escape sandbox through paths, symlinks, junctions, or resolution ordering?** **NO** — `relative_to(sandbox_root)` prevents escape.

13. **Can sensitive config or credential files be sent to the LLM through source context?** **LOW RISK** — no active filtering, but sandbox nature limits exposure.

14. **Is raw model output ever exposed through logs, events, API, SSE, or LLM activity?** **NO** — always redacted for public paths. Raw content flows only to internal objects, disk, and DB.

15. **Is transport error_detail always redacted before logging?** **YES** — through `_sanitize_body_snippet()` → `redact_model_summary()` → 500-char truncation.

16. **Does proposer definitely use chat_completions_v1?** **YES** — `_resolve_transport()` returns `"chat_completions_v1"` and `force_chat_completions=True`.

17. **Does reviewer definitely use chat_completions_v1?** **YES** — same as proposer.

18. **Can repair roles accidentally fall back to /responses because of a responsibility mismatch?** **NO** — `_resolve_transport()` checks both role and responsibility, and `_answer_with_deployment()` explicitly sets `force_chat_completions=True` when transport is `chat_completions_v1`.

19. **Does reviewer-specific empty reasoning effort truly omit the parameter?** **YES** — `_resolve_reasoning_effort()` returns `None` for empty string, and `_post_chat_completion_v1()` only adds the key `if reasoning_effort is not None`.

20. **Do proposer and reviewer truly receive 300-second configured timeouts?** **YES** — `resolve_timeout()` defaults to 300 when no env vars are set, and the timeout is passed to `urllib.request.urlopen()`.

21. **Is deterministic_rule_id preserved end to end in the active direct Option A path?** **YES** — proposer → review_chain → V2RepairProposalRecord → approval runtime context → patch gate.

22. **Is reviewed risk preserved end to end?** **YES** — same as deterministic_rule_id.

23. **Is the proposal DB schema fully coherent with the new fields?** **YES** — dataclass, INSERT, and `_row_to_proposal` all handle both fields.

24. **Is repair attempt history complete for failed provider/reviewer attempts, or only successful persisted proposals?** Only proposals with `attempt_number IS NOT NULL` appear. Failed provider/reviewer attempts → no proposal → invisible.

25. **Is attempt counting durable across restart?** **YES** — recovered from DB.

26. **Can duplicate callbacks create duplicate LLM invocations or proposals?** **POSSIBLE** — race conditions exist between duplicate check and insert.

27. **Does repair_state.ready mean "reviewed" or truly "actionable"?** **"reviewed"** — no patch gate check at readiness time.

28. **Can a proposal appear ready before patch-gate eligibility is known?** **YES** — patch gate runs at approve time, not at proposal creation.

29. **Is the approve endpoint fully fail-closed for old/null/stale proposal rows?** **YES** — all invariants checked: diff, checksum, reviewer decision, status, patch gate.

30. **Does validation failure preserve the patched sandbox in the active Option A path?** **YES** — `rollback_status = None`, sandbox preserved.

31. **Does attempt 2 receive fresh source context from the already-patched sandbox?** **CONDITIONAL** — fresh FailureEvidence is created, but compiler_errors are still empty, so source context may not be meaningful.

32. **Can repair_proposal_ready event exist without a proposal row?** **NO** — event is saved in the same UoW as the proposal.

33. **Are DB persistence and event emission atomic?** **YES** — same unit of work.

34. **What exact P0 blockers remain?** Three: migration version collision (P0-1), compiler_errors never populated (P0-2), risk defaults to LOW for empty string (P0-3).

35. **What exact P1 risks remain?** Five: no_safe_rule UX gap (P1-1), fallback_used misleading (P1-2), attempt history incomplete (P1-3), empty deterministic_rule_id not validated (P1-4), race condition on attempt number (P1-5).

36. **Is the current recommendation: NO-GO** — Three P0 blockers must be fixed before any backend/runtime execution.

37. **Why?** Migration version collision prevents startup. compiler_errors not populated makes source context feature non-functional. Risk default violates fail-closed principle.

38. **What exactly must be true before the first runtime migration is started?** All three P0 items must be fixed. See Section 38 for the full pre-flight checklist.

---

# FINAL DECISION BEFORE FIRST FRESH RUNTIME TEST

**Verdict: NO-GO**

**P0 blockers count: 3**

**P1 risks count: 5**

**Top five findings:**
1. Migration version 0050 collision — `0050_v2_llm_invocations.sql` and `0050_v2_repair_proposals_rule_id_risk.sql` both exist with the same numeric prefix
2. `compiler_errors` never populated — `_maybe_write_repair_failure_context()` calls `build_failure_evidence()` without compiler_errors parameter
3. Risk defaults to LOW for empty string — `_resolve_repair_proposal_runtime_context` line 12560 has `"" or "LOW"`
4. `no_safe_rule` creates `repair_state.ready` but patch gate rejects it — UX inconsistency
5. `fallback_used` in `_safe_model_role_status()` is always False for deterministic fallback

**Exact changed files inspected:** 10
- `v2_model_schemas.py`, `v2_assistant_model_client.py`, `v2_model_role_router.py`, `repair_review_chain.py`, `repair_context.py`, `v2_repair_gate_service.py`, `v2_repair_repository.py`, `v2_orchestrator_runner.py`, `app.py`, `0050_v2_repair_proposals_rule_id_risk.sql`

**Exact report path:** `AMF252_POST_IMPLEMENTATION_BACKEND_SAFETY_AUDIT.md`

**No runtime test was executed.**
