# F2 - Deterministic Artifact + Primary LLM + Reviewer LLM

## Purpose

For Analysis and Planning first, every model-required output is produced through:

```text
deterministic artifact
-> primary LLM reasoning
-> reviewer LLM validation
-> final Markdown artifact
-> next agent input
```

## User Story

As an operator, I want model-written Analysis and Planning artifacts reviewed by another model so that the next agent receives a clearer, safer, auditable artifact.

## Backend Behavior

The backend persists deterministic artifacts first, invokes the primary LLM only with backend-resolved artifact context, invokes a reviewer LLM on the primary output, and stores final Markdown only after reviewer validation.

## Artifact Model

- Deterministic Analysis artifact.
- Primary Analysis reasoning.
- Reviewer Analysis result.
- Final Analysis Markdown.
- Deterministic Planning artifact.
- Primary Planning reasoning.
- Reviewer Planning result.
- Final Planning Markdown.

## API/UI Implications

UI may display deterministic, primary, reviewer, and final artifacts separately. The next agent consumes final reviewed Markdown only. Public contracts expose artifact refs and checksums, not model runtime internals.

## Tasks

- F2-T1: Define deterministic artifact contract.
- F2-T2: Define primary LLM role.
- F2-T3: Define reviewer LLM role.
- F2-T4: Define reviewer decisions.
- F2-T5: Define final Markdown artifact schema.
- F2-T6: Define retry/revision behavior.
- F2-T7: Define metadata and checksum binding.
- F2-T8: Define tests for reviewer-required behavior.

## Subtasks

- Define deterministic Analysis and Planning artifact shapes.
- Define primary LLM inputs/outputs.
- Define reviewer input and decision schema.
- Define accept/reject/request-revision/failed-closed behavior.
- Store primary reasoning and reviewer notes separately.
- Bind final Markdown to exact input checksums.
- Block checkpoint acceptance on stale or missing reviewer output.

## Final Markdown Schema

- Summary
- Inputs used
- Deterministic findings
- File names and file paths
- Primary LLM reasoning
- Reviewer LLM notes
- Risks
- Confidence
- Recommended next step
- Machine-readable metadata

## Files To Inspect

- `migration_factory/agents/analysis_agent/`
- `migration_factory/agents/planning_agent/`
- `migration_factory/control_tower/application/v2_reviewer_service.py`
- `migration_factory/control_tower/application/v2_model_role_router.py`
- `migration_factory/control_tower/application/v2_assistant_model_client.py`
- `migration_factory/control_tower/application/v2_model_schemas.py`
- `migration_factory/control_tower/application/v2_gate_artifact_resolver.py`
- `migration_factory/control_tower/schemas/artifact_revision.py`
- `migration_factory/control_tower/infrastructure/sqlite/`
- `migration_factory/control_tower/adapters/fastapi/app.py`

## Acceptance Criteria

- Deterministic artifact is created first.
- Primary LLM reasons from deterministic artifact only.
- Reviewer LLM reviews primary output.
- Reviewer may accept, reject, or request revision.
- Final Markdown artifact is persisted and checksum-bound.
- Next agent receives final reviewed Markdown, not raw LLM output.
- Deterministic fallback cannot satisfy model-required reviewed artifact.

## Tests To Add/Update

- Artifact schema tests.
- Fake primary/reviewer model tests.
- Missing reviewer fail-closed tests.
- Stale checksum tests.
- Final Markdown schema tests.

## Out Of Scope

- Applying the chain to every later agent in the first implementation slice.
- Public model/provider selection.
