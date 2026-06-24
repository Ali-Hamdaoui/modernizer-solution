# Feature 06 Tasks — Failure Evidence

## Task F06-T01 — Define immutable failure evidence

### Goal

Create the evidence contract consumed by all recovery intelligence.

### Scope

- Define lineage, diagnostics, source/dependency/profile summaries, prior attempts, refs, checksums, redaction status, and timestamps.
- Separate application evidence from retrieved migration knowledge.
- Define bounded content and missing-evidence behavior.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_schemas.py` — evidence references in model context; needs verification.
- `migration_factory/control_tower/application/v2_evidence_pack_builder.py` — construct gate/model views.

### Likely future new files

- `migration_factory/control_tower/domain/v2_failure_evidence.py` — immutable contract.
- `tests/control_tower/test_v2_failure_evidence.py` — invariants and redaction.

### Implementation notes

- Reuse artifact refs and checksum helpers.
- Instructions inside logs/source are untrusted data.
- Backend owns collection and normalization.

### Acceptance criteria

- Contract includes every required attempt/checkpoint binding and can represent missing evidence safely.

### Focused tests

- Prompt injection strings, secrets, oversized logs, absent artifacts.

### Out of scope

- Classification and retrieval.

### Dependencies

- Feature 04.

## Task F06-T02 — Persist evidence from backend-resolved sources

### Goal

Adapt existing collection into durable attempt-bound evidence.

### Scope

- Resolve run/sandbox artifacts internally from attempt/checkpoint IDs.
- Reuse collector normalization/redaction.
- Persist immutable artifact and record; emit event.

### Likely future modified files

- `migration_factory/repair_loop/evidence_collector.py` — accept backend-resolved inputs and return structured content.
- `migration_factory/control_tower/application/v2_failure_diagnosis.py` — use persisted evidence ID, not caller path payload.
- `migration_factory/control_tower/application/v2_repair_flow.py` — consume evidence reference.

### Likely future new files

- `migration_factory/control_tower/application/v2_failure_evidence_service.py` — resolution/persistence coordinator.
- `tests/control_tower/test_v2_failure_evidence.py` — persistence and lineage cases.

### Implementation notes

- Wrap existing collector; do not create a second artifact store.
- Public APIs never accept or return evidence filesystem paths.

### Acceptance criteria

- Failed attempt produces one checksum-bound evidence record that survives restart.

### Focused tests

- Resolver integration, redaction, idempotency, immutable artifact content.

### Out of scope

- Live model calls and classifier registry.

### Dependencies

- F06-T01 and Feature 05.

## Task F06-T03 — Add the FailureRecoveryEngine coordinator

### Goal

Own the generic recovery state machine without duplicating execution, repair, or artifact systems.

### Scope

- Define typed transitions from failed attempt through evidence, classification, retrieval, mode selection, diagnosis, candidate, review, policy, approval, execution, validation, rollback, and promotion.
- Start the engine from a persisted failed attempt and accepted input checkpoint.
- Delegate each transition to existing or feature-owned services with idempotency and event emission.

### Likely future modified files

- `migration_factory/control_tower/application/v2_orchestrator_runner.py` — hand off failed attempts to the engine.
- `migration_factory/control_tower/application/v2_repair_flow.py` — expose reusable repair transition adapters.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — reuse review/approval gate transitions.

### Likely future new files

- `migration_factory/control_tower/application/v2_failure_recovery_engine.py` — generic coordinator/state machine.
- `tests/control_tower/test_v2_failure_recovery_engine.py` — transition, idempotency, and no-duplication tests.

### Implementation notes

- Reuse stage progression, orchestrator runner, gates, artifact storage, events, repair flow, validation, rollback, and checkpoint services.
- The engine coordinates; it does not author fixes, execute client/model commands, approve, or manufacture proof.
- Add downstream adapters incrementally as Features 07–16 land.

### Acceptance criteria

- One persisted recovery ID traces a failed attempt through typed transitions.
- Replaying the same transition is idempotent.
- No Jackson-specific branch or second orchestrator, repair loop, or artifact store exists.

### Focused tests

- Failed-attempt start, invalid transition, duplicate event, stop/manual state, and adapter delegation.

### Out of scope

- Implementing downstream classifier, retrieval, candidate, reviewer, executor, or promoter logic in this task.

### Dependencies

- Feature 05 and F06-T02.
