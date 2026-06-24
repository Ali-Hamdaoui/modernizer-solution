# F5 - Build/Test Repair Agent Review Loop

## Purpose

When build or tests fail, a dedicated Repair Agent analyzes the failure and proposes a reviewed diff before any patch is applied.

F5 is not a simple repair loop. It is an agentic repair workflow with a Primary Repair LLM and an independent Reviewer LLM.

## User Story

As an operator, I want build/test fixes to be proposed, reviewed, explained, and approved before application so that risky repairs stay under human and backend governance.

## Backend Behavior

The backend captures build/test failure evidence, builds a deterministic failure artifact, invokes the Primary Repair LLM, invokes the Reviewer LLM, stores immutable proposal/review artifacts, presents the proposal to the user, and applies only the exact approved reviewed diff.

## Artifact Model

- Failure evidence artifact.
- Deterministic failure artifact.
- Repair context pack.
- Primary repair reasoning artifact.
- Proposed diff artifact.
- Reviewer repair artifact.
- User repair decision artifact.
- Apply result artifact.
- Build/test rerun proof artifact.
- Rollback artifact when required.

## API/UI Implications

UI/API must support build/test error summary, root cause hypothesis, files that will change, proposed diff, why the fix is needed, risks, confidence, reviewer notes, approve, reject, request another review, and user comments.

Decisions must bind to exact proposal and reviewer checksums. API must never accept an unreviewed diff for application.

## Repair Agent Inputs

- Build failure logs.
- Test failure logs.
- Compiler output.
- Test output.
- Changed files.
- Current repository state.
- Previous accepted Analysis artifact.
- Previous accepted Planning artifact.
- Current source profile.
- Target profile.
- Migration stage/agent context.
- Previous repair proposals if repeated.
- Previous reviewer notes.
- User comments.
- Current artifact/checkpoint checksums.

## Tasks

- F5-T1: Define failure evidence capture.
- F5-T2: Define Repair Agent input context.
- F5-T3: Define deterministic failure artifact.
- F5-T4: Define primary Repair LLM role.
- F5-T5: Define Reviewer LLM role for repair.
- F5-T6: Define proposed diff artifact.
- F5-T7: Define policy validation before presentation.
- F5-T8: Define user decision actions.
- F5-T9: Define request-another-review loop.
- F5-T10: Define exact-diff approval and apply behavior.
- F5-T11: Define build/test rerun behavior.
- F5-T12: Define repeated failure behavior.
- F5-T13: Define rollback and proof behavior.
- F5-T14: Define UI/API presentation contract.
- F5-T15: Define tests.

## Subtasks

- Capture build logs.
- Capture test logs.
- Normalize compiler/test errors.
- Collect changed files.
- Collect previous artifacts.
- Build repair context pack.
- Bind context pack to checksum.
- Call Primary Repair LLM.
- Call Reviewer LLM.
- Store primary reasoning.
- Store reviewer notes.
- Store proposed diff.
- Validate proposed diff.
- Present diff to user.
- Accept/reject/request-review.
- Store user comments.
- Re-run repair with comments.
- Apply only approved exact diff.
- Rerun build/test.
- Record proof.
- Roll back on failure when required.

## OpenRewrite / Jackson Guidance

OpenRewrite/Jackson recipes can be backend-allowlisted repair strategies for migration-specific failures, especially Jackson 2 to Jackson 3. The LLM does not execute OpenRewrite directly. The Repair Agent may recommend an allowlisted backend repair mode. The backend validates and executes allowed repair modes only after user approval and checksum binding.

## Files To Inspect

- `migration_factory/agents/build_agent/`
- `migration_factory/agents/test_agent/`
- `migration_factory/control_tower/application/v2_repair_flow.py`
- `migration_factory/control_tower/application/v2_repair_gate_service.py`
- `migration_factory/control_tower/application/v2_reviewer_service.py`
- `migration_factory/control_tower/application/v2_model_role_router.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/control_tower/application/v2_model_schemas.py`
- `migration_factory/control_tower/application/v2_orchestrator_runner.py`
- `migration_factory/control_tower/application/v2_stage_progression.py`
- `migration_factory/control_tower/schemas/artifact_revision.py`
- `migration_factory/control_tower/schemas/phase_gate.py`
- `migration_factory/control_tower/domain/entities.py`
- `migration_factory/control_tower/infrastructure/sqlite/`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/repair_loop/evidence_collector.py`
- `migration_factory/repair_loop/rule_registry.py`
- `migration_factory/repair_loop/patch_gate.py`
- `migration_factory/repair_loop/patch_apply.py`
- `migration_factory/repair_loop/validation_runner.py`

## Acceptance Criteria

- Build Agent failures enter Repair Agent flow.
- Test Agent failures enter Repair Agent flow.
- Primary Repair LLM proposes root cause and fix.
- Reviewer LLM reviews exact proposed diff.
- Final proposal is stored as an artifact.
- User sees diff plus explanation.
- User can approve, reject, or request another review with comments.
- Backend applies only exact approved reviewed diff.
- Backend reruns Build or Test Agent depending on failure source.
- Repeat failure starts another Repair Agent cycle.
- Rejection applies no patch and stores reason.

## Tests To Add/Update

- Build failure evidence tests.
- Test failure evidence tests.
- Repair context checksum/redaction tests.
- Primary Repair LLM schema tests.
- Reviewer LLM exact-diff tests.
- User decision API tests.
- Request-another-review loop tests.
- Exact approved diff apply tests.
- Stale diff rejection tests.
- Rollback and proof tests.
- OpenRewrite/Jackson allowlist tests.

## Out Of Scope

- Autonomous repair execution.
- LLM-selected commands.
- LLM-selected sandbox or filesystem targets.
- Frontend implementation in this docs task.
