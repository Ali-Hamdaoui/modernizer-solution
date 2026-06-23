# Feature 05 Tasks — Retry / Resume / Fork

## Task F05-T01 — Define checkpoint recovery actions

### Goal

Make retry, resume, fork, and restart semantics explicit and non-overlapping.

### Scope

- Define preconditions, input checkpoint selection, parent attempt, idempotency, and output behavior.
- Define invalid states and conflict responses.
- Specify which actions require human choice and gates.

### Likely future modified files

- `migration_factory/control_tower/application/v2_stage_progression.py` — compatibility and stage-order validation.
- `migration_factory/control_tower/adapters/fastapi/app.py` — action request/response contracts.
- `web/control-tower/lib/contracts.ts` — typed safe actions.

### Likely future new files

- `migration_factory/control_tower/application/v2_recovery_action_service.py` — action policy/orchestration adapter.
- `tests/control_tower/test_v2_recovery_actions.py` — semantic matrix.

### Implementation notes

- Reuse checkpoint, attempt, gate, and command services.
- Human chooses the action; backend validates and creates execution.
- Chatbot may explain or draft a typed action but cannot execute it.

### Acceptance criteria

- Each action has deterministic lineage and rejects incompatible checkpoint/stage/profile state.

### Focused tests

- Table-driven action preconditions and actor authority.

### Out of scope

- Repair candidate generation.

### Dependencies

- Features 02–04.

## Task F05-T02 — Prove retry from accepted checkpoint

### Goal

Create a second failed-stage attempt without rerunning accepted earlier stages.

### Scope

- Resolve accepted input checkpoint.
- Atomically create attempt and backend-owned command.
- Preserve prior failed attempt and emit lineage events.

### Likely future modified files

- `migration_factory/control_tower/application/v2_stage_progression.py` — checkpoint-fed command preparation.
- `migration_factory/control_tower/adapters/fastapi/app.py` — retry endpoint wiring.
- `web/control-tower/lib/controlTowerApi.ts` — ID-only request.

### Likely future new files

- `tests/control_tower/test_v2_retry_from_checkpoint.py` — Stage 4 retry proof.
- `tests/control_tower/test_v2_recovery_actions.py` — idempotency/concurrency.

### Implementation notes

- Backend derives sandbox and argv.
- Accepted Stage 3 checkpoint remains immutable.
- Do not start MVP-B execution work until this passes.

### Acceptance criteria

- Stage 4 retry creates a new Stage 4 attempt using the same accepted Stage 3 checkpoint and no Stage 1–3 commands.

### Focused tests

- Happy path, stale checksum, duplicate key, concurrent retry, missing checkpoint.

### Out of scope

- Repair generation and promotion.

### Dependencies

- F05-T01.
