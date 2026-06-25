# Feature 11 Tasks — Independent Reviewer

## Task F11-T01 — Enforce reviewer identity independence

### Goal

Fail closed unless proposer and reviewer identities are provably distinct.

### Scope

- Define canonical backend-resolved identity fields.
- Compare Azure AI Foundry project/deployment/model/version identity as available.
- Persist both identities and failure reason.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_role_router.py` — canonical identity resolution.
- `migration_factory/control_tower/application/v2_reviewer_service.py` — independence gate.
- `migration_factory/control_tower/infrastructure/sqlite/v2_reviewer_repository.py` — identity persistence.

### Likely future new files

- `tests/control_tower/test_v2_reviewer_model_identity.py` — equality/alias cases.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/<next>_reviewer_identity.sql` — suggested append-only columns/table; needs verification.

### Implementation notes

- Role name difference is insufficient.
- Backend, not client/model, supplies identity and invokes the reviewer through the Azure AI Foundry adapter.

### Acceptance criteria

- Same or unknown identity cannot produce an accepted review.

### Focused tests

- Same deployment, aliases, missing metadata, distinct fake identities.

### Out of scope

- Model-provider configuration UI and provider selection.

### Dependencies

- Feature 10.

## Task F11-T02 — Review exact candidate revisions

### Goal

Persist strict critique against every relevant immutable binding.

### Scope

- Build generic and mode-specific checklist from the controlled context-pack revision.
- Bind candidate, evidence, classification, retrieval, mode, checkpoint, and attempt checksums.
- Reject stale/missing bindings.

### Likely future modified files

- `migration_factory/control_tower/application/v2_reviewer_service.py` — exact context review.
- `migration_factory/control_tower/infrastructure/sqlite/v2_reviewer_repository.py` — additional bindings.

### Likely future new files

- `migration_factory/control_tower/application/v2_review_policy.py` — checklist composition.
- `tests/control_tower/test_v2_independent_reviewer.py` — fake reviewer and stale cases.

### Implementation notes

- Reuse existing checksum gate.
- Reviewer is critic only; acceptance is not human approval.

### Acceptance criteria

- Accepted critique can be replay-verified against exact immutable inputs.

### Focused tests

- Stale candidate/pack/evidence, malformed output, rejected/manual verdict.

### Out of scope

- Candidate apply.

### Dependencies

- F11-T01 and Feature 08.
