# AMF-252 Soft Materialization and Git Recovery Audit

## Executive Summary
The current failure is not an apply-time sandbox failure and not a rebuild/test regression. The reviewed repair chain produced a reviewer-accepted diff, but backend materialization rejected it before approval because the reviewed diff was not structurally safe enough to expose as an applyable proposal.

The persisted reviewed diff for job `c929857bcd0142e89898a4cf43cbe464` is malformed in a very specific way:
- the second `diff --git` file block starts with a leading space, so it is no longer a real file header
- the persisted diff does not contain a literal `?` line, but the backend recount failure message indicates that a transient `?`-prefixed contamination was seen during materialization or cleanup
- the reviewer-accepted diff therefore needs a soft recovery pipeline before the backend decides it is unrecoverable

The right fix is a centralized, backend-only soft materialization pipeline in `v2_repair_gate_service.py`, backed by normalization helpers in `safe_diff_preview.py`, that:
- preserves the raw reviewed diff artifact unchanged
- creates a sanitized candidate artifact separately
- retries safe recovery steps in a temp sandbox only
- only exposes `approve_sandbox_apply` after a recovered canonical diff passes strict validation
- keeps the final Apply path strict and unsafe-free

## Evidence From Current Job
Current job: `c929857bcd0142e89898a4cf43cbe464`

Observed job state from the run artifacts:
- `failure_summary = BUILD_FAILED_IN_SANDBOX`
- reviewer completed and returned `decision = accept`
- `proposal_created = false`
- `gate_created = false`
- `policy_ran = false`
- `reviewer_self_repair_attempted = false`
- `reviewer_self_repair_succeeded = false`
- `backend_generated_diff = false`
- `backend_import_replacement_fallback_attempted` is absent in the persisted chain
- `reviewer_applicability_repair_attempted` is absent in the persisted chain
- `retry_status` is not populated in the persisted `review_chain.json`
- backend unavailable state reported `kind = materialization_failed`
- backend unavailable reason was `MALFORMED_DIFF`
- detail was `hunk_count_mismatch_recount_failed: git apply --check --recount failed: warning: recount: unexpected line: ? error: corrupt patch`

Artifact evidence:
- `repair_failure_evidence.json` confirms the compilation failure was a type mismatch in two files:
  - `SearchService.java`
  - `DTOHelpers.java`
- `repair_context_pack.json` shows the repair intent was narrow and grounded:
  - replace `new Sort(..., <String>)` with `new Sort(..., Collections.singletonList(<String>))`
  - add `java.util.Collections` import where needed
- `review_chain.json` shows the reviewer accepted the repair and the final reviewed diff existed
- `final_reviewed_repair_artifact.json` and `reviewer_repair_llm_output.json` both reflect an accepted reviewer output

## Exact Bad Diff Analysis
Persisted diff file:
- [`final_reviewed_repair.diff`](C:/Users/abdelilah.mortaki/Desktop/modernized-v2-runs/.migration/runs/v2-c929857b/repair_chain/final_reviewed_repair.diff)

Exact malformed lines in the persisted artifact:
- line 18 is ` diff --git a/src/main/java/com/total/corp/common/dto/DTOHelpers.java b/src/main/java/com/total/corp/common/dto/DTOHelpers.java`
- that leading space means the second file header is no longer a real `diff --git` header
- the rest of the second file block then follows as if it were context inside the first hunk

What I could confirm and what I could not:
- I could confirm the persisted diff does not contain a literal line starting with `?`
- I could not confirm a literal `?` line in the final file because it is not present on disk in the reviewed artifact
- the backend recount error still strongly suggests a transient `?`-prefixed contamination was present in the validation path or in an earlier in-memory candidate

What this means structurally:
- the patch is not just wrong counts
- it is structurally invalid because one file block is misframed
- the hunk count mismatch is a consequence, not the only issue
- the raw diff also appears to have been contaminated by a non-unified-diff line in the materialization path, based on the recount error message

Why `git apply --check --recount` failed:
- `git apply` requires a clean unified diff structure
- the reviewed diff already contains a malformed file-header transition
- recount then trips on the unexpected non-patch line content and reports `corrupt patch`
- because the temp validation failed before a canonicalized patch could be produced, backend materialization stopped

## Current Code Path
Where the diff is generated:
- `migration_factory/orchestrator/repair_review_chain.py`
- `produce_repair_review_chain()` writes `final_reviewed_repair.diff` and `final_reviewed_repair_artifact.json`
- reviewer self-repair and schema repair live here already

Where reviewer output is accepted:
- `migration_factory/orchestrator/repair_review_chain.py`
- reviewer accept-contract handling and final diff persistence happen near the end of the chain
- `skip_self_repair=True` is set by the gate-service caller for this reviewed-repair path, so reviewer self-repair is intentionally bypassed in this job

Where `final_reviewed_repair.diff` is written:
- `migration_factory/orchestrator/repair_review_chain.py`
- the file is written after reviewer accept handling and after the optional import-replacement fallback branch

Where `build_safe_diff_preview` runs:
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `_validate_direct_proposal_diff()` calls `build_safe_diff_preview()` before any approval exposure
- `migration_factory/control_tower/application/v2_repair_projection.py` also uses `build_safe_diff_preview()` when building proposal projections

Where `canonicalize_with_recount` runs:
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `_validate_direct_proposal_diff()` calls `canonicalize_with_recount()` only when the preview reports `hunk_count_mismatch`

Where materialization failure is emitted:
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `_emit_reviewed_repair_materialization_failed()` writes the backend unavailable event
- `_emit_reviewed_repair_unavailable()` mirrors that into the unavailable projection

Where the current stage is stopped:
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `create_reviewed_repair_gate_on_failure()` returns early if direct proposal validation fails

Why self-repair/fallback did not run for this job:
- `reviewer_self_repair` did not run because the reviewed chain was invoked with `skip_self_repair=True`
- `reviewer_applicability_repair` only runs later, in the gated apply-check path, after a materialized proposal exists
- `backend_import_replacement_fallback` is only attempted inside `produce_repair_review_chain()` when the reviewer output itself has a mechanical structural issue before the final reviewed diff is persisted
- this job reached the later direct-materialization validation stage with a reviewer-accepted reviewed diff already written, so the earlier repair hooks were no longer in play

## Existing Recovery Hooks
| Hook / field / function | Exists? | Currently wired? | Why not triggered for `c929857b...` | Should wire now? |
|---|---:|---:|---|---:|
| `reviewer_self_repair` | Yes | Yes, in `repair_review_chain.py` | `skip_self_repair=True` on the reviewed-repair chain bypassed it | Yes, but only as part of the soft recovery orchestration, not by changing the main review path |
| `reviewer_applicability_repair` | Yes | Yes, in `v2_repair_gate_service.py` | Only runs after a proposal exists and `PATCH_CHECK_FAILED` occurs | Yes, but only after recovery produces a canonical diff |
| `reviewer_self_repair_schema_repair` | Yes | Yes, in `repair_review_chain.py` | Would only matter during reviewer self-repair or reviewer schema failure | Yes, but not as the first-line fix for this case |
| `backend_generated_diff` | Yes | Partially, via import replacement fallback | The reviewed diff never reached a successful backend-generated replacement promotion | Yes, as a deterministic fallback flag for recognized simple repairs |
| `backend_import_replacement_fallback` | Yes | Yes, in `repair_review_chain.py` | The failure here is in reviewed-diff materialization, not the earlier reviewer mechanical issue branch | Yes, but only if the reviewed diff remains structurally unrecoverable |
| `canonicalize_with_recount` | Yes | Yes, in `safe_diff_preview.py` and `v2_repair_gate_service.py` | It ran too late and only as a single retry strategy | Yes, but as one step inside a larger soft recovery pipeline |

Other relevant existing hooks:
- `build_safe_diff_preview()` exists and is already the right place to centralize text cleanup and parse status
- `reviewed_repair_unavailable` exists and already carries many useful fields
- `retry_status` / `retry_reason` already exist in the unavailable payload path
- `patch_apply.py` already has strict validation and should remain unchanged for the final apply path

## Proposed Soft Materialization Pipeline
Centralize this in `v2_repair_gate_service.py`, with reusable cleanup helpers in `safe_diff_preview.py`.

Proposed sequence:
1. Receive raw reviewer diff artifact.
2. Preserve the raw artifact unchanged and keep its checksum.
3. Normalize text in a new helper:
   - strip BOM
   - normalize CRLF to LF
   - strip trailing NUL/control contamination
   - remove Markdown fences if present
   - isolate the first valid unified-diff block
4. Produce a sanitized candidate artifact separately, with its own checksum and metadata.
5. Run `build_safe_diff_preview()` on the sanitized candidate, not on the raw string.
6. If preview is structurally clean, continue with strict validation.
7. If preview reports hunk count mismatch:
   - try `git apply --check --recount --verbose` in a temp sandbox only
   - if that passes, apply in temp copy and regenerate canonical diff with `git diff --binary`
8. If counts are structurally okay but context is fragile:
   - try whitespace-tolerant dry-run in temp sandbox only
   - if it passes, apply in temp copy and regenerate canonical diff
9. If blob/index metadata exists:
   - try a temp-only `git apply --3way --check`
   - if a safe 3-way recovery works, regenerate canonical diff from the temp copy
10. If the patch is still ambiguous, use `git apply --reject` in temp copy only for diagnostics.
11. If the repair intent is simple and grounded, try deterministic backend regeneration:
   - recognize `new Sort(<direction>, <stringColumn>)`
   - rewrite to `new Sort(<direction>, java.util.Collections.singletonList(<stringColumn>))`
   - add the `java.util.Collections` import if needed
   - write edits into temp copy only
   - regenerate canonical diff with `git diff --binary`
12. If recovery succeeds:
   - persist a recovered canonical diff artifact separately
   - recompute checksum
   - mark `safe_diff_preview.parse_status = parsed`
   - mark applicability `passed`
   - expose `approve_sandbox_apply` only now
13. If recovery fails:
   - preserve raw and sanitized artifacts
   - emit an unavailable state that says backend soft recovery was exhausted
   - do not create a proposal
   - do not start apply/rebuild/test

Important boundary:
- do not let `--reject` or partial temp-only application ever authorize final approval
- the final approval gate must still require a clean canonical diff that passes strict `git apply --check`

## Proposed Git Soft Strategy
Strict rule:
- final approval must still require a clean canonical diff

Command strategy:
- strict first:
  - `git apply --check --verbose <diff>`
- recount retry:
  - `git apply --check --recount --verbose <diff>`
- whitespace-tolerant temp-only retry:
  - `git apply --check --ignore-space-change --ignore-whitespace --whitespace=fix <diff>`
- 3-way temp-only retry when metadata supports it:
  - `git apply --3way --check <diff>`
- diagnostic-only temp copy:
  - `git apply --reject <diff>`
- final gate before exposing Apply:
  - regenerated canonical diff must pass `git apply --check --verbose <canonical.diff>`

Sandbox rules:
- real sandbox: only strict validation of the final canonical diff
- temp sandbox: all recovery experiments, including reject, 3-way, and whitespace-tolerant attempts
- never apply a malformed diff to the real sandbox

Why `--reject` is temp-only:
- it can leave partial application artifacts
- it is diagnostic, not authorization
- it is useful only to understand whether a clean regeneration is possible

Why final Apply still needs a clean diff:
- because user approval is a trust boundary
- because partial application or reject output does not prove the final artifact is safe
- because final approval must be based on a deterministic canonical diff, not a recovery experiment

## Backend State/UX Strategy
Current behavior is too terminal for a recoverable format failure. `MALFORMED_DIFF` is being turned into a hard unavailable state immediately.

Recommended state model:
- keep `reviewed_repair_materialization_failed`
- add a softer retry state when recovery remains possible, such as:
  - `repair_materialization_retry_required`
  - `waiting_for_backend_retry`
  - `reviewed_repair_unavailable`
  - `repair_loop_status = MATERIALIZATION_RETRY_REQUIRED`
- avoid terminal `stage_failed` if recovery attempts remain

Recommended UX:
- “Reviewed repair needs backend retry”
- “Diff was malformed and could not be safely materialized”
- “No apply/rebuild/test started”
- “Recovery attempts: normalized / recount / whitespace / 3way / backend generated”
- if recovery succeeds, show the recovered canonical diff
- if recovery fails, do not expose approve action

Current contract support:
- `RepairMaterializationUnavailable` already has:
  - `retry_status`
  - `retry_reason`
  - `reviewer_applicability_repair_attempted`
  - `reviewer_applicability_repair_succeeded`
  - `reviewer_self_repair_attempted`
  - `reviewer_self_repair_succeeded`
  - `backend_import_replacement_fallback_*`
  - `backend_generated_diff`
- this is enough for a coarse retry/unavailable message

Missing for the soft-recovery UX:
- `soft_recovery_attempted`
- `soft_recovery_steps`
- `soft_recovery_status`
- `recovered_diff_checksum`
- `recovered_diff_ref`
- `materialization_retry_status`

Conclusion on projection fields:
- existing fields are enough to render a basic unavailable state
- new fields are needed if the UI must show the exact soft recovery sequence and the recovered canonical artifact reference

## Files To Change
Likely:
- [`migration_factory/control_tower/application/v2_repair_gate_service.py`](C:/Users/abdelilah.mortaki/Desktop/modernizer-solution/migration_factory/control_tower/application/v2_repair_gate_service.py)
  - centralize the reviewed-diff soft materialization pipeline
  - keep final Apply strict
  - emit soft-recovery-aware unavailable state
- [`migration_factory/control_tower/application/safe_diff_preview.py`](C:/Users/abdelilah.mortaki/Desktop/modernizer-solution/migration_factory/control_tower/application/safe_diff_preview.py)
  - add normalization helpers
  - add sanitized-candidate parsing support
  - keep parse status and checksum behavior deterministic

Possibly:
- [`migration_factory/control_tower/application/v2_repair_projection.py`](C:/Users/abdelilah.mortaki/Desktop/modernizer-solution/migration_factory/control_tower/application/v2_repair_projection.py)
  - surface soft recovery metadata if the API contract is extended
- [`web/control-tower/lib/contracts.ts`](C:/Users/abdelilah.mortaki/Desktop/modernizer-solution/web/control-tower/lib/contracts.ts)
  - only if new soft-recovery fields are added to the API contract
- [`web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx`](C:/Users/abdelilah.mortaki/Desktop/modernizer-solution/web/control-tower/app/migrations/[jobId]/RepairProposalPanel.tsx)
  - only if the new fields need to be rendered

## Files Not To Change
- do not change the apply/rebuild/test continuation path
- do not change `run_validation_after_patch`
- do not duplicate `run_build_agent` or `run_test_agent`
- do not refactor `_handle_exit`
- do not rewrite LangGraph
- do not change the direct apply endpoint unless a clear bug is proven
- do not change `migration_factory/repair_loop/patch_apply.py` unless a tiny shared helper becomes unavoidable

## Implementation Plan Without Tests
No tests.
No pytest.
No npm test.
No vitest.

Phase 1: audit artifact and exact bad line
- preserve the raw reviewed diff artifact
- record the precise malformed line and whether the transient `?` came from a cleanup artifact or a reviewer payload contamination

Phase 2: add diff normalization helper
- centralize BOM, CRLF, fence, and control-character cleanup in `safe_diff_preview.py`
- isolate the first valid unified-diff block
- make sanitization explicit and artifacted

Phase 3: add a soft recovery orchestrator/helper
- create a single recovery flow for reviewed diffs in `v2_repair_gate_service.py`
- drive recount, whitespace-tolerant, 3-way, and reject-only diagnostics in temp sandboxes only

Phase 4: wire into direct reviewed/candidate materialization
- apply the soft recovery path before materialization failure is emitted
- keep candidate diff handling unchanged unless a tiny shared fix is proven necessary

Phase 5: add deterministic backend generation only for recognized simple repair classes
- support the narrow `Sort(String)` to `Collections.singletonList(String)` rewrite
- keep it grounded in the context pack and source excerpts

Phase 6: improve unavailable projection fields
- add `soft_recovery_*` or `materialization_retry_status` only if the UI needs them
- otherwise keep the contract minimal and reuse existing retry fields

Phase 7: keep the final approval gate strict
- only expose approval after a recovered canonical diff passes strict `git apply --check`
- never authorize approval from reject-only or partial temp application

## Acceptance Criteria
- malformed reviewed diff gets soft recovery attempts before unavailable
- raw bad diff is preserved as an artifact
- sanitized or recovered diff is persisted separately with checksum
- recovered diff must pass safe preview and strict git validation
- `approve_sandbox_apply` is exposed only after the final canonical diff passes
- failed recovery does not start apply/rebuild/test
- no duplicated build/test/orchestrator logic
- the current `MALFORMED_DIFF` case produces a clearer retry/recovery state

## Safe Commands Only
Allowed:
- inspect files
- `git diff`
- `git status`
- `py_compile` if code changes are later approved

Not allowed:
- `pytest`
- `npm test`
- `vitest`
- full migration
- external APIs
- real LLM calls

