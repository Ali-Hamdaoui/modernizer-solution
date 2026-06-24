# F1 - Agent Checkpoints and User Decisions

## Purpose

Stop after Analysis and Planning so users can review, request changes, continue, stop, or download artifacts.

## User Story

As an operator, I want to review Analysis and Planning before downstream changes so that early mistakes do not drive the rest of the migration.

## Backend Behavior

The backend opens governed checkpoints after Analysis and Planning. It persists state, artifact refs, checksums, user decisions, comments, reasons, and resume decisions. It auto-continues later agents only when risk and failure checks allow.

## Artifact Model

- Checkpoint state artifact.
- User decision artifact.
- Artifact preview/download refs.
- Resume decision artifact.

## API/UI Implications

UI/API actions use checkpoint IDs, artifact refs, checksums, decisions, and comments. They do not accept paths, argv, env, commands, or runtime-provider details.

## Tasks

- F1-T1: Define checkpoint state model.
- F1-T2: Define user decisions.
- F1-T3: Define Analysis checkpoint.
- F1-T4: Define Planning checkpoint.
- F1-T5: Define safe auto-continue rules.
- F1-T6: Define stop conditions.
- F1-T7: Define artifact download/preview behavior.
- F1-T8: Define resume behavior.

## Subtasks

- Define checkpoint statuses and terminal states.
- Define continue, stop, request analysis modification, request planning modification, download artifacts.
- Persist job state, current agent/stage, checkpoint status, artifact refs, user decision, comments, reason, resume decision.
- Bind decisions to artifact checksums.
- Define stale-artifact rejection.
- Define resume without user-supplied paths or commands.

## Files To Inspect

- `migration_factory/control_tower/application/v2_stage_progression.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/application/v2_gate_action_service.py`
- `migration_factory/control_tower/application/v2_phase_gate_service.py`
- `migration_factory/control_tower/schemas/phase_gate.py`
- `migration_factory/control_tower/schemas/run_configuration.py`
- `migration_factory/control_tower/domain/entities.py`
- `migration_factory/control_tower/infrastructure/sqlite/`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/agents/analysis_agent/`
- `migration_factory/agents/planning_agent/`
- `migration_factory/agents/build_agent/`
- `migration_factory/agents/test_agent/`

## Acceptance Criteria

- Analysis Agent stops for review.
- Planning Agent stops for review.
- Transformation Agents auto-continue only when no risk is detected.
- Build Agent auto-continues only when build succeeds.
- Test Agent auto-continues only when tests pass.
- System stops on risk, build failure, test failure, target profile reached, stale artifact, reviewer failure, or approval required.

## Tests To Add/Update

- Checkpoint state transition tests.
- Gate action tests for user decisions.
- Auto-continue and stop-condition tests.
- Resume validation and idempotency tests.

## Out Of Scope

- Building frontend screens in this docs task.
- Repair Agent implementation.
