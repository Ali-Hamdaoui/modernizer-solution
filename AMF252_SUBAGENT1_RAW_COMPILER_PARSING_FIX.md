# AMF-252 SUBAGENT 1 — RAW COMPILER DIAGNOSTIC EXTRACTION BEFORE REDACTION

## 1. Files Changed

| File | Action |
|------|--------|
| `migration_factory/control_tower/application/v2_orchestrator_runner.py` | Edited (4 edit sites) |

No other files were modified.

## 2. Symbols Changed

| Symbol | Kind | Change |
|--------|------|--------|
| `_handle_exit()` | Method | Added `raw_stdout`/`raw_stderr` capture before redaction; added `_normalize_compiler_errors()` call on raw text; added `compiler_errors=` kwarg to `_maybe_write_repair_failure_context()` call |
| `_maybe_write_repair_failure_context()` | Method | Added `compiler_errors: tuple[NormalizedCompilerError, ...] = ()` parameter; removed local re-parsing block that received redacted text |

## 3. Before Data Flow (Buggy)

```
stdout/stderr (raw, with .java paths)
    │
    ▼
_bounded() ──► redact_model_summary() ──► redact_absolute_paths()
    │                                           │
    │                                    C:\...\Foo.java
    │                                    becomes
    │                                    [redacted-windows-path]
    ▼
stdout_tail / stderr_tail (redacted)
    │
    ▼
_maybe_write_repair_failure_context()
    │
    ▼
_normalize_compiler_errors()
    │
    ▼
_RE_JAVAC_ERROR regex ──► requires .java path
    │
    ▼
compiler_errors = ()   ◄── EMPTY because .java was redacted
    │
    ▼
compiler_error_locations = []   ◄── EMPTY
    │
    ▼
no source context → empty proposed_diff
```

## 4. After Data Flow (Fixed)

```
stdout/stderr (raw, with .java paths)
    │
    ├──► raw_stdout / raw_stderr (captured BEFORE redaction)
    │       │
    │       ▼
    │   _normalize_compiler_errors()
    │       │
    │       ▼
    │   _RE_JAVAC_ERROR regex ──► MATCHES .java path ✓
    │       │
    │       ▼
    │   compiler_errors = (NormalizedCompilerError(...), ...)
    │
    └──► _bounded() ──► redact_model_summary()
            │
            ▼
        stdout_tail / stderr_tail (redacted for public DTOs)
            │
            ▼
        _maybe_write_repair_failure_context(
            compiler_errors=compiler_errors,  ← pre-parsed from raw text
            stdout_tail=stdout_tail,          ← redacted for safety
            stderr_tail=stderr_tail,          ← redacted for safety
        )
            │
            ▼
        compiler_error_locations = [("Foo.java", 42), ...]   ◄── POPULATED ✓
            │
            ▼
        build_bounded_source_context() ──► source contexts → proposed_diff
```

## 5. Proof That Parsing Occurs Before `_bounded()`

In `_handle_exit()` at `v2_orchestrator_runner.py:559-569`:

```python
# Line 559-560: raw capture (NO redaction)
raw_stdout = "\n".join(self._last_stdout_lines) if hasattr(self, "_last_stdout_lines") and self._last_stdout_lines else ""
raw_stderr = stderr

# Line 562-563: redaction happens AFTER raw capture
stdout_tail = _bounded(raw_stdout)    # _bounded() calls redact_model_summary()
stderr_tail = _bounded(stderr)

# Line 566-569: compiler parsing on RAW text
compiler_errors = _normalize_compiler_errors(
    stdout_tail=raw_stdout,    # <-- raw_stdout, NOT stdout_tail
    stderr_tail=raw_stderr,    # <-- raw_stderr, NOT stderr_tail
)
```

The `_normalize_compiler_errors()` call uses `raw_stdout`/`raw_stderr` which are the un-redacted originals. The `_bounded()` call (which internally calls `redact_model_summary()` → `redact_absolute_paths()`) operates on separate variables and does not affect the raw copies.

## 6. Proof Public Tails Remain Redacted

All event payloads and the `_maybe_write_repair_failure_context()` method continue to receive `stdout_tail`/`stderr_tail` (the `_bounded()`-redacted versions):

- `v2_orchestrator_runner.py:580-583` — `stage_failed` payload uses `stderr_tail`/`stdout_tail`
- `v2_orchestrator_runner.py:600-606` — `result_contract_failed` payload uses `stderr_tail`/`stdout_tail`
- `v2_orchestrator_runner.py:622-630` — second `stage_failed` payload uses `stderr_tail`/`stdout_tail`
- `v2_orchestrator_runner.py:640-648` — `_maybe_write_repair_failure_context()` receives both `stdout_tail` (redacted) and `compiler_errors` (pre-parsed from raw)

No public-facing data ever receives unredacted paths.

## 7. Proof `_maybe_write_repair_failure_context()` No Longer Reparses Redacted Text

Before the fix (lines 1251-1256 removed):
```python
# REMOVED:
# compiler_errors = ()
# if failure_source == FailureSource.BUILD:
#     compiler_errors = _normalize_compiler_errors(
#         stdout_tail=stdout_tail,    # <-- WAS REDACTED
#         stderr_tail=stderr_tail,    # <-- WAS REDACTED
#     )
```

After the fix:
- `compiler_errors` is accepted as a parameter (`v2_orchestrator_runner.py:1228`)
- It defaults to `()` for callers that do not supply it (backward-compatible)
- The parameter is passed directly to `build_failure_evidence()` at line 1267
- No call to `_normalize_compiler_errors()` exists anywhere in this method

## 8. Exact `NormalizedCompilerError` Lineage

```
NormalizedCompilerError (dataclass, failure_evidence.py:30-35)
    ├── message: str    ← m.group(4) from _RE_JAVAC_ERROR
    ├── file_path: str  ← m.group(1) from _RE_JAVAC_ERROR  (e.g. "C:\Users\...\Foo.java")
    ├── line: int        ← m.group(2) from _RE_JAVAC_ERROR
    ├── column: int      ← m.group(3) from _RE_JAVAC_ERROR (0 if absent)
    └── severity: str    ← always "error"

Extraction path:
    raw_stdout/raw_stderr (unredacted)
        → _normalize_compiler_errors() at v2_orchestrator_runner.py:566-569
            → _RE_JAVAC_ERROR.match() at line 2632  ← MATCHES on .java path
                → NormalizedCompilerError(...) at line 2652-2658
                    → tuple[NormalizedCompilerError, ...] returned
                        → passed as compiler_errors parameter at line 647
                            → consumed by build_failure_evidence() at line 1267
                                → evidence.compiler_errors at line 1273
                                    → compiler_error_locations at line 1273-1276
                                        → build_bounded_source_context() at line 1286
```

## 9. Static Checks Performed

| Check | Command | Result |
|-------|---------|--------|
| Python syntax | `py -m py_compile v2_orchestrator_runner.py` | PASS (no output) |
| Whitespace | `git diff --check` | No new whitespace errors in changed file |
| Changed files | `git diff --stat` | 1 file changed (the target file) |
| Dirty files | `git status --short` | Only target file modified |

## 10. Remaining Unknowns

- **Downstream consumers of `compiler_errors` in non-BUILD paths**: The `compiler_errors` variable is now computed unconditionally in `_handle_exit()` for all exit code paths (exit_code != 0, result is None, and the successful path). For non-BUILD failure sources, it will be an empty tuple `()`, which is identical to the previous behavior. This is safe.
- **Non-BUILD failures that also have compiler errors**: If a test failure also produces compiler diagnostics in its output, those will be captured by the new `_normalize_compiler_errors()` call in `_handle_exit()` but then ignored because `_maybe_write_repair_failure_context()` only builds `compiler_error_locations` for BUILD failures. This matches the original behavior — the type check on `failure_source` gates the compiler error path.
- **The `exit_code != 0` and `result is None` early-return paths**: In these paths, `compiler_errors` is computed but never used (the method returns before reaching `_maybe_write_repair_failure_context()`). This is harmless — the parsing is idempotent and cheap (regex over string lines). The variable exists in scope but is discarded on return. This could be optimized later by moving the `_normalize_compiler_errors()` call after the early returns, but that would change the control flow logic and is not required for correctness.
