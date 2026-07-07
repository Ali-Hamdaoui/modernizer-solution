# Repair Future Handoff

This bundle was prepared from the current `modernizer-solution` workspace for future repair work.

## What the graph analysis surfaced

- Core high-connectivity nodes are centered on the Control Tower runtime and persistence layer:
  - `JobState`
  - `NotFoundError`
  - `utc_now_text()`
  - `CommandExecutionDto`
  - `SqlitePhaseGateRepository`
  - `V2PhaseGateService`
  - `TargetProofLevel`
  - `RunConfigurationDto`
  - `StageChainLedgerRecord`
  - `apply_pending_migrations()`
- A notable bridge is `RepairService`, which appears in repair persistence and restart-state tests. That makes repair flow regressions likely to fan out into orchestration behavior.

## Token configuration findings

The repo does define input/output token budgets in code and in the launcher script.

- `migration_factory/control_tower/application/v2_settings.py:80-83`
  - Main and reviewer token env refs are declared here.
- `migration_factory/control_tower/application/v2_settings.py:120-121`
  - Fallback token env refs are declared here.
- `migration_factory/control_tower/application/v2_model_role_config.py:89-93`
  - Default role budgets are read from env with fallback values of `50000` input tokens and `20000` output tokens.
- `run-control-tower-backend.ps1:361-410`
  - The launcher explicitly sets:
    - `AI_MIGRATION_DEFAULT_MAX_INPUT_TOKENS=50000`
    - `AI_MIGRATION_DEFAULT_MAX_OUTPUT_TOKENS=20000`
    - `AI_MIGRATION_MAIN_MAX_INPUT_TOKENS=50000`
    - `AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS=20000`
    - `AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS=50000`
    - `AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS=20000`
    - `AI_MIGRATION_FALLBACK_MAX_INPUT_TOKENS=50000`
    - `AI_MIGRATION_FALLBACK_MAX_OUTPUT_TOKENS=20000`

## Repair notes

- If you are fixing model-role behavior, check both the runtime launcher and the settings loader. The launcher can override what the app would otherwise infer from env.
- If you are fixing token-budget regressions, inspect:
  - `migration_factory/control_tower/application/v2_model_role_router.py`
  - `migration_factory/control_tower/application/v2_assistant_model_client.py`
  - `migration_factory/control_tower/application/v2_model_role_config.py`
  - `run-control-tower-backend.ps1`
- The graph report already exists at `graphify-out/GRAPH_REPORT.md` and shows `0 input / 0 output` token cost for the graph build itself.

## Suggested next checks

1. Validate the live env values used by the backend launcher.
2. Confirm the main/reviewer/fallback model role budgets are still aligned with the intended provider behavior.
3. Re-run the most relevant repair tests if you change any token or model-role config path.
