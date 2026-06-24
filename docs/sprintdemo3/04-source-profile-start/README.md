# F4 - Start From Current App State

## Purpose

User can start from the real current state of the application and skip older stages.

## User Story

As an operator with an already-modernized app, I want the system to start from the current profile so that it does not rerun obsolete migrations.

## Backend Behavior

Analysis detects source profile evidence. The user can manually override the detected profile with a reason. The backend validates the resulting source/target pair, records skipped stages, and resumes from compatible checkpoints.

## Artifact Model

- Source-profile detection artifact.
- Manual override decision artifact.
- Skipped-stage ledger.
- Resume compatibility artifact.

## API/UI Implications

UI/API may expose detected source profile, confidence, evidence summary, override action, skipped-stage explanation, and resume options. It must not accept execution paths or raw commands.

## Tasks

- F4-T1: Define source-profile detection artifact.
- F4-T2: Define manual override action.
- F4-T3: Define skipped-stage ledger.
- F4-T4: Define profile pair validation.
- F4-T5: Define resume-from-checkpoint behavior.
- F4-T6: Define tests for already-modernized apps.

## Subtasks

- Define source-profile evidence fields.
- Define confidence and uncertainty reporting.
- Define override comments and validation.
- Define skipped-stage ledger entry format.
- Explain skipped stages in final artifacts.
- Validate checkpoint/profile compatibility on resume.

## Files To Inspect

- `migration_factory/agents/analysis_agent/`
- `migration_factory/profile_reader.py`
- `migration_factory/profiles/`
- `migration_factory/control_tower/application/v2_stage_progression.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/schemas/run_configuration.py`
- `migration_factory/control_tower/schemas/pipeline_definition.py`
- `migration_factory/control_tower/infrastructure/sqlite/`
- `migration_factory/control_tower/adapters/fastapi/app.py`

## Acceptance Criteria

- Analysis detects source profile.
- User can manually override source profile.
- Backend validates override reason.
- Skipped stages are recorded.
- Skipped stages are explained.
- Already-modernized apps are not forced through old migration stages.
- Resume from checkpoint is supported.

## Tests To Add/Update

- Source-profile detection fixture tests.
- Manual override validation tests.
- Skipped-stage ledger persistence tests.
- Already-modernized app route tests.
- Resume compatibility tests.

## Out Of Scope

- Arbitrary checkpoint import.
- User-authored backend commands.
