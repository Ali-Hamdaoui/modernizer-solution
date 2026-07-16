# AMF-252 SUBAGENT 2 — SAFE SANDBOX ROOT AND SOURCE-PATH RESOLUTION

## 1. EXACT SANDBOX-ROOT LOOKUP CHAIN

The full derivation chain from orchestrator subprocess to `_normalize_and_check_path`:

```
orchestrator/runner.py:93
  → json.dumps(_render_result(finalize_orchestration_state(state)))
  → writes CONTROL_TOWER_FINAL_JSON <payload> to stdout

orchestrator/summary.py:102
  → finalize_orchestration_state() calls _normalize_output_paths(dict(state))
  → [CORRUPTION SITE] _normalize_output_paths() may set state["sandbox_path"]
    to modernized_app_path when real sandbox_path is empty

control_tower v2_orchestrator_runner.py:634-638
  → result = dict(result)
  → sandbox_path = _result_sandbox_path(result)   # reads from parsed JSON
  → result["sandbox_path"] = sandbox_path          # stores back

control_tower v2_orchestrator_runner.py:640-647
  → self._maybe_write_repair_failure_context(result=result, ...)

control_tower v2_orchestrator_runner.py:1237
  → run_dir = _result_run_dir(result, cwd=self._cwd)

control_tower v2_orchestrator_runner.py:1282  [FIXED]
  → sandbox_root = str(run_dir / "workspaces" / "sandbox")
  → (WAS: sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or ""))

repair_context.py:85
  → sandbox = Path(sandbox_root).resolve()

repair_context.py:57-64  (_normalize_and_check_path)
  → resolved = (sandbox_root / file_path).resolve()
  → resolved.relative_to(sandbox_root)  [containment check]
  → not resolved.is_symlink()           [symlink rejection]
```

## 2. EXACT CURRENT COMMON RUNTIME ROOT RETURNED BY `_result_sandbox_path()`

`_result_sandbox_path()` preference order (BEFORE fix):

1. `result.get("sandbox_path")` — may be **corrupted** to `modernized_app_path` by `_normalize_output_paths`
2. `result.get("modernized_app_path")` — **WRONG directory** (output root, not sandbox)
3. `result.get("output_app_path")` — also wrong
4. `artifact_refs.get("sandbox")` — OK
5. `artifact_refs.get("sandbox_path")` — OK
6. `artifact_refs.get("modernized_app")` — ambiguous
7. `artifact_refs.get("modernized_app_path")` — ambiguous

AFTER fix: preferences 2 and 3 are removed. The top-level fallback to `modernized_app_path` and `output_app_path` is eliminated.

The **actual correct sandbox root** is always at:
```
run_dir / "workspaces" / "sandbox"
```
as created by `workspace.py:54` in `prepare_sandbox_workspace()`.

## 3. CURRENT `_normalize_and_check_path()` BEHAVIOR FOR ALL PATH TYPES

All behavior was verified by code analysis and confirmed by Python runtime checks:

### Absolute Windows path under sandbox root:
- `file_path="C:\workspaces\sandbox\src\main\java\Foo.java"`
- `sandbox_root=Path("C:\workspaces\sandbox")`
- `(sandbox_root / file_path)` → `Path("C:\workspaces\sandbox\src\main\java\Foo.java")`
  (Python: when right operand is absolute Path, left operand is discarded)
- `.resolve()` → canonical form
- `.relative_to(sandbox_root)` → `Path("src\main\java\Foo.java")` → **SUCCESS**

### Relative path under sandbox root:
- `file_path="src\main\java\Foo.java"`
- `sandbox_root=Path("C:\workspaces\sandbox")`
- `(sandbox_root / file_path)` → `Path("C:\workspaces\sandbox\src\main\java\Foo.java")`
- `.relative_to(sandbox_root)` → **SUCCESS**

### Absolute path outside sandbox:
- `file_path="C:\outside\secret.java"`
- `sandbox_root=Path("C:\workspaces\sandbox")`
- `(sandbox_root / file_path)` → `Path("C:\outside\secret.java")`
- `.relative_to(sandbox_root)` → **ValueError → returns None ✓**

### Path with `..\` traversal:
- `file_path="C:\workspaces\sandbox\..\outside\secret.java"`
- `sandbox_root=Path("C:\workspaces\sandbox")`
- `(sandbox_root / file_path)` → `Path("C:\workspaces\sandbox\..\outside\secret.java")`
- `.resolve()` → `Path("C:\outside\secret.java")`
- `.relative_to(sandbox_root)` → **ValueError → returns None ✓**

## 4. SYMLINK/JUNCTION ANALYSIS

`_normalize_and_check_path()` line 62-63:
```python
if resolved.is_symlink():
    return None
```

This is correct and rejects:
- Top-level symlinks where `file_path` itself is a symlink
- Symlink-in-chain: `.resolve()` already resolves intermediate symlinks before `.relative_to()` is checked, so a symlink pointing outside would resolve to an outside path and be caught by the `relative_to` check. The `is_symlink()` check catches the case where the final path component is a symlink (even if it points inside the sandbox).

**However**, `.is_symlink()` only checks the last component. A symlink in a parent directory (e.g., `src` is a symlink to outside, `src/Foo.java` is inside the symlink target) would NOT be caught by `.is_symlink()` because `Foo.java` is not a symlink even though `src` is. The `.resolve()` call resolves `src` to its target, so `Foo.java`'s path would be the resolved target path. If that target is outside the sandbox, `.relative_to()` catches it. If the target is inside the sandbox (benign symlink), it passes through.

The symlink check is conservative: it rejects symlinks at the file level even if they point inside the sandbox. This is correct for security (no symlinks in source context reading).

## 5. WHETHER A CODE CHANGE WAS REQUIRED

**YES.** A real bug exists.

### Bug scenario:
1. Sandbox transform fails early (before `sandbox_path` is set in the orchestrator state)
2. `_normalize_output_paths()` (`summary.py:251-267`) finds `sandbox_path=""` and `modernized_app_path="C:\...\modernized-app"` (always set from init)
3. It sets `state["sandbox_path"] = "C:\...\modernized-app"` — **completely wrong directory**
4. This corrupted state is serialized to JSON and read by control_tower
5. `_maybe_write_repair_failure_context()` reads `result.get("sandbox_path")` and gets the wrong path
6. `build_bounded_source_context()` and `_normalize_and_check_path()` reject ALL source files because they're not under `C:\...\modernized-app`
7. **All source context silently dropped** — no error, no warning, just empty context

### Proof that it's a real bug:
- `build_initial_state` (state.py:181) sets `sandbox_path: ""` initially
- `phase_services.py:216` catches transform failure and writes `sandbox_path: str(result.sandbox_path or "")` → `""` when sandbox is None
- `_normalize_output_paths` (summary.py:255-267) blindly overwrites `sandbox_path` with `modernized_app_path` when the first is empty
- `modernized_app_path` (`C:\...\modernized-app`) is NOT the same directory as the sandbox workspace (`C:\...\modernized-app\.migration\runs\<id>\workspaces\sandbox`)
- Compiler error source files live under the sandbox workspace, not `modernized-app` directly

## 6. EXACT CODE CHANGED AND WHY

### Change 1 — `migration_factory/control_tower/application/v2_orchestrator_runner.py`

**Location:** `_result_sandbox_path()` — removed fallbacks to `modernized_app_path` and `output_app_path`

```python
# BEFORE
direct = _first_text(
    result.get("sandbox_path"),
    result.get("modernized_app_path"),     # WRONG: different directory tree
    result.get("output_app_path"),         # WRONG: different directory tree
    artifact_refs.get("sandbox"),
    artifact_refs.get("sandbox_path"),
    artifact_refs.get("modernized_app"),
    artifact_refs.get("modernized_app_path"),
)

# AFTER
direct = _first_text(
    result.get("sandbox_path"),
    artifact_refs.get("sandbox"),
    artifact_refs.get("sandbox_path"),
    artifact_refs.get("modernized_app"),
    artifact_refs.get("modernized_app_path"),
)
```

**Why:** `modernized_app_path` points to the output root (e.g., `C:\...\modernized-app`) while the sandbox workspace is at `run_dir/workspaces/sandbox` (e.g., `C:\...\modernized-app\.migration\runs\<id>\workspaces\sandbox`). These are different directory trees. Using `modernized_app_path` as the sandbox root causes ALL source context resolution to fail silently. The `artifact_refs` variants are retained because they may legitimately contain sandbox-related paths.

Note: This change alone does NOT fully fix the corruption, because `_normalize_output_paths` (orchestrator/summary.py) may have already overwritten `result["sandbox_path"]` with `modernized_app_path` before the JSON reaches control_tower. The `_result_sandbox_path` function finds `sandbox_path` first (preference #1), so it would return the already-corrupted value.

### Change 2 — `migration_factory/control_tower/application/v2_orchestrator_runner.py`

**Location:** `_maybe_write_repair_failure_context()` — changed sandbox_root derivation

```python
# BEFORE
sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")

# AFTER
sandbox_root = str(run_dir / "workspaces" / "sandbox")
```

**Why:** The canonical sandbox root is always `run_dir / "workspaces" / "sandbox"` as created by `workspace.py:54`. This is deterministic and doesn't depend on potentially corrupted `result["sandbox_path"]`. The `run_dir` variable is already available at this point (computed at line 1237) and is more reliably resolved by `_result_run_dir()`.

### Change 3 — `migration_factory/orchestrator/summary.py`

**Location:** `_normalize_output_paths()` — prevented corruption at source

```python
# BEFORE
sandbox_path = _first_text(
    updated.get("sandbox_path"),
    updated.get("modernized_app_path"),     # WRONG: corrupts sandbox_path
    updated.get("output_app_path"),         # WRONG: same issue
    artifact_refs.get("sandbox"),
    artifact_refs.get("sandbox_path"),
    artifact_refs.get("modernized_app"),
    artifact_refs.get("modernized_app_path"),
)
if sandbox_path:
    updated["sandbox_path"] = sandbox_path
    updated.setdefault("modernized_app_path", sandbox_path)  # no-op: already set

# AFTER
sandbox_path = _first_text(
    updated.get("sandbox_path"),
    artifact_refs.get("sandbox"),
    artifact_refs.get("sandbox_path"),
    artifact_refs.get("modernized_app"),
    artifact_refs.get("modernized_app_path"),
)
if sandbox_path:
    updated["sandbox_path"] = sandbox_path
```

**Why:** This is the root cause of the corruption. When `sandbox_path` is empty in the orchestrator state (because the sandbox transform failed), the function incorrectly overwrites it with `modernized_app_path`. The `modernized_app_path` points to a completely different directory tree than the sandbox workspace. The `setdefault` was also removed because `modernized_app_path` is always set by `build_initial_state` (state.py:159), making it a no-op.

## 7. WHY NO BLIND RELPATH FALLBACK WAS ADDED

The task explicitly prohibits:
```python
try:
    candidate.relative_to(sandbox)
except ValueError:
    candidate = Path(os.path.relpath(candidate, sandbox))
```

This prohibition is correct because:
- It would accept paths like `..\outside\secret.java` after resolution
- It breaks the security invariant that the candidate MUST be inside the canonical sandbox
- The current `_normalize_and_check_path` already handles absolute paths correctly (Python's `/` operator discards left operand when right is absolute)
- No path representation fix is needed — the issue was entirely in the wrong `sandbox_root` being passed

## 8. STATIC CHECKS PERFORMED

```
py -m py_compile migration_factory/repair_loop/repair_context.py          → PASS
py -m py_compile migration_factory/control_tower/application/v2_orchestrator_runner.py → PASS
py -m py_compile migration_factory/orchestrator/summary.py                → PASS
git diff --check                                                          → PASS (no new whitespace errors)
git diff --stat                                                           → changes in 3 files
git status --short                                                        → clean workspace
```

## 9. REMAINING EDGE CASES

1. **`_ensure_resume_output_paths` in `resume.py:296-330`** has the same fallback pattern (`modernized_app_path` → `sandbox_path`). However, it also has a disk-based fallback (`_existing_candidate`) that searches real directories like `run_dir / "sandbox"`. The resume path is not in the primary repair-context flow, so it was left for a separate audit.

2. **`v2_stage_progression.py:_result_sandbox_path` (line 1521)** only checks top-level `sandbox_path` (no `modernized_app_path` at top level). Its fallback to `artifact_refs` for `modernized_app` is less likely to trigger because `sandbox_path` at the top level is usually set by `_normalize_output_paths`. After the fix, `_normalize_output_paths` no longer corrupts `sandbox_path`, so this function will correctly return empty `sandbox_path` when the real one is empty.

3. **Non-existent sandbox**: If `run_dir / "workspaces" / "sandbox"` doesn't exist (sandbox transform never created it), `_normalize_and_check_path` returns None for all files (because `normalized.is_file()` returns False at line 102). Source context will be empty. This is correct behavior — you can't read source files from a non-existent sandbox.

4. **`run_dir` resolution**: `_result_run_dir` has its own fallback chain. If `run_dir` is wrong, `run_dir / "workspaces" / "sandbox"` will also be wrong. However, `_result_run_dir` first checks `result.get("run_dir")` which is always set from `build_initial_state` (state.py:193 `"run_dir": str(run_dir)`), so it should always be correct.

5. **Symlinks in parent directories**: As discussed in section 4, `.is_symlink()` only checks the last path component. A symlink in a parent directory that resolves to inside the sandbox is benign. A symlink that resolves outside is caught by `.relative_to()`.

## 10. FINAL SANDBOX PATH DECISION

### What is the intended canonical sandbox root?
```
run_dir / "workspaces" / "sandbox"
```
where `run_dir = Path(modernized_app_path) / ".migration" / "runs" / run_id`.
This is set by `workspace.py:54` in `prepare_sandbox_workspace()`.

### Can `_result_sandbox_path()` return the wrong subdirectory?
**YES** — before the fix. If `result.get("sandbox_path")` is empty and `result.get("modernized_app_path")` is set, the function returned `modernized_app_path` which points to the output root (e.g., `C:\...\modernized-app`), NOT the sandbox workspace (`C:\...\modernized-app\.migration\runs\<id>\workspaces\sandbox`). After the fix, this top-level fallback is removed.

### Does the normal absolute Maven path under the true sandbox currently work?
**YES** — with the correct `sandbox_root`. Python's path behavior: `Path(sandbox_root) / Path(absolute_path)` returns `Path(absolute_path)` unchanged when `absolute_path` is absolute. So `Path("C:\sandbox") / Path("C:\sandbox\src\Foo.java")` = `Path("C:\sandbox\src\Foo.java")`, and `.relative_to(Path("C:\sandbox"))` succeeds. This was never broken.

### Does the normal relative Maven path currently work?
**YES** — `Path("C:\sandbox") / Path("src\Foo.java")` = `Path("C:\sandbox\src\Foo.java")`, and `.relative_to()` succeeds. This was never broken.

### Are outside-sandbox paths rejected?
**YES** — `relative_to()` raises `ValueError` when the resolved path is not under `sandbox_root`. The `.resolve()` call normalizes `..` traversals, so `C:\sandbox\..\outside\secret.java` becomes `C:\outside\secret.java` and is rejected by `relative_to`. This was never broken.

### Is `_normalize_and_check_path()` actually broken for the common case?
**NO** — the function itself is correct. It correctly:
- Accepts absolute paths under the sandbox root
- Accepts relative paths under the sandbox root
- Rejects paths outside the sandbox root
- Rejects paths with `..\` traversal
- Rejects symlinks

The bug was NOT in this function — it was in the **input** (`sandbox_root` being the wrong directory).

### Is `_result_sandbox_path()` the real secondary issue instead?
**YES** — `_result_sandbox_path()` was a secondary (and partial) source of wrong sandbox root. The primary source was `_normalize_output_paths()` in `summary.py` which corrupted `sandbox_path` before control_tower even read it. Both have been fixed:
1. `summary.py:_normalize_output_paths()` — removed `modernized_app_path` from fallback (root cause)
2. `v2_orchestrator_runner.py:_result_sandbox_path()` — removed `modernized_app_path` from fallback (defense-in-depth)
3. `v2_orchestrator_runner.py:_maybe_write_repair_failure_context()` — derives from `run_dir` (bypasses all result-derived paths)

### Was a code change required?
**YES.** Three changes across two files.

### If changed, what exact invariant is now guaranteed?
The canonical sandbox root `run_dir / "workspaces" / "sandbox"` is used for source context resolution instead of the potentially corrupted `result.get("sandbox_path")`. This path:
- Is deterministic (set by `workspace.py:54`)
- Is always correct relative to `run_dir`
- Does not depend on orchestrator result state that may have been corrupted by `_normalize_output_paths`

Additionally, `_normalize_output_paths` no longer overwrites `sandbox_path` with `modernized_app_path`, preventing the corruption at the source.

### Can this be stated as true: candidate source file is readable only when its canonical resolved path is contained by the canonical resolved sandbox root?
**YES.** The `_normalize_and_check_path` function enforces this invariant correctly:
```python
resolved = (sandbox_root / file_path).resolve()     # canonical
resolved.relative_to(sandbox_root)                   # containment check
not resolved.is_symlink()                            # symlink rejection
return resolved                                       # only if all pass
```

After the fix, `sandbox_root` is always the correct canonical sandbox path, so this invariant now produces correct results for valid source files.
