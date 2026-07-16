# SUBAGENT B — Complete Source Context Trace

## 1. What exact `sandbox_root` is passed?

**File:** `migration_factory/control_tower/application/v2_orchestrator_runner.py:1278`
```python
sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")
```
`result` is the orchestrator final JSON dict. `sandbox_path` inside that dict is resolved by `_result_sandbox_path()` at line 2559:

```python
def _result_sandbox_path(result: dict[str, Any]) -> str:
    artifact_refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}
    direct = _first_text(
        result.get("sandbox_path"),
        result.get("modernized_app_path"),
        result.get("output_app_path"),
        artifact_refs.get("sandbox"),
        artifact_refs.get("sandbox_path"),
        artifact_refs.get("modernized_app"),
        artifact_refs.get("modernized_app_path"),
    )
    if direct:
        return direct
    summary_ref = _first_text(artifact_refs.get("orchestration_summary"), result.get("orchestration_summary"))
    if summary_ref:
        try:
            summary_path = Path(summary_ref)
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                return _first_text(summary.get("sandbox_path"), ...)
        except Exception:
            return ""
    return ""
```

## 2. Is it `modernized-v2-runs` root OR run-specific `workspaces\sandbox`?

The orchestrator runner is launched with argv built in `_build_phase_argv()` (line 2101-2155). The `setup.output_parent_path` is passed as `--modernized`. The orchestrator result `sandbox_path` is typically a **run-specific sandbox workspace** — e.g. `<run_dir>/workspaces/sandbox` — set by the orchestrator subprocess (runner.py). The actual value originates from the orchestrator process and is included in its final JSON output.

## 3. Where does `sandbox_root` originate? (trace back)

```
1. Orchestrator subprocess (migration_factory/orchestrator/runner.py)
   → produces FINAL_JSON with "sandbox_path" key

2. V2OrchestratorRunner._run_process() [v2_orchestrator_runner.py:316]
   → subprocess stdout → _extract_final_json() [line 2494]
   → returns result dict

3. V2OrchestratorRunner._handle_exit() [line 544]
   → calls _maybe_write_repair_failure_context() [line 632]

4. _maybe_write_repair_failure_context() [line 1210]
   → result dict has "sandbox_path" populated by _result_sandbox_path(result) [line 627-630]
   
5. Line 1278: sandbox_root = str(result.get("sandbox_path") or result.get("sandbox_root") or "")
```

## 4. Can an absolute Maven path resolve correctly?

**NO — on Windows.** This is the root cause of the bug.

**File:** `migration_factory/repair_loop/repair_context.py:53-64`
```python
def _normalize_and_check_path(file_path: str, sandbox_root: Path) -> Path | None:
    resolved = (sandbox_root / file_path).resolve()
    try:
        resolved.relative_to(sandbox_root)
    except ValueError:
        return None
    if resolved.is_symlink():
        return None
    return resolved
```

On Windows, when `file_path` is absolute (e.g. `C:\Users\...\.migration\runs\R123\workspaces\sandbox\src\main\java\Foo.java`):
- `Path(sandbox_root) / absolute_file_path` → the absolute right operand **replaces** the left operand (Python pathlib behavior on Windows: `Path('D:\\sandbox') / 'C:\\abs\\path'` → `C:\\abs\\path`)
- `resolved.relative_to(sandbox_root)` → **ValueError** because the resolved path is not under sandbox_root
- Function returns `None`
- File is **silently skipped**

**On Linux**, absolute paths (`/home/user/.../Foo.java`) also replace the left operand, so they also fail `relative_to`. Only if the file_path is already under sandbox_root (but then they'd be sandbox-relative) would it work.

## 5. Can a sandbox-relative Java path resolve correctly?

**YES** — if `file_path` is relative (e.g. `src/main/java/Foo.java`):
- `Path(sandbox_root) / 'src/main/java/Foo.java'` → `Path('<sandbox>/src/main/java/Foo.java')`
- `resolved.relative_to(sandbox_root)` → succeeds
- File is read

## 6. How are Windows paths handled? (backslashes vs forward slashes)

No explicit normalization. The `file_path` comes from the Maven regex at `v2_orchestrator_runner.py:2596`:
```python
_RE_JAVAC_ERROR = re.compile(
    r'\[ERROR\]\s+(.+?\.[Jj][Aa][Vv][Aa])\s*:\s*\[?(\d+)(?:,\s*(\d+))?\]?\s+(.+)',
)
```
Group 1 (`file_path`) captures the path exactly as Maven/javac emits it — Windows paths with backslashes (`C:\Users\...`). These are passed directly to Path(), which on Windows handles both separators internally. No `replace("\\", "/")` is applied anywhere between regex → `NormalizedCompilerError` → `_normalize_and_check_path` → `relative_to`.

## 7. Is path traversal blocked?

**YES.** `_normalize_and_check_path` at `repair_context.py:57-59`:
```python
resolved = (sandbox_root / file_path).resolve()
try:
    resolved.relative_to(sandbox_root)
except ValueError:
    return None
```
`resolve()` resolves `..` components, then `relative_to()` checks containment. Any traversal escaping sandbox_root → ValueError → return None.

## 8. Are symlink escapes blocked?

**YES.** `repair_context.py:62-63`:
```python
if resolved.is_symlink():
    return None
```

## 9. What happens when `compiler_errors` is empty?

**File:** `v2_orchestrator_runner.py:1251-1256`
```python
compiler_errors = ()
if failure_source == FailureSource.BUILD:
    compiler_errors = _normalize_compiler_errors(...)
```
If failure_source is TEST (not BUILD), `compiler_errors` stays `()`. But the guard at line 1279:
```python
if sandbox_root and (compiler_error_locations or changed_files):
```
still passes if `changed_files` is non-empty, so source context can still be built from changed_files.

## 10. What happens when `changed_files` is empty?

Same guard at line 1279 — if sandbox_root is set AND at least one of `compiler_error_locations` or `changed_files` is non-empty, `build_bounded_source_context` is called. If both are empty, it is skipped entirely → `source_contexts = ()`.

## 11. Why was `source_contexts` absent from runtime `repair_context_pack.json`?

**Root cause chain:**

1. Maven emits absolute paths: `[ERROR] C:\Users\...\.migration\runs\R123\workspaces\sandbox\src\main\java\Foo.java:[42,17] error: cannot find symbol`
2. `_normalize_compiler_errors()` regex extracts `file_path` = `C:\Users\...\Foo.java` (absolute)
3. `sandbox_root` = `C:\Users\...\.migration\runs\R123\workspaces\sandbox` (also absolute, but different object)
4. In `_normalize_and_check_path()`: `(sandbox_root / file_path)` on Windows → file_path is absolute → **right operand replaces left** → result is `file_path` unchanged
5. `resolved.relative_to(sandbox_root)` → **ValueError** (not a subpath) → return `None`
6. **Every file is skipped** → `source_contexts = ()` (empty tuple)
7. `build_repair_context_pack(source_contexts=())` → line 261: `tuple(source_contexts or ())` → empty
8. `context_pack_to_dict()` at line 352: `if pack.source_contexts:` → **False** → no `"source_contexts"` key in JSON
9. JSON written to `repair_context_pack.json` → **no `source_contexts` key**

Secondary scenario: If `sandbox_root` itself was empty string (line 1278 fallback), then guard at line 1279 fails and `build_bounded_source_context` is never called.

## 12. Does `RepairContextPack` actually declare `source_contexts`?

**YES.** `migration_factory/repair_loop/repair_context.py:159`:
```python
@dataclass(frozen=True)
class RepairContextPack:
    ...
    source_contexts: tuple[RepairSourceContext, ...] = ()
```

## 13. Does `context_pack_to_dict` serialize it?

**YES — conditionally.** `repair_context.py:328-364`:
```python
def context_pack_to_dict(pack: RepairContextPack) -> dict[str, Any]:
    result = { ... }
    if pack.source_contexts:                        # line 352
        result["source_contexts"] = [               # line 353
            {
                "path": sc.path,
                "content_checksum": sc.content_checksum,
                "start_line": sc.start_line,
                "end_line": sc.end_line,
                "content": sc.content,              # line 359 — FULL content included
                "reason_included": sc.reason_included,
            }
            for sc in pack.source_contexts
        ]
    return result
```
If `source_contexts` is empty tuple, the key is **omitted** from the dict.

## 14. Does `_context_pack_from_dict` restore it?

**YES.** `migration_factory/control_tower/application/v2_repair_gate_service.py:1744-1785`:
```python
def _context_pack_from_dict(data: dict[str, Any]) -> Any:
    raw_contexts = data.get("source_contexts") or ()   # line 1750
    source_contexts: list[RepairSourceContext] = []
    for sc in raw_contexts:
        if isinstance(sc, dict):
            source_contexts.append(RepairSourceContext(
                path=str(sc.get("path", "")),
                content_checksum=str(sc.get("content_checksum", "")),
                start_line=int(sc.get("start_line", 0)),
                end_line=int(sc.get("end_line", 0)),
                content=str(sc.get("content", "")),
                reason_included=str(sc.get("reason_included", "")),
            ))
    ...
    return RepairContextPack(
        ...
        source_contexts=tuple(source_contexts),    # line 1784
    )
```
If `source_contexts` key is absent from JSON, `data.get("source_contexts")` returns `None`, `or ()` makes it empty tuple → `source_contexts` stays empty.

## 15. Does checksum calculation include it?

**YES — partially.** `repair_context.py:162-193`:
```python
def compute_context_pack_checksum(pack: RepairContextPack) -> str:
    payload: dict[str, Any] = {
        ...
        "source_contexts": [
            {
                "path": sc.path,
                "content_checksum": sc.content_checksum,
                "start_line": sc.start_line,
                "end_line": sc.end_line,
                "reason_included": sc.reason_included,
            }
            for sc in pack.source_contexts
        ],
    }
```
**Note:** `content` is **NOT** included in the checksum payload. This means two packs with the same context metadata but different source content would have the same checksum. This is a secondary bug.

## 16. Does `_primary_repair_prompt` actually include source contents?

**YES — when source_contexts is non-empty.** `repair_review_chain.py:87-127`:
```python
def _primary_repair_prompt(context_pack, deterministic_checksum):
    context_dict = context_pack_to_dict(context_pack)
    source_contexts = context_dict.get("source_contexts") or []   # line 89
    source_section = ""
    if source_contexts:                                            # line 90
        parts = []
        for sc in source_contexts:
            parts.append(
                f"--- {sc['path']} (lines {sc['start_line']}-{sc['end_line']}, "
                f"reason: {sc['reason_included']}) ---\n"
                f"{sc['content']}\n"
                f"--- end {sc['path']} ---"
            )
        source_section = "\n\nSOURCE CONTEXT:\n" + "\n\n".join(parts)
    return (f"You are the AMF-252 repair proposer.\n..."
            f"{source_section}\n\n"
            f"Context:\n{json.dumps(context_dict, sort_keys=True)}")   # line 126
```
If `source_contexts` is empty (because serialization omitted it), then `source_section = ""` and **no Java source code appears in the prompt**. The full `context_dict` is still appended at line 126 but does NOT contain the `source_contexts` key.

## 17. If compiler errors become valid, is there any NEXT blocker preventing actual Java code from reaching GPT-5 mini?

**Potential blockers, in order:**

| Blocker | Location | Condition |
|---|---|---|
| `MAX_SOURCE_CONTEXT_FILES = 3` | repair_context.py:37 | At most 3 files can be included |
| `MAX_SOURCE_CONTEXT_CHARS = 40000` | repair_context.py:40 | Total excerpt chars capped at 40K |
| Empty excerpt check | repair_context.py:114 | `if not excerpt.strip(): continue` |
| Remaining budget < 200 | repair_context.py:118-122 | Skips file if <200 chars remain |
| File not found | repair_context.py:102-103 | `if not normalized.is_file(): continue` |
| Read error | repair_context.py:105-107 | OSError/UnicodeDecodeError → skip |
| `#AZURE_OPENAI_PROPOSER_DEPLOYMENT` not set | v2_model_role_router.py:85 | `os.environ.get(primary_env_ref, "")` empty → `_try_invoke` returns None → maybe fallback |
| Fallback also unavailable | v2_model_role_router.py:125-158 | Fallback deployment empty or fails → `_deterministic_result` with `success=False` |
| Proposer output fails validation | repair_review_chain.py:556-613 | JSON parse fail, missing fields, markdown-fenced diff, empty diff |
| Reviewer rejects | repair_review_chain.py:702-705 | `reviewer_output["decision"] != "accept"` |

**If all these pass, Java source DOES reach GPT-5 mini** via the `_primary_repair_prompt` string passed to `client.answer_with_role(role=V2ModelRole.PROPOSER, prompt=...)` at `repair_review_chain.py:534-536`.

---

## ACTUAL SANDBOX ROOT:
Result dict key `"sandbox_path"` (populated by `_result_sandbox_path()` at `v2_orchestrator_runner.py:2559`). Falls back through `"modernized_app_path"`, `"output_app_path"`, `artifact_refs["sandbox"]`, etc. On failure: empty string.

Actual value at runtime: typically `<run_dir>/workspaces/sandbox` — e.g. `C:\Users\...\.migration\runs\R123\workspaces\sandbox`.

## PATH RESOLUTION VERDICT:
**FAIL on Windows.** Absolute Maven paths (extracted by `_RE_JAVAC_ERROR` regex at `v2_orchestrator_runner.py:2596`) always fail in `_normalize_and_check_path()` at `repair_context.py:57` because `Path(sandbox_root) / absolute_path` discards sandbox_root on Windows, and `relative_to(sandbox_root)` raises ValueError. Result: every file skipped, `source_contexts = ()`.

## SERIALIZATION VERDICT:
`context_pack_to_dict()` at `repair_context.py:352` only serializes `source_contexts` if non-empty. Empty tuple → key omitted from JSON → absent from `repair_context_pack.json`. Checksum calculation (`compute_context_pack_checksum` at `repair_context.py:182`) always includes source_contexts metadata but **omits `content`**.

## PROMPT DELIVERY VERDICT:
When `source_contexts` is empty (due to path resolution failure), `_primary_repair_prompt()` at `repair_review_chain.py:89-90` produces `source_section = ""`. The `Context:` JSON dump at line 126 also lacks `source_contexts` key. **No Java source reaches GPT-5 mini.** When source_contexts IS non-empty, the `content` field is fully included in the prompt.

## NEXT LIKELY BLOCKER:
After fixing path resolution, the next blocker is most likely:
1. **Proposer model unavailable** — `AZURE_OPENAI_PROPOSER_DEPLOYMENT` env var not set → `_try_invoke` returns `None` → deterministic fallback with `success=False` → `RepairReviewChainProductionError`
2. **Reviewer rejects** — mismatched checksums or policy violations cause `reviewer_output["decision"] != "accept"` → chain fails closed

## MINIMUM FIX BOUNDARY:
**File:** `migration_factory/repair_loop/repair_context.py`

**Location:** `build_bounded_source_context()` (line 75-133) and `_normalize_and_check_path()` (line 53-64)

**Fix:** Before joining with `sandbox_root`, strip the drive/prefix from absolute `file_path` so it becomes sandbox-relative. Options:
- **Option A** (in `_normalize_and_check_path`): If `file_path` is absolute and `file_path` starts with `sandbox_root`, extract the relative suffix manually instead of relying on pathlib `/` operator.
- **Option B** (in `_normalize_and_check_path`): Use `os.path.relpath(file_path, sandbox_root)` as fallback when `relative_to` fails, then re-check.
- **Option C** (in `build_bounded_source_context`): Strip paths to their sandbox-relative form before calling `_normalize_and_check_path` (e.g., if `file_path` starts with `sandbox_root`, remove the prefix).

**Additional:** `compute_context_pack_checksum` at `repair_context.py:182-191` should include `content` in the checksum payload to prevent silent content drift.
