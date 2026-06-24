# F3 - Target Profile Control

## Purpose

User can choose the final migration target profile and the system stops there.

## User Story

As an operator, I want to migrate only to my selected target profile so that the system does not overshoot into unnecessary future migrations.

## Backend Behavior

The backend validates `source_profile` and `target_profile`, computes required stages, persists the selected target, and stops when the target is reached.

## Artifact Model

- Profile selection artifact.
- Profile validation artifact.
- Stage/profile mapping artifact.
- Checkpoint metadata with source and target profile.

## API/UI Implications

Public API/UI may expose `source_profile`, `target_profile`, validation status, included stages, and excluded stages. It must not expose provider/model/deployment/env refs as product API fields.

## Tasks

- F3-T1: Define profile model.
- F3-T2: Define profile validation.
- F3-T3: Define stage/profile mapping.
- F3-T4: Define stop-at-target behavior.
- F3-T5: Define API fields.
- F3-T6: Define artifact/checkpoint metadata.
- F3-T7: Define tests for target overshoot prevention.

## Subtasks

- Define profile identifiers and ordering.
- Define invalid source/target pair behavior.
- Define included/excluded stage output.
- Persist target profile in job configuration.
- Stop pipeline at target profile.
- Add overshoot regression cases.

## Files To Inspect

- `migration_factory/control_tower/application/v2_stage_progression.py`
- `migration_factory/control_tower/schemas/run_configuration.py`
- `migration_factory/control_tower/schemas/pipeline_definition.py`
- `migration_factory/profiles/`
- `migration_factory/profile_reader.py`
- `migration_factory/agents/planning_agent/`
- `migration_factory/control_tower/adapters/fastapi/app.py`

## Acceptance Criteria

- User provides or confirms `source_profile`.
- User selects `target_profile`.
- Backend validates source/target pair.
- Pipeline includes only required stages.
- Pipeline stops at target profile.
- Pipeline does not continue to higher profiles.
- Target profile is persisted in job configuration.

## Tests To Add/Update

- Profile validation tests.
- Stage/profile route tests.
- Target overshoot prevention tests.
- Resume-after-target tests.

## Out Of Scope

- Provider/model profile selection.
- Arbitrary custom stage execution.
