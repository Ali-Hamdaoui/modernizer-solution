# SUBAGENT A — COMPILER EVIDENCE TRACE

## 1. Maven Subprocess → Raw stdout/stderr

### File: `migration_factory/agents/build_agent/runner.py`

| Step | Symbol | Line | Detail |
|------|--------|------|--------|
| Popen creation | `subprocess.Popen()` | 67–77 | `command` spawned with `stdout=PIPE, stderr=PIPE, text=True` |
| Raw capture thread | `_enqueue_lines()` | 379–388 | Reads `stream` line-by-line, calls `output_queue.put((source, line.rstrip("\n")))` |
| Raw line storage | `_record_line()` | 406–413 | Appends `line` to either `stdout: list[str]` or `stderr: list[str]` |
| Return struct | `ProcessRunResult.stdout` | 36 | `list[str]` — **unredacted, untruncated** |
| Return struct | `ProcessRunResult.stderr` | 37 | `list[str]` — **unredacted, untruncated** |

**Raw Maven output first available at:** `runner.py:36-37` → `ProcessRunResult.stdout` / `ProcessRunResult.stderr` (full `list[str]`)

---

## 2. Exact Variable Names Containing Raw stdout/stderr

| Location | Variable | Type | State |
|----------|----------|------|-------|
| `runner.py:98-99` | `stdout: list[str]`, `stderr: list[str]` | `list[str]` | RAW, unredacted |
| `runner.py:36-37` | `ProcessRunResult.stdout`, `ProcessRunResult.stderr` | `list[str]` | RAW, unredacted |
| `agent.py:231-232` | `result.stdout`, `result.stderr` | `list[str]` | RAW, unredacted (passed from runner) |
| `agent.py:220-238` | `build_error_contract(stdout=result.stdout, stderr=result.stderr)` | `list[str]` | RAW passed to contract builder |
| `schemas.py:86-87` | `stdout: list[str]`, `stderr: list[str]` (parameters) | `list[str]` | RAW at function entry |

---

## 3. Where Is It Truncated?

### File: `migration_factory/contracts/build/schemas.py`

| Line | Code | Effect |
|------|------|--------|
| 98 | `tail_size: int = 40` | Default tail length = 40 lines |
| 118 | `stdout_tail=stdout[-tail_size:]` | Last 40 lines of stdout → `BuildErrorContract.stdout_tail` |
| 119 | `stderr_tail=stderr[-tail_size:]` | Last 40 lines of stderr → `BuildErrorContract.stderr_tail` |

**Truncation:** `schemas.py:118-119` — takes `[-40:]` slices. The full `ProcessRunResult.stdout`/`stderr` (list of all lines) is **lost** after this point; only the 40-line tails survive into the contract.

---

## 4. Where Is It Redacted?

### TWO SEPARATE REDACTION PATHS

### Path A: V2 Orchestrator Runner (the primary path for FailureEvidence)

**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py`

| Line | Code | What happens |
|------|------|-------------|
| 426 | `self._last_stdout_lines = list(stdout_lines)` | RAW stdout saved (full list) |
| 427 | `final_json = _extract_final_json("\n".join(stdout_lines))` | RAW stdout JSON-scanned for result |
| 435 | `stderr="\n".join(stderr_lines)` | RAW stderr joined |
| **559** | `stdout_tail = _bounded("\n".join(self._last_stdout_lines) ...)` | **REDACTION HAPPENS HERE** |
| **560** | `stderr_tail = _bounded(stderr)` | **REDACTION HAPPENS HERE** |
| 2997 | `def _bounded(value: str) -> str:` | Calls `redact_model_summary(value)` then truncates to `_MAX_TEXT=4096` |
| 2998 | `redacted = redact_model_summary(value)` | Full redaction pipeline runs |

### `_bounded()` at `v2_orchestrator_runner.py:2997-3001`:
```python
def _bounded(value: str) -> str:
    redacted = redact_model_summary(value)     # ← REDACTION
    if len(redacted) <= _MAX_TEXT:             # _MAX_TEXT = 4096
        return redacted
    return redacted[:_MAX_TEXT] + "...[truncated]"
```

### `redact_model_summary()` at `redaction.py:165-179`:
```python
def redact_model_summary(summary: str) -> str:
    result = summary
    result = redact_absolute_paths(result)        # ← [redacted-path], [redacted-windows-path]
    result = redact_env_assignments(result)
    result = redact_sensitive_env_vars(result)
    result = redact_secret_keys(result)
    result = redact_deployment_identifiers(result)
    result = _TOKEN_VALUE_RE.sub("[redacted-token]", result)
    result = redact_raw_prompts(result)
    return result
```

### `redact_absolute_paths()` at `redaction.py:127-137`:
```python
def redact_absolute_paths(text: str) -> str:
    if _looks_like_url(text):
        return text
    text = _WINDOWS_ABSOLUTE_PATH_RE.sub("[redacted-windows-path]", text)  # C:\Users\...
    text = _POSIX_ABSOLUTE_PATH_RE.sub("[redacted-path]", text)            # /home/... or /path/to/Foo.java
    text = _HOME_DIR_RE.sub("[redacted-home-path]", text)
    return text
```

### Path B: Build Agent Contract (legacy, NOT used by FailureEvidence)

**File:** `migration_factory/agents/build_agent/agent.py:220-239`
- `build_error_contract(stdout=result.stdout, stderr=result.stderr)` 
- Stores raw text into `BuildErrorContract.stdout_tail[-40:]` / `stderr_tail[-40:]`
- These contracts are written to JSON files on disk and are **NOT redacted** (they still contain full Windows paths, etc.)

### Path C: Evidence Collector (separate old path)

**File:** `migration_factory/repair_loop/evidence_collector.py:140-147`
- `_redact_text()` replaces secrets and home dir — but this is a *different* redaction for the old repair pipeline

---

## 5. Does `_normalize_compiler_errors()` Receive Raw or Redacted Text?

**REDACTED.** 

**File:** `v2_orchestrator_runner.py:1252-1256`
```python
compiler_errors = ()
if failure_source == FailureSource.BUILD:
    compiler_errors = _normalize_compiler_errors(
        stdout_tail=stdout_tail,     # ← ALREADY REDACTED by _bounded()
        stderr_tail=stderr_tail,     # ← ALREADY REDACTED by _bounded()
    )
```

The `stdout_tail` and `stderr_tail` variables were set at lines 559-560 via `_bounded()`, which already called `redact_model_summary()`.

---

## 6. What Exact Text Inputs Are Passed to `_normalize_compiler_errors()`?

Redacted text where:
- `C:\Users\abdelilah.mortaki\Desktop\...\Foo.java` → `[redacted-windows-path]`
- `/path/to/Foo.java` → `[redacted-path]`
- Anything matching `_POSIX_ABSOLUTE_PATH_RE` → `[redacted-path]`
- Anything matching `_WINDOWS_ABSOLUTE_PATH_RE` → `[redacted-windows-path]`
- Env assignments → `[redacted-env]`
- Tokens → `[redacted-token]`
- Etc.

The combined input is: `f"{stdout_tail}\n{stderr_tail}"` (line 2627), where both have been through `_bounded()`.

---

## 7. Why Did Runtime Show `[ERROR] [redacted-path] incompatible types...`?

Because `redact_absolute_paths()` at `redaction.py:127-137` ran **before** `_normalize_compiler_errors()` could parse the javac diagnostic lines.

The javac compiler error line like:
```
[ERROR] /home/user/project/Foo.java:[42,17] incompatible types: String cannot be converted to int
```

Its file path portion `/home/user/project/Foo.java` is matched by `_POSIX_ABSOLUTE_PATH_RE` (`redaction.py:33-35`):
```python
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:/<])(?<!/)/(?:[^/\s]+/)*[^/\s]+"
)
```

This regex matches the `/path/to/Foo.java` portion and replaces it with `[redacted-path]`.

On Windows, `C:\Users\...\Foo.java` is matched by `_WINDOWS_ABSOLUTE_PATH_RE` (`redaction.py:27-29`):
```python
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z]:)(?<![A-Za-z])[A-Za-z]:[\\/](?:[^\\/\s:]*[\\/])*[^\\/\s:]*"
)
```
This replaces the full Windows path with `[redacted-windows-path]`.

**Result after redaction:**
```
[ERROR] [redacted-path]:[42,17] incompatible types: String cannot be converted to int
```

Then `_RE_JAVAC_ERROR` regex at line 2596-2598 fails to match because:
```python
_RE_JAVAC_ERROR = re.compile(
    r'\[ERROR\]\s+(.+?\.[Jj][Aa][Vv][Aa])\s*:\s*\[?(\d+)(?:,\s*(\d+))?\]?\s+(.+)',
)
```
The regex requires `.java` in the path — but redaction replaced the path with `[redacted-path]` which contains no `.java` substring. So **no match**, and the error is silently dropped.

---

## 8. Where Was Original `Foo.java:[line,column]` Destroyed?

**Root loss point:** `v2_orchestrator_runner.py:559-560` → `_bounded()` call

Trace:
1. `v2_orchestrator_runner.py:559` — `_bounded()` calls `redact_model_summary()` (line 2998)
2. `redaction.py:172` — `redact_model_summary()` calls `redact_absolute_paths(result)`
3. `redaction.py:134-135` — `redact_absolute_paths()` applies `_WINDOWS_ABSOLUTE_PATH_RE.sub()` and `_POSIX_ABSOLUTE_PATH_RE.sub()`
4. The absolute path containing the `.java` filename is replaced with `[redacted-path]` or `[redacted-windows-path]`
5. The original `Foo.java:[42,17]` location information is **irrecoverably lost** in the string

The original `File.java:[line,column]` information was carried in the absolute path string (e.g., `C:\Users\...\Foo.java:[42,17]`). Redaction nukes the entire path including the filename before the parser can extract it.

---

## 9. Is the Full Maven Log File Still Available Internally After Redaction?

**YES, via two mechanisms:**

### A. Build Error Contract JSON files on disk
- **File pattern:** `migration_factory/contracts/build/build-error-*.json`
- **Contains:** `stdout_tail` and `stderr_tail` (last 40 lines, **UNREDACTED** — stored raw by `build_error_contract()` at `schemas.py:118-119`)
- BUT: only 40 lines (truncated but not redacted)
- The `BuildErrorContract` is available at `build_result.error_contract_path` from `run_build_agent()` return value

### B. phase2_transform.log
- **Path:** `<run_dir>/logs/phase2_transform.log`
- **Contains:** Full subprocess output (both stdout and stderr interleaved via the `_OutputTee` mechanism in `transform_v1_after_approval.py:441-447`)
- **Status:** RAW and complete on disk

### C. `ProcessRunResult` (in-memory only, lost after agent returns)
- The full `ProcessRunResult.stdout` / `stderr` lists are available only during the `run_build_agent()` call
- They are truncated to 40 lines when stored in `BuildErrorContract` and are **not persisted** anywhere in full

---

## 10. Is There an Existing Structured Build Error Contract Containing file, line, column, message?

**NO.**

- `BuildErrorContract` (`schemas.py:14-45`) has `stdout_tail`, `stderr_tail`, `message`, `matched_line` — but NO structured `file`, `line`, `column` fields
- `NormalizedCompilerError` (`failure_evidence.py:30-35`) has `message`, `file_path`, `line`, `column`, `severity` — but it is only populated by `_normalize_compiler_errors()` which receives REDACTED text
- The JSON contracts on disk (`build-error-*.json`) contain raw text but no structured compiler error fields

---

## 11. Is There Already Another Compiler Parser in the Repo?

**YES, exactly one:** `_normalize_compiler_errors()` at `v2_orchestrator_runner.py:2616-2662` with regex `_RE_JAVAC_ERROR` at line 2596-2598.

There is NO other javac diagnostic parser anywhere in the codebase.

---

## 12. What Is the Smallest Safe Insertion Point to Parse Diagnostics BEFORE Public Redaction?

### Answer: At `v2_orchestrator_runner.py:1252`, replace:

```python
# CURRENT (BROKEN) — redacted text passed:
compiler_errors = ()
if failure_source == FailureSource.BUILD:
    compiler_errors = _normalize_compiler_errors(
        stdout_tail=stdout_tail,        # ← already redacted
        stderr_tail=stderr_tail,        # ← already redacted
    )
```

### With:

Parse from the RAW `self._last_stdout_lines` / raw stderr **before** `_bounded()` is called. At line 559, `stdout_tail = _bounded(...)` is computed — but the raw lines are still available in `self._last_stdout_lines` (set at line 426) and the raw `stderr` parameter.

The raw stderr `"\n".join(stderr_lines)` is available inside `_handle_exit()` — it's the `stderr` parameter (line 552). The raw stdout is `self._last_stdout_lines`.

**Insert at `v2_orchestrator_runner.py:1250-1256`** (inside `_maybe_write_repair_failure_context`):

The method already receives `stdout_tail` (redacted) and `stderr_tail` (redacted). To get raw text, you would need to either:
- Pass raw lines into `_maybe_write_repair_failure_context` as additional parameters
- Or parse directly from `self._last_stdout_lines` and the raw stderr that was passed to `_handle_exit`

**Method:** Add parsing at `_handle_exit` line ~560 (BEFORE `_bounded()` is called), using the raw `self._last_stdout_lines` and the raw stderr list before passing to `_bounded()`.

---

## SUMMARY: Complete Data Flow

```
Maven subprocess (raw bytes)
  │
  ▼
runner.py:67-77 — subprocess.Popen with PIPE
  │
  ▼
runner.py:379-388 — _enqueue_lines() captures RAW lines
  │
  ▼
runner.py:406-413 — _record_line() → ProcessRunResult.stdout (RAW list[str])
                                          ProcessRunResult.stderr (RAW list[str])
  │
  ├─────────────────────────────────────────────────────┐
  │                                                     │
  ▼                                                     ▼
agent.py:220-238                                   v2 Orchestrator
  │   build_error_contract()                        │
  ▼   stdout=result.stdout (RAW)                    ▼
schemas.py:118-119                              v2_orchestrator_runner.py:358-359
  stdout_tail[-40:]  ← TRUNCATED only              stdout_lines: list[str] (RAW)
  stderr_tail[-40:]  ← NOT REDACTED                stderr_lines: list[str] (RAW)
  │                                                   │
  ▼ Persisted as JSON                                 ▼
build-error-*.json                              v2_orchestrator_runner.py:426
  stdout_tail: [40 lines raw]                     self._last_stdout_lines (RAW)
  stderr_tail: [40 lines raw]                       │
                                                    │
                                          v2_orchestrator_runner.py:559-560
                                            _bounded() ← REDACTION APPLIED HERE
                                              redact_model_summary()
                                                redact_absolute_paths()
                                                  → [redacted-path]
                                                  → [redacted-windows-path]
                                                    │
                                                    ▼
                                          v2_orchestrator_runner.py:1252-1256
                                            _normalize_compiler_errors(
                                              stdout_tail ← REDACTED,
                                              stderr_tail ← REDACTED
                                            )
                                              │
                                              ▼ NO MATCH (path replaced by placeholder)
                                            () ← empty tuple
                                              │
                                              ▼
                                            FailureEvidence(compiler_errors=())
```

---

## ROOT LOSS POINT:

**File:** `v2_orchestrator_runner.py:559-560`  
**Symbol:** `_bounded()`  
**Detail:** `redact_model_summary()` nukes absolute paths (including `.java` filenames and `[line,column]`) via `redact_absolute_paths()` BEFORE the javac diagnostic regex can extract structured data.

---

## EXACT RAW SOURCE AVAILABLE AT:

- **`migration_factory/control_tower/application/v2_orchestrator_runner.py:426`** — `self._last_stdout_lines` (list[str], raw, unredacted, full output)
- **`migration_factory/control_tower/application/v2_orchestrator_runner.py:427`** — `"\n".join(stdout_lines)` used to extract final JSON (raw)
- **`migration_factory/control_tower/application/v2_orchestrator_runner.py:435`** — `stderr = "\n".join(stderr_lines)` passed into `_handle_exit` (raw, but then redacted at line 560)
- **`migration_factory/agents/build_agent/runner.py:36-37`** — `ProcessRunResult.stdout`/`stderr` (raw full lists, but ephemeral)
- **`migration_factory/contracts/build/build-error-*.json`** — 40 tail lines, raw (unredacted), persisted to disk

---

## EXACT REDACTION POINT:

**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py:2997-3001`  
**Symbol:** `_bounded()`  
**Called from:** line 559 (`stdout_tail = _bounded(...)`) and line 560 (`stderr_tail = _bounded(stderr)`)  
**Redactor called:** `redaction.py:165` — `redact_model_summary()`  
**Destructive sub-step:** `redaction.py:134-135` — `redact_absolute_paths()` replaces `.java`-bearing paths with `[redacted-path]` or `[redacted-windows-path]`

---

## EXACT PARSER INPUT TODAY:

`_normalize_compiler_errors()` receives the string `f"{stdout_tail}\n{stderr_tail}"` at line 2627, where:
- `stdout_tail` = **redacted** (paths replaced, truncated to 4096 chars)
- `stderr_tail` = **redacted** (paths replaced, truncated to 4096 chars)
- Example line received: `[ERROR] [redacted-path]:[42,17] incompatible types: String cannot be converted to int`
- `_RE_JAVAC_ERROR` regex requires `.java` in the path → **fails to match** → error silently dropped

---

## MINIMUM FIX BOUNDARY:

**Insert structured parsing at `v2_orchestrator_runner.py:~558`**, BEFORE `_bounded()` is called, using the raw `self._last_stdout_lines` and the raw stderr (available as the `stderr` parameter of `_handle_exit`). 

The parsed `NormalizedCompilerError` tuple can be computed from the raw text and passed into `_maybe_write_repair_failure_context()` alongside the redacted tails. No redaction logic needs to change; the compiler errors just need to be extracted from the raw lines before they are corrupted.

**Exact insertion zone:** `v2_orchestrator_runner.py`, in method `_handle_exit()` (line 544), between line 558 (where raw data is still available) and line 561 (where `_bounded()` is called).
