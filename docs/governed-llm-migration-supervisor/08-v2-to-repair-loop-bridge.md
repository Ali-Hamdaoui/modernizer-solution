# V2 to Repair Loop Bridge

## Goal

Bridge approved V2 repair proposals into the existing safe repair-loop lifecycle rather than relying on thin V2 apply logic.

This is the biggest risk area.

This feature is the execution bridge for LLM work. Approved LLM proposals are not advisory only; they become repair-loop attempts. The safety boundary is not "LLM cannot work," it is "LLM work must enter through patch gate, sandbox apply, validation, rollback, and ledger."

Architectural center:

- Without the bridge, the LLM only talks.
- With the bridge, approved LLM proposals become governed sandbox migration work.
- The bridge must route through `patch_gate`, `rule_registry`, `patch_apply`, `validation_runner`, `rollback`, and `ledger`.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_repair_flow.py`
  - `V2RepairFlowService.apply_patch()` currently requires approved proposal, then records an applied `SandboxAction`.
  - UNCERTAIN: this path does not itself run `patch_gate`, `rule_registry`, `patch_apply`, validation, rollback, or ledger.
- `migration_factory/repair_loop/patch_gate.py`
  - `evaluate_patch_proposal()` checks deterministic rule id, risk, unified diff, out-of-scope claims, paths, sandbox containment, legacy path rejection, symlink traversal, and security patch review.
- `migration_factory/repair_loop/rule_registry.py`
  - `ALLOWED_RULE_IDS` and `evaluate_rule()`.
- `migration_factory/repair_loop/patch_apply.py`
  - `apply_patch_to_sandbox()` writes patch artifacts, snapshots files, runs `git apply --check`, applies patch, records hashes.
  - `rollback_patch()` restores snapshot.
- `migration_factory/repair_loop/validation_runner.py`
  - `run_validation_after_patch()` runs build/test/H2 validation and returns artifact refs.
- `migration_factory/repair_loop/ledger.py`
  - `new_ledger()`, `append_attempt()`, `base_attempt()`, `write_patch_attempt_result()`, `write_ledger()`.
- `migration_factory/copilot_repair/response_validator.py`
  - Validates response shape and patch proposal safety.

What already exists:

- Patch safety gate.
- Deterministic rule allowlist.
- Sandbox patch apply.
- Snapshot rollback.
- Validation rerun.
- Repair ledger.

What must not be duplicated:

- Patch apply.
- Rollback.
- Validation runner.
- Repair ledger.
- Rule registry.
- Patch gate.

## Proposed Implementation

Correct implementation:

```text
approved V2 repair proposal
-> convert to existing repair-loop attempt
-> patch_gate
-> rule_registry
-> patch_apply sandbox-only
-> validation_runner
-> ledger
-> cockpit event
```

Steps:

1. `V2AssistantActionResolver` resolves command/stage/sandbox/run_dir.
2. Convert approved V2 proposal to repair-loop proposal dict:
   - `deterministic_rule_id`
   - `risk`
   - `requires_human_review`
   - `unified_diff`
   - `expected_validation`
   - `limitations`
3. Call `evaluate_patch_proposal()`.
4. If not `ALLOWED`, persist blocked/needs-review result and emit event.
5. If allowed, call `apply_patch_to_sandbox()`.
6. Run `run_validation_after_patch()`.
7. If validation fails, call `rollback_patch()` and record rollback in ledger.
8. Append attempt and write ledger result.
9. Emit cockpit events:
   - `repair_patch_gate_completed`
   - `repair_patch_applied`
   - `repair_validation_completed`
   - `repair_rollback_completed` when needed.

Bridge policy:

- LLM-created repair objects are eligible work inputs only after reviewer and human approval gates.
- Backend resolves the proposal, binding checksum, sandbox, deterministic rule, and validation command.
- Patch gate and validation results are authoritative over model claims.

## Data / Schema Changes

Bridge result fields:

```text
attempt
proposal_id
binding_checksum
patch_gate_status
deterministic_rule_id
touched_paths
patch_ref
patch_result_ref
validation_artifact_refs
rollback_status
ledger_ref
final_status
```

Do not replace `repair_ledger.json`; reference it.

Technical basis: OpenRewrite already provides migration recipes that modify build files and Java/Spring APIs, so the bridge should preserve OpenRewrite/Maven/proof as execution truth rather than turning the LLM into a patch engine: [OpenRewrite Spring Boot 3 guide](https://docs.openrewrite.org/running-recipes/popular-recipe-guides/migrate-to-spring-3), [OpenRewrite UpgradeSpringBoot_3_5](https://docs.openrewrite.org/recipes/java/spring/boot3/upgradespringboot_3_5-community-edition).

## Backend Flow

```text
human approves exact proposal checksum
-> backend bridge loads proposal and binding
-> patch_gate validates paths/risk/rule/diff
-> rule_registry resolves allowlisted deterministic rule when present
-> patch_apply snapshots and applies in sandbox
-> validation_runner reruns Maven/tests/H2 checks
-> rollback on failed validation
-> write ledger
-> emit events/proof updates
```

## UI / Cockpit Impact

Show real repair-loop state:

- Patch gate decision.
- Deterministic rule id.
- Touched paths.
- Validation result.
- Rollback status.
- Ledger artifact ref.

Do not show a frontend-only "applied" state.

## Human Supervision Point

The human approves exact proposal/binding checksum before bridge execution. Human may reject or request revision before approval.

## Safety / Governance

- Sandbox only: bridge must call `validate_patch_paths()` through `patch_gate`.
- No legacy mutation: `patch_gate` rejects legacy path touches.
- Human approval boundary: model proposal and reviewer critique cannot approve.
- Backend-owned action gate: approved LLM proposals enter work only through bridge, patch gate, sandbox apply, validation, rollback, ledger, and proof.
- Checksum/proof gates: approval checksum, binding checksum, patch gate, validation rerun, ledger, and proof remain source of truth.

## Tests

Targeted tests:

- Extend `tests/test_copilot_repair_loop.py`.
- Extend `tests/control_tower/test_v2_repair_flow.py`.
- Extend `tests/control_tower/test_v2_assistant_repair_api.py`.
- Add `test_v2_approved_repair_routes_through_patch_gate`.
- Add `test_v2_repair_bridge_rejects_legacy_path`.
- Add `test_v2_repair_bridge_rolls_back_on_validation_failure`.
- Add `test_v2_repair_bridge_writes_ledger_and_events`.

## Risks

- Bypassing `patch_gate` through `V2RepairFlowService.apply_patch()`.
- Running validation with arbitrary Maven command instead of backend-owned validation.
- Losing repair-loop ledger as source of truth.
- Applying a patch after a stale approval.

## Open Questions

- Should `V2RepairFlowService.apply_patch()` be deprecated, wrapped, or made private behind the bridge?
- How should V2 proposal shape carry `unified_diff` when current `RepairProposal` only stores summaries/affected paths?
- Should POM-only deterministic rules generate diffs backend-side instead of accepting model-proposed diffs?
