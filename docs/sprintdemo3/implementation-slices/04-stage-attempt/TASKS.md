# Feature 04 Tasks — StageAttempt

## Task F04-T01 — Define StageAttempt lifecycle

### Goal

Create a precise execution-attempt model for normal and recovery runs.

### Scope

- Define attempt cause: initial, retry, resume, fork, or repair.
- Bind job, stage, input checkpoint, parent/fork attempt, command, status, output, failure, validation, and timestamps.
- Define allowed transitions and immutable terminal states.

### Likely future modified files

- `migration_factory/control_tower/domain/__init__.py` — export if needed.
- `migration_factory/control_tower/application/v2_stage_progression.py` — create attempt before queueing.

### Likely future new files

- `migration_factory/control_tower/domain/v2_stage_attempt.py` — aggregate.
- `tests/control_tower/test_v2_stage_attempt.py` — lifecycle tests.

### Implementation notes

- Reuse existing transition/idempotency vocabulary where compatible.
- Attempt is not a gate and not merely a command.
- Backend creates and transitions attempts.

### Acceptance criteria

- Invalid transitions and missing checkpoint bindings fail.

### Focused tests

- Cause-specific lineage and terminal immutability.

### Out of scope

- Recovery action endpoints.

### Dependencies

- Feature 03.

## Task F04-T02 — Persist attempts around runner execution

### Goal

Record durable attempt state before, during, and after execution.

### Scope

- Add migration, repository, service, and UoW wiring.
- Integrate runner success/failure callbacks and artifact refs.
- Preserve all terminal attempts.

### Likely future modified files

- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — transition attempts from execution results.
- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py` — repository wiring.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — replace gate-count approximation where appropriate; needs verification.

### Likely future new files

- `migration_factory/control_tower/application/v2_attempt_service.py` — lifecycle operations.
- `migration_factory/control_tower/infrastructure/sqlite/v2_stage_attempt_repository.py` — persistence.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/<next>_stage_attempts.sql` — schema.
- `tests/control_tower/test_v2_attempt_service.py` — integration and restart behavior.

### Implementation notes

- Reuse events, commands, and artifact refs rather than copying content.
- Do not delete or overwrite failed attempts.

### Acceptance criteria

- Runner outcomes leave queryable immutable attempt history after restart.

### Focused tests

- Repository round trip, callbacks, duplicate events, failure preservation.

### Out of scope

- UI timeline.

### Dependencies

- F04-T01.

## Task F04-T03 — Define recovery events and audit correlation

### Goal

Make every attempt and downstream recovery action replayable through safe versioned events.

### Scope

- Define checkpoint, attempt, recovery, evidence, classification, retrieval, diagnosis, candidate, review, policy, approval, execution, rollback, validation, and promotion event types.
- Require job, checkpoint, attempt, correlation, and causation identifiers.
- Define model identity/schema/context/output audit fields and selected policy IDs, versions, and checksums.

### Likely future modified files

- `migration_factory/control_tower/domain/f15_events.py` — extend the existing event taxonomy.
- `migration_factory/control_tower/infrastructure/sqlite/v2_event_repository.py` — persist/query correlations.
- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — emit attempt lifecycle events.

### Likely future new files

- `tests/control_tower/test_v2_demo3_event_taxonomy.py` — event schema and redaction.
- `tests/control_tower/test_v2_demo3_audit_correlation.py` — end-to-end correlation/replay.

### Implementation notes

- Reuse the existing event stream and model invocation audit; do not create a second ledger.
- Event payloads expose logical IDs/checksums, never paths, argv, env, commands, secrets, or raw logs.
- Backend is the only authoritative event producer for state transitions and proof.

### Acceptance criteria

- A job can be traced from input checkpoint through attempt, recovery artifacts, decision, execution, validation, and output checkpoint.
- Model and policy records preserve exact versions/checksums used.

### Focused tests

- Required fields, causation chain, replay order, duplicate event handling, and redaction.

### Out of scope

- New event transport or observability platform.

### Dependencies

- F04-T01 and F04-T02.
