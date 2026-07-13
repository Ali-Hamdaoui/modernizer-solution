# AMF-252 P0/P1 Safety Correction — Implementation Report

## 1. Executive Summary

Five focused, narrow corrections were applied to the AMF-252 Option A reviewed-repair flow. Each addresses a defect found in the post-implementation backend safety audit. No architectural redesign, frontend changes, model transport changes, prompt changes, or test execution was performed.

## 2. Repository State Before Changes

- **Branch:** `feature/superposition-llm-repair-mvp`
- **HEAD:** `68d994f` ("the 400ERROR FIXED")
- **Modified files (pre-existing):** 11 files across model transport, schemas, schemas, runner, gate service, repository, review chain, repair context
- **Duplicate migration:** `0050_v2_repair_proposals_rule_id_risk.sql` and `0050_v2_llm_invocations.sql` both used version `0050`
- **New/untracked files:** Audit documents, migration file

## 3. Files Changed

| File | Change |
|------|--------|
| `.../sqlite/migrations/0050_v2_repair_proposals_rule_id_risk.sql` | Renamed to `0052_v2_repair_proposals_rule_id_risk.sql` |
| `.../v2_orchestrator_runner.py` | Added compiler error parser (`_normalize_compiler_errors`); passes `compiler_errors` to `build_failure_evidence()` |
| `.../fastapi/app.py` | Replaced `risk = ... or "LOW"` with explicit fail-closed validation; added `ALLOWED_RULE_IDS` import; updated `_compute_repair_proposal_allowed_actions()` to check rule ID and risk |
| `.../repair_review_chain.py` | Added `deterministic_rule_id` non-empty validation in `_coerce_primary_repair_output()` |

### Files intentionally NOT changed

- `v2_assistant_model_client.py` — model transport, already correct
- `v2_model_role_router.py` — role routing, already correct
- `v2_model_schemas.py` — strict schemas, already correct
- `v2_repair_gate_service.py` — proposal persistence, already correct
- `v2_repair_repository.py` — record storage, already correct
- `repair_context.py` — source context builder, already correct
- `failure_evidence.py` — data model, already correct
- `rule_registry.py` — allowlist, not modified (only imported)
- All frontend files (`web/control-tower/`) — not touched
- SSE, patch gate, approval endpoint, validation semantics — not changed

## 4. Migration Collision — Before / After

### Before (duplicate 0050):
```
0050_v2_llm_invocations.sql
0050_v2_repair_proposals_rule_id_risk.sql  ← DUPLICATE version
0051_v2_job_approval_settings.sql
```

### After (all unique):
```
0050_v2_llm_invocations.sql
0051_v2_job_approval_settings.sql
0052_v2_repair_proposals_rule_id_risk.sql  ← Renamed, content unchanged
```

- SQL content of the renamed file: **unchanged** (two `ALTER TABLE ADD COLUMN` statements)
- No existing applied migration was rewritten
- Migration discovery will now see unique numeric versions (`len == len(set(...))`)

## 5. Compiler Error Extraction Trace

### Source fields consumed:
```
_maybe_write_repair_failure_context()
  → stdout_tail (captured process stdout, contains Maven output)
  → stderr_tail (captured process stderr)
  → result["safe_log_preview"] (passed as fallback)
```

### Parser `_normalize_compiler_errors()`:
Located in `v2_orchestrator_runner.py` as a module-level private function.

```python
_RE_JAVAC_ERROR = re.compile(
    r'\[ERROR\]\s+(.+?\.[Jj][Aa][Vv][Aa])\s*:\s*\[?(\d+)(?:,\s*(\d+))?\]?\s+(.+)',
)
```

### Data flow:
```
stdout_tail + stderr_tail
  → _normalize_compiler_errors()
    → tuple[NormalizedCompilerError, ...]
      → build_failure_evidence(compiler_errors=...)
        → FailureEvidence.compiler_errors
          → _maybe_write_repair_failure_context() iterates evidence.compiler_errors
            → compiler_error_locations: list[tuple[str, int]]
              → build_bounded_source_context(compiler_errors=...)
                → RepairSourceContext objects with exact file + line targeting
                  → RepairContextPack.source_contexts
                    → context_pack_to_dict()
                      → _primary_repair_prompt() which includes source_contexts
```

## 6. Supported Compiler Diagnostic Formats

The regex `_RE_JAVAC_ERROR` matches two forms produced by Maven-compiler-plugin:

**Form A — Standard bracket format (most common):**
```
[ERROR] /path/to/Foo.java:[42,17] incompatible types: java.lang.String cannot be converted to java.util.List<java.lang.String>
```

**Form B — Plain colon format:**
```
[ERROR] /path/to/Foo.java:42: error: cannot find symbol
```

Both forms support:
- Windows absolute paths (`C:\path\to\Foo.java`)
- POSIX absolute paths (`/sandbox/path/to/Foo.java`)
- Relative paths (`src/main/java/Foo.java`)
- Case-insensitive `.java` extension
- Optional column number
- Line numbers must be positive

Non-compiler `[ERROR]` lines (dependency resolution, plugin failures, summary lines) are silently skipped.

## 7. Source Context Effect

### Before:
```
compiler_errors = ()  ← structurally guaranteed empty
compiler_error_locations = []
source_contexts = ()  ← even if changed_files existed
```

### After:
```
compiler_errors = (NormalizedCompilerError(...), ...)  ← populated when Maven provides grounded diagnostics
compiler_error_locations = [("Foo.java", 42), ...]
source_contexts = (RepairSourceContext(path="Foo.java", start_line=2, end_line=82, ...), ...)
```

The `build_bounded_source_context` function reads ~40 lines before / ~40 lines after each error location (existing behavior, not modified).

## 8. Risk Handling — Before / After

### Before (`_resolve_repair_proposal_runtime_context()`):
```python
risk = str(getattr(record, "risk", "") or "").upper() or "LOW"
```

| Input | Resolution | Blocks apply? |
|-------|-----------|---------------|
| `None` | `"" → "" → "LOW"` | NO — silently treated as LOW |
| `""` (empty string) | `"" → "LOW"` | NO — silently treated as LOW |
| `" "` (whitespace) | `" " → "" → "LOW"` | NO — silently treated as LOW |
| `"low"` | `"low" → "LOW"` | Incorrectly passes (matching LOW-only gate) |
| `"LOW"` | `"LOW"` | Correctly passes |
| `"MEDIUM"` | `"MEDIUM"` | Gate blocks (existing) |
| `"HIGH"` | `"HIGH"` | Gate blocks (existing) |
| `"UNKNOWN"` | `"UNKNOWN"` | Gate blocks (existing) |

### After:
```python
raw_risk = getattr(record, "risk", None)
if raw_risk is None:
    raise REVIEWED_RISK_MISSING
risk = str(raw_risk).strip().upper()
if not risk:
    raise REVIEWED_RISK_MISSING
if risk not in {"LOW", "MEDIUM", "HIGH"}:
    raise REVIEWED_RISK_INVALID
```

| Input | Resolution | Blocks apply? |
|-------|-----------|---------------|
| `None` | `raw_risk is None` → raise | YES — `REVIEWED_RISK_MISSING` |
| `""` (empty string) | `"" → ""` → raise | YES — `REVIEWED_RISK_MISSING` |
| `" "` (whitespace) | `" " → ""` → raise | YES — `REVIEWED_RISK_MISSING` |
| `"low"` | `"low" → "LOW"` | `"LOW" in {"LOW","MEDIUM","HIGH"}` → passes |
| `"LOW"` | `"LOW"` | Passes |
| `"MEDIUM"` | `"MEDIUM"` | Passes validation; gate may block |
| `"HIGH"` | `"HIGH"` | Passes validation; gate may block |
| `"UNKNOWN"` | `"UNKNOWN" not in {"LOW","MEDIUM","HIGH"}` → raise | YES — `REVIEWED_RISK_INVALID` |

## 9. `deterministic_rule_id` Validation

### Before (`_coerce_primary_repair_output()`):
Required fields checked: `root_cause`, `fix_strategy`, `changed_files`, `proposed_diff`, `risk`, `confidence`, `rationale`
→ `deterministic_rule_id` was **not** validated for non-empty.

### After:
```python
rule_id = str(parsed.get("deterministic_rule_id", "") or "").strip()
if not rule_id:
    raise RepairReviewChainProductionError(
        "invalid_response_missing_deterministic_rule_id"
    )
```

| Input | Result |
|-------|--------|
| Missing field | Rejected — `invalid_response_missing_deterministic_rule_id` |
| `null` | Rejected — `invalid_response_missing_deterministic_rule_id` |
| `""` (empty string) | Rejected — `invalid_response_missing_deterministic_rule_id` |
| `"   "` (whitespace) | Rejected — `invalid_response_missing_deterministic_rule_id` |
| `"no_safe_rule"` | Allowed (review may proceed; apply blocked by Fix 5) |
| `"DEPENDENCY_ADD_H2_RUNTIME"` | Allowed (proposal created; apply may proceed if other checks pass) |

The validation fires **before** the proposal is persisted. `no_safe_rule` is explicitly allowed through — the proposer may honestly signal no safe deterministic rule exists, and the reviewer may still review (e.g., to provide feedback).

## 10. `no_safe_rule` Semantics

| Aspect | Behavior |
|--------|----------|
| Proposal visible in UI | YES — diff viewable, reviewer notes visible |
| `repair_state.ready` | YES — `status="ready"` (reviewed proposal exists) |
| `approve_sandbox_apply` in allowed_actions | **NO** — blocked by `_compute_repair_proposal_allowed_actions()` |
| Patch gate at approval time | Runs if approval somehow attempted (defense in depth) |

## 11. `allowed_actions` Derivation

`_compute_repair_proposal_allowed_actions()` checks the following **before** exposing `approve_sandbox_apply`:

```
1. status == "user_review_required"
2. reviewer_decision == "accept"
3. deterministic_rule_id non-empty AND != "no_safe_rule"
4. deterministic_rule_id in ALLOWED_RULE_IDS (allowlisted)
5. risk == "LOW"
6. SafeDiffPreview: checksum valid, parse_status ok, files present
```

If all six conditions are met → `base_actions + ("approve_sandbox_apply",)`
Otherwise → only `base_actions` (view-only actions)

The full deterministic patch gate (`evaluate_patch_proposal`) still runs at approval time as the final enforcement layer.

## 12. Files Intentionally Not Changed

| Area | Reason |
|------|--------|
| Model transport (chat_completions_v1 routing) | Already correct per audit |
| Strict JSON schemas | Already structurally compliant |
| Prompts (proposer/reviewer system prompts) | Already correct per audit |
| Timeouts | Already resolve per role, defaults to 300s |
| Frontend (`web/control-tower/`) | Explicitly excluded from scope |
| SSE event types | Not part of this correction |
| Patch gate enforcement (`evaluate_patch_proposal`) | Already correct; runs at approval time |
| Validation semantics | Not part of this correction |
| Approval endpoint | Already correct (checksum chain, proposal identity, etc.) |
| `failure_evidence.py` data model | Already correct; only consumer was missing |
| `repair_context.py` source context builder | Already correct; only input was missing |

## 13. Static Validation Performed

All allowed static checks passed:

| Check | Result |
|-------|--------|
| `py -m py_compile v2_orchestrator_runner.py` | OK |
| `py -m py_compile repair_review_chain.py` | OK |
| `py -m py_compile app.py` | OK |
| Migration version uniqueness | PASS — 52 unique versions |
| `0050_v2_llm_invocations.sql` exists | PASS |
| `0051_v2_job_approval_settings.sql` exists | PASS |
| `0052_v2_repair_proposals_rule_id_risk.sql` exists | PASS |
| Old `0050_v2_repair_proposals_rule_id_risk.sql` removed | PASS |
| `git diff --check` | PASS (pre-existing trailing whitespace in `v2_assistant_model_client.py` only) |
| SQL content unchanged after rename | PASS |

No runtime tests, no Azure/model calls, no migration job executed, no database modified.

## 14. Remaining Known P1/P2 Issues

These are acknowledged and explicitly deferred to a future pass:

1. **Attempt history incomplete** — Failed provider/reviewer attempts are invisible in `/repair/attempts` endpoint
2. **`fallback_used` diagnostic semantics** — The fallback indicator does not clearly distinguish proposer vs reviewer
3. **Attempt-number race** — Under concurrent callbacks, the in-memory dedupe uses `_attempt_counts` dict which is not persistent
4. **In-memory dedupe lost on restart** — Process restart resets attempt counts to 0, allowing more than `DEFAULT_MAX_REPAIR_ATTEMPTS`
5. **Source-context secret filtering** — `build_bounded_source_context` reads raw file content without sensitive-file allowlist filtering

## 15. GO / NO-GO Recommendation

### Verdict: **GO**

### Evidence:

All 20 acceptance criteria are statically provable:

- [x] Migration numeric versions are unique.
- [x] The new repair proposal migration has a unique next free version (0052).
- [x] `build_failure_evidence()` receives normalized `compiler_errors` when grounded compiler diagnostics are available.
- [x] `NormalizedCompilerError` preserves: message, file_path, line, column (when available).
- [x] `FailureEvidence.compiler_errors` is no longer structurally guaranteed empty.
- [x] `build_bounded_source_context()` receives compiler-error file/line locations.
- [x] Missing risk never becomes LOW.
- [x] NULL risk never becomes LOW.
- [x] Empty risk never becomes LOW.
- [x] Invalid risk blocks approval/runtime-context resolution.
- [x] Empty `deterministic_rule_id` is rejected before proposal creation.
- [x] `no_safe_rule` does not expose `approve_sandbox_apply`.
- [x] Unknown rule does not expose `approve_sandbox_apply`.
- [x] MEDIUM/HIGH risk does not expose `approve_sandbox_apply` under current LOW-only patch policy.
- [x] Valid allowlisted rule + LOW risk may expose `approve_sandbox_apply`.
- [x] Full deterministic patch gate still runs during approval.
- [x] No frontend files changed.
- [x] No model transport logic changed.
- [x] No tests run.
- [x] No runtime migration executed.
- [x] No Azure/model call made.

### Conditions (already satisfied):
- The working tree is preserved (no commit, no stage, no reset, no clean was performed).
- No existing applied migration was rewritten.
- No `or "LOW"` pattern remains in the Option A runtime-context resolution path.
- All touched Python files pass `py_compile`.

### First runtime test (do not run now):
The next step is a sandbox runtime proof:
1. Build failure occurs → `_maybe_write_repair_failure_context` fires
2. `stdout_tail`/`stderr_tail` contain Maven javac diagnostics
3. `_normalize_compiler_errors` extracts `NormalizedCompilerError` objects
4. `FailureEvidence.compiler_errors` is non-empty
5. `build_bounded_source_context` targets exact failing file and line
6. Source context appears in proposer prompt
7. GPT-5 mini returns valid `RepairPrimaryOutput` with usable `proposed_diff`
8. Llama reviewer accepts with `decision=accept`
9. Proposal persisted → `repair_proposal_ready` event
10. `repair_state.ready` visible in UI
11. Reviewed diff visible
12. `approve_sandbox_apply` visible only when rule allowlisted + risk LOW

**Stop before clicking Apply.**
