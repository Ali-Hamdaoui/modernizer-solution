# Feature 08 Tasks — Retrieval Pack Builder

## Task F08-T01 — Define retrieval policy and pack contracts

### Goal

Make targeted migration knowledge immutable and auditable.

### Scope

- Define policy selection by signature/profile.
- Define source ID/version/provenance/checksum, query topics, limits, and required entries.
- Define pack bindings and untrusted-content framing.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_schemas.py` — strict retrieval pack references.
- `migration_factory/control_tower/application/retrievers.py` — reuse adapter; exact change needs verification.

### Likely future new files

- `migration_factory/control_tower/domain/v2_retrieval_pack.py` — pack contract.
- `migration_factory/control_tower/application/v2_retrieval_pack_builder.py` — policy selection/build.
- `tests/control_tower/test_v2_retrieval_pack_builder.py` — contract/policy tests.

### Implementation notes

- Retrieved text is data, never instructions.
- Backend selects policy; LLM does not choose sources.

### Acceptance criteria

- Pack is reproducible and provenance/checksum complete.

### Focused tests

- Wrong profile, stale source, missing required topic, bounds.

### Out of scope

- Candidate authoring.

### Dependencies

- Features 06–07.

## Task F08-T02 — Persist and expose retrieval packs to model roles

### Goal

Provide exact immutable retrieval context to proposer and reviewer.

### Scope

- Persist pack and resolve by ID/checksum.
- Add bounded model context projection.
- Ensure proposer and reviewer receive the same referenced pack revision.

### Likely future modified files

- `migration_factory/control_tower/application/v2_failure_diagnosis.py` — invoke builder after classification.
- `migration_factory/control_tower/application/v2_model_schemas.py` — pack binding.

### Likely future new files

- `migration_factory/control_tower/infrastructure/sqlite/v2_retrieval_pack_repository.py` — persistence.
- `tests/control_tower/test_v2_retrieval_pack_builder.py` — round trip and fake provider.

### Implementation notes

- Reuse artifact storage; repository may store metadata only.
- No live web or model calls in tests.

### Acceptance criteria

- Exact pack checksum is available to candidate and review records.

### Focused tests

- Restart durability, stale checksum, deterministic fake retrieval.

### Out of scope

- General RAG UI.

### Dependencies

- F08-T01 and F08-T03.

## Task F08-T03 — Enforce controlled context-pack policy

### Goal

Ensure assistant model inputs are backend-selected, redacted, bounded, and auditable.

### Scope

- Define allowed source categories for summaries, artifacts, snippets, diagnostics, and retrieved migration knowledge.
- Reject unrestricted repository upload, secrets, raw environment variables, and unredacted raw terminal logs.
- Record source artifact references, checksums, selection reason, redaction decisions, role, and policy version.
- Produce role-specific bounded projections for the Control Tower assistant, proposer, and reviewer.

### Likely future modified files

- `migration_factory/control_tower/application/v2_evidence_pack_builder.py` — provide policy-approved evidence excerpts.
- `migration_factory/control_tower/application/v2_model_schemas.py` — strict controlled context manifest.
- `migration_factory/control_tower/application/v2_failure_diagnosis.py` — consume context pack by ID/checksum.

### Likely future new files

- `migration_factory/control_tower/application/v2_controlled_context_policy.py` — selection, bounds, and redaction policy.
- `tests/control_tower/test_v2_controlled_context_policy.py` — allowed/forbidden content and traceability.

### Implementation notes

- Context content is data, never authority or instructions.
- The backend, not the frontend, chatbot, or model, chooses context sources.
- Reuse existing evidence-pack, artifact-resolution, redaction, and bounded-context mechanisms.

### Acceptance criteria

- Context contains only allowed summaries, artifacts, snippets, and retrieved entries.
- No unrestricted repository upload, secret, raw environment variable, or unredacted raw terminal log is included.
- Context-pack source references and checksums are recorded for traceability.
- Every model invocation can be audited back to the exact controlled context-pack revision.

### Focused tests

- Allowed-source matrix, secret/env/log redaction, size bounds, stale source checksum, role-specific projection, and manifest replay.

### Out of scope

- Model invocation and candidate generation.

### Dependencies

- F08-T01.
