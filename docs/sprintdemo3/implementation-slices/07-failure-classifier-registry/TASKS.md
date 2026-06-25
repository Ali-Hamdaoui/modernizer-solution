# Feature 07 Tasks — Failure Classifier Registry

## Task F07-T01 — Define versioned failure signatures

### Goal

Represent deterministic match rules independently from repair content.

### Scope

- Define signature ID/version, class, profile constraints, evidence predicates, exclusions, priority, confidence, and matched evidence.
- Seed `JACKSON_JSONNODE_UNRESOLVED` and one non-Jackson fixture.
- Preserve Jackson annotation exclusions.

### Likely future modified files

- `migration_factory/agents/failure_classifier/agent.py` — delegate matching to registry.
- `migration_factory/repair_loop/rule_registry.py` — remove any classification coupling; exact change needs verification.

### Likely future new files

- `migration_factory/control_tower/application/v2_failure_signature_registry.py` — registry/evaluator.
- `migration_factory/control_tower/domain/v2_failure_classification.py` — persisted result.
- `tests/control_tower/test_v2_failure_signature_registry.py` — registry cases.

### Implementation notes

- Signatures identify failure; they do not prescribe exact fixes.
- Backend owns authoritative classification.

### Acceptance criteria

- New signatures can be registered without editing recovery orchestration.

### Focused tests

- Jackson, Hibernate/Jakarta, exclusions, profile mismatch, version.

### Out of scope

- Retrieval and repair mode selection.

### Dependencies

- Feature 06.

## Task F07-T02 — Integrate deterministic classification

### Goal

Persist one safe classification result for each evidence record.

### Scope

- Evaluate signatures against normalized immutable evidence.
- Handle no match and conflicting match explicitly.
- Bind evidence checksum and registry version.

### Likely future modified files

- `migration_factory/control_tower/application/v2_failure_diagnosis.py` — consume persisted classification.
- `migration_factory/agents/failure_classifier/agent.py` — compatibility adapter.

### Likely future new files

- `tests/control_tower/test_v2_failure_classifier_registry.py` — end-to-end classification behavior.
- `migration_factory/control_tower/infrastructure/sqlite/v2_failure_classification_repository.py` — suggested persistence; needs verification.

### Implementation notes

- Do not call a model to break ties.
- Unknown/ambiguous classification must block trusted automatic repair.

### Acceptance criteria

- Classification is reproducible from evidence and registry version.

### Focused tests

- Unknown, ambiguity, restart durability, checksum mismatch.

### Out of scope

- Candidate generation.

### Dependencies

- F07-T01.
