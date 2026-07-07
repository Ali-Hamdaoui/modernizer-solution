# AMF-252 Repair UI/Gate Forensics

Job: 2223d92206df4bdd8498d417976d9af6
Generated: 2026-07-07T16:24:10.6506448+01:00

## Executive Diagnosis

- Current repair gate is unavailable/materialization_failed.
- Diff is likely not displayed because reviewer decision is needs_revision or reason code REVIEWER_REQUESTED_REVISION.
- This means the reviewer did not approve a final reviewed diff. UI should show reviewer requested revision, not a missing diff bug.
- Repair attempts are empty. Validation timeline should not render.
- No approve_sandbox_apply action is exposed.

## Current Reviewed Repair Gate

| Field | Value |
|---|---|
| proposal exists | False |
| unavailable.kind | materialization_failed |
| unavailable.title | Reviewed Repair Materialization Failed |
| reason_code | REVIEWER_REQUESTED_REVISION |
| reviewer_decision | needs_revision |
| final_diff_exists | False |
| reviewed_diff_checksum |  |
| attempts_count | 0 |
| can_view_diff | False |
| can_approve | False |
| reviewer_self_repair_attempted | False |
| reviewer_self_repair_succeeded | False |
| backend_generated_diff | False |
| next_action | No repair proposal available. |
| detail | decision=needs_revision |

## Why Diff May Not Display

Result: Expected no reviewed diff display.

The reviewer requested revision. A final reviewed diff should not be exposed as applyable. The UI should show:
- reviewer requested revision
- no backend validation or apply path
- no repair proposal available
- optional raw draft or reviewer output diagnostics only if a read-only artifact exists

## Failure Summary Scoping

Top-level repair_loop_active: False
Top-level repair_events count: 0

| type | scope | title | repair_loop_status | reason_code | next_operator_action |
|---|---|---|---|---|---|
| build_failed | original_stage_failure | Stage 1 Build/Transform Failure | REPAIR_REVIEW_REQUIRED |  | Review build failure details and logs. If the issue persists, check preflight configuration. |
| reviewed_repair_materialization_failed | repair_materialization_failure | Reviewed Repair Materialization Failed | blocked | REVIEWER_REQUESTED_REVISION | No repair proposal available. |

### Scope Check
No repair materialization blocker is incorrectly scoped as original_stage_failure.

## Pipeline Analysis

| Field | Value |
|---|---|
| status | blocked |
| latest_message | Reviewer requested a revision of the repair proposal. |
| last_updated | 2026-07-07T14:27:41.637016Z |

Pipeline status is consistent with blocked materialization state.

## Event Snapshot Signal

| sequence | type | status | message | reason_code | reviewer_decision |
|---|---|---|---|---|---|
| 1121 | build_failed | failed | Sandbox build failed: BUILD_FAILED_IN_SANDBOX |  |  |
| 1122 | repair_started | running | Repair loop status: REPAIR_REVIEW_REQUIRED |  |  |
| 1123 | build_failed | failed | Build result: BUILD_FAILED_IN_SANDBOX |  |  |
| 1125 | repair_chain_started | started | Reviewed repair chain started. |  |  |
| 1126 | reviewed_repair_materialization_failed | failed | Reviewer requested a revision of the repair proposal. | REVIEWER_REQUESTED_REVISION | needs_revision |
| 1127 | transform_failed | failed | Transform/build failed: REPAIR_REVIEW_REQUIRED |  |  |
| 1129 | repair_chain_started | started | Reviewed repair chain started. |  |  |
| 1130 | stage_failed | failed | Stage 1 real orchestrator completed with terminal failure: REPAIR_REVIEW_REQUIRED. |  |  |

## Recommended Fix Classification

This is likely a new state-specific UI/copy issue, not the old Problem B leak.

Recommended fix:
- Add a distinct frontend branch for REVIEWER_REQUESTED_REVISION or reviewer_decision = needs_revision.
- Title: Reviewer Requested Revision.
- Explain: Reviewer found the draft diff structurally invalid and requested a corrected repair proposal.
- Do not show approve/apply.
- Do not show validation timeline.
- Optionally expose raw draft/reviewer output as read-only diagnostics if backend has artifact refs.
