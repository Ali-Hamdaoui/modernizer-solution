# Feature 10 Tasks — LLM Repair Candidate Generator

## Task F10-T01 — Persist the immutable diagnosis artifact

### Goal

Create a grounded diagnosis record that is separate from the proposed repair.

### Scope

- Define diagnosis ID, schema version, attempt/checkpoint/evidence/classification/retrieval bindings, author identity, findings, uncertainty, provenance, checksum, and timestamps.
- Persist immutable revisions and emit `diagnosis_created` with correlation/causation IDs.
- Keep diagnosis explanatory; it cannot classify authoritatively, approve, execute, or prove success.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_schemas.py` — strict diagnosis output schema.
- `migration_factory/control_tower/application/v2_failure_diagnosis.py` — adapt current diagnosis flow to persisted artifacts.
- `migration_factory/control_tower/application/v2_repair_flow.py` — consume diagnosis ID/checksum.

### Likely future new files

- `migration_factory/control_tower/domain/v2_diagnosis_artifact.py` — immutable diagnosis contract.
- `tests/control_tower/test_v2_diagnosis_artifact.py` — schema, persistence, and audit tests.

### Implementation notes

- Reuse artifact revisions, model role routing, context checksums, and model audit.
- Diagnosis is model-authored advisory content; backend-owned classification remains authoritative.

### Acceptance criteria

- Diagnosis can be independently verified from exact immutable context and author identity.
- Candidate generation cannot proceed with a stale or missing diagnosis checksum.

### Focused tests

- Valid/malformed/refused output, stale context, immutable revision, event and audit bindings.

### Out of scope

- Exact repair content and review.

### Dependencies

- Features 06, 08, and 09.

## Task F10-T02 — Define exact repair candidate schema

### Goal

Create a strict immutable contract for deterministic and generative candidates.

### Scope

- Define diagnosis binding, mode, safety-envelope version, remaining context bindings, author identity, candidate type, exact content, touched paths, baseline checksums, risks, and validation intent.
- Require `repair_candidate.diff` for actionable generative diff modes.
- Reject command, argv, env, sandbox, approval, classification, and success-proof fields.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_schemas.py` — strict output validation.
- `migration_factory/control_tower/application/v2_repair_flow.py` — persist candidate revisions.

### Likely future new files

- `migration_factory/control_tower/domain/v2_repair_candidate.py` — aggregate.
- `tests/control_tower/test_v2_llm_authored_patch_candidate.py` — exact diff/forbidden fields.

### Implementation notes

- LLM authors content only inside backend-selected envelope.
- Exact bytes and checksum are source of truth.

### Acceptance criteria

- Actionable candidate cannot omit exact change content or any required binding.

### Focused tests

- Schema matrix, raw command rejection, checksum determinism.

### Out of scope

- Review and apply.

### Dependencies

- F10-T01.

## Task F10-T03 — Generate and revise candidates with a fake proposer

### Goal

Integrate proposer role invocation and immutable revision creation.

### Scope

- Build bounded prompt/context from persisted refs.
- Resolve backend model identity and validate output.
- Persist initial and feedback-driven revisions without overwriting.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_role_router.py` — resolve proposer identity.
- `migration_factory/control_tower/application/v2_repair_gate_service.py` — revision gate integration.
- `migration_factory/control_tower/application/v2_repair_flow.py` — orchestration adapter.

### Likely future new files

- `migration_factory/control_tower/application/v2_repair_candidate_generator.py` — generation/revision.
- `tests/control_tower/test_v2_repair_candidate_generator.py` — fake proposer cases.

### Implementation notes

- Reuse artifact revision patterns.
- Human feedback can request revision; chatbot cannot write/apply files.
- No live model calls in tests.

### Acceptance criteria

- Each revision has new immutable ID/checksum and exact context bindings.

### Focused tests

- Valid, malformed, empty, timeout, stale context, feedback revision.

### Out of scope

- Reviewer and approval.

### Dependencies

- F10-T02, F10-T04, and F10-T05.

## Task F10-T04 — Define the Azure AI Foundry provider contract

### Goal

Implement and document a single Azure AI Foundry model-provider path for DEMO3.

### Scope

- Define a backend-owned adapter contract for the Control Tower assistant, proposer, and reviewer roles.
- Accept only controlled context-pack references and backend-resolved role/deployment configuration.
- Map provider failures to stable safe backend errors and auditable invocation outcomes.
- Keep provider credentials and raw provider responses out of public APIs and events.

### Likely future modified files

- `migration_factory/control_tower/application/v2_model_role_router.py` — resolve Foundry role/deployment identity.
- `migration_factory/control_tower/application/v2_repair_candidate_generator.py` — invoke the backend adapter.
- `migration_factory/control_tower/adapters/fastapi/app.py` — expose safe health/status only.

### Likely future new files

- `migration_factory/control_tower/infrastructure/azure_ai_foundry_adapter.py` — single provider implementation.
- `tests/control_tower/test_v2_azure_ai_foundry_adapter.py` — contract and safe-error tests.

### Implementation notes

- Azure AI Foundry is the only supported DEMO3 provider.
- The frontend never calls Foundry and never supplies provider, endpoint, deployment, credentials, or fallback choices.
- Do not add a generic multi-provider router, direct OpenAI path, Copilot runtime path, or fallback provider.

### Acceptance criteria

- Backend has one documented AI-provider contract and it is Azure AI Foundry-only.
- No frontend direct call to Foundry exists.
- No Copilot runtime path exists.
- Provider errors are mapped to safe backend errors.
- Secrets are never returned in API responses or events.

### Focused tests

- Adapter request/response contract, role resolution, safe error mapping, credential redaction, and no-network fake.

### Out of scope

- Provider selection UI and additional providers.

### Dependencies

- Feature 08 and F10-T01.

## Task F10-T05 — Document Azure AI Foundry configuration and validation

### Goal

Document and validate the backend runtime configuration required for Azure AI Foundry.

### Scope

- Define placeholder configuration keys for project/model endpoint, deployment identities, authentication mode, timeout, and bounded retry policy.
- Document the expected Azure AI Foundry project/model endpoint shape without real tenant, subscription, project, deployment, or secret values.
- Define readiness/health behavior that reports safe configured/unavailable state without revealing credentials.
- Map missing configuration, authentication failure, timeout, rate limit, content filter, and malformed response outcomes.

### Likely future modified files

- Backend settings/configuration module — exact location needs verification.
- `migration_factory/control_tower/application/v2_model_role_router.py` — consume validated Foundry role configuration.
- Safe health/status projection — exact endpoint needs verification.

### Likely future new files

- `tests/control_tower/test_v2_azure_ai_foundry_configuration.py` — configuration and failure-mode matrix.

### Implementation notes

- Documentation and tests use placeholders only, for example `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and role-specific deployment references.
- No real endpoints, API keys, tenant IDs, subscription IDs, project names, or deployment names belong in source or docs.
- A health check validates configuration/connectivity safely; it must not perform migration work or expose secrets.

### Acceptance criteria

- Required environment/configuration keys are listed as placeholders only.
- Expected endpoint shape and backend-only use are documented.
- Health/check behavior is defined.
- Missing config, auth failure, model timeout, rate limit, content filter, and malformed response have safe documented outcomes.

### Focused tests

- Missing/invalid config, safe health projection, fake auth failure, timeout, rate limit, content filter, malformed response, and recursive secret leakage.

### Out of scope

- Provisioning Azure resources or storing real credentials.

### Dependencies

- F10-T04.
