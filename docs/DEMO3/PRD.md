# DEMO3 Product Requirements Document

## Generic Governed Failure Recovery, Checkpointed Execution, and LLM-Authored Reviewed Repair

**Product:** AI Migration Control Tower

**Release:** DEMO3

**Document status:** Proposed implementation baseline

**Target baseline:** `stable`

**Baseline commit after documentation merge:** `ea6d5db4bf5ce9d22ceb3f372ff780e0254c0709`

**Runtime-code base before docs:** `ff84d69ad5e17098d08d4efbfe76c500effc2d49`

**Date:** 2026-06-23

**Source inputs:** current repository architecture and the existing DEMO3 product baseline

---

## 1. Executive Summary

DEMO3 evolves the AI Migration Control Tower from a mostly linear migration runner into a generic governed failure-recovery engine for failed migration stages.

The product delivered by DEMO3 is not a Jackson repair system or a catalog of backend-authored fixed repairs. It is a reusable recovery flow that supports checkpointed stage attempts, immutable failure evidence, deterministic or broad failure classification, targeted retrieval, policy-selected repair modes, LLM-authored diagnosis and exact repair candidates, independent model review, backend safety validation, human-approved sandbox execution, validation proof, and checkpoint promotion.

Azure AI Foundry is the only supported LLM provider and AI runtime for DEMO3. The Control Tower assistant is powered through a backend-owned Azure AI Foundry adapter and Azure AI Foundry project/model endpoint. GitHub Copilot is not a product dependency, runtime assistant engine, fallback provider, client delivery requirement, or part of the product data path.

```text
Frontend Cockpit
    ↓
Control Tower Backend
    ↓
Azure AI Foundry Adapter
    ↓
Azure AI Foundry model endpoint
```

The Control Tower backend is the only boundary allowed to call Azure AI Foundry. The frontend sends user intent and governed actions to the backend; it never invokes a model endpoint directly and never receives provider credentials.

### 1.1 Foundry-only LLM runtime boundary

Azure AI Foundry is the only allowed LLM runtime boundary for DEMO3 and future governed repair work.

All proposer, reviewer, assistant, diagnosis, candidate-generation, retrieval-grounded explanation, and repair-review model calls must go through a backend-owned Azure AI Foundry adapter. The adapter owns credential resolution, endpoint binding, role-to-deployment mapping, request construction, response validation, safe error mapping, redaction, audit, and invocation records.

Frontend code must never call Azure AI Foundry directly and must never receive model keys, endpoints, deployments, environment variable names, provider configuration, provider credentials, or provider selection controls. Application services should not read model provider environment variables directly; they should depend on the backend Foundry adapter contract. Model role routing is a backend capability concern, not a public provider contract.

Model-required operations fail closed when Foundry is unavailable, malformed, or policy-invalid. Deterministic non-model assistance may still exist for status, explanations, and local guidance, but it must be explicitly labeled as non-model output and must not masquerade as a successful model response or satisfy proposer, reviewer, repair-candidate, or repair-review requirements.

Azure OpenAI-specific code, configuration, public DTOs, and terminology are current implementation debt unless encapsulated behind the Azure AI Foundry adapter contract and hidden from public and product surfaces.

### 1.2 Copilot prohibition

GitHub Copilot must not be used by DEMO3.

GitHub Copilot is not an allowed runtime, fallback, planning engine, repair provider, report generator, reviewer, proposer, or execution assistant. Prohibited uses include runtime assist, repair generation, planning generation, analysis enrichment, review, final report generation, TUI status or probing, fallback after Foundry failure, and any CLI, SDK, or hidden execution path.

Historical Copilot schemas and artifacts may remain readable for legacy compatibility, and old Copilot code may remain temporarily as dead or quarantined code. It must not be reachable from Control Tower, DEMO3, orchestrator, repair, report, TUI, public API, or frontend runtime paths. New features must not add Copilot calls, provider selection to the frontend, or provider internals in public DTOs.

The central authority split is:

```text
LLM proposes the possible fix.
Independent reviewer critiques the exact proposal.
Backend judges whether the proposal is safe, bounded, approved, and applicable.
Human decides whether it may run.
Backend applies it only in a derived sandbox.
Compile, tests, or configured validation determine whether it worked.
```

The backend is not the repair brain. It is the judge, guard, executor, and proof recorder. For generative modes, the proposer LLM is the exact repair author. For deterministic modes, the proposer LLM recommends and explains an allowed backend-known mechanism and its reviewed parameters. The human is the decision owner, and sandbox validation is the truth.

The generic pipeline is:

```text
failed attempt
-> failure evidence
-> deterministic or broad classification
-> targeted retrieval based on failure class and migration profile
-> repair mode and safety-envelope selection
-> LLM-authored diagnosis
-> LLM-authored repair candidate
   -> deterministic recipe plan OR
   -> bounded source patch OR
   -> POM diff OR
   -> config diff OR
   -> test fix OR
   -> manual-review recommendation
-> independent reviewer model
-> generic backend validators
-> human approval
-> sandbox execution
-> compile/test or configured validation proof
-> new checkpoint
```

The first deterministic validation fixture is a Stage 4 Spring Boot 4 / Java 21 migration that fails because of an incomplete Jackson 2 to Jackson 3 migration. `JACKSON_JSONNODE_UNRESOLVED` is the first registered failure signature, the Jackson retrieval policy is the first targeted retrieval example, the OpenRewrite Jackson recipe is the first repair strategy example, and the same scenario is the first end-to-end test.

That fixture validates the engine; it does not define the architecture. Future failure classes and fixes must plug into the same core recovery flow through policies, structured candidate artifacts, generic validators, and sandbox proof rather than new hardcoded orchestration branches or backend-authored repair logic for every failure.

The invariant is:

```text
Chatbot interprets.
Human decides.
Backend validates, persists, executes in sandbox, and proves with artifacts.
```

Artifacts remain the source of truth. Validation remains proof.

The architecture distinction is:

```text
Backend is fixed around generic safety and execution rules.
Backend is not fixed around specific repair knowledge.

LLMs provide flexibility by authoring exact generative fixes the backend did not know in advance.
Backend provides safety by validating, sandboxing, rolling back, and proving.
```

DEMO3 must reuse F15 gates, artifact revisions, stage progression, the orchestrator runner, repair services, reviewer persistence, artifact resolution, event streaming, repositories, validation, rollback, and proof systems. It must not introduce an autonomous migration agent, a second orchestrator, a Jackson-specific core engine, or a frontend-controlled execution path.

---

## 2. Product Vision

A migration is not a single disposable run. It is a governed graph of:

```text
approved inputs
stage attempts
accepted checkpoints
failure evidence
failure signatures
retrieval packs
repair modes and safety envelopes
diagnosis artifacts
LLM-authored repair candidates
independent reviews
human decisions
sandbox executions
validation proofs
promoted checkpoints
```

DEMO3 establishes a generic graph-shaped recovery path across failure classes. It should make the platform capable of answering:

- Which exact prior-stage checkpoint was used?
- Which stage attempt failed?
- What immutable evidence describes the failure?
- Which deterministic signature and failure class matched?
- Which retrieval policy selected the migration knowledge?
- Which repair mode and safety envelope governed the proposal?
- What exact recipe plan, source patch, POM diff, configuration change, or test fix did the LLM author?
- Which candidate revision did the reviewer inspect?
- Which exact revision did the human approve?
- What did the backend execute, under which policy, and in which backend-bound sandbox?
- Which configured validation proved the result?
- Which checkpoint contains the promoted output?

Every answer must come from persisted backend evidence, not model memory or frontend state.

The architecture must support additional compiler, dependency, test, runtime, configuration, framework, and build-tool failures without changing the core recovery orchestration or requiring the backend to contain a deterministic fix implementation for each new failure.

---

## 3. Current Repository Reality

### 3.1 Baseline branch

The implementation baseline is:

```text
stable
```

Baseline commit after documentation merge:

```text
ea6d5db4bf5ce9d22ceb3f372ff780e0254c0709
```

Runtime-code base before docs:

```text
ff84d69ad5e17098d08d4efbfe76c500effc2d49
```

Implementation branches must be created from `stable` after the Foundry-only foundation documentation is merged. Earlier exploratory work happened on `chatbot-optimization`, but DEMO3 implementation must proceed from `stable` after the Foundry-only baseline is accepted.

### 3.2 Existing assets to reuse

The repository already contains:

- persisted F15 phase gates;
- immutable gate decisions;
- artifact revision records;
- checksum stale protection;
- idempotent gate actions;
- analysis, planning, approval, repair, and stage-completion gate concepts;
- backend-generated stage commands;
- the V2 orchestrator runner;
- role-based model routing;
- structured model-output validation;
- repair proposals and revision metadata;
- reviewer critiques bound to proposal and context checksums;
- sandbox patch application, validation, rollback, and repair ledger capabilities;
- deterministic failure classification;
- bounded evidence collection;
- gate-bound artifact resolution and redaction;
- event streaming and cockpit projections.

Primary reuse points:

```text
migration_factory/control_tower/application/v2_stage_progression.py
migration_factory/control_tower/application/v2_orchestrator_runner.py
migration_factory/control_tower/application/v2_gate_action_service.py
migration_factory/control_tower/application/v2_phase_gate_service.py
migration_factory/control_tower/application/v2_failure_diagnosis.py
migration_factory/control_tower/application/v2_repair_flow.py
migration_factory/control_tower/application/v2_repair_gate_service.py
migration_factory/control_tower/application/v2_reviewer_service.py
migration_factory/control_tower/application/v2_model_role_router.py
migration_factory/control_tower/application/v2_gate_artifact_resolver.py
migration_factory/control_tower/application/v2_evidence_pack_builder.py
migration_factory/repair_loop/
migration_factory/control_tower/infrastructure/sqlite/
web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx
```

The existing failure classifier and repair rule registry already demonstrate deterministic matching, structured proposals, patch-path checks, sandbox patch application, rollback, reviewer checksum gates, and validation. DEMO3 generalizes those concepts into explicit failure-signature, retrieval-policy, repair-mode, candidate-validation, review, execution, validation, and checkpoint-promotion abstractions. Existing fixed rules are reuse points, not the limit of future repair generation.

### 3.3 Stage 4 branch gap

The active branch is currently limited to three governed stages. Its stage-progression code and public description explicitly exclude a Boot 4 stage.

Stage 4 work exists in another branch history, including:

```text
3c11315 - enable four-stage progression
980c068 - add governed Stage 4 schema support
b48ae40 - bind Stage 4 progression to accepted artifacts
1e06b32 - persist stage output artifact revision before Stage 4 progression
```

DEMO3 must review and port the required behavior. These commits are reconciliation inputs, not authoritative patches to apply blindly.

### 3.4 Existing checkpoint terminology

The repository has durable LangGraph run-state persistence. This supports resuming an interrupted orchestration run, but it is not the `StageCheckpoint` required by DEMO3.

DEMO3 `StageCheckpoint` means:

```text
an immutable, checksum-bound, validated logical output of a completed stage
that the backend may reuse as input for a later attempt
```

It must not mean:

- a frontend-visible directory;
- a raw sandbox path;
- an in-memory state snapshot;
- an unvalidated command result;
- a mutable working tree.

### 3.5 Existing security debt relevant to DEMO3

The current stage progression contract still permits a client `sandbox_path` in some modes and returns continuation details containing `sandbox_path` and `argv`.

DEMO3 must remove these from the public recovery contract. Policy-dependent rejection is insufficient: path and command input must be impossible for every DEMO3 checkpoint, retry, resume, fork, and repair API.

---

## 4. Problem Statement

### 4.1 Later-stage failures cause excessive restart cost

When a later stage fails, users need to preserve proven earlier-stage work. A Stage 4 failure should not force Stages 1 through 3 to run again when the accepted Stage 3 result remains valid.

### 4.2 Stage output is not a first-class reusable object

The current V2 progression path resolves a sandbox from command result data. That is adequate for linear progression but insufficient for:

- multiple attempts of the same stage;
- retry from a precise input;
- resume after operator delay;
- alternative strategy forks;
- lineage and audit;
- checksum compatibility validation.

### 4.3 Failure evidence is not complete enough

Existing failure evidence is useful but does not consistently bind:

- the failed attempt;
- its input checkpoint;
- normalized diagnostics;
- relevant source snippets and hashes;
- migration profile;
- dependency summary;
- transformation results;
- build and test results;
- prior repair attempts.

Without these bindings, a model can produce plausible but weakly grounded repair advice.

### 4.4 Static failure-specific design would not scale

A recovery flow implemented as Jackson-specific branches or a fixed catalog of backend-authored repairs would make every new failure or fix require orchestration changes. That would couple the engine to known symptoms, duplicate policy logic, and prevent LLMs from proposing bounded fixes for failures the backend has never seen.

Failure recognition, retrieval, repair-mode selection, review add-ons, execution constraints, and validation requirements must be registry- or policy-driven. Exact repair content may be deterministic or LLM-authored. The core engine must remain stable as new signatures, repair modes, and candidate patches are added.

### 4.5 The Jackson fixture exposes a broader recovery gap

The current deterministic classifier does not identify the targeted Jackson 2 to Jackson 3 `JsonNode` failure. It generally degrades to `UNKNOWN_MIGRATION_FAILURE`.

This is the first acceptance gap, not the only product problem. The same engine must later support failures such as:

- `JAKARTA_IMPORT_NOT_MIGRATED`;
- `SPRING_SECURITY_REMOVED_API`;
- `HIBERNATE_6_API_BREAK`;
- `MAVEN_PLUGIN_INCOMPATIBLE`;
- `TEST_FAILURE`;
- `RUNTIME_STARTUP_FAILURE`;
- `CONFIG_PROPERTY_REMOVED`;
- `DEPENDENCY_CONFLICT`.

### 4.6 Reviewer independence is not enforced

The platform can route proposer and reviewer roles to different deployments, but it does not yet prove that they are different model identities for a specific author/review pair.

### 4.7 Application evidence and migration knowledge are mixed conceptually

Application evidence describes what happened in this job. Retrieved migration knowledge describes how approved guidance relates to the classified failure. They require separate provenance, policies, artifacts, and checksums.

### 4.8 Recovery UX is incomplete

The cockpit can show gates, failures, proposals, reviews, and validation traces, but it cannot yet present checkpoint lineage, attempt history, or checkpoint-based retry, resume, and fork actions.

---

## 5. DEMO3 Goals

DEMO3 must:

1. Bring governed Stage 4 support to implementation branches created from `stable`.
2. Ensure Stage 4 consumes an accepted, validated Stage 3 checkpoint.
3. Remove frontend and chatbot control over paths, commands, argv, env, and filesystem targets.
4. Persist immutable `StageCheckpoint` and `StageAttempt` records.
5. Retry a failed stage from the same accepted input checkpoint.
6. Preserve every failed and successful attempt.
7. Introduce a generic `FailureRecoveryEngine` that orchestrates the governed recovery flow.
8. Persist complete, immutable failure evidence through an `EvidenceCollector`.
9. Classify failures deterministically through a `FailureClassifier` and `FailureSignature` registry.
10. Build targeted retrieval packs through `RetrievalPackBuilder` and `KnowledgeRetrievalPolicy`.
11. Select an allowlisted repair mode and safety envelope through `RepairStrategyRegistry`.
12. Generate schema-valid diagnosis and exact repair-candidate artifacts through `RepairCandidateGenerator`, including bounded source, POM, configuration, and test diffs.
13. Enforce exact-revision review through an `IndependentReviewer`.
14. Enforce backend policy through `BackendPolicyValidator`.
15. Require a `HumanApprovalGate` before execution.
16. Apply repairs only through `SandboxRepairExecutor`.
17. Use compile, focused tests, or other configured validation as final proof.
18. Promote successful outputs through `CheckpointPromoter`.
19. Show the complete recovery lineage in the cockpit.
20. Prove the engine first with the Stage 4 Jackson fixture.
21. Allow future signatures, retrieval policies, repair modes, LLM-authored fixes, review add-ons, and validation rules without changing core orchestration.
22. Apply reviewed and approved LLM-authored bounded diffs without requiring backend-authored fix logic for each failure.
23. Use Azure AI Foundry as the single DEMO3 model-provider path through a backend-owned adapter.
24. Keep GitHub Copilot outside the product runtime, client data path, security requirements, and migration execution flow.
25. Disable or quarantine every Copilot runtime path before implementing DEMO3 model-backed repair.
26. Remove public provider/configuration leakage before exposing DEMO3 model status, recovery, or repair contracts.
27. Bind every model invocation to redacted, bounded, content-checksummed, policy-versioned context packs.

---

## 6. Non-Goals

DEMO3 does not include:

- arbitrary autonomous code repair;
- production source mutation;
- deployment, pull request creation, or merge;
- support for every migration failure type in the first release;
- support for every framework or build system in the first release;
- dynamic LLM-authored executable stages;
- cross-job checkpoint reuse;
- checkpoint import from arbitrary filesystems;
- advanced checkpoint retention or pruning;
- a general enterprise policy editor;
- a full-scale vector-search platform;
- historical repair-memory learning;
- generalized LLM-authored analysis and planning in the first delivery slice;
- advanced multi-fork comparison UI;
- replacement of the current orchestrator or repair loop;
- a hardcoded Jackson-only architecture;
- a static one-failure repair system;
- a requirement that every future repair be a pre-known deterministic recipe or backend-authored rule;
- authoritative model classification;
- model-selected paths, commands, environments, or sandboxes;
- direct OpenAI API access;
- multi-provider selection, routing, or runtime fallback;
- frontend or browser calls to Azure AI Foundry;
- GitHub Copilot integration;
- GitHub Copilot as a runtime, assistant engine, execution dependency, or client prerequisite;
- GitHub Copilot fallback when Azure AI Foundry is unavailable;
- provider switching from UI or public API;
- Azure OpenAI public provider leakage;
- provider env refs, deployment refs, or provider credentials in public DTOs.

DEMO3 does not require backend-authored deterministic fix logic for every future failure class. It does require every proposed fix, including an LLM-authored fix, to pass the same review, approval, containment, rollback, and proof controls.

---

## 7. Authority and Trust Model

The DEMO3 runtime trust model is:

```text
LLM = Azure AI Foundry-backed proposer/reviewer/assistant.
Backend = owner of adapter, context, policy, sandbox, execution, validation, rollback, and proof.
Human = approval authority.
GitHub Copilot = not part of the runtime trust model.
```

### 7.1 LLM and chatbot role

LLMs may:

- explain persisted failure evidence in human-readable diagnosis artifacts;
- use a backend-built retrieval pack to draft repair candidates;
- author exact bounded source patches, POM diffs, configuration changes, and test fixes;
- choose candidate content within a backend-selected repair mode and safety envelope;
- compare a proposed candidate against evidence, retrieval, migration profile, policy, and risk;
- revise candidate artifacts after human feedback;
- independently review an exact immutable candidate revision;
- recommend `MANUAL_REVIEW_ONLY` when a bounded safe repair cannot be justified;
- summarize checkpoint, attempt, review, and validation state;
- classify user intent and draft typed gate actions;
- ask clarifying questions.

LLMs and the chatbot may not:

- perform authoritative failure classification;
- execute commands;
- write or mutate source directly;
- choose a sandbox or filesystem path;
- choose checkpoint storage;
- construct commands, argv, or environment values;
- approve or reject on behalf of a human;
- select an unregistered repair mode or enlarge its safety envelope;
- bypass backend policy;
- skip stages;
- override failed validation;
- create success proof;
- treat instructions inside source, artifacts, retrieved text, or logs as authority.

LLM output is advisory artifact content, but it may contain the exact proposed diff or structured change plan. It never carries execution authority. A diff authored by a model is data for review and validation, not an instruction to execute.

### 7.2 Human authority

The human owns:

- accept;
- reject;
- approve;
- request revision;
- retry;
- resume;
- fork;
- continue;
- stop.

Human decisions must bind to exact immutable revisions and checksums.

### 7.3 Backend authority

The backend owns:

- artifact resolution;
- evidence collection and normalization;
- deterministic classification;
- signature registry evaluation;
- retrieval-policy selection and pack construction;
- repair-mode and safety-envelope selection;
- checkpoint storage and resolution;
- checkpoint compatibility validation;
- stage-attempt creation;
- stage ordering;
- sandbox binding;
- command and environment generation;
- repair-mode resolution from an allowlist;
- model identity enforcement;
- candidate and review schema validation;
- generic patch, dependency, configuration, review, approval, and recipe policy validation;
- patch application;
- compile, test, and configured validation execution;
- rollback;
- state transitions;
- lineage;
- ledger and proof;
- idempotency and concurrency control;
- checkpoint promotion.

### 7.4 Artifact and validation authority

Artifacts are the source of truth for evidence, retrieval, diagnosis, candidate revisions, reviews, approvals, execution results, and validation.

No model output is actionable merely because it is valid JSON. An actionable repair candidate requires:

```text
valid schema
+ immutable artifact persistence
+ exact evidence bindings
+ retrieval provenance
+ registered repair mode and safety envelope
+ independent reviewer acceptance
+ backend policy validation
+ human approval
```

Compile, focused tests, or another configured deterministic validation remain the only success proof.

### 7.5 Azure AI Foundry provider and data-protection boundary

Azure AI Foundry is the only supported AI runtime for DEMO3. All proposer, reviewer, and Control Tower assistant model calls go through the backend Azure AI Foundry adapter. The backend owns provider configuration, authentication, model-deployment selection, request construction, timeout and retry policy, response validation, error mapping, and model-invocation audit.

The browser and frontend:

- never call Azure AI Foundry directly;
- never receive endpoint keys, deployment keys, API keys, tokens, provider credentials, or raw provider configuration;
- never choose a provider, endpoint, deployment, fallback model, or model client;
- send only user intent, governed action fields, IDs, checksums, feedback, and idempotency data allowed by the public backend contract.

The backend sends controlled context packs rather than unrestricted repository content. No source code, logs, diffs, artifacts, or retrieved material is sent to a model unless selected by backend policy for the specific role and invocation. Every context pack must be bounded, redacted, checksum-bound, and auditable, with source references recorded for traceability. Secrets, raw environment variables, unredacted terminal logs, credentials, and unrestricted repository uploads are forbidden model inputs.

For DEMO3, GitHub Copilot is not part of the product data path. The client does not need Copilot licenses, Copilot organization settings, Copilot Chat, Copilot CLI, or Copilot cloud-agent access to run the Control Tower. No client feature or migration execution may depend on Copilot being installed, enabled, licensed, or available.

Existing repository names containing `copilot_*` are legacy internal naming and do not define the DEMO3 provider architecture. They require a later code/API naming and dependency audit where they create client-facing ambiguity; they are not renamed by this PRD.

---

## 8. Required Delivery Order

The required order is:

```text
0. Foundry-only foundation and Copilot quarantine
1. Stage 4 branch reconciliation
2. public API hardening
3. StageCheckpoint and StageAttempt persistence
4. retry from accepted checkpoint
5. generic evidence schema and collector
6. FailureSignature registry with Jackson fixture first
7. KnowledgeRetrievalPolicy registry and targeted retrieval packs
8. RepairStrategyRegistry as an allowed-mode and safety-envelope registry, with deterministic OpenRewrite and generative bounded-patch modes
9. diagnosis and repair candidate generation
10. independent review
11. backend policy validation and human approval
12. sandbox execution and configured validation
13. checkpoint promotion
14. cockpit recovery UX
```

Foundation 0 is a blocker for Stage 4 and DEMO3 implementation because the current stable codebase still contains reachable Copilot runtime paths, Azure OpenAI-specific application plumbing, provider/env-ref public DTO leakage, deterministic fallback semantics that can look like assistant output, and context-pack checksums that are not content-derived or policy-versioned.

Foundation 0 includes:

```text
FND-01 Disable/quarantine Copilot runtime paths
FND-02 Add Azure AI Foundry adapter/config contract
FND-03 Remove public provider/config leakage
FND-04 UI/report/docs terminology cleanup
FND-05 Context-pack enforcement
FND-06 Compatibility mapping for legacy Copilot/Azure OpenAI names
```

The stage/checkpoint spine must exist before model-assisted recovery. LLM analysis and planning expansion must not block the core checkpoint-repair MVP. No Stage 4, repair, report, TUI, public API, or frontend runtime path may depend on Copilot or expose Azure OpenAI provider internals while this foundation remains incomplete.

---

## 9. Migration Graph and Recovery Architecture

### 9.1 Migration graph

Previous model:

```text
Stage 1 -> Stage 2 -> Stage 3 -> Stage 4
```

DEMO3 model:

```text
Stage 3 checkpoint C3
    |
    +-> Stage 4 attempt A4.1 -> failed -> evidence E1
    |                                  -> signature S1
    |                                  -> retrieval pack K1
    |                                  -> repair mode M1
    |                                  -> candidate P1
    |                                  -> review V1
    |
    +-> Stage 4 attempt A4.2 -> repaired -> validated -> checkpoint C4
    |
    +-> Stage 4 attempt A4.3 -> alternative reviewed strategy fork
```

The graph is controlled by backend validation. A user may request an edge but cannot define its storage location or executable parameters.

### 9.2 Generic recovery components

`FailureRecoveryEngine`

: Coordinates the generic recovery state machine. It consumes persisted IDs and policy results, delegates to existing services, and does not implement failure-specific branches.

`EvidenceCollector`

: Collects bounded, redacted, immutable evidence for the exact failed attempt and input checkpoint according to an `EvidenceSchema`.

`FailureClassifier`

: Deterministically evaluates registered `FailureSignature` entries and returns a `FailureClass`, signature ID, confidence, and matched evidence.

`RetrievalPackBuilder`

: Selects `KnowledgeRetrievalPolicy` by signature and migration profile, retrieves only approved knowledge, and persists a checksum-bound retrieval pack.

`RepairStrategyRegistry`

: Resolves an allowlisted repair mode and safety envelope compatible with the signature, profile, candidate type, review requirements, execution policy, and validation policy. Some modes map to deterministic backend-known mechanisms. Other modes authorize the proposer LLM to author a bounded diff or change plan that generic backend validators can assess.

`RepairCandidateGenerator`

: Uses the exact evidence, retrieval pack, selected repair mode, and safety envelope to request schema-valid diagnosis and candidate artifacts from the proposer model. For generative modes, an actionable candidate contains the exact source, POM, configuration, or test diff that will be reviewed and applied. A plan without exact change bytes is advisory only.

`IndependentReviewer`

: Reviews the exact candidate revision using generic checks plus mode-specific or deterministic-implementation review requirements. The reviewer model identity must differ from the author identity.

`BackendPolicyValidator`

: Coordinates generic validators for lineage, checksums, model identity, registry membership, patch applicability, path containment, dependency policy, configuration policy, review, approval, execution policy, validation policy, and stale-state protection. It judges a candidate; it does not need to know the correct repair in advance.

`HumanApprovalGate`

: Records accept, reject, or revise decisions against the exact reviewed candidate and policy context.

`SandboxRepairExecutor`

: Resolves backend-owned execution details and applies either a deterministic mechanism or an approved LLM-authored candidate in a backend-bound sandbox. It records actual changes, validates containment, and rolls back failed repairs.

`CheckpointPromoter`

: Promotes a successful attempt output only after configured validation proof passes and all checkpoint-promotion rules are satisfied.

### 9.3 Core lineage rule

Every attempt must identify:

- its stage;
- its input checkpoint;
- its creation reason;
- its parent attempt when applicable;
- its failure evidence when failed;
- its classification and signature;
- its retrieval pack;
- its selected repair mode, safety-envelope version, and deterministic strategy revision when applicable;
- its diagnosis and candidate revisions;
- its independent review;
- its human decision;
- its execution and validation result;
- its output checkpoint when successful.

---

## 10. Generic Domain Abstractions

### 10.1 Recovery policy abstractions

`FailureClass`

: Stable category used by the engine and reporting. Examples include package rename, removed API, dependency conflict, test failure, runtime startup failure, and configuration incompatibility.

`FailureSignature`

: Versioned deterministic matching definition that maps evidence and migration profile to a `FailureClass` and signature ID.

`EvidenceSchema`

: Versioned definition of required and optional evidence fields for a stage profile and failure family.

`KnowledgeRetrievalPolicy`

: Versioned mapping from signature and migration profile to approved retrieval topics, corpus constraints, required provenance, and quality gates.

`RepairStrategy`

: Versioned policy entry that defines an allowed repair mode and safety envelope. It may identify a deterministic mechanism such as an OpenRewrite recipe, or a generative mode such as `LLM_AUTHORED_PATCH`. It constrains what candidate artifacts may contain, which logical paths and change types are permitted, which validators and approvals are required, how execution occurs, and which proof must pass. It does not need to encode the exact future fix.

`ReviewPolicy`

: Generic reviewer checklist plus optional failure-, mode-, or deterministic-implementation-specific checks.

`ExecutionPolicy`

: Backend-owned constraints for sandbox resolution, allowed actions, touched paths, containment, rollback, and command generation.

`ValidationPolicy`

: Required compile, test, runtime, dependency, configuration, or other deterministic proof for a repair mode and stage profile.

`CheckpointPromotionPolicy`

: Rules that determine whether validated attempt output may become a reusable accepted checkpoint.

### 10.2 StageCheckpoint

Required fields:

```text
checkpoint_id
job_id
stage_index
checkpoint_status
checkpoint_kind
profile_id
profile_version
input_checkpoint_id
created_by_attempt_id
source_artifact_revision_ids
artifact_manifest_checksum
content_checksum
validation_report_ref
validation_report_checksum
compatibility_contract_version
sandbox_binding_ref
created_at
accepted_at
accepted_by
superseded_by_checkpoint_id
```

Rules:

- Immutable after insertion.
- Does not expose a filesystem path.
- Candidate checkpoints are not reusable.
- Only validated and accepted checkpoints are reusable.
- Acceptance binds to exact content and validation checksums.
- Superseded and invalid checkpoints remain visible but are not reusable.
- A checkpoint cannot be accepted when its producing attempt failed.

### 10.3 StageAttempt

Required fields:

```text
attempt_id
job_id
stage_index
input_checkpoint_id
parent_attempt_id
created_reason
strategy_revision_id
attempt_status
command_id
profile_id
profile_version
failure_evidence_ref
failure_evidence_checksum
output_checkpoint_id
started_at
completed_at
created_at
```

Allowed creation reasons:

```text
initial
retry
repair_retry
resume
fork
```

Rules:

- Every execution creates a distinct attempt.
- A retry never overwrites the failed attempt.
- Only the backend creates command and sandbox bindings.
- An attempt has at most one output checkpoint.
- A failed attempt must not produce an accepted output checkpoint.

### 10.4 Recovery requests

`RetryRequest` public fields:

```text
failed_attempt_id
input_checkpoint_id
expected_checkpoint_checksum
idempotency_key
request_checksum
human_reason
```

`ResumeRequest` public fields:

```text
checkpoint_id
target_stage_index
expected_checkpoint_checksum
idempotency_key
request_checksum
human_reason
```

`ForkRequest` public fields:

```text
checkpoint_id
target_stage_index
strategy_revision_id
expected_checkpoint_checksum
idempotency_key
request_checksum
human_reason
```

The backend verifies compatibility and creates new attempts. Requests never contain paths, commands, argv, env, or arbitrary patches.

### 10.5 FailureEvidence

Required fields:

```text
schema_version
job_id
stage_index
attempt_id
input_checkpoint_id
profile_id
profile_version
command_run_id
failure_category
normalized_diagnostics
source_snippets
source_file_hashes
pom_summary
dependency_tree_summary
transformation_summary
build_summary
test_summary
runtime_summary
log_artifact_refs
previous_repair_attempt_ids
sandbox_binding_ref
artifact_checksums
created_at
```

### 10.6 FailureClassification

Required fields:

```text
classification_id
attempt_id
failure_evidence_checksum
failure_class
signature_id
ecosystem
framework
stage_profile
confidence
matched_evidence
classifier_version
created_at
content_checksum
```

### 10.7 RetrievalPack

Required fields:

```text
retrieval_pack_id
job_id
attempt_id
failure_evidence_checksum
classification_checksum
signature_id
profile_id
retrieval_policy_id
query_templates
corpus_version
entries
created_at
content_checksum
```

Each entry contains:

```text
source_id
source_type
title
source_url_or_internal_ref
publisher
document_version
published_or_updated_at
retrieved_at
chunk_id
chunk_checksum
relevance_score
content_excerpt
```

### 10.8 DiagnosisArtifact

Required fields:

```text
diagnosis_id
attempt_id
input_checkpoint_id
failure_evidence_checksum
classification_checksum
retrieval_pack_checksum
failure_class
signature_id
root_cause
evidence_refs
knowledge_refs
confidence
uncertainties
recommended_next_action
author_model_identity
schema_version
content_checksum
created_at
```

### 10.9 RepairCandidate

Required fields:

```text
candidate_id
revision_id
revision_number
revision_of
attempt_id
input_checkpoint_id
diagnosis_id
failure_evidence_checksum
classification_checksum
retrieval_pack_checksum
repair_mode
safety_envelope_version
repair_policy_id
deterministic_strategy_id
root_cause
proposed_repair
recipe_id_or_patch_plan
affected_paths
candidate_artifact_refs
expected_validation
risks
rollback_plan
candidate_payload_ref
proposed_diff_ref
author_model_identity
schema_version
content_checksum
created_at
```

`candidate_payload_ref` identifies the canonical `repair_candidate.json` revision. For generative modes, `proposed_diff_ref` is required and identifies the exact immutable diff bytes reviewed and approved. Structured POM or configuration plans may accompany the candidate as explanatory artifacts, but they are not executable until materialized as an exact diff in a new candidate revision. For deterministic modes, the candidate identifies the exact allowed recipe, version, and parameters; the backend may add a dry-run result.

### 10.10 ReviewerCritique

Required fields:

```text
critique_id
candidate_revision_id
candidate_checksum
failure_evidence_checksum
classification_checksum
retrieval_pack_checksum
repair_mode
repair_policy_id
deterministic_strategy_id
review_policy_id
input_checkpoint_id
attempt_id
reviewer_model_identity
author_model_identity
decision
evidence_coverage
diagnostic_match
profile_fit
checkpoint_fit
repair_mode_fit
dependency_policy_fit
path_policy_fit
validation_fit
expected_failure_resolution
remaining_risks
required_revisions
human_summary
schema_version
content_checksum
created_at
```

Decision values:

```text
accept_for_human_review
revision_required
reject
review_unavailable
failed_closed_same_model
```

---

## 11. Persistence Model

### 11.1 Lifecycle records

DEMO3 should add append-only relational records for:

- stage checkpoints;
- stage attempts;
- recovery requests or recovery decisions;
- failure classifications;
- retrieval-pack metadata;
- diagnosis metadata;
- repair-strategy bindings;
- repair-candidate review bindings when existing proposal and reviewer tables cannot represent the required lineage.

### 11.2 Registry and policy persistence

Signatures, retrieval policies, repair modes and safety envelopes, deterministic strategy definitions, review policies, execution policies, validation policies, and checkpoint-promotion policies must be versioned and auditable.

The implementation may use configuration, code-backed registries, or persisted policy records, provided that:

- core orchestration does not branch on Jackson-specific logic or on the exact contents of an LLM-authored fix;
- selected entries and versions are recorded;
- unknown or disabled entries fail closed;
- policy changes cannot silently alter an already-reviewed candidate.

The current repair loop and patch gate require deterministic rule IDs. DEMO3 must reuse their sandbox application, path checks, rollback, ledger, and validation behavior through an adapter or generalization that accepts a versioned repair mode and generic safety envelope. It must not require a new deterministic rule implementation for each accepted LLM-authored patch.

### 11.3 Artifact storage

Large JSON, Markdown, reports, diffs, logs, and source snippets remain immutable artifacts. Relational records store identifiers, lifecycle state, checksums, policy versions, and references.

The system should not create a unique table for every artifact filename.

### 11.4 Migration rules

- Add append-only migrations only.
- Do not modify applied migrations.
- Preserve existing V1/V2 compatibility unless DEMO3 explicitly replaces an unsafe public contract.
- Add indexes for job, stage, checkpoint, attempt, signature, strategy, parent attempt, status, and checksum lookup.
- Enforce immutable terminal records with triggers where practical.

### 11.5 Concurrency rules

- At most one active execution attempt per job and stage unless a reviewed fork policy explicitly permits otherwise.
- Duplicate idempotency key plus request checksum returns the original result.
- Same idempotency key with a different request checksum is rejected.
- Checkpoint acceptance must be atomic with validation-state verification.
- Two concurrent retries must not create duplicate commands for the same accepted request.

---

## 12. Checkpoint Validation

Before a checkpoint may be used, the backend must verify:

```text
checkpoint exists
checkpoint belongs to the job
checkpoint status is accepted
checkpoint is not superseded or invalid
content checksum matches
artifact manifest checksum matches
validation report checksum matches
source artifacts are resolvable
source stage precedes target stage
profile transition is permitted
Java and build-tool requirements are compatible
checkpoint compatibility contract is supported
sandbox binding is backend-resolvable
no conflicting active attempt exists
```

Validation failure must reject the request without creating a command or exposing internal execution details.

`CheckpointPromotionPolicy` must additionally verify:

- the producing attempt succeeded;
- the configured `ValidationPolicy` passed;
- required evidence and execution artifacts exist;
- actual touched paths satisfy policy;
- rollback is not pending;
- output checksums are final;
- promotion is idempotent.

---

## 13. Stage 4 Foundation Requirements

DEMO3 requires a governed fourth stage on the active branch.

Stage 4 must:

- be represented in stage schemas and projections;
- be created only after accepted Stage 3 output exists;
- consume a backend-resolved Stage 3 checkpoint;
- use backend-generated commands and environment;
- run in a backend-bound sandbox;
- persist its attempt before execution;
- persist output artifacts before checkpoint promotion;
- produce either immutable failure evidence or a candidate output checkpoint;
- preserve all F15 gate and stage-order invariants.

There must be no direct Stage 3 bypass and no direct Stage 4 jump from chatbot or frontend input.

---

## 14. Public API Contract

### 14.1 Permitted client inputs

DEMO3 recovery APIs may accept:

```text
job_id
attempt_id
checkpoint_id
candidate_revision_id
strategy_revision_id
expected checksums
idempotency key
typed human decision
human reason or revision feedback
```

### 14.2 Forbidden client inputs

DEMO3 recovery APIs must reject:

```text
sandbox_path
source_path
target_path
working_directory
filesystem target
command
command string
argv
environment
environment variables
recipe command
raw executable plan
arbitrary patch target
model-supplied success status
model-supplied approval
```

Unknown fields must be rejected.

### 14.3 Public response restrictions

Public responses and events must not expose:

- raw sandbox paths;
- absolute filesystem paths;
- raw commands;
- argv;
- environment values;
- secrets;
- unredacted logs.

They may expose safe IDs, checksums, statuses, policy identifiers, strategy identifiers, validation summaries, and sanitized evidence summaries.

### 14.4 Compatibility endpoint

Any existing path-bearing compatibility endpoint must not be used by DEMO3 recovery flows. If retained temporarily, it must be clearly isolated from the canonical ID-only contract.

---

## 15. Generic Recovery Flows

### 15.1 Initial execution

```text
accepted input checkpoint
-> backend validates checkpoint
-> backend creates stage attempt
-> backend resolves sandbox and command
-> stage runs
-> success produces candidate output checkpoint
-> failure starts FailureRecoveryEngine
```

### 15.2 Failure recovery

```text
failed attempt
-> EvidenceCollector persists evidence
-> FailureClassifier evaluates FailureSignature registry
-> RetrievalPackBuilder selects KnowledgeRetrievalPolicy
-> RepairStrategyRegistry selects an allowed repair mode and safety envelope
-> RepairCandidateGenerator creates LLM-authored diagnosis and candidate
   -> deterministic recipe plan OR
   -> bounded source patch OR
   -> POM diff OR
   -> config diff OR
   -> test fix OR
   -> manual-review recommendation
-> IndependentReviewer reviews exact revision
-> BackendPolicyValidator runs generic candidate, review, approval, and safety validators
-> HumanApprovalGate records decision
-> SandboxRepairExecutor applies the approved recipe or candidate artifact
-> ValidationPolicy runs deterministic proof
-> CheckpointPromoter creates accepted checkpoint on success
```

### 15.3 Retry unchanged

```text
failed attempt
-> human requests retry
-> backend validates original input checkpoint
-> backend creates child attempt
-> backend creates fresh execution details
-> stage reruns unchanged
```

### 15.4 Repair and retry

```text
reviewed and approved candidate
-> backend validates candidate, policies, checksums, and lineage
-> backend creates repair_retry child attempt
-> backend applies repair in derived sandbox
-> backend validates result
-> success promotes checkpoint
-> failure persists new evidence and may re-enter recovery
```

### 15.5 Revision

```text
human requests revision with feedback
-> backend persists feedback artifact
-> proposer model receives exact prior revision, evidence, retrieval, repair mode, safety envelope, and feedback
-> new immutable candidate revision is created
-> independent reviewer reviews the new exact revision
```

Approval of an earlier revision must not authorize a later revision.

### 15.6 Resume and fork

Resume creates a new attempt from an accepted checkpoint. It does not reuse a stale process or old command.

Fork creates a new attempt using a typed, reviewed repair mode and candidate revision. It does not accept argv, a command string, or an unbound arbitrary patch.

---

## 16. Failure Classification

### 16.1 FailureClassifier

`FailureClassifier` is deterministic and authoritative for classification. It consumes immutable evidence and migration-profile context, evaluates a versioned `FailureSignatureRegistry`, and persists:

- `FailureClass`;
- signature ID;
- confidence;
- matched evidence;
- classifier and registry version.

The classifier must not call an LLM to decide the authoritative failure class.

A broad classification is still a deterministic, registered match with an explicit safety policy, such as `TEST_FAILURE` or `DEPENDENCY_CONFLICT`, but it identifies a family rather than one exact root cause. It may authorize retrieval and diagnosis while using a narrower repair envelope or requiring manual review. `UNKNOWN_MIGRATION_FAILURE` and unresolved ambiguous matches remain non-actionable.

Classification order should be deterministic:

1. validate the evidence schema;
2. evaluate high-specificity signatures;
3. evaluate broader ecosystem and stage-profile signatures;
4. preserve all matched evidence;
5. resolve ambiguity according to registry policy;
6. return an unknown, non-actionable result when no safe match exists.

### 16.2 FailureSignature registry

A registry entry may have this shape:

```json
{
  "failure_class": "PACKAGE_RENAMED",
  "signature_id": "JACKSON_JSONNODE_UNRESOLVED",
  "ecosystem": "java",
  "framework": "spring-boot",
  "stage_profile": "springboot-3.5-java21-to-4.0-java21",
  "confidence": "high",
  "matched_evidence": []
}
```

This is an example of the registry model, not a hardcoded core path.

### 16.3 First registered signature fixture

The first deterministic signature is:

```text
JACKSON_JSONNODE_UNRESOLVED
```

The classifier should consider the existing evidence categories described by this PRD, including compiler diagnostics, imports, dependency information, profile, and transformation results.

The first fixture must preserve the Jackson annotation exception: Jackson annotation imports must not be blindly migrated with databind package changes.

### 16.4 Future signatures

Future registry entries can include:

```text
JAKARTA_IMPORT_NOT_MIGRATED
SPRING_SECURITY_REMOVED_API
HIBERNATE_6_API_BREAK
MAVEN_PLUGIN_INCOMPATIBLE
TEST_FAILURE
RUNTIME_STARTUP_FAILURE
CONFIG_PROPERTY_REMOVED
DEPENDENCY_CONFLICT
```

Each new signature must plug into the same engine through:

- deterministic signature matching;
- a retrieval policy;
- one or more compatible repair strategies;
- generic and mode-specific review checks;
- execution constraints;
- validation rules;
- checkpoint-promotion rules.

Adding a signature must not require changing the core recovery state machine.

---

## 17. RAG and Retrieval Requirements

### 17.1 RetrievalPackBuilder

`RetrievalPackBuilder` creates a targeted, immutable migration-knowledge artifact after deterministic classification.

It must:

- select `KnowledgeRetrievalPolicy` by signature and migration profile;
- keep job evidence separate from migration knowledge;
- use only approved, versioned corpus entries;
- record provenance, retrieval time, versions, chunk checksums, and relevance;
- bind the pack to the exact evidence and classification checksums;
- fail closed when required knowledge is unavailable or below the quality threshold.

The LLM does not choose the corpus, query scope, or authoritative retrieval policy.

### 17.2 KnowledgeRetrievalPolicy registry

An example policy is:

```json
{
  "signature_id": "JACKSON_JSONNODE_UNRESOLVED",
  "retrieval_topics": [
    "spring_boot_4_jackson_3",
    "openrewrite_jackson_2_to_3",
    "jackson_annotation_exception"
  ]
}
```

This is the first policy example, not the only retrieval model and not a hardcoded branch in the core engine.

### 17.3 Retrieval policy inputs

Policy selection may use:

- signature ID;
- failure class;
- ecosystem;
- framework;
- source and target profile;
- stage index;
- detected dependency state;
- configured strategy family.

It must not use model preference as authority.

### 17.4 Retrieval quality gate

A trusted retrieval pack must:

- contain the required topics for the selected policy;
- contain provenance and checksums;
- match the migration profile;
- exclude unapproved sources;
- remain immutable after candidate generation;
- be re-created when evidence, classification, profile, or policy changes.

---

## 18. LLM Generation Requirements

All model generation in this section is performed by the Control Tower backend through the Azure AI Foundry adapter. “Proposer model” and “reviewer model” describe governed roles backed by Foundry model deployments, not selectable product providers. Direct OpenAI API use, Copilot runtime invocation, and provider fallback are not supported DEMO3 paths.

### 18.1 Proposer model role

The proposer model receives:

- a backend-selected controlled context pack containing allowed failure evidence;
- deterministic classification;
- targeted retrieval pack;
- selected allowlisted repair mode and safety envelope;
- migration profile;
- checkpoint and attempt context;
- schema and safety constraints;
- prior revision and human feedback when revising.

The controlled context pack must exclude secrets, raw environment variables, unrestricted repository content, and raw terminal logs unless a backend redaction policy produces an explicitly allowed bounded excerpt. Its manifest records source artifact references, checksums, redaction decisions, role, and policy version.

It may:

- explain the evidence in a human-readable diagnosis;
- connect retrieved migration knowledge to the observed failure;
- author the exact bounded repair candidate within a generative mode, including a source patch, POM diff, configuration diff, or test fix;
- recommend and explain the exact allowed recipe, version, and parameters within a deterministic mode;
- recommend manual review when no safe candidate is justified;
- identify uncertainty and risk;
- propose expected validation;
- revise the candidate after human feedback.

It may not:

- change the authoritative classification;
- choose a sandbox, absolute filesystem target, command, argv, or environment;
- invent executable authority;
- select an unregistered repair mode or exceed its policy envelope;
- approve its own candidate;
- claim success.

### 18.2 Native structured output

Diagnosis and repair candidates must use strict, versioned schemas. Required bindings must include evidence, classification, retrieval, checkpoint, attempt, selected repair mode, safety-envelope version, author identity, and content checksum.

### 18.3 Diagnosis

The diagnosis must:

- explain what failed;
- cite exact evidence references;
- cite relevant retrieval entries;
- identify uncertainties;
- distinguish observed facts from proposed interpretation;
- recommend a next action without executing it.

### 18.4 Repair candidate

The candidate must:

- remain inside the selected `RepairStrategy` repair mode and safety envelope;
- contain or reference the exact immutable diff bytes when the mode is generative;
- describe intended changes and affected logical scope;
- identify risks and rollback expectations;
- declare the expected `ValidationPolicy`;
- avoid raw commands, argv, env, and sandbox paths;
- remain non-actionable until review, backend validation, and human approval.

### 18.5 LLM-Authored Bounded Repair Candidates

LLMs are central to flexible repair generation. The proposer model may author exact changes that the backend did not know in advance, including:

- Java or other source patches;
- `pom.xml` dependency or plugin diffs;
- bounded configuration changes;
- focused test adjustments;
- structured manual-review recommendations when no safe bounded fix is justified.

The model output must be persisted as immutable candidate artifacts. A candidate revision may emit:

```text
repair_candidate.json
repair_candidate.md
repair_candidate.diff
pom_change_plan.json          # optional
config_change_plan.json       # optional
```

The backend accepts only structured candidate artifacts and policy-supported diffs or plans. Raw commands in model prose or fields are ignored or rejected and never become executable authority.

For a generative repair to become actionable, `repair_candidate.diff` is required and is the canonical proposed change. `pom_change_plan.json` and `config_change_plan.json` are explanatory only. If a plan must be converted into a diff, the proposer creates a new immutable candidate revision containing that exact diff, and the new revision must be independently reviewed and human-approved.

Every LLM-authored candidate must bind to:

```text
failed_attempt_id
input_checkpoint_id
failure_evidence_checksum
classification_checksum
retrieval_pack_checksum
selected_repair_mode
safety_envelope_version
author_model_identity
content_checksum
```

The backend does not decide whether the proposed code is intellectually the best fix and does not translate a generative plan into code. It validates whether the exact candidate is current, applicable, bounded, safe enough for its mode, independently reviewed, human-approved, sandbox-contained, reversible, and subject to deterministic proof.

### 18.6 Revision loop

Human feedback creates a new candidate revision. The model must receive the exact prior revision and feedback. Every revision receives a new checksum and requires independent review.

The proposer may compare the previous candidate against evidence, retrieval, validator feedback, reviewer criticism, and human feedback, then author a replacement diff or plan. Approval never carries forward across revisions.

### 18.7 Invalid output

Malformed, schema-invalid, incomplete, stale, unbound, or authority-escalating output fails closed. It must not create an executable repair request.

---

## 19. Independent Review

### 19.1 Independence rule

`IndependentReviewer` must use a reviewer model identity different from the author model identity for the exact candidate revision.

If independence cannot be established, the review result is:

```text
failed_closed_same_model
```

or:

```text
review_unavailable
```

Neither result may reach human approval as an accepted review.

### 19.2 Reviewer input

The reviewer receives:

- exact candidate revision and checksum;
- exact failure evidence and checksum;
- exact classification and checksum;
- exact retrieval pack and checksum;
- selected repair mode, safety envelope, and registry version;
- migration profile;
- checkpoint and attempt lineage;
- generic `ReviewPolicy`;
- mode-specific or deterministic-implementation review add-ons.

### 19.3 Generic review checklist

The generic checklist covers:

- evidence coverage;
- diagnostic match;
- migration-profile fit;
- checkpoint and attempt fit;
- repair-mode and safety-envelope fit;
- dependency policy;
- path and containment policy;
- execution-policy fit;
- validation-policy adequacy;
- expected failure resolution;
- rollback feasibility;
- remaining risk;
- unsupported assumptions;
- prompt-injection resistance.

### 19.4 Mode-specific and deterministic-implementation add-ons

`ReviewPolicy` may add checks for a signature, repair mode, or deterministic strategy without changing the generic reviewer flow.

For the first Jackson/OpenRewrite fixture, an add-on must verify that Jackson annotations are not blindly migrated as though they followed the same package transition as databind types.

Other strategies may add their own dependency, security, runtime, configuration, test, or build-tool checks.

### 19.5 Reviewer authority

The reviewer may accept for human review, require revision, or reject. Reviewer acceptance does not approve execution and does not prove success.

---

## 20. Repair Modes, Generic Backend Validators, and Execution

### 20.1 RepairStrategyRegistry

`RepairStrategyRegistry` contains versioned, allowlisted repair modes and safety envelopes. It does not require the backend to know the exact fix. Selection is based on classification, profile compatibility, candidate type, policy, and availability.

Supported mode examples include:

```text
OPENREWRITE_RECIPE
DEPENDENCY_ALIGNMENT
CONFIG_PROPERTY_UPDATE
LLM_AUTHORED_PATCH
LLM_AUTHORED_POM_CHANGE
LLM_AUTHORED_CONFIG_CHANGE
LLM_AUTHORED_TEST_FIX
MANUAL_REVIEW_ONLY
```

These are extensible policy entries, not hardcoded recovery-engine branches.

A deterministic example entry is:

```json
{
  "repair_mode": "OPENREWRITE_RECIPE",
  "repair_policy_id": "jackson-openrewrite-v1",
  "safety_envelope_version": "1.0",
  "signature_id": "JACKSON_JSONNODE_UNRESOLVED",
  "profile_ids": ["springboot-3.5-java21-to-4.0-java21"],
  "recipe_id": "org.openrewrite.java.jackson.UpgradeJackson_2_3",
  "recipe_version_policy": "backend_pinned",
  "review_policy_id": "jackson-openrewrite-review-v1",
  "execution_policy_id": "sandbox-openrewrite-v1",
  "validation_policy_id": "java-compile-focused-tests-v1",
  "requires_independent_review": true,
  "requires_human_approval": true,
  "registry_entry_checksum": "<persisted checksum>"
}
```

This is the first deterministic mode example, not a hardcoded core path.

A generative example entry is:

```json
{
  "repair_mode": "LLM_AUTHORED_PATCH",
  "repair_policy_id": "bounded-java-patch-v1",
  "safety_envelope_version": "1.0",
  "description": "LLM may propose a bounded patch candidate artifact.",
  "compatible_failure_classes": [
    "PACKAGE_RENAMED",
    "REMOVED_API",
    "TEST_FAILURE"
  ],
  "profile_ids": ["springboot-3.5-java21-to-4.0-java21"],
  "review_policy_id": "bounded-patch-review-v1",
  "execution_policy_id": "sandbox-patch-apply-v1",
  "validation_policy_id": "java-compile-focused-tests-v1",
  "requires_independent_review": true,
  "requires_human_approval": true,
  "execution": "sandbox_patch_apply",
  "validation": ["compile", "focused_tests"],
  "constraints": {
    "max_files": 8,
    "max_diff_lines": 400,
    "allowed_paths": [
      "src/main/java/**",
      "src/test/java/**",
      "src/main/resources/**",
      "pom.xml"
    ],
    "forbidden_paths": [
      ".git/**",
      ".github/**",
      "**/secrets/**",
      "**/application-prod.yml"
    ],
    "allow_dependency_changes": true,
    "allow_config_changes": true
  },
  "registry_entry_checksum": "<persisted checksum>"
}
```

These limits are illustrative and must be reconciled with current repository path policy, security controls, stage profile, and implementation capacity. They are not claims about current code defaults.

Some modes are deterministic, such as an OpenRewrite recipe already known by the backend. The LLM recommends and explains the exact allowed recipe and parameters, but does not invent its executable implementation. Some modes are generative, such as an LLM-authored bounded patch whose exact diff bytes were not known by the backend. All modes require backend validation, independent review, human approval, sandbox execution or an explicit no-execution outcome, rollback handling where applicable, and deterministic validation proof.

### 20.2 Repair-mode selection

The backend selects compatible repair-mode entries from the registry. For deterministic modes, the backend resolves a known mechanism. For generative modes, the proposer LLM authors the exact candidate content within the selected envelope. The model may not create a new execution mode, enlarge limits, or turn prose commands into authority.

If multiple modes or deterministic implementations are compatible, policy may:

- select a preferred mode deterministically;
- present reviewed alternatives to the human;
- require a reviewed fork;
- fail closed for manual review.

### 20.3 Preconditions

Execution requires:

```text
failed attempt exists
input checkpoint is valid
failure evidence is immutable
classification is authoritative and actionable, whether the matched signature is specific or broad
retrieval pack satisfies policy
repair mode and safety envelope are registered and compatible
candidate is schema-valid
candidate binds to exact evidence, repair mode, and envelope
independent review accepts exact revision
backend policy validation passes
human approves exact reviewed checksum
```

### 20.4 Generic backend validators

`BackendPolicyValidator` coordinates generic validators. These validators determine whether a proposal may advance; they do not encode the correct repair for every failure.

`PatchValidator`

- verifies the patch applies cleanly;
- verifies baseline and file checksums match;
- verifies touched paths are allowed;
- blocks absolute paths, traversal, and symlink escape;
- enforces file-count, diff-size, and binary-file limits;
- blocks forbidden files and out-of-envelope change types.

`DependencyPolicyValidator`

- verifies dependency edits are allowed for the selected repair mode;
- validates dependency coordinates and document structure;
- rejects blocked dependencies and repositories;
- applies configured version, scope, platform, and convergence policy.

`ConfigPolicyValidator`

- blocks or escalates sensitive configuration paths;
- rejects introduced secrets or secret-like values;
- protects production-only configuration;
- verifies the selected mode permits configuration changes.

`ReviewValidator`

- verifies reviewer independence;
- verifies the reviewer accepted the exact candidate checksum;
- verifies generic and mode-specific review checks passed.

`ApprovalValidator`

- verifies the human approved the exact reviewed candidate checksum;
- rejects stale, superseded, revised, or differently bound candidates.

Before execution, the validator set must also verify:

- all artifact checksums and lineage;
- no stale superseding revision exists;
- model identities satisfy independence;
- repair-mode, safety-envelope, and policy versions match the reviewed candidate;
- requested logical scope is allowed;
- a generative actionable candidate contains an exact diff rather than only a plan;
- the exact diff or deterministic recipe parameters are structurally valid and applicable;
- sandbox binding is backend-owned;
- command and environment will be backend-generated;
- validation and rollback policies are available;
- no unsafe or conflicting attempt is active.

### 20.5 SandboxRepairExecutor

`SandboxRepairExecutor` provides the generic `SandboxExecutor` role. It:

- resolves the sandbox from backend state;
- maps a deterministic mode to a backend-owned implementation or applies an approved candidate artifact through a generic sandbox adapter;
- creates command, argv, and env internally;
- applies only in the sandbox;
- never mutates the original or legacy source;
- records actual touched paths and diff;
- verifies the proposed generative diff checksum equals the reviewed and approved checksum before apply;
- verifies the applied candidate bytes equal the exact reviewed candidate bytes;
- rejects traversal, symlink escape, and out-of-policy changes;
- runs configured validation;
- rolls back failed repair attempts;
- persists execution and ledger artifacts.

### 20.6 ValidationRunner, rollback, and CheckpointPromoter

`ValidationRunner` executes the `ValidationPolicy`; its result determines success or failure. The policy may require:

- compile;
- focused tests;
- broader configured tests;
- runtime startup validation;
- configuration validation;
- dependency convergence or other deterministic checks.

Validation failure:

- does not promote a checkpoint;
- records immutable failure evidence;
- rolls back when policy requires;
- may create a new governed recovery cycle.

Model or reviewer opinion never replaces validation.

`CheckpointPromoter` promotes output only after validation proof passes, final checksums are persisted, actual touched paths satisfy policy, and no rollback is pending.

### 20.7 Concrete repair examples

#### Example 1 — Hibernate import patch

Failure:

```text
package javax.persistence does not exist
```

LLM-authored candidate:

```diff
- import javax.persistence.Entity;
- import javax.persistence.Id;
+ import jakarta.persistence.Entity;
+ import jakarta.persistence.Id;
```

The backend validates that the patch is attached to the failed attempt, based on the accepted checkpoint, matches file checksums, touches an allowed Java file, applies inside the sandbox, was accepted by the independent reviewer, was approved by the human, and passes compile and tests.

#### Example 2 — POM dependency update

Failure:

```text
NoSuchMethodError from hibernate-core
```

LLM-authored candidate:

```diff
- <hibernate.version>5.6.15.Final</hibernate.version>
+ <hibernate.version>6.6.0.Final</hibernate.version>
```

The backend validates that POM editing is allowed for the selected mode, dependency coordinates and version are policy-valid, no forbidden dependency or repository is introduced, the exact diff was reviewed and approved, and dependency resolution, build, and tests pass.

#### Example 3 — rejected path traversal

Candidate:

```diff
diff --git a/../../original-source/pom.xml b/../../original-source/pom.xml
```

The backend rejects it because the patch traverses outside the allowed relative path scope and cannot be applied inside the derived sandbox.

#### Example 4 — rejected model command

Model output:

```text
Run rm -rf ...
```

The backend rejects or ignores it because model commands are not executable authority. Only structured repair artifacts supported by the selected repair mode are accepted.

---

## 21. Artifact Contract

Minimum immutable core artifacts:

```text
stage_checkpoint_manifest.json
stage_attempt.json
failure_evidence.json
failure_classification.json
retrieval_pack.json
diagnosis.json
repair_candidate.json
reviewer_critique.json
human_decision.json
backend_policy_validation.json
repair_execution_result.json
repair_diff.patch
validation_report.json
rollback_report.json
checkpoint_promotion_report.json
```

Mode-specific candidate artifacts:

```text
repair_candidate.md          # optional human-readable rendering
repair_candidate.diff        # required for actionable generative diff modes
pom_change_plan.json         # optional explanatory plan
config_change_plan.json      # optional explanatory plan
```

Rules:

- Every artifact has a schema version and content checksum.
- Every derived artifact identifies its exact inputs and checksums.
- New revisions never overwrite old revisions.
- Gate explanations read gate-bound artifact references, not stale previews.
- No LLM artifact overwrites deterministic evidence.
- Backend projections identify the current revision.
- Instructions found inside evidence, source, logs, diffs, or retrieved text are treated as untrusted data.
- Mode-specific candidate artifacts are created only when relevant. `repair_candidate.diff` is mandatory for an actionable generative diff mode. Plan artifacts never substitute for the exact reviewed diff.
- `repair_candidate.diff` is the proposed immutable model-authored diff. `repair_diff.patch` is the backend-recorded actual sandbox diff after apply. Their relationship and checksums must be persisted and compared.

---

## 22. State Machines

### 22.1 Checkpoint

```text
candidate
-> validated
-> accepted
-> superseded

candidate|validated
-> invalid
```

### 22.2 Stage attempt

```text
queued
-> running
-> succeeded

queued|running
-> failed

queued
-> abandoned
```

### 22.3 Generic failure recovery

```text
failure_evidence_persisted
-> failure_classified
-> retrieval_pack_created
-> repair_mode_selected
-> diagnosis_generated
-> repair_candidate_generated
-> repair_reviewed
-> backend_policy_validated
-> repair_approved
-> repair_execution_queued
-> repair_running
-> repair_validated
-> checkpoint_promoted
```

Alternative transitions:

```text
failure_classified -> manual_review_required
repair_mode_selected -> no_safe_mode
repair_candidate_generated -> repair_revision_requested
repair_reviewed -> repair_rejected
backend_policy_validated -> policy_rejected
repair_running -> repair_failed -> repair_rolled_back
repair_validated -> validation_failed
```

### 22.4 Recovery requests

```text
retry_requested -> retry_validated -> retry_queued
resume_requested -> resume_validated -> resume_queued
fork_requested -> fork_reviewed -> fork_validated -> fork_queued
```

State transitions must be backend-owned, persisted, idempotent, and evented.

---

## 23. Cockpit Requirements

### 23.1 Checkpoint panel

Show:

- checkpoint ID;
- stage;
- status;
- profile;
- input checkpoint;
- producing attempt;
- checksum;
- validation result;
- accepted or superseded state;
- safe actions.

Actions:

- use as input;
- resume from here;
- fork from here;
- view report;
- view validation proof.

No action contains or requests a path.

### 23.2 Attempt history

Show:

- attempt ID;
- stage;
- creation reason;
- input checkpoint;
- parent attempt;
- status;
- failure evidence;
- failure class and signature;
- retrieval policy and pack;
- repair mode and safety envelope;
- candidate revision;
- independent review;
- human decision;
- validation result;
- output checkpoint;
- event timeline.

### 23.3 Failed-stage panel

Default presentation:

```text
Stage failed.
Failure: <signature ID or unclassified>
Class: <failure class>
Input: <accepted checkpoint>
Recommended: <policy-selected governed options>
```

Possible actions:

1. Review proposed repair and retry.
2. Retry unchanged.
3. Fork with a reviewed compatibility repair mode.
4. Resume later.
5. Restart from Stage 1.

Restart must be secondary when a valid checkpoint exists.

### 23.4 Repair review panel

Show:

- normalized diagnostics;
- evidence summary;
- deterministic classification;
- retrieved knowledge summary;
- selected repair mode and safety envelope;
- diagnosis;
- candidate revision;
- redacted dry-run diff, recipe plan, or structured change plan;
- reviewer identity and decision;
- generic and mode-specific review results;
- backend policy status;
- validation plan;
- remaining risks;
- approval checksum.

### 23.5 Security UX

The cockpit must never display:

- raw sandbox paths;
- absolute filesystem paths;
- raw command strings;
- argv;
- environment values;
- secrets;
- unredacted logs.

---

## 24. Event Requirements

Minimum new events:

```text
stage_checkpoint_candidate_created
stage_checkpoint_validated
stage_checkpoint_accepted
stage_checkpoint_invalid
stage_checkpoint_superseded

stage_attempt_created
stage_attempt_started
stage_attempt_succeeded
stage_attempt_failed
stage_attempt_abandoned

failure_evidence_created
failure_classified
retrieval_pack_created
repair_mode_selected
diagnosis_created
repair_candidate_created
repair_candidate_revised
repair_candidate_reviewed
backend_policy_validated
backend_policy_rejected
repair_approval_recorded
repair_execution_started
repair_execution_validated
repair_execution_failed
repair_rollback_completed
checkpoint_promotion_completed

retry_requested
resume_requested
fork_requested
```

Public event payloads use IDs, checksums, statuses, repair-mode identifiers, policy identifiers, deterministic strategy identifiers when applicable, and sanitized summaries only.

---

## 25. First Validation Fixture

This fixture validates the generic engine. It must not introduce Jackson-specific branches into `FailureRecoveryEngine`, retrieval orchestration, review orchestration, execution orchestration, or checkpoint promotion.

### 25.1 Preconditions

- Stage 4 has been implemented on a Foundation-0-compliant branch created from `stable`.
- Stage 3 has produced an accepted checkpoint.
- The Stage 4 profile is bound to Spring Boot 4 and Java 21.
- The sample application contains an incomplete Jackson migration.

### 25.2 Failure

Stage 4 compile emits a diagnostic equivalent to:

```text
cannot find symbol
symbol: class JsonNode
```

### 25.3 Expected governed path

The backend:

1. Persists the failed Stage 4 attempt.
2. Collects evidence from the attempt, checkpoint, source imports, POM summary, dependency tree, profile, transformation report, and compiler diagnostics.
3. Matches registered signature `JACKSON_JSONNODE_UNRESOLVED`.
4. Selects the Jackson knowledge-retrieval policy for the exact migration profile.
5. Selects the allowlisted deterministic `OPENREWRITE_RECIPE` repair mode.
6. Requests a diagnosis and repair candidate from the proposer model.
7. Requests review of the exact candidate revision from an independent model.
8. Applies generic backend policy checks plus the Jackson annotation exception add-on.
9. Records human approval of the exact reviewed revision.
10. Executes the backend-resolved recipe in the derived sandbox.
11. Persists the actual diff.
12. Runs compile and focused tests.
13. Promotes the successful output to an accepted Stage 4 checkpoint.

### 25.4 Candidate constraints

The candidate must not:

- perform blind string replacement;
- replace Jackson annotation packages indiscriminately;
- add arbitrary unmanaged dependency versions;
- supply a command line;
- target legacy source;
- bypass the registered repair mode or safety envelope.

### 25.5 Expected result

- The failed attempt remains visible.
- The successful child attempt is linked to the same accepted Stage 3 input checkpoint.
- Evidence, classification, retrieval, strategy, candidate, review, approval, execution, validation, and promotion artifacts are checksum-bound.
- Compile and required focused tests pass.
- A validated Stage 4 checkpoint is accepted.
- The cockpit shows the complete lineage.

---

## 26. MVP Scope

DEMO3 MVP is a generic checkpointed retry and repair framework proven through one seeded failure fixture.

### 26.1 MVP-A: Stage 4 and checkpoint retry

Included:

1. Stage 4 foundation.
2. ID-only recovery APIs.
3. `StageCheckpoint`.
4. `StageAttempt`.
5. Stage 4 retry from an accepted Stage 3 checkpoint.
6. Immutable failure evidence.
7. Attempt and checkpoint cockpit lineage.

Exit result:

```text
accepted Stage 3 checkpoint
-> failed Stage 4 attempt
-> retry without rerunning Stages 1-3
```

### 26.2 MVP-B: Generic governed recovery engine

Included:

1. `FailureRecoveryEngine`.
2. `EvidenceCollector` and versioned `EvidenceSchema`.
3. `FailureClassifier` and `FailureSignature` registry.
4. `RetrievalPackBuilder` and `KnowledgeRetrievalPolicy`.
5. `RepairStrategyRegistry` for deterministic and generative repair modes.
6. `RepairCandidateGenerator`.
7. `IndependentReviewer`.
8. `BackendPolicyValidator`.
9. `HumanApprovalGate`.
10. `SandboxRepairExecutor`.
11. `ValidationPolicy`.
12. `CheckpointPromoter`.
13. Generic cockpit recovery presentation.
14. Jackson fixture as the first end-to-end proof.

End-to-end proof:

```text
accepted Stage 3 checkpoint
-> failed Stage 4 Jackson fixture
-> immutable evidence
-> registered signature
-> targeted retrieval policy
-> registered repair mode and safety envelope
-> LLM-authored diagnosis and candidate
   -> deterministic recipe plan or bounded diff
-> independent review
-> backend policy validation
-> human approval
-> sandbox repair
-> compile/focused-test proof
-> accepted Stage 4 checkpoint
```

---

## 27. Implementation Phases

### Phase 0: Foundry-only foundation and Copilot quarantine

- Disable or quarantine Copilot runtime paths across Control Tower, orchestrator, repair, report, TUI, public API, and frontend surfaces.
- Add the Azure AI Foundry adapter/config contract as the only model invocation boundary.
- Remove provider names, provider-kind fields, environment references, deployment references, provider credentials, and fallback-provider details from public DTOs and frontend contracts.
- Clean UI, report, TUI, and current docs terminology so current product surfaces say Azure AI Foundry or provider-neutral AI, not Copilot or Azure OpenAI internals.
- Enforce redacted, bounded, content-checksummed, policy-versioned context packs bound to invocation records.
- Add compatibility mapping so legacy Copilot and Azure OpenAI names remain readable only through internal/historical compatibility boundaries.

Exit criterion: DEMO3 can begin only after Copilot is unreachable from product runtime paths, Foundry is the only model boundary, public contracts leak no provider internals, deterministic assistance is explicitly non-model, and context packs are content-bound.

### Phase 1: Stage 4 reconciliation

- Review Stage 4 commits from the other branch.
- Port the minimum coherent Stage 4 foundation.
- Preserve F15 gates and read-only analysis.
- Verify Stage 3-to-Stage 4 binding.
- Add focused four-stage progression tests.

Exit criterion: governed Stage 4 can run from backend-resolved accepted Stage 3 evidence.

### Phase 2: API hardening

- Add canonical ID-only checkpoint and recovery requests.
- Remove path and argv from DEMO3 frontend calls.
- Remove sensitive fields from public responses.
- Add strict rejection tests.

Exit criterion: no DEMO3 client contract can influence execution location or command construction.

### Phase 3: checkpoint and attempt foundation

- Add domain models.
- Add append-only migrations.
- Add repositories and UoW wiring.
- Add checkpoint validation service.
- Add attempt lifecycle and events.
- Promote successful stage output through candidate, validation, and acceptance.

Exit criterion: Stage 3 produces a reusable accepted checkpoint and every Stage 4 execution has a durable attempt.

### Phase 4: retry

- Add retry action and validation.
- Create a new attempt from the failed attempt's input checkpoint.
- Preserve failed history.
- Add idempotency and concurrency tests.

Exit criterion: failed Stage 4 can rerun without executing Stages 1 through 3.

### Phase 5: generic evidence and classification

- Version the generic evidence schema.
- Expand bounded evidence collection.
- Normalize compiler, test, runtime, dependency, and transformation evidence.
- Add `FailureSignatureRegistry`.
- Register the Jackson signature first.
- Add negative, ambiguity, and unknown-failure tests.

Exit criterion: classification is deterministic and adding a signature does not change core orchestration.

### Phase 6: targeted retrieval and repair-mode registry

- Add `KnowledgeRetrievalPolicy`.
- Persist retrieval packs.
- Add `RepairStrategyRegistry`.
- Bind retrieval and repair-mode selection to signature and profile.
- Add deterministic OpenRewrite and generative bounded-patch entries.
- Add Jackson retrieval and OpenRewrite entries first without making recipe execution the only repair path.

Exit criterion: retrieval and repair-mode selection are registry-driven and checksum-bound, and at least one generative mode can accept an LLM-authored candidate artifact.

### Phase 7: generation and revision

- Add strict diagnosis and candidate schemas.
- Generate against exact evidence, retrieval, selected repair mode, and safety envelope.
- Support exact bounded source, POM, configuration, and test candidate diffs.
- Add human-feedback revision flow.
- Fail closed on invalid or authority-escalating responses.

Exit criterion: model output remains advisory, exact, immutable, and strategy-bounded.

### Phase 8: reviewer governance

- Persist author and reviewer model identities.
- Enforce independence.
- Add generic review checklist and mode-specific or deterministic-implementation add-ons.
- Expand checksum and lineage bindings.
- Add stale, missing-evidence, same-model, and unavailable-review tests.

Exit criterion: only an independently accepted exact revision can reach human approval.

### Phase 9: policy, execution, and checkpoint promotion

- Validate registry, lineage, checksums, paths, execution, and validation policy.
- Map deterministic modes to backend-owned mechanisms and generative modes to generic validated sandbox apply.
- Apply in sandbox.
- Persist actual diff.
- Run configured validation.
- Roll back on failure.
- Create accepted checkpoint on success.

Exit criterion: proof, not model opinion, determines the outcome.

### Phase 10: cockpit

- Add checkpoint panel.
- Add attempt timeline.
- Add generic classification, retrieval, strategy, review, approval, and proof views.
- Add recovery actions.
- Add security and accessibility tests.

Exit criterion: an operator can understand and complete the full recovery flow without paths or commands.

### Phase 11: later analysis and planning intelligence

- Add LLM analysis and planning artifacts.
- Add independent review.
- Add user revision loops.
- Reuse `ArtifactRevision` and gate services.

This phase is outside the core DEMO3 MVP unless earlier phases finish without weakening acceptance criteria.

---

## 28. Acceptance Criteria

### 28.0 Foundry-only foundation

- Azure AI Foundry adapter is the only model invocation boundary for DEMO3.
- No DEMO3 runtime path invokes GitHub Copilot CLI, SDK, report generation, analysis enrichment, planning assist, repair generation, review, TUI probing, or fallback.
- No Control Tower public API returns `copilot`, `azure_openai`, `provider_kind`, provider environment references, deployment references, provider credentials, or fallback-provider details.
- No frontend bundle displays Copilot or Azure OpenAI provider internals.
- Frontend never calls Azure AI Foundry directly and never receives provider configuration.
- Application services do not directly read model provider environment variables outside the backend-owned Foundry adapter/config contract.
- Foundry failures fail closed for model-required operations.
- Deterministic non-model assistance is explicitly labeled non-model and cannot satisfy proposer, reviewer, repair-candidate, or repair-review requirements.
- Context packs are redacted, bounded, content-checksummed, policy-versioned, source-traceable, and bound to model invocation records.
- Historical Copilot and Azure OpenAI names remain readable only through internal compatibility mappings and cannot activate current product runtime behavior.

### 28.1 Stage 4

- Stage 4 exists on a Foundation-0-compliant implementation branch created from `stable`.
- Stage schemas, job projections, persistence constraints, and UI support Stage 4.
- Stage 4 consumes an accepted Stage 3 checkpoint.
- No direct Stage 4 jump is possible.
- Focused Stage 4 progression tests pass.

### 28.2 Security

- Frontend cannot submit sandbox paths, commands, argv, env, or patch targets.
- Recovery responses do not expose them.
- Unknown fields are rejected.
- Backend resolves all execution details.
- Azure AI Foundry is the only supported DEMO3 model provider.
- Every model call passes through the backend Azure AI Foundry adapter.
- Frontend and browser code never call Azure AI Foundry or receive provider credentials.
- Backend policy selects, bounds, redacts, and audits every controlled context pack.
- Secrets, raw environment variables, unrestricted repository uploads, and unredacted terminal logs are not model inputs.
- GitHub Copilot is not a product runtime, fallback, client dependency, or part of the client data path.
- Legacy source remains unchanged.
- Symlink and traversal escapes are rejected.
- Instructions inside evidence, source, logs, or retrieved text cannot escalate authority.

### 28.3 Checkpoints

- Successful Stage 3 produces a candidate, validated, accepted checkpoint.
- Checkpoint checksum covers its artifact manifest and validation binding.
- Invalid, superseded, stale, incompatible, or foreign-job checkpoints are rejected.
- Checkpoint storage location is never a public input.
- Promotion follows `CheckpointPromotionPolicy`.

### 28.4 Attempts

- Every Stage 4 execution creates a new attempt.
- Failed attempts remain visible.
- Retry creates a child attempt from the same input checkpoint.
- Repair retry links strategy, candidate, review, approval, and parent attempt.
- Successful attempt links exactly one output checkpoint.

### 28.5 Failure evidence

- Failure evidence references the exact attempt and checkpoint.
- Evidence follows a versioned `EvidenceSchema`.
- Evidence includes the configured diagnostic, source, dependency, profile, transformation, build, test, runtime, and log data required for the failure family.
- Evidence is immutable, bounded, redacted, and checksum-bound.

### 28.6 Generic classification

- Classification is deterministic and model-independent.
- `FailureClassifier` evaluates versioned `FailureSignature` entries.
- Unknown or ambiguous failures remain safely non-actionable.
- New failure signatures can be registered without changing core recovery orchestration.
- The first fixture maps the known `JsonNode` failure to `JACKSON_JSONNODE_UNRESOLVED`.
- The Jackson annotation exception is preserved.

### 28.7 Retrieval

- Retrieval policy is selected by signature and migration profile.
- Retrieval uses versioned approved sources.
- Entries have provenance and checksums.
- Pack binds to evidence and classification.
- Missing required retrieval prevents trusted repair.
- Adding a retrieval policy does not require a new core-engine branch.

### 28.8 Repair modes and safety envelopes

- `RepairStrategyRegistry` selects an allowed repair mode and safety envelope, not only a fixed backend-known repair.
- Deterministic modes such as `OPENREWRITE_RECIPE` and generative modes such as `LLM_AUTHORED_PATCH` are supported by the same recovery state machine.
- Mode compatibility is checked against signature, profile, candidate type, review, execution, and validation policy.
- Unknown or disabled modes fail closed.
- The Jackson/OpenRewrite mapping is a registry entry, not core orchestration logic.
- Adding a repair mode does not require changing the generic recovery state machine.

### 28.9 Model outputs

- Diagnosis and candidate use strict schemas.
- Invalid output fails closed.
- Candidate binds to evidence, classification, retrieval, checkpoint, attempt, repair mode, safety-envelope version, author identity, and content checksum.
- A repair candidate can be an LLM-authored bounded diff, not only a deterministic recipe.
- An actionable generative candidate contains the exact diff bytes; an explanatory plan alone cannot execute.
- LLMs can explain, author exact bounded changes, compare, recommend manual review, and revise artifacts.
- No model output contains execution, approval, classification, path, command, or success-proof authority.
- Raw commands from model output are rejected or ignored.

### 28.10 Review

- Reviewer identity differs from author identity.
- Same-model path fails closed.
- Review binds to exact candidate, evidence, classification, retrieval, strategy, checkpoint, and attempt.
- Stale or missing bindings are rejected.
- Reviewer checklist supports generic base checks plus mode-specific or deterministic-implementation checks.
- Reviewer acceptance does not approve execution.

### 28.11 Approval and execution

- Human approval is required.
- Approval binds to the exact reviewed candidate checksum.
- `BackendPolicyValidator` passes before execution.
- Backend rejects stale-checksum patches.
- Backend rejects patches outside allowed path scope.
- Backend rejects unreviewed patches.
- Backend rejects unapproved patches.
- Backend selects the execution adapter, recipe version when applicable, command, environment, and sandbox.
- Backend can apply a reviewed and approved LLM-authored patch in the sandbox.
- Backend applies the exact reviewed and approved candidate bytes and records the resulting actual diff separately.
- Actual diff and touched paths are persisted.
- Configured validation determines the result.
- Validation failure rolls back when required and does not promote a checkpoint.
- Successful repair creates an accepted Stage 4 checkpoint.

### 28.12 Generic extensibility

- Core recovery orchestration contains no Jackson-only branch.
- A future signature can be added through registry and policy entries.
- Retrieval policy is selected by signature and profile.
- Repair mode and safety envelope are selected by registry.
- Reviewer policy combines generic checks with mode-specific or deterministic-implementation add-ons.
- Execution and validation are policy-bound.
- The same artifact, approval, execution, proof, and checkpoint-promotion flow applies across failure classes.
- A non-Jackson, non-recipe fixture can produce and apply a candidate patch without adding a core orchestration branch.

### 28.13 Cockpit

- Cockpit shows checkpoint and attempt lineage.
- Cockpit shows failed and successful attempts.
- Cockpit shows failure class, signature, retrieval policy, strategy, candidate, review, approval, and validation proof.
- Cockpit presents repair, retry, fork, resume, and restart choices.
- Restart is secondary when a valid checkpoint exists.
- Cockpit hides paths, argv, env, commands, secrets, and unredacted logs.

---

## 29. Test Strategy

### 29.1 Domain tests

- checkpoint state validation;
- attempt state validation;
- lineage rules;
- compatibility checks;
- immutable terminal records;
- policy-version binding;
- checkpoint-promotion rules.

### 29.2 Persistence tests

- append-only migration behavior;
- repository round trips;
- indexes and uniqueness;
- restart durability;
- concurrent retry idempotency;
- registry and policy version persistence.

### 29.3 Security tests

- forbidden request fields;
- strict extra-field rejection;
- no sensitive public response fields;
- path traversal and symlink escape;
- prompt injection inside evidence and retrieved text;
- no client reviewer-decision injection;
- no model authority escalation;
- raw model command rejection;
- stale-checksum patch rejection;
- unreviewed and unapproved patch rejection;
- no direct legacy-source mutation.

### 29.4 Classifier tests

- signature registry matching;
- profile constraints;
- confidence and matched-evidence persistence;
- ambiguous matches;
- unknown failure;
- first Jackson signature fixture;
- Jackson annotation exception;
- registration of a non-Jackson fixture without orchestration changes.

### 29.5 Retrieval and repair-mode tests

- policy selected by signature and profile;
- wrong-profile policy rejected;
- missing required retrieval fails closed;
- provenance and checksum validation;
- deterministic and generative repair modes selected from registry;
- unknown and disabled mode rejection;
- safety-envelope binding and limit enforcement;
- generic mode selection with Jackson fixture first.

### 29.6 Model and reviewer tests

- Azure AI Foundry adapter success, refusal, timeout, malformed response, redaction, and audit-binding tests;
- no-live-model tests using a fake Foundry adapter;
- valid structured output;
- malformed JSON;
- schema mismatch;
- refusal or empty output;
- model timeout;
- same model;
- stale candidate;
- stale evidence;
- wrong checkpoint or attempt;
- missing retrieval;
- wrong strategy binding;
- exact generative diff persistence;
- model-command rejection;
- human-feedback revision;
- generic review checks;
- mode-specific or deterministic-implementation review add-on.

### 29.6.1 Foundry-only and prohibition tests

- Copilot reachability and quarantine tests for Control Tower, orchestrator, repair, report, TUI, public API, and frontend entry points;
- recursive public DTO leakage tests forbidding `copilot`, `azure_openai`, `provider_kind`, provider env refs, provider credentials, deployment refs, and fallback-provider details;
- frontend text and contract tests proving no Copilot or Azure OpenAI provider internals are rendered or typed for current DEMO3 surfaces;
- context-pack checksum and policy-version tests using canonical redacted content;
- search-based regression tests for forbidden public/runtime terms with an allowlist for historical compatibility, tests, and audits;
- deterministic non-model assistance tests proving it is labeled non-model and cannot satisfy model-required proposer/reviewer gates;
- Foundry failure tests proving model-required operations fail closed and do not use Copilot, Azure OpenAI fallback, or deterministic success-shaped output.

### 29.7 Execution tests

- deterministic implementation mapping;
- reviewed and approved LLM-authored patch apply;
- backend-owned command construction;
- sandbox-only apply;
- touched-path validation;
- stale baseline checksum rejection;
- file-count and diff-size limit enforcement;
- dependency and configuration policy validation;
- compile success;
- focused-test success;
- configured non-compile validation;
- validation failure and rollback;
- ledger persistence;
- checkpoint promotion.

### 29.8 First end-to-end fixture

Use a deterministic fixture that:

1. Has an accepted Stage 3 checkpoint.
2. Fails Stage 4 on `JsonNode`.
3. Produces the expected registered signature.
4. Selects the expected retrieval policy.
5. Selects the expected registered OpenRewrite strategy.
6. Produces a deterministic fake proposer result that recommends and explains the exact registered recipe and parameters.
7. Produces an independent fake reviewer result.
8. Records human approval.
9. Applies an allowed fixture repair.
10. Passes compile and focused-test fixture validation.
11. Creates a Stage 4 checkpoint.
12. Exposes safe cockpit projections.

The test proves the generic recovery engine through the Jackson fixture. It must not test a separate Jackson-only workflow.

A second focused fixture must prove flexibility with a non-Jackson, non-recipe failure. It must produce an LLM-authored bounded patch, pass independent review and backend validators, require human approval, apply only in the sandbox, and promote a checkpoint only after configured validation succeeds. The test must assert that the reviewed and approved `repair_candidate.diff` checksum equals the exact proposed bytes passed to the executor, that the resulting sandbox diff corresponds to those bytes, and that no backend deterministic rule encodes the fixture-specific fix. Adding this fixture must not require a new core orchestration branch.

Tests should be focused by phase. The full suite is not required for each implementation job.

---

## 30. Observability and Audit

DEMO3 must make these correlations queryable:

```text
job
-> checkpoint
-> attempt
-> command
-> failure evidence
-> classification and signature
-> retrieval policy and pack
-> repair mode and safety envelope
-> diagnosis
-> repair candidate revision
-> reviewer critique
-> backend policy result
-> human decision
-> sandbox action
-> validation
-> output checkpoint
```

Model audit should record:

- role;
- backend-resolved model identity;
- schema;
- prompt and context checksum;
- output artifact checksum;
- token usage where available;
- status and failure reason;
- correlation and causation IDs.

Policy audit should record:

- signature-registry version;
- retrieval-policy version;
- repair-mode and safety-envelope version;
- deterministic strategy version when applicable;
- review-policy version;
- execution-policy version;
- validation-policy version;
- checkpoint-promotion-policy version.

Audit records must not store secrets or unredacted paths.

---

## 31. Success Metrics

### 31.1 Product

- Operator can recover Stage 4 without restarting Stages 1 through 3.
- Operator can explain why the stage failed.
- Operator can see exact checkpoint and attempt lineage.
- Operator can review evidence, classification, retrieval, strategy, candidate, and reviewer verdict.
- Operator retains final approval.
- The product framing and workflow remain valid for non-Jackson failure classes.

### 31.2 Technical

- 100% of attempts have an input checkpoint.
- 100% of accepted checkpoints are checksum-bound and validated.
- 100% of actionable classifications are deterministic and registry-backed.
- 100% of actionable retrieval packs bind to a signature and profile.
- 100% of actionable repair candidates bind to an allowlisted repair mode and safety envelope.
- 100% of actionable model outputs pass schema validation.
- 100% of actionable repair candidates have independent review.
- 0 same-model accepted reviews.
- 0 repair executions without human approval.
- 0 DEMO3 public requests accepting execution paths or commands.
- Known Jackson fixture is classified correctly.
- Successful repair produces a new checkpoint.
- A reviewed and approved LLM-authored bounded patch can be applied without a pre-authored deterministic fix rule.

### 31.3 Quality

- Reduced `UNKNOWN_MIGRATION_FAILURE` for registered signatures.
- No blind Jackson annotation replacement.
- No loss of failed-attempt history.
- No unnecessary Stage 1 restart in the demo recovery path.
- No Jackson-specific branch in the generic recovery engine.
- A non-Jackson signature can be registered without orchestration changes.
- A non-Jackson, non-recipe candidate can be generated and validated without backend-authored fix logic.

---

## 32. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Stage 4 code diverged on another branch | Unsafe or incomplete port | Reconcile behavior commit-by-commit with focused tests |
| Existing path-bearing API reused | Frontend influences execution | Canonical ID-only APIs and strict schemas |
| Command result treated as checkpoint | Stale or ambiguous input | First-class accepted `StageCheckpoint` |
| Jackson fixture becomes architecture | New failures require core changes | Generic engine plus versioned signature, retrieval, strategy, review, execution, and validation policies |
| Repair registry becomes a static fix catalog | Backend must know every future fix | Registry defines modes and envelopes; LLM authors exact bounded candidates |
| Registries become unversioned configuration | Reviewed candidates change meaning | Persist selected entry IDs, versions, and checksums |
| Too many lifecycle tables | Complexity and brittle state | Tables for aggregates; artifacts for large immutable content |
| Model JSON accepted as trusted | Unsafe repair | Schema, review, backend policy, human approval, validation |
| Provider ambiguity or fallback path | Unreviewed client architecture and inconsistent data controls | Azure AI Foundry-only backend adapter; no direct OpenAI, Copilot runtime, or multi-provider route |
| Browser receives provider credentials or calls Foundry | Secret exposure and policy bypass | Backend-only model gateway, secret-redaction tests, and strict public response contracts |
| Excess repository context reaches a model | Source, log, or secret disclosure | Controlled context-pack policy with allowlisting, bounds, redaction, checksums, and source traceability |
| Legacy `copilot_*` names appear client-facing | Client assumes a Copilot license or runtime dependency | Treat as internal legacy naming, hide from DEMO3 product contracts, and track a later naming/dependency refactor |
| Same model authors and reviews | Weak review | Persist identity and fail closed |
| Retrieval provides irrelevant advice | Poor repair quality | Signature/profile policy, approved corpus, retrieval quality gate |
| Strategy is incompatible with profile | Unsafe or ineffective repair | Registry compatibility checks and backend validation |
| Retry races | Duplicate attempts or commands | Atomic validation and idempotency |
| Repair touches unexpected files | Source or security risk | Touched-path policy, sandbox containment, rollback |
| LLM-authored patch is plausible but wrong | Failed or harmful repair | Independent review, generic validators, human approval, sandbox apply, deterministic validation |
| Scope expands into all failure classes | Delayed first proof | Build generic extension points, prove with one seeded fixture |

---

## 33. File-Level Delivery Map

### 33.1 Stage and orchestration

```text
migration_factory/control_tower/application/v2_job_service.py
migration_factory/control_tower/application/v2_stage_progression.py
migration_factory/control_tower/application/v2_orchestrator_runner.py
migration_factory/control_tower/adapters/fastapi/app.py
migration_factory/control_tower/schemas/
```

### 33.2 Domain and persistence

```text
migration_factory/control_tower/domain/
migration_factory/control_tower/infrastructure/sqlite/migrations/
migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py
migration_factory/control_tower/infrastructure/sqlite/*repository.py
```

### 33.3 Evidence, classification, retrieval, and repair

```text
migration_factory/agents/failure_classifier/agent.py
migration_factory/repair_loop/evidence_collector.py
migration_factory/repair_loop/rule_registry.py
migration_factory/repair_loop/patch_gate.py
migration_factory/repair_loop/patch_apply.py
migration_factory/repair_loop/validation_runner.py
migration_factory/control_tower/application/v2_failure_diagnosis.py
migration_factory/control_tower/application/v2_model_schemas.py
migration_factory/control_tower/application/v2_repair_flow.py
migration_factory/control_tower/application/v2_repair_gate_service.py
new registry, policy, generic-validator, retrieval-pack, and checkpoint-promotion application modules as needed
```

New modules should wrap or adapt existing systems rather than duplicate:

- stage progression;
- orchestrator runner;
- assistant router and service;
- repair flow;
- plan revision;
- artifact storage and resolution;
- event streaming;
- repositories and UoW;
- validation, rollback, and ledger.

### 33.4 Review and model routing

```text
migration_factory/control_tower/application/v2_model_role_router.py
migration_factory/control_tower/application/v2_reviewer_service.py
migration_factory/control_tower/infrastructure/sqlite/v2_reviewer_repository.py
```

### 33.5 Cockpit

```text
web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx
web/control-tower/lib/contracts.ts
web/control-tower/lib/controlTowerApi.ts
web/control-tower/tests/
```

### 33.6 Focused test families

```text
tests/control_tower/test_v2_stage_progression.py
tests/control_tower/test_v2_orchestrator_runner.py
tests/control_tower/test_v2_stage_output_resolver.py
tests/control_tower/test_v2_artifact_revisions.py
tests/control_tower/test_v2_failure_diagnosis.py
tests/control_tower/test_v2_repair_flow.py
tests/control_tower/test_v2_repair_review_gate.py
tests/control_tower/test_v2_model_role_router.py
new checkpoint, attempt, recovery-engine, registry, retrieval, generic-validator, generative-patch, Jackson-fixture, and reviewer-independence tests
```

---

## 34. Definition of Done

DEMO3 is done when a reviewer can verify both the generic architecture and the first fixture.

Generic engine:

```text
Azure AI Foundry is the only model-provider runtime.
The backend Azure AI Foundry adapter owns every model call and provider secret.
Controlled context packs are bounded, redacted, checksum-bound, and auditable.
No frontend, browser, or GitHub Copilot runtime path exists.
StageCheckpoint and StageAttempt are durable.
FailureRecoveryEngine has no Jackson-only orchestration branch.
EvidenceCollector persists immutable evidence.
FailureClassifier uses registered deterministic signatures.
RetrievalPackBuilder selects policy by signature and profile.
RepairStrategyRegistry selects allowed repair modes and safety envelopes.
RepairCandidateGenerator lets the proposer LLM recommend exact allowed deterministic recipe parameters or author immutable bounded source, POM, configuration, and test diffs.
IndependentReviewer reviews exact revisions with a distinct model identity.
BackendPolicyValidator judges lineage, applicability, review, approval, containment, and safety without needing to know the exact fix in advance.
HumanApprovalGate binds decisions to exact reviewed checksums.
SandboxRepairExecutor owns paths, commands, execution, and rollback.
ValidationPolicy provides proof.
CheckpointPromoter creates reusable output only after proof.
```

First validation fixture:

```text
Stage 3 accepted checkpoint exists.
Stage 4 attempt fails on the known Jackson issue.
Failure evidence is complete and immutable.
Classifier returns JACKSON_JSONNODE_UNRESOLVED.
Retrieval policy selects the approved Jackson migration topics.
Strategy registry selects the approved OpenRewrite strategy.
Candidate is schema-valid and checksum-bound.
Independent reviewer accepts the exact candidate.
Human approves the exact reviewed revision.
Backend applies the repair in a derived sandbox.
Compile and focused tests pass.
Failed attempt remains visible.
Successful attempt produces an accepted Stage 4 checkpoint.
Cockpit shows the lineage and leaks no execution details.
```

Extensibility:

```text
A non-Jackson signature can be registered without changing core orchestration.
Its retrieval policy is selected by signature and profile.
Its repair mode and safety envelope are selected by registry.
The proposer LLM can author a bounded non-recipe candidate patch.
Its reviewer uses generic checks plus mode-specific or deterministic-implementation add-ons.
Generic backend validators reject stale, unsafe, out-of-scope, unreviewed, or unapproved candidates.
The approved candidate can be applied only in a derived sandbox.
Its configured validation controls checkpoint promotion.
```

No criterion may be replaced by an LLM assertion.

---

## 35. Final Product Principle

DEMO3 must never become:

```text
LLM says fix
-> system applies fix
```

It must implement:

```text
failed attempt
-> immutable evidence
-> deterministic registered signature
-> targeted policy-driven retrieval
-> allowlisted repair mode and safety envelope
-> grounded LLM-authored diagnosis and exact candidate
   -> reviewed recommendation of an allowed deterministic recipe and parameters OR
   -> bounded source/POM/config/test diff OR
   -> manual-review recommendation
-> independent critique
-> generic backend validators
-> human approval
-> sandbox execution
-> configured validation proof
-> immutable checkpoint
```

Jackson is the first fixture through this flow. It is not the product architecture.

Backend governance is intentionally stable around generic safety, execution, rollback, and proof. Repair knowledge is intentionally flexible: the LLM may propose an unknown future fix, but it cannot execute, approve, bypass policy, choose the sandbox, or manufacture proof.

DEMO3 must also never force:

```text
later stage fails
-> restart from Stage 1
```

when this is valid:

```text
later stage fails
-> reuse accepted prior-stage checkpoint
-> retry, repair, or fork under governance
```

The generic governed recovery graph is the product delivered by DEMO3.
