# Feature 03 Tasks — StageCheckpoint

## Task F03-T01 — Define StageCheckpoint invariants

### Goal

Specify the immutable logical output contract used by later attempts.

### Scope

- Define identity, lineage, status, profile, artifact manifest, validation proof, and timestamps.
- Define draft/accepted/rejected rules and compatibility checks.
- Keep filesystem locations out of public/domain identity.

### Likely future modified files

- `migration_factory/control_tower/domain/__init__.py` — export aggregate if project convention requires it.
- `migration_factory/control_tower/application/v2_stage_progression.py` — consume checkpoint identity.

### Likely future new files

- `migration_factory/control_tower/domain/v2_stage_checkpoint.py` — aggregate and invariants.
- `tests/control_tower/test_v2_stage_checkpoint.py` — domain cases.

### Implementation notes

- Reuse checksum and timestamp helpers.
- Artifacts/checksums are authority; sandbox path is not.
- Backend alone creates and accepts checkpoints.

### Acceptance criteria

- Model includes all PRD-required bindings and rejects invalid accepted state.

### Focused tests

- Required fields, stage/profile mismatch, missing proof, immutability.

### Out of scope

- Persistence and promotion workflow.

### Dependencies

- Feature 01.

## Task F03-T02 — Persist and resolve checkpoints

### Goal

Store checkpoints durably and resolve accepted inputs by ID.

### Scope

- Add append-only migration, repository, UoW wiring, and application service.
- Resolve artifact refs through existing artifact systems.
- Add idempotent accepted-checkpoint lookup.

### Likely future modified files

- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py` — repository wiring.
- `migration_factory/control_tower/application/v2_gate_artifact_resolver.py` — checkpoint-bound artifact resolution.
- `migration_factory/control_tower/application/v2_gate_action_service.py` — acceptance integration.

### Likely future new files

- `migration_factory/control_tower/application/v2_checkpoint_service.py` — create/read/accept operations.
- `migration_factory/control_tower/infrastructure/sqlite/v2_stage_checkpoint_repository.py` — persistence.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/<next>_stage_checkpoints.sql` — append-only schema.
- `tests/control_tower/test_v2_checkpoint_service.py` — service/persistence behavior.

### Implementation notes

- Follow existing repository/UoW conventions.
- Do not duplicate artifact storage.

### Acceptance criteria

- Accepted checkpoint survives restart and resolves exact manifest/proof checksums.

### Focused tests

- Migration, repository round trip, duplicate acceptance, missing artifacts.

### Out of scope

- Retry APIs and checkpoint promotion after repair.

### Dependencies

- F03-T01.
