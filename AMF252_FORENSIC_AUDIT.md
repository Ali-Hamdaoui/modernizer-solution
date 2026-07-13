
# AMF-252 — FORENSIC AUDIT ANALYSIS

## REPOSITORY AUDIT SCOPE

- **Repository:** `C:\Users\abdelilah.mortaki\Desktop\modernizer-solution`
- **Branch:** `feature/superposition-llm-repair-mvp`
- **Audit mode:** Static code extraction only — zero runtime, zero implementation, zero Azure calls
- **Goal:** Determine WHY `repair_failure_evidence.json` had `compiler_errors = []` and `repair_context_pack.json` had zero `source_contexts`, resulting in GPT-5 mini receiving no Java source code

---

## 1. COMPLETE END-TO-END DATA FLOW (annotated with exact file:line)

```
═══ PHASE 1: ORCHESTRATOR SUBPROCESS EXECUTION ═══

v2_orchestrator_runner.py:367-377:
  process = self._popen_factory(
      _normalized_argv(argv),
      stdout=subprocess.PIPE,    ← capture stdout
      stderr=subprocess.PIPE,    ← capture stderr
      text=True,
      encoding="utf-8",
  )

v2_orchestrator_runner.py:358-359:
  stdout_lines: list[str] = []     ← RAW, empty list
  stderr_lines: list[str] = []     ← RAW, empty list

v2_orchestrator_runner.py:395-419:
  out_thread = threading.Thread(target=self._read_stream, args=(process.stdout, stdout_lines), ...)
  err_thread = threading.Thread(target=self._read_stream, args=(process.stderr, stderr_lines), ...)

v2_orchestrator_runner.py:457-493 (_read_stream):
  def _read_stream(self, stream_handle, captured, ...):
      for raw_line in stream_handle:
          line = raw_line.rstrip("\r\n")
          captured.append(line)           ← APPENDS RAW LINE (verbatim Maven/javac output)
          ...

v2_orchestrator_runner.py:421-438:
  exit_code = process.wait()
  out_thread.join(timeout=5)
  err_thread.join(timeout=5)
  self._last_stdout_lines = list(stdout_lines)    ← ★ RAW stdout stored at line 426
  final_json = _extract_final_json("\n".join(stdout_lines))
  self._handle_exit(
      ...
      result=final_json,
      stderr="\n".join(stderr_lines),      ← ★ RAW stderr passed at line 435
      ...
  )

═══ PHASE 2: REDACTION (THE PRIMARY BUG) ═══

v2_orchestrator_runner.py:544-560 (_handle_exit):
  def _handle_exit(self, ..., stderr: str, ...):
      # stderr is RAW at function entry (line 552)

      # ★ LINE 559: REDACTION APPLIED FIRST ★
      stdout_tail = _bounded(                                          ← CALLS _bounded()
          "\n".join(self._last_stdout_lines) if hasattr(self, "_last_stdout_lines") else ""
      )

      # ★ LINE 560: REDACTION APPLIED FIRST ★
      stderr_tail = _bounded(stderr)                                    ← CALLS _bounded()

v2_orchestrator_runner.py:2997-3001 (_bounded):
  def _bounded(value: str) -> str:
      redacted = redact_model_summary(value)   ← ★ REDACTION PIPELINE
      if len(redacted) <= _MAX_TEXT:            # _MAX_TEXT = 4096 (line 55)
          return redacted
      return redacted[:_MAX_TEXT] + "...[truncated]"

redaction.py:165-179 (redact_model_summary):
  def redact_model_summary(summary: str) -> str:
      result = summary
      result = redact_absolute_paths(result)     ← ★ DESTRUCTIVE STEP (line 172)
      result = redact_env_assignments(result)
      ...
      return result

redaction.py:127-137 (redact_absolute_paths):
  def redact_absolute_paths(text: str) -> str:
      if _looks_like_url(text):
          return text
      text = _WINDOWS_ABSOLUTE_PATH_RE.sub("[redacted-windows-path]", text)  ← ★ NUKE
      text = _POSIX_ABSOLUTE_PATH_RE.sub("[redacted-path]", text)            ← ★ NUKE
      text = _HOME_DIR_RE.sub("[redacted-home-path]", text)
      return text

redaction.py:27-29 (_WINDOWS_ABSOLUTE_PATH_RE):
  _WINDOWS_ABSOLUTE_PATH_RE = re.compile(
      r"(?<![A-Za-z]:)(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\/\s:]*[\\/])*[^\\/\s:]*"
  )
  # Matches: C:\Users\...\.migration\runs\R123\workspaces\sandbox\src\main\java\Foo.java
  # Replaces ENTIRE path including ".java" with "[redacted-windows-path]"
  # Does NOT capture :[42,17] — those survive as trailing text

redaction.py:33-35 (_POSIX_ABSOLUTE_PATH_RE):
  _POSIX_ABSOLUTE_PATH_RE = re.compile(
      r"(?<![A-Za-z0-9_:/<])(?<!/)/(?:[^/\s]+/)*[^/\s]+"
  )
  # Matches /home/user/.../Foo.java
  # Replaces ENTIRE path including ".java" with "[redacted-path]"

═══ BEFORE REDACTION (raw Maven stderr) ═══
  [ERROR] C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java:[42,17] incompatible types: String cannot be converted to int

═══ AFTER REDACT_ABSOLUTE_PATHS ═══
  [ERROR] [redacted-windows-path]:[42,17] incompatible types: String cannot be converted to int

═══ PHASE 3: COMPILER ERROR PARSING (receives CORRUPTED input) ═══

v2_orchestrator_runner.py:632-639:
  self._maybe_write_repair_failure_context(
      ...
      stdout_tail=stdout_tail,      ← ALREADY REDACTED + TRUNCATED
      stderr_tail=stderr_tail,      ← ALREADY REDACTED + TRUNCATED
  )

v2_orchestrator_runner.py:1210-1256 (_maybe_write_repair_failure_context):
  compiler_errors = ()
  if failure_source == FailureSource.BUILD:
      compiler_errors = _normalize_compiler_errors(
          stdout_tail=stdout_tail,      ← REDACTED TEXT
          stderr_tail=stderr_tail,      ← REDACTED TEXT
      )

v2_orchestrator_runner.py:2596-2598 (_RE_JAVAC_ERROR regex):
  _RE_JAVAC_ERROR = re.compile(
      r'\[ERROR\]\s+(.+?\.[Jj][Aa][Vv][Aa])\s*:\s*\[?(\d+)(?:,\s*(\d+))?\]?\s+(.+)',
  )
  # Group 1: requires ".java" suffix in the captured path
  # Input: "[ERROR] [redacted-windows-path]:[42,17] incompatible types..."
  # Match: FAIL — "[redacted-windows-path]" contains no ".java" substring
  # Result: line silently skipped

v2_orchestrator_runner.py:2616-2662 (_normalize_compiler_errors):
  combined = f"{stdout_tail}\n{stderr_tail}"     # ← redacted text
  for line in combined.splitlines():
      m = _RE_JAVAC_ERROR.match(line.strip())    # ← NO MATCHES
      if not m:
          continue                               # ← EVERY LINE SKIPPED
  ...
  return ()                                      # ← EMPTY TUPLE

═══ PHASE 4: FAILURE EVIDENCE CONSTRUCTION (empty compiler_errors) ═══

v2_orchestrator_runner.py:1257-1272:
  evidence = build_failure_evidence(
      ...
      compiler_errors=compiler_errors,    ← ()
      stdout_tail=stdout_tail,            ← redacted
      stderr_tail=stderr_tail,            ← redacted
  )

failure_evidence.py:129-208 (build_failure_evidence):
  evidence = FailureEvidence(
      compiler_errors=tuple(compiler_errors or ()),    ← ()
      ...
  )

v2_orchestrator_runner.py:1273-1276:
  compiler_error_locations: list[tuple[str, int]] = []
  for err in evidence.compiler_errors:    ← ITERATES OVER EMPTY
      ...                                 ← NOTHING ADDED

v2_orchestrator_runner.py:1278-1286:
  sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")
  source_contexts: tuple[Any, ...] = ()
  if sandbox_root and (compiler_error_locations or changed_files):
      # ← BOTH EMPTY → GUARD FAILS, build_bounded_source_context() NEVER CALLED
      from migration_factory.repair_loop.repair_context import build_bounded_source_context
      source_contexts = build_bounded_source_context(
          sandbox_root=sandbox_root,
          compiler_errors=compiler_error_locations or None,
          changed_files=changed_files,
      )

═══ PHASE 5: CONTEXT PACK SERIALIZATION (source_contexts omitted from JSON) ═══

v2_orchestrator_runner.py:1288-1311:
  context_pack = build_repair_context_pack(
      failure_evidence=evidence,
      source_contexts=source_contexts,              ← ()
  )
  ...
  context_path.write_text(
      json.dumps(context_pack_to_dict(context_pack), ...) + "\n"
  )

repair_context.py:328-364 (context_pack_to_dict):
  result = {
      "job_id": pack.job_id,
      ...
      # ← NO "source_contexts" KEY IN BASE DICT
  }
  if pack.source_contexts:                            ← FALSE (empty tuple)
      result["source_contexts"] = [...]               ← NOT EXECUTED
  return result                                       ← KEY OMITTED FROM JSON

═══ PHASE 6: DESERIALIZATION + PROMPT CONSTRUCTION ═══

v2_repair_gate_service.py:1744-1785 (_context_pack_from_dict):
  raw_contexts = data.get("source_contexts") or ()    ← None → ()
  source_contexts: list[RepairSourceContext] = []
  for sc in raw_contexts:                             ← NOTHING
      ...
  return RepairContextPack(
      source_contexts=tuple(source_contexts),          ← ()
  )

repair_review_chain.py:87-127 (_primary_repair_prompt):
  context_dict = context_pack_to_dict(context_pack)
  source_contexts = context_dict.get("source_contexts") or []   ← []
  source_section = ""
  if source_contexts:                                             ← FALSE
      parts = []
      ...                                                         ← NOT EXECUTED
      source_section = "\n\nSOURCE CONTEXT:\n" + "\n\n".join(parts)
  ...
  f"{source_section}\n\n"                                        ← EMPTY STRING
  f"Context:\n{json.dumps(context_dict, sort_keys=True)}"         ← NO source_contexts key

═══ PHASE 7: GPT-5 MINI INVOCATION (zero source code) ═══

repair_review_chain.py:533-536:
  primary_result = client.answer_with_role(
      role=V2ModelRole.PROPOSER,
      prompt=_primary_repair_prompt(context_pack, deterministic_checksum),
      # PROMPT CONTAINS NO JAVA SOURCE CODE
      # NO FILE PATHS
      # NO LINE NUMBERS
      # NO SOURCE CONTEXT
      fallback="...",
      ...
  )
```

---

## 2. EXACT ROOT CAUSE ANALYSIS

### PRIMARY BUG (100% reproducible)

| Attribute | Value |
|-----------|-------|
| **Bug** | Redaction applied BEFORE compiler diagnostic parsing |
| **File** | `migration_factory/control_tower/application/v2_orchestrator_runner.py` |
| **Lines** | 559-560 (redaction), then 1252-1256 (parsing) |
| **Redaction function** | `_bounded()` at line 2997 → `redact_model_summary()` at redaction.py:165 → `redact_absolute_paths()` at redaction.py:127 |
| **What is destroyed** | The `.java` filename inside the absolute path. `redact_absolute_paths()` replaces the entire matching path (including `Foo.java`) with `[redacted-windows-path]` or `[redacted-path]` |
| **Regex that fails** | `_RE_JAVAC_ERROR` at line 2596: requires `.+?\.[Jj][Aa][Vv][Aa]` (any characters ending with `.java`). Redacted placeholder has no `.java` → **no match** → line silently skipped |
| **Result** | `_normalize_compiler_errors()` returns empty tuple `()` |
| **Downstream impact** | `compiler_error_locations` empty → guard at line 1279 fails → `build_bounded_source_context()` never called → `source_contexts = ()` → key omitted from JSON → no Java code in GPT-5 prompt |

### SECONDARY BUG (conditional — depends on sandbox_root resolution)

| Attribute | Value |
|-----------|-------|
| **Bug** | Path resolution assumes file_path is sandbox-relative; fails if absolute Maven path doesn't share sandbox_root prefix |
| **File** | `migration_factory/repair_loop/repair_context.py` |
| **Lines** | 53-64 (`_normalize_and_check_path`) |
| **Mechanism** | `resolved = (sandbox_root / file_path).resolve()` — on Windows, if `file_path` is absolute (has drive+root), Python pathlib's `/` operator **discards the left operand** and returns just `file_path`. Then `resolved.relative_to(sandbox_root)` throws `ValueError` if paths don't share exact prefix. |
| **Trigger condition** | ONLY fires when `sandbox_root` is NOT a proper prefix of the absolute `file_path`. If sandbox_root is `.../sandbox` and Maven path is `.../sandbox/src/main/java/Foo.java`, `relative_to` **succeeds** |
| **Risk scenario** | If `sandbox_root` resolves to `modernized_app_path` (a subdirectory) instead of `sandbox_path`, or if Maven uses short 8.3 paths vs long paths, or if path casing differs |
| **Verdict** | Real but less common than Bug A. NOT the primary blocker at runtime — the primary blocker is Bug A preventing any NormalizedCompilerError from being created |

---

## 3. EXACT POINT WHERE COMPILER LOCATION IS DESTROYED

```
FIRST IRRECOVERABLE POINT:  v2_orchestrator_runner.py:559-560
CALL CHAIN:  _bounded() → redact_model_summary() → redact_absolute_paths()
```

**BEFORE:**
```
[ERROR] C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java:[42,17] incompatible types: String cannot be converted to int
```

**AFTER `redact_absolute_paths()`:**
```
[ERROR] [redacted-windows-path]:[42,17] incompatible types: String cannot be converted to int
```

The `.java` extension was part of the matched path: the regex `_WINDOWS_ABSOLUTE_PATH_RE` captures `[A-Za-z]:[\\/](?:[^\\/\s:]*[\\/])*[^\\/\s:]*` — the final `[^\\/\s:]*` matches `Foo.java`. The entire match (drive letter to `.java`) is replaced with `[redacted-windows-path]`.

The regex `_RE_JAVAC_ERROR` at line 2596 requires `.+?\.[Jj][Aa][Vv][Aa]` in the captured text. `[redacted-windows-path]` contains no `.java` → **the javac error line is silently dropped from all analysis**.

---

## 4. REGEX VERIFICATION

### `_WINDOWS_ABSOLUTE_PATH_RE` (redaction.py:27-29)

```
r"(?<![A-Za-z]:)(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\/\s:]*[\\/])*[^\\/\s:]*"
```

| Component | Meaning |
|-----------|---------|
| `(?<![A-Za-z]:)` | Negative lookbehind: not preceded by single letter + colon (avoids matching `http://`) |
| `(?<![A-Za-z])` | Negative lookbehind: not preceded by single letter |
| `[A-Za-z]:` | Drive letter + colon (e.g., `C:`) |
| `[\\/]` | Backslash or forward slash (directory separator) |
| `(?:[^\\/\s:]*[\\/])*` | Zero or more directory segments (non-separator chars ending with separator) |
| `[^\\/\s:]*` | Final filename (no separator, no space, no colon) — **matches `Foo.java`** |

**Match on:** `C:\Users\...\Foo.java` — replaces ENTIRE string with `[redacted-windows-path]`

### `_POSIX_ABSOLUTE_PATH_RE` (redaction.py:33-35)

```
r"(?<![A-Za-z0-9_:/<])(?<!/)/(?:[^/\s]+/)*[^/\s]+"
```

| Component | Meaning |
|-----------|---------|
| `(?<![A-Za-z0-9_:/<])` | Negative lookbehind: not preceded by alphanumeric, underscore, colon, slash, or angle bracket |
| `(?<!/)` | Negative lookbehind: not preceded by slash |
| `/` | Leading slash |
| `(?:[^/\s]+/)*` | Zero or more directory segments |
| `[^/\s]+` | Final filename (no slash, no space) — **matches `Foo.java`** |

**Match on:** `/home/user/.../Foo.java` — replaces ENTIRE string with `[redacted-path]`

### `_RE_JAVAC_ERROR` (v2_orchestrator_runner.py:2596-2598)

```
r'\[ERROR\]\s+(.+?\.[Jj][Aa][Vv][Aa])\s*:\s*\[?(\d+)(?:,\s*(\d+))?\]?\s+(.+)'
```

| Component | Meaning |
|-----------|---------|
| `\[ERROR\]` | Literal `[ERROR]` |
| `\s+` | One or more whitespace |
| `(.+?\.[Jj][Aa][Vv][Aa])` | **Group 1: file_path** — non-greedy any-chars, then `.java` (case-insensitive) |
| `\s*:\s*` | Optional whitespace, colon, optional whitespace |
| `\[?(\d+)` | Optional `[`, then **Group 2: line number** |
| `(?:,\s*(\d+))?` | Optional comma, space, **Group 3: column number** |
| `\]?` | Optional `]` |
| `\s+(.+)` | Space then **Group 4: error message** |

**Match requires:** `.java` (or `.Java`, `.JAVA`, etc.) in Group 1.

**Input after redaction:** `[ERROR] [redacted-windows-path]:[42,17] incompatible types...`

**Result:** Group 1 tries to match `[redacted-windows-path]` — no `.java` found → **NO MATCH**.

---

## 5. NORMALIZED COMPILER ERROR: WHAT WOULD BE CAPTURED (with fix applied)

If `_normalize_compiler_errors()` received RAW text:

```
[ERROR] C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java:[42,17] incompatible types: String cannot be converted to int
```

Then:
- **Group 1 (file_path):** `C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java` ← BACKSLASHES PRESERVED
- **Group 2 (line):** `42`
- **Group 3 (column):** `17`
- **Group 4 (message):** `incompatible types: String cannot be converted to int`

Result: `NormalizedCompilerError(file_path="C:\\Users\\abdelilah\\.migration\\runs\\R123\\workspaces\\sandbox\\src\\main\\java\\com\\example\\Foo.java", line=42, column=17, message="incompatible types: String cannot be converted to int", severity="error")`

---

## 6. SANDBOX ROOT RESOLUTION

```
v2_orchestrator_runner.py:627:
  sandbox_path = _result_sandbox_path(result)

v2_orchestrator_runner.py:629-630:
  if sandbox_path:
      result["sandbox_path"] = sandbox_path

v2_orchestrator_runner.py:1278:
  sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")

v2_orchestrator_runner.py:2559-2593 (_result_sandbox_path):
  Lookup chain:
    1. result["sandbox_path"]          ← primary
    2. result["modernized_app_path"]   ← fallback 1
    3. result["output_app_path"]       ← fallback 2
    4. artifact_refs["sandbox"]        ← fallback 3
    5. artifact_refs["sandbox_path"]   ← fallback 4
    6. artifact_refs["modernized_app"] ← fallback 5
    7. artifact_refs["modernized_app_path"] ← fallback 6
    8. From orchestration_summary.json: same chain
```

**Typical runtime value:** `C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox`

---

## 7. PATH RESOLUTION VERIFICATION (post-fix scenario)

If Bug A is fixed, NormalizedCompilerError provides:
```
file_path = "C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java"
sandbox_root = Path("C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox")
```

Then:
```python
resolved = (sandbox_root / file_path).resolve()
# On Windows: right operand (file_path) is absolute → replaces left → resolved = file_path
# resolved = C:\Users\abdelilah\.migration\runs\R123\workspaces\sandbox\src\main\java\com\example\Foo.java

resolved.relative_to(sandbox_root)
# C:\...\sandbox\src\main\java\com\example\Foo.java relative to C:\...\sandbox
# = src\main\java\com\example\Foo.java → SUCCESS ✓
```

**Verdict:** Path resolution works correctly when sandbox_root is the sandbox directory and file_path is under it. The `relative_to()` call succeeds because the absolute file_path IS under sandbox_root. The `/` operator discards the left operand, but the right operand contains the full absolute path which includes the sandbox_root prefix.

**Edge case risk:** If `sandbox_root` falls through to `modernized_app_path` (a subdirectory like `.../sandbox/modernized-app`) instead of `sandbox_path`, then `relative_to()` would fail because the Java source file is in `.../sandbox/src/main/java/`, not under `.../sandbox/modernized-app/`. This is a real but less common failure mode.

---

## 8. COMPLETE SERIALIZATION AUDIT

| Step | File:Line | Input | Output | Bug? |
|------|-----------|-------|--------|------|
| 1. `_normalize_compiler_errors` | `v2_orch_runner.py:2616` | Redacted stdout_tail+stderr_tail | `()` | YES — wrong input |
| 2. `build_failure_evidence` | `failure_evidence.py:129` | `compiler_errors=()` | `FailureEvidence(compiler_errors=())` | OK but empty |
| 3. `failure_evidence_to_dict` | `failure_evidence.py:211` | Empty errors | `"compiler_errors": []` in JSON | OK |
| 4. Build `compiler_error_locations` | `v2_orch_runner.py:1273` | Empty errors | `[]` | OK but empty |
| 5. Guard check | `v2_orch_runner.py:1279` | Both empty | Skip `build_bounded_source_context` | YES — guard passes due to primary bug |
| 6. `build_repair_context_pack` | `repair_context.py:224` | `source_contexts=()` | `RepairContextPack(source_contexts=())` | OK but empty |
| 7. `context_pack_to_dict` | `repair_context.py:328` | Empty source_contexts | **No `source_contexts` key** | YES — conditional omission |
| 8. JSON write | `v2_orch_runner.py:1308` | Dict without key | `repair_context_pack.json` has no key | YES |
| 9. `_context_pack_from_dict` | `v2_repair_gate_svc.py:1744` | No key | `() via .get("source_contexts") or ()` | OK — handles absence |
| 10. `_primary_repair_prompt` | `repair_review_chain.py:87` | Empty source_contexts | `source_section = ""` | YES — no Java code |
| 11. GPT-5 mini invocation | `repair_review_chain.py:534` | Prompt with empty source_section | Returns no_safe_rule | YES |

---

## 9. CHECKSUM AUDIT

`compute_context_pack_checksum()` at repair_context.py:162-193:

```python
def compute_context_pack_checksum(pack: RepairContextPack) -> str:
    payload: dict[str, Any] = {
        ...
        "source_contexts": [
            {
                "path": sc.path,                ✓
                "content_checksum": sc.content_checksum,  ✓
                "start_line": sc.start_line,     ✓
                "end_line": sc.end_line,         ✓
                "reason_included": sc.reason_included,      ✓
                # NOTE: "content" is NOT included ← SECONDARY BUG
            }
            for sc in pack.source_contexts
        ],
    }
    return sha256_canonical_json(payload)
```

**Checksum deficiency:** `content` (the actual Java source text) is excluded from the checksum payload. Two context packs with identical metadata but different source content would have the same checksum. This allows silent content drift.

---

## 10. PROMPT DELIVERY AUDIT

`_primary_repair_prompt()` at repair_review_chain.py:87-127:

```python
def _primary_repair_prompt(context_pack, deterministic_checksum):
    context_dict = context_pack_to_dict(context_pack)
    source_contexts = context_dict.get("source_contexts") or []   ← []
    source_section = ""
    if source_contexts:                                            ← FALSE
        parts = []
        for sc in source_contexts:
            parts.append(
                f"--- {sc['path']} (lines {sc['start_line']}-{sc['end_line']}, "
                f"reason: {sc['reason_included']}) ---\n"
                f"{sc['content']}\n"
                f"--- end {sc['path']} ---"
            )
        source_section = "\n\nSOURCE CONTEXT:\n" + "\n\n".join(parts)
    return (
        "You are the AMF-252 repair proposer.\n"
        ...
        f"{source_section}\n\n"                      ← EMPTY STRING
        f"Context:\n{json.dumps(context_dict, sort_keys=True)}"   ← NO source_contexts key
    )
```

**When `source_contexts` is non-empty:** The `content` field IS included (line 97: `{sc['content']}`). **If Bug A is fixed and Bug B doesn't trigger, Java source code will reach GPT-5 mini.**

---

## 11. SECONDARY BLOCKER ANALYSIS (after Bug A is fixed)

| Potential blocker | File:Line | Condition | Likelihood |
|-------------------|-----------|-----------|------------|
| sandbox_root fallback to wrong dir | `v2_orch_runner.py:1278` | `sandbox_path` not in result, falls to `modernized_app_path` | MEDIUM — depends on orchestrator output |
| Path format mismatch | `repair_context.py:57` | Forward slashes in Maven path vs backslashes in sandbox_root | LOW — Python normalizes on `.resolve()` |
| Short vs long path (8.3) | `repair_context.py:59` | `relative_to` fails if Maven uses `C:\Users\ABDELI~1\...` | LOW — modern Maven uses long paths |
| Case mismatch | `repair_context.py:59` | Drive letter case differs (C: vs c:) | LOW — `.resolve()` normalizes |
| `MAX_SOURCE_CONTEXT_FILES = 3` | `repair_context.py:37` | More than 3 error files, extra files dropped | **REAL** — first 3 only |
| `MAX_SOURCE_CONTEXT_CHARS = 40000` | `repair_context.py:40` | Total excerpt chars exceed 40K | **REAL** — truncated or files skipped |
| `remaining > 200` guard | `repair_context.py:118-122` | Less than 200 chars remaining in budget | **REAL** — last file skipped |
| Proposer model unavailable | `v2_model_role_router.py:85` | `AZURE_OPENAI_PROPOSER_DEPLOYMENT` not set | **REAL** — deployment config |
| Proposer validation | `repair_review_chain.py:556-613` | JSON parse failure, missing fields | **REAL** — model output quality |
| Reviewer rejects | `repair_review_chain.py:702-705` | `decision != "accept"` | **REAL** — review gate |

**None of these block Bug A's fix value.** They are downstream operational concerns. The critical path from NormalizedCompilerError → source_contexts in prompt IS fully functional once Bug A is fixed (assuming sandbox_root resolves correctly).

---

## 12. ALTERNATE RAW TEXT SOURCES (available for parsing if needed)

| Source | Location | Contents | State |
|--------|----------|----------|-------|
| `self._last_stdout_lines` | `v2_orch_runner.py:426` | Full stdout list[str] | RAW, in-memory |
| `stderr` param of `_handle_exit` | `v2_orch_runner.py:552` | Full stderr joined | RAW, in-memory |
| `ProcessRunResult.stdout` | `runner.py:36` | Full stdout list[str] | RAW, ephemeral |
| `ProcessRunResult.stderr` | `runner.py:37` | Full stderr list[str] | RAW, ephemeral |
| `BuildErrorContract.stdout_tail` | `schemas.py:118` | Last 40 lines | NOT REDACTED, persisted to disk |
| `BuildErrorContract.stderr_tail` | `schemas.py:119` | Last 40 lines | NOT REDACTED, persisted to disk |
| `phase2_transform.log` | `<run_dir>/logs/phase2_transform.log` | Full interleaved output | RAW, persisted to disk |

**Recommended insertion point for parsing:** Use raw `self._last_stdout_lines` and the raw `stderr` parameter inside `_handle_exit()` (line ~558), **BEFORE** the `_bounded()` calls at lines 559-560.

---

## 13. EXACT INSERTION POINT ANALYSIS

### Current order (BROKEN):
```
  v2_orch_runner.py:559  stdout_tail = _bounded(...)     ← REDACT
  v2_orch_runner.py:560  stderr_tail = _bounded(stderr)  ← REDACT
  ...
  v2_orch_runner.py:632  _maybe_write_repair_failure_context(..., stdout_tail, stderr_tail)
    v2_orch_runner.py:1252  _normalize_compiler_errors(   ← PARSE (TOO LATE)
        stdout_tail=stdout_tail,     ← ALREADY REDACTED
        stderr_tail=stderr_tail,     ← ALREADY REDACTED
    )
```

### Required order (FIX):
```
  v2_orch_runner.py:~558  raw_errors = _normalize_compiler_errors(    ← PARSE FIRST
                              raw_stdout="\n".join(self._last_stdout_lines),
                              raw_stderr=stderr,     ← RAW stderr from _handle_exit param
                          )
  v2_orch_runner.py:559  stdout_tail = _bounded(...)                   ← REDACT AFTER
  v2_orch_runner.py:560  stderr_tail = _bounded(stderr)                ← REDACT AFTER
  ...
  v2_orch_runner.py:632  _maybe_write_repair_failure_context(..., raw_errors, stdout_tail, stderr_tail)
    # USE pre-parsed raw_errors, IGNORE redacted tails for error parsing
```

### Files requiring modification:
1. `v2_orchestrator_runner.py` — `_handle_exit()` (line 544): Parse before `_bounded()`, pass pre-parsed errors to `_maybe_write_repair_failure_context()`
2. `v2_orchestrator_runner.py` — `_maybe_write_repair_failure_context()` (line 1210): Accept pre-parsed errors, remove internal `_normalize_compiler_errors()` call
3. `repair_context.py` — `_normalize_and_check_path()` (line 53): Add fallback for edge case where sandbox_root != prefix of absolute file_path

### Files NOT needing modification:
1. `redaction.py` — All redaction logic is correct for its privacy purpose; just needs to run AFTER parsing
2. `failure_evidence.py` — All logic correct; just needs correct input
3. `repair_review_chain.py` — Prompt builder is correct; just needs non-empty source_contexts
4. `v2_repair_gate_service.py` — Deserialization correctly handles missing key
5. `runner.py` — Raw capture is correct

---

## 14. FORENSIC SUMMARY

```
CULPRIT:  v2_orchestrator_runner.py:559-560  _bounded() call
MECHANISM: redact_absolute_paths() replaces C:\...\Foo.java with [redacted-windows-path]
           BEFORE _normalize_compiler_errors() regex can extract file/line/column
REGEX:     _WINDOWS_ABSOLUTE_PATH_RE matches drive:\path\...\file.java → replaces entire string
REGEX:     _RE_JAVAC_ERROR requires ".java" in captured text → gets [redacted-windows-path] → no match
RESULT:    compiler_errors = ()
CHAIN:     () → empty compiler_error_locations → guard fails → no source_contexts
           → context_pack_to_dict omits key → JSON has no source_contexts
           → _primary_repair_prompt has source_section = "" → GPT-5 mini gets zero Java code
FIX:       Parse javac diagnostics from raw self._last_stdout_lines and raw stderr
           BEFORE redaction in _handle_exit(), at v2_orchestrator_runner.py line ~558
```

---

## 15. RAW SOURCE AVAILABILITY CONFIRMATION

| Check | Answer | Confidence |
|-------|--------|------------|
| Is raw Maven stdout available at _handle_exit entry? | YES — `self._last_stdout_lines` (list[str], line 426) | PROVEN |
| Is raw Maven stderr available at _handle_exit entry? | YES — `stderr` parameter (line 552) | PROVEN |
| Is it truncated before _bounded? | NO — full list available | PROVEN |
| Is it redacted before _bounded? | NO — raw until line 559 | PROVEN |
| Can _RE_JAVAC_ERROR parse raw text? | YES — regex is correct, only fails on redacted input | PROVEN |
| Will NormalizedCompilerError have correct file_path? | YES — group 1 captures `C:\...\Foo.java` | PROVEN |
| Will NormalizedCompilerError have line/column? | YES — groups 2/3 capture [42,17] | PROVEN |
| Can _normalize_and_check_path resolve absolute path? | YES — if sandbox_root is proper prefix of file_path | PROVEN |
| Will build_bounded_source_context read files? | YES — if compiler_error_locations is non-empty | PROVEN |
| Will context_pack_to_dict include source_contexts? | YES — condition `if pack.source_contexts:` becomes True | PROVEN |
| Will _primary_repair_prompt include Java source? | YES — `{sc['content']}` is rendered in source_section | PROVEN |
| Will GPT-5 mini receive Java code? | YES — full content flows through prompt | PROVEN |
