# AMF-252 Windows Compiler Path Fix Report

## Summary

Patched the javac compiler-error normalization path so malformed Windows drive paths of the form `/C:/...` are normalized to `C:/...` before they are stored in `NormalizedCompilerError.file_path`.

This is a narrow fix only in `migration_factory/control_tower/application/v2_orchestrator_runner.py`. The source-context containment gate in `migration_factory/repair_loop/repair_context.py` was inspected and left unchanged.

## Files Changed

- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `AMF252_WINDOWS_COMPILER_PATH_FIX_REPORT.md`

## Exact Symbols Changed

- `_RE_JAVAC_ERROR` was left unchanged.
- Added `_normalize_compiler_source_path(value: str) -> str`.
- Updated `_normalize_compiler_errors()` to call `_normalize_compiler_source_path(m.group(1))` before creating `NormalizedCompilerError`.

## Before / After Path Examples

### Malformed Windows drive path

- Before: `/C:/Users/abdelilah.mortaki/Desktop/modernized-v2-runs/.migration/runs/v2-1b9ac07d/workspaces/sandbox/src/main/java/com/total/corp/common/dto/DTOHelpers.java`
- After: `C:/Users/abdelilah.mortaki/Desktop/modernized-v2-runs/.migration/runs/v2-1b9ac07d/workspaces/sandbox/src/main/java/com/total/corp/common/dto/DTOHelpers.java`

### Normal Windows absolute path

- Before: `C:/Users/abdelilah.mortaki/Desktop/modernized-v2-runs/.migration/runs/v2-1b9ac07d/workspaces/sandbox/src/main/java/com/total/corp/common/dto/DTOHelpers.java`
- After: `C:/Users/abdelilah.mortaki/Desktop/modernized-v2-runs/.migration/runs/v2-1b9ac07d/workspaces/sandbox/src/main/java/com/total/corp/common/dto/DTOHelpers.java`

### POSIX path

- Before: `/home/user/Foo.java`
- After: `/home/user/Foo.java`

## Containment Verdict

`migration_factory/repair_loop/repair_context.py` still enforces:

- `candidate.resolve()`
- `candidate.relative_to(sandbox)`
- `candidate.is_file()`

So sandbox containment remains intact. This patch does not weaken source-path filtering or add any outside-sandbox fallback.

## Static Checks

Requested checks are to be run only:

- `py -m py_compile migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `py -m py_compile migration_factory/repair_loop/repair_context.py`
- `git diff --check`
- `git diff --stat`
- `git status --short`

## Remaining Unknowns

- Whether the malformed `/C:/...` shape appears only in javac output or also in other compiler/error sources.
- Whether there are other path-normalization sites elsewhere in the repair pipeline that can emit the same malformed shape.
- Whether the next controlled runtime test will now produce non-empty source contexts for the two compiler errors.

## GO / NO-GO For One Controlled Runtime Test

GO.

Rationale: the parser already extracts the real compiler errors, and this fix only normalizes the malformed Windows drive prefix before source resolution. It does not change containment, redaction, prompts, transport, or reviewer flow.
