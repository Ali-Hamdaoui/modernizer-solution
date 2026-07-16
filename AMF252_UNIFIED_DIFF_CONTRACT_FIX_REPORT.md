# AMF-252 Unified Diff Contract Fix Report

## Summary

Patched the proposer-facing contract so the repair proposer is explicitly required to emit raw Git unified diff text in `proposed_diff`, and added narrow failure diagnostics to preserve structural evidence when proposer validation fails.

This is a narrow fix in:

- `migration_factory/orchestrator/repair_review_chain.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`

The primary validator was inspected and left unchanged. Reviewer sequencing was also left unchanged.

## Files Changed

- `migration_factory/orchestrator/repair_review_chain.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `AMF252_UNIFIED_DIFF_CONTRACT_FIX_REPORT.md`

## Exact Symbols Changed

- `migration_factory/orchestrator/repair_review_chain.py`
  - `_primary_repair_prompt()`
  - `_persist_proposer_diagnostic()`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
  - `_system_prompt_for_role()`
- Inspected and unchanged:
  - `_validate_primary_repair_output()`

## Proven Runtime Root Cause

The proposer was successfully diagnosing the code but returned `proposed_diff` in Codex/apply_patch dialect instead of raw Git unified diff text.

Observed failure shape:

- `proposed_diff` began with `*** Begin Patch`
- primary semantic validation rejected it with `invalid_response_non_unified_diff`
- reviewer invocation never occurred

This is a contract mismatch, not a code-understanding failure.

## Before Prompt Contract

Before this change, the proposer prompts only said the patch should be a raw Git-style unified diff, and they did not explicitly require:

- `diff --git` as the first non-whitespace content
- `---`, `+++`, and `@@` headers for modified files
- explicit rejection of `*** Begin Patch` / `*** Update File:` / `*** Add File:` / `*** Delete File:`
- explicit invalidation of the Codex/apply_patch dialect for AMF-252

## After Prompt Contract

The proposer contract now explicitly states:

- `proposed_diff` MUST contain raw Git unified diff text
- the first non-whitespace content MUST be `diff --git`
- every modified file MUST use:
  - `diff --git a/<relative-path> b/<relative-path>`
  - `--- a/<relative-path>`
  - `+++ b/<relative-path>`
  - `@@ -oldStart,oldCount +newStart,newCount @@`
- repository paths must be sandbox/repository-relative
- `*** Begin Patch`, `*** Update File:`, `*** Add File:`, `*** Delete File:` are forbidden
- Markdown fences are forbidden inside `proposed_diff`
- explanatory prose, plain source code, JSON, and absolute host paths are forbidden inside `proposed_diff`
- if no safe unified diff can be produced, the model must fail closed with:
  - `proposed_diff = ""`
  - `deterministic_rule_id = "no_safe_rule"`
  - `no_fix_reason = "<specific reason>"`

## Exact Valid Unified-Diff Example Added

```diff
diff --git a/src/main/java/com/example/Foo.java b/src/main/java/com/example/Foo.java
--- a/src/main/java/com/example/Foo.java
+++ b/src/main/java/com/example/Foo.java
@@ -10,1 +10,1 @@
-    final Sort sort = new Sort(direction, column);
+    final Sort sort = Sort.by(direction, column);
```

## Exact Forbidden Apply_Patch Markers Added

```text
*** Begin Patch
*** Update File:
*** Add File:
*** Delete File:
*** End Patch
```

The primary prompt also states that this Codex/apply_patch dialect is invalid for AMF-252.

## Validator

`_validate_primary_repair_output()` was not changed.

Why:

- the current blocker is upstream contract mismatch, not a missing semantic guard
- the existing validator already remains fail-closed for malformed `proposed_diff`
- keeping the validator unchanged preserves the current reviewer gate behavior

## Reviewer Sequencing

Unchanged.

Reviewer invocation still occurs only after primary output parsing and validation pass.

## Diagnostic Improvements

Added narrow structural diagnostics to `repair_diagnostic_proposer.json` when proposer validation fails:

- `proposed_diff_length`
- `proposed_diff_checksum`
- `proposed_diff_format`
- `proposed_diff_preview`
- `has_diff_git`
- `has_old_file_marker`
- `has_new_file_marker`
- `has_hunk_marker`
- `has_apply_patch_begin`
- `has_apply_patch_update_file`

These fields preserve failure shape without exposing the full patch through the public artifact.

## Static Checks Performed

- `py -m py_compile migration_factory/orchestrator/repair_review_chain.py`
- `py -m py_compile migration_factory/control_tower/application/v2_assistant_model_client.py`
- `git diff --check`
- `git diff --stat`
- `git status --short`
- Static call-site inspection for:
  - `_primary_repair_prompt`
  - `_system_prompt_for_role`
  - `_validate_primary_repair_output`

Result:

- both Python files compiled successfully
- `git diff --check` passed after fixing one trailing-whitespace issue; Git still emitted existing LF/CRLF conversion warnings on unrelated tracked files
- `git diff --stat` and `git status --short` showed pre-existing unrelated workspace changes in addition to the two targeted edits

## Remaining Unknowns

- whether every future proposer completion will obey the stricter prompt contract
- whether there are other proposer paths outside this chain that can still emit apply_patch dialect
- whether the new structural diagnostics are sufficient for any future malformed proposer outputs

## GO / NO-GO For One Controlled Runtime Test

GO.

Rationale: the failure was a patch-dialect contract mismatch, and the proposer contract is now explicit enough to require raw Git unified diff output while keeping fail-closed behavior intact.

## Decision Table

- Compiler evidence path: unchanged
- Source-context path: unchanged
- Model transport: unchanged
- Primary schema: unchanged
- Proposer system prompt: changed
- Primary repair prompt: changed
- Primary validator: unchanged
- Reviewer flow: unchanged
- Patch gate: unchanged
- Frontend: unchanged
