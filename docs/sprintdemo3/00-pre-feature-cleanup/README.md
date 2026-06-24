# F0 - Pre-Feature Codebase Cleanup

## Purpose

Clean the codebase before implementation so DEMO3 is backend/API driven, auditable, and not dependent on Copilot, TUI, dead CLI paths, or duplicated orchestration.

## User Story

As an operator, I want one governed product workflow so that migration decisions, artifacts, execution, and proof are controlled through the backend API/UI path.

## Backend Behavior

The backend API/UI path is the product control surface. Copilot, TUI, dead CLI/debug paths, duplicate orchestration, and stale terminology are inventoried and either removed, quarantined, or explicitly retained as compatibility-only code.

## Artifact Model

- Copilot runtime inventory.
- TUI/CLI inventory.
- Duplicate orchestration report.
- Public contract leakage scan.
- Cleanup report.

## API/UI Implications

Public product contracts must not expose `sandbox_path`, argv, env, command, provider, endpoint, deployment, or env ref. UI text must not imply Copilot or TUI participation in DEMO3.

## Tasks

- F0-T1: Inventory Copilot runtime paths.
- F0-T2: Disable/quarantine Copilot from product runtime.
- F0-T3: Inventory TUI and CLI runtime paths.
- F0-T4: Remove/quarantine TUI from product workflow.
- F0-T5: Identify duplicate orchestration logic.
- F0-T6: Identify unused modules/dependencies.
- F0-T7: Clean stale product terminology.
- F0-T8: Generate cleanup report.

## Subtasks

- Search for Copilot imports and runtime calls.
- Search for TUI entrypoints.
- Search for CLI commands that execute or mutate workflows.
- Search for command execution paths.
- Search for provider/runtime leakage in contracts and docs.
- Verify no public API exposes forbidden execution/runtime fields.
- Mark retained legacy modules as compatibility-only.

## Files To Inspect

- `migration_factory/orchestrator/`
- `migration_factory/copilot_assist/`
- `migration_factory/copilot_repair/`
- `migration_factory/final_report/`
- `migration_factory/tui/`
- `migration_factory/cli.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/application/v2_settings.py`
- `migration_factory/control_tower/application/v2_model_role_router.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/agents/analysis_agent/`
- `migration_factory/agents/planning_agent/`

## Acceptance Criteria

- Copilot is not part of the migration workflow.
- TUI is not part of the product workflow.
- No product path can invoke Copilot.
- Backend API/UI path is the product control surface.
- Cleanup report is generated.

## Tests To Add/Update

- Search-based regression tests for forbidden product runtime paths.
- API/contract tests for forbidden public fields.
- Documentation terminology checks.

## Out Of Scope

- Implementing F1-F5.
- Removing historical compatibility artifacts without a cleanup decision.
- Any runtime code change in this docs-only task.
