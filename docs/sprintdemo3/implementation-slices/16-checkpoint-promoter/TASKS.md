# Feature 16 Tasks — Checkpoint Promoter

## Task F16-T01 — Define promotion policy and transaction

### Goal

Specify the only valid transition from validated attempt to accepted checkpoint.

### Scope

- Require successful terminal attempt and validation proof.
- Require exact input lineage and artifact manifest checksums.
- Define idempotency, concurrency, and rollback on persistence failure.

### Likely future modified files

- `migration_factory/control_tower/application/v2_stage_progression.py` — consume promoted output.
- `migration_factory/control_tower/application/v2_gate_action_service.py` — stage completion acceptance.

### Likely future new files

- `migration_factory/control_tower/application/v2_checkpoint_promoter.py` — policy/transaction coordinator.
- `tests/control_tower/test_v2_checkpoint_promoter.py` — promotion matrix.

### Implementation notes

- Reuse checkpoint, attempt, artifact, gate, and UoW systems.
- Backend alone promotes; validation proof is mandatory.

### Acceptance criteria

- No failed, running, stale, or proof-less attempt can promote.

### Focused tests

- Status/proof matrix, duplicate request, concurrent promotion.

### Out of scope

- Cockpit rendering.

### Dependencies

- Features 03, 04, 15.

## Task F16-T02 — Freeze artifacts and link output checkpoint

### Goal

Create complete immutable output lineage after successful promotion.

### Scope

- Freeze/resolve artifact manifest and checksums.
- Create accepted checkpoint and update attempt output reference atomically.
- Emit safe promotion event.

### Likely future modified files

- `migration_factory/control_tower/application/v2_gate_action_service.py` — completion integration.
- `migration_factory/control_tower/application/v2_artifact_revision_service.py` — requested likely path, but file does not currently exist; needs verification.
- `migration_factory/control_tower/infrastructure/sqlite/v2_artifact_revision_repository.py` — likely reuse if no service is added.

### Likely future new files

- `migration_factory/control_tower/application/v2_checkpoint_promoter.py` — implementation.
- `tests/control_tower/test_v2_checkpoint_promoter.py` — artifact and transaction tests.

### Implementation notes

- Do not copy artifact systems.
- Store logical refs/checksums, not public paths.

### Acceptance criteria

- Querying attempt, checkpoint, and proof yields one consistent immutable chain.

### Focused tests

- Manifest mismatch, transaction rollback, event redaction.

### Out of scope

- Retention/pruning.

### Dependencies

- F16-T01.
