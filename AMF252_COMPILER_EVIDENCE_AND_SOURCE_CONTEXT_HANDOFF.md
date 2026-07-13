
# AMF-252 — Compiler Evidence & Source Context Handoff

## 1. Executive Verdict

**Two independent bugs block Java source code from reaching GPT-5 mini:**

| Bug | Phase | Root File | Effect |
|-----|-------|-----------|--------|
| **A: Redaction before parsing** | Build output processing | `v2_orchestrator_runner.py:559-560` | `redact_absolute_paths()` destroys `.java` paths before `_normalize_compiler_errors()` regex can extract them → `compiler_errors = ()` |
| **B: Absolute path resolution on Windows** | Source context building | `repair_context.py:53-64` | `Path(sandbox_root) / absolute_path` silently discards sandbox_root → `relative_to()` raises ValueError → every file skipped → `source_contexts = ()` |

Both must be fixed. Fix A alone produces valid `NormalizedCompilerError` objects but they still can't load source files. Fix B alone never receives valid compiler errors because redaction already destroyed the paths.

---

## 2. Exact Runtime Evidence

| Evidence | Value |
|----------|-------|
| `compiler_errors` in `repair_failure_evidence.json` | `[]` (empty) |
| `changed_files` in `repair_failure_evidence.json` | `[]` (empty) |
| `source_contexts` in `repair_context_pack.json` | **Key absent entirely** |
| GPT-5 mini received | `no_safe_rule`, confidence 0.35, reason: "insufficient source context" |
| Raw javac line before redaction | `[ERROR] C:\Users\...\Foo.java:[42,17] incompatible types: String cannot be converted to int` |
| Same line after redaction | `[ERROR] [redacted-windows-path]:[42,17] incompatible types: String cannot be converted to int` |
| Regex match result | FAIL — `_RE_JAVAC_ERROR` requires `.java` in path, redaction produces `[redacted-windows-path]` with no `.java` |

---

## 3. Subagent A Findings

See: `SUBAGENT_A_COMPILER_EVIDENCE_TRACE.md` (full trace)

**8 critical findings:**

1. **Raw output first available:** `migration_factory/agents/build_agent/runner.py:36-37` — `ProcessRunResult.stdout` / `stderr` (full `list[str]`, unredacted)
2. **In orchestrator runner:** `v2_orchestrator_runner.py:426` — `self._last_stdout_lines` (raw), `:435` — raw stderr joined string
3. **Truncation:** `migration_factory/contracts/build/schemas.py:118-119` — `[-40:]` slices; full list lost after contract construction
4. **Redaction:** `v2_orchestrator_runner.py:2997-3001` — `_bounded()` calls `redact_model_summary()` → `redact_absolute_paths()` at `redaction.py:127-137`
5. **Redaction ordering:** `_bounded()` called at lines 559-560; `_normalize_compiler_errors()` called at line 1252-1256 (after redaction)
6. **Regex failure:** `_RE_JAVAC_ERROR` at line 2596 requires `.java` extension; redacted text has no `.java` → no match → empty tuple
7. **Raw log still available:** Full output in `phase2_transform.log` on disk; `BuildErrorContract` JSON files with 40 unredacted tail lines
8. **No structured build error contract:** `BuildErrorContract` has no `file`/`line`/`column` fields; only `NormalizedCompilerError` (ephemeral, after redaction)

---

## 4. Subagent B Findings

See: `SUBAGENT_B_SOURCE_CONTEXT_TRACE.md` (full trace)

**8 critical findings:**

1. **sandbox_root:** Result of `_result_sandbox_path()` at `v2_orchestrator_runner.py:2559` — typically `<run_dir>/workspaces/sandbox`
2. **Path resolution bug:** `_normalize_and_check_path()` at `repair_context.py:57` — `Path(sandbox_root) / absolute_path` on Windows: absolute right operand replaces left operand, then `relative_to()` throws `ValueError`
3. **Every file skipped silently:** `_normalize_and_check_path` returns `None` for every absolute Maven path → `source_contexts = ()`
4. **Empty guard:** `build_bounded_source_context()` is skipped entirely when both `compiler_error_locations` and `changed_files` are empty (line 1279)
5. **Serialization omits empty key:** `context_pack_to_dict()` at line 352: `if pack.source_contexts:` → False → no `"source_contexts"` key in JSON
6. **Deserialization handles missing key:** `_context_pack_from_dict()` handles missing key correctly (returns empty tuple)
7. **Checksum is incomplete:** `compute_context_pack_checksum()` includes `source_contexts` metadata but **NOT** `content` — secondary bug
8. **Prompt delivery:** `_primary_repair_prompt()` at `repair_review_chain.py:89-90` — empty `source_section` when source_contexts empty; no Java code in prompt

---

## 5. Full End-to-End Current Flow

```
Maven subprocess (Popen with PIPE)
  │  stdout, stderr: list[str] (RAW)
  ▼
runner.py:67-77  — _enqueue_lines() captures RAW
  │
  ▼
ProcessRunResult.stdout / stderr (list[str], FULL, RAW)
  │
  ├──→ agent.py:220 build_error_contract()
  │     └→ schemas.py:118-119  stdout_tail[-40:]  (TRUNCATED, NOT REDACTED)
  │       └→ build-error-*.json  (40 lines, raw)
  │
  └──→ v2_orchestrator_runner.py:426 self._last_stdout_lines (RAW)
        └→ :559  _bounded("\n".join(self._last_stdout_lines))
             └→ :2998  redact_model_summary()
                  └→ :172  redact_absolute_paths()  ★ REDACTION ★
                       └→ replaces C:\...\Foo.java → [redacted-windows-path]
             └→ :3001  redacted[:_MAX_TEXT]  (truncated to 4096 chars)
        │
        ▼
        :1252  _normalize_compiler_errors(stdout_tail=REDACTED, stderr_tail=REDACTED)
          │  regex _RE_JAVAC_ERROR requires ".java" → NO MATCH
          ▼
        () ← empty compiler_errors tuple
          │
          ▼
        :1278 FailureEvidence(compiler_errors=())
          │
          ▼
        :1279 if sandbox_root and (compiler_error_locations or changed_files):
          │  BOTH EMPTY → guard fails → build_bounded_source_context() SKIPPED
          ▼
        :1409 source_contexts = ()
          │
          ▼
        :1411 RepairContextPack(source_contexts=())
          │
          ▼
        :1412 context_pack_to_dict() → line 352:
          │  if pack.source_contexts: → FALSE → key OMITTED
          ▼
        repair_context_pack.json  (NO "source_contexts" key)
          │
          ▼
        v2_repair_gate_service.py  _context_pack_from_dict()
          │  data.get("source_contexts") → None → ()
          ▼
        repair_review_chain.py:89  _primary_repair_prompt()
          │  source_contexts = [] → source_section = ""
          ▼
        GPT-5 mini receives:  (no source code, no file paths, no line numbers)
          → proposer returns no_safe_rule, confidence 0.35
          → reason: insufficient source context
          → no proposal created
          → repair_state = blocked
```

---

## 6. Exact Point Where Raw Compiler Location Is Lost

**First loss (Bug A):** `v2_orchestrator_runner.py:559-560` — `_bounded()` → `redact_absolute_paths()` replaces the full path (including `.java` filename and line/column suffix) with `[redacted-windows-path]` or `[redacted-path]`.

**Second loss (Bug B):** `repair_context.py:57` — `Path(sandbox_root) / absolute_path` silently discards sandbox_root on Windows; `relative_to()` raises ValueError at line 59; function returns `None`.

---

## 7. Exact Redaction Ordering

```
Line 559: stdout_tail = _bounded(value)           ← REDACTED FIRST
Line 560: stderr_tail = _bounded(value)           ← REDACTED FIRST
  ...
Line 1252: _normalize_compiler_errors(             ← PARSES AFTER REDACTION
    stdout_tail=stdout_tail,    # already [redacted-*]
    stderr_tail=stderr_tail,    # already [redacted-*]
  )
```

---

## 8. Exact Sandbox Root Currently Used

```
Source: result dict key "sandbox_path"
Resolver: v2_orchestrator_runner.py:2559  _result_sandbox_path()
Fallback chain: sandbox_path → modernized_app_path → output_app_path
               → artifact_refs.sandbox → artifact_refs.modernized_app
Actual runtime value: C:\Users\abdelilah.mortaki\.migration\runs\<run_id>\workspaces\sandbox
```

---

## 9. Exact Source-Context Serialization Path

```
1. build_bounded_source_context()  → tuple[RepairSourceContext]
2. RepairContextPack(source_contexts=...)
3. context_pack_to_dict():
     if pack.source_contexts:           ← line 352
         result["source_contexts"] = [...]  ← OMITTED if empty
4. JSON → repair_context_pack.json
5. _context_pack_from_dict():
     raw_contexts = data.get("source_contexts") or ()   ← line 1750
6. RepairContextPack(source_contexts=tuple(source_contexts))
7. _primary_repair_prompt():
     source_contexts = context_dict.get("source_contexts") or []  ← line 89
     source_section = "" if not source_contexts                   ← line 90-91
8. Proposer prompt has NO source code
```

---

## 10. Why GPT-5 Mini Got No Source Code

Three sequential failures:

| Step | What failed | Why |
|------|-------------|-----|
| 1 | `_normalize_compiler_errors()` returned `()` | Redaction corrupted paths before regex could parse them (Bug A) |
| 2 | `build_bounded_source_context()` was never called | Guard at line 1279: `compiler_error_locations` AND `changed_files` both empty |
| 3 | Even if called, path resolution would fail | Absolute path handling broken on Windows (Bug B) |

Result: `RepairContextPack.source_contexts = ()` → serialization omitted key from JSON → deserialization reads empty → `source_section = ""` → no Java code in GPT-5 mini prompt.

---

## 11. Whether Parser-Only Fix Is Sufficient

**NO.**

Fixing only the parser (Bug A) produces valid `NormalizedCompilerError` objects with correct `file_path`, `line`, `column`. But then Bug B blocks every single file from being read — `_normalize_and_check_path()` returns `None` for every absolute path because `Path(sandbox_root) / absolute_path` on Windows silently replaces sandbox_root.

Both bugs must be fixed.

---

## 12. Whether Sandbox-Root Fix Is Also Required

**YES.**

Bug B is independently fatal. Even if compiler errors were parsed correctly (e.g., if the regex somehow worked on redacted text), every `file_path` is an absolute Windows path (e.g., `C:\Users\...\Foo.java`). The `sandbox_root / file_path` operation on Windows yields just `file_path` (absolute right operand replaces left), then `resolved.relative_to(sandbox_root)` throws `ValueError`. Every file returns `None`.

---

## 13. Exact Files/Symbols That Need Modification Later

### Fix A: Parse before redaction

| File | Symbol | Line | Change |
|------|--------|------|--------|
| `v2_orchestrator_runner.py` | `_handle_exit()` | ~558 | Insert compiler diagnostic parsing BEFORE `_bounded()` calls using raw `self._last_stdout_lines` and raw stderr |
| `v2_orchestrator_runner.py` | `_normalize_compiler_errors()` | 2616 | No change needed (regex is correct, input was the problem) |
| `v2_orchestrator_runner.py` | `_maybe_write_repair_failure_context()` | 1210 | Accept pre-parsed `NormalizedCompilerError` tuple instead of computing from redacted tails |
| `v2_orchestrator_runner.py` | `_bounded()` | 2997 | No change needed |
| `redaction.py` | `redact_absolute_paths()` | 127 | No change needed |

### Fix B: Handle absolute paths in source context

| File | Symbol | Line | Change |
|------|--------|------|--------|
| `repair_context.py` | `_normalize_and_check_path()` | 53-64 | Add fallback: if `relative_to()` fails, try `os.path.relpath()` to extract sandbox-relative portion |

---

## 14. Files That Must NOT Be Changed

| File | Reason |
|------|--------|
| `redaction.py` | Redaction is correct for its intended privacy purpose; the bug is ordering, not the redactor |
| `migration_factory/agents/build_agent/runner.py` | Raw capture is correct and complete |
| `migration_factory/contracts/build/schemas.py` | Contract schema is fine; `BuildErrorContract` is unrelated to FailureEvidence |
| `migration_factory/repair_loop/evidence_collector.py` | Old path, not used by current repair flow |
| `migration_factory/copilot_repair/request_builder.py` | Not involved in this flow |
| `migration_factory/copilot_repair/adapter.py` | Not involved in this flow |
| `migration_factory/repair_loop/repair_context.py` lines 75-133: `build_bounded_source_context()` | Logic is correct; the fix is in `_normalize_and_check_path()` which it calls |

---

## 15. Smallest Safe Implementation Plan

### Step 1: Fix A — Parse before redaction

**File:** `v2_orchestrator_runner.py`

In `_handle_exit()` (line 544), between the raw data availability (~line 558) and `_bounded()` calls (~line 559-560):

1. Extract raw stdout string from `self._last_stdout_lines` (already stored at line 426)
2. Raw stderr is the `stderr` parameter of `_handle_exit` (available at line 552)
3. Call `_normalize_compiler_errors()` on **raw** text, store result
4. Pass pre-parsed `NormalizedCompilerError` tuple into `_maybe_write_repair_failure_context()` alongside the redacted tails
5. Update `_maybe_write_repair_failure_context()` to accept the pre-parsed errors instead of recomputing from redacted text

### Step 2: Fix B — Handle absolute paths in source context

**File:** `repair_context.py` in `_normalize_and_check_path()` (line 53-64)

After `resolved = (sandbox_root / file_path).resolve()`, if `relative_to()` raises `ValueError`:

- Try `os.path.relpath(file_path, str(sandbox_root))` to compute a sandbox-relative path
- If the relative path doesn't start with `..`, join with sandbox_root and re-check
- OR: If `file_path` starts with `str(sandbox_root)`, strip the prefix

### Step 3 (Optional): Include content in checksum

**File:** `repair_context.py` in `compute_context_pack_checksum()` (line 182-191)

Add `"content": sc.content` to the checksum payload. This is NOT blocking the current bug but prevents silent content drift.

---

# FINAL IMPLEMENTATION DECISION

| # | Question | Answer | Confidence |
|---|----------|--------|------------|
| 1 | Is raw Maven compiler output available before redaction? | **PROVEN** | HIGH CONFIDENCE |
| 2 | Exact function holding it? | `V2OrchestratorRunner._handle_exit()` at line 552 `stderr` param (`"\n".join(stderr_lines)` raw) and `self._last_stdout_lines` at line 426 (raw `list[str]`) | HIGH CONFIDENCE |
| 3 | Exact function destroying path/location? | `redact_absolute_paths()` at `redaction.py:127-137`, called from `_bounded()` at `v2_orchestrator_runner.py:2997-3001` | HIGH CONFIDENCE |
| 4 | Does compiler parsing currently occur before or after redaction? | **AFTER** — `_bounded()` at lines 559-560, `_normalize_compiler_errors()` at line 1252 | HIGH CONFIDENCE |
| 5 | Exact function to move/add parsing into? | `_handle_exit()` in `v2_orchestrator_runner.py`, between line ~558 and line 559 | HIGH CONFIDENCE |
| 6 | Is current regex sufficient on raw Maven output? | **PROVEN** — `_RE_JAVAC_ERROR` at line 2596 correctly matches `[ERROR] C:\...\Foo.java:[42,17] message`; it only fails on redacted `[redacted-windows-path]` | HIGH CONFIDENCE |
| 7 | Is current `sandbox_root` correct? | **PROVEN** — value `<run_dir>/workspaces/sandbox` is correct; the bug is in path resolution, not the root value | HIGH CONFIDENCE |
| 8 | Will valid compiler errors automatically create `source_contexts`? | **POSSIBLE** — only if `_normalize_and_check_path()` is also fixed (Bug B). If both fixes are applied, yes | HIGH CONFIDENCE |
| 9 | Will `source_contexts` survive serialization/deserialization? | **PROVEN** — `context_pack_to_dict()` serializes when non-empty; `_context_pack_from_dict()` restores correctly | HIGH CONFIDENCE |
| 10 | Will actual Java source reach `_primary_repair_prompt`? | **PROVEN** — when `source_contexts` is non-empty, `content` is included in the prompt via `source_section` | HIGH CONFIDENCE |
| 11 | Are both backend fixes needed: (A) parse before redaction, (B) correct sandbox root? | **PROVEN — both are independently required** | HIGH CONFIDENCE |
| 12 | What is the minimum safe fix? | **(A)** Parse compiler diagnostics in `_handle_exit()` before `_bounded()` call, pass pre-parsed errors to `_maybe_write_repair_failure_context()`. **(B)** Add fallback path resolution in `_normalize_and_check_path()` for absolute paths on Windows. | HIGH CONFIDENCE |
