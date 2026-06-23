# DEMO3 Architecture

## AI Runtime Boundary

```text
Frontend Cockpit
    ↓ user intent, IDs, checksums, governed actions
Control Tower Backend
    ↓ controlled context pack
Azure AI Foundry Adapter
    ↓
Azure AI Foundry model endpoint
```

Azure AI Foundry is the only supported DEMO3 LLM provider. The backend is the only component allowed to invoke it and owns credentials, deployment selection, request construction, response validation, safe error mapping, and audit. The frontend has no provider SDK/client, endpoint, deployment key, API key, or direct model call.

GitHub Copilot is not a product runtime, assistant engine, fallback provider, client delivery dependency, or part of the data path. Existing `copilot_*` names in code are legacy internal naming and require later refactoring only where they leak into client-facing contracts or UI.

## Core Components

- `FailureRecoveryEngine`: coordinates the existing services and state transitions; proposed location needs verification. It must not replace `v2_orchestrator_runner.py` or `v2_repair_flow.py`.
- `EvidenceCollector`: persists immutable, redacted evidence bound to failed attempt and input checkpoint.
- `FailureClassifier`: evaluates versioned deterministic signatures. Model classification is advisory only.
- `RetrievalPackBuilder`: selects approved migration knowledge by signature and profile, with provenance and checksums.
- `RepairModeRegistry`: selects an allowed mode and safety envelope, not a fixture-specific fix.
- `RepairCandidateGenerator`: asks a Foundry-backed proposer role for strict-schema diagnosis and exact candidate content through the backend adapter.
- `IndependentReviewer`: uses a distinct backend-resolved model identity to critique the exact revision.
- `BackendPolicyValidator`: enforces generic lineage, checksum, path, size, dependency, configuration, review, and approval rules.
- `HumanApprovalGate`: records the human decision against the exact reviewed checksum.
- `SandboxRepairExecutor`: applies exact approved bytes in a backend-derived sandbox and records the actual result.
- `ValidationRunner`: executes backend-configured compile, focused tests, or other deterministic checks.
- `CheckpointPromoter`: creates an accepted output checkpoint only after validation proof.

## Authority

```text
Azure AI Foundry proposer deployment = repair author
Azure AI Foundry reviewer deployment = critic
Human = decision owner
Backend = model gateway / governor / executor / proof recorder
Sandbox + validation = truth
Artifacts/checkpoints = source of truth
```

The LLM may author source, POM, configuration, or test diffs. It may not choose paths, sandboxes, commands, argv, env, approval, stage order, or success. Reviewer acceptance is not execution approval. Human approval does not replace backend validation.

The backend provides each model role with a controlled context pack. The pack contains only policy-selected, bounded, redacted artifacts or snippets and records source references and checksums. Secrets, raw environment variables, unrestricted repository uploads, and unredacted terminal logs are prohibited.

## Normal Flow

```text
Original app
-> Stage 1
-> accepted checkpoint C1
-> Stage 2
-> accepted checkpoint C2
-> Stage 3
-> accepted checkpoint C3
-> Stage 4
-> accepted checkpoint C4
```

Each stage execution is a distinct `StageAttempt`. Each checkpoint binds its input, creating attempt, artifact manifest checksum, validation checksum, profile, and state.

## Failure Flow

```text
Stage 4 fails
-> preserve accepted Stage 3 checkpoint C3
-> create failed attempt A4.1
-> collect evidence
-> classify
-> retrieve knowledge
-> select repair mode/safety envelope
-> backend invokes Azure AI Foundry with a controlled context pack
-> Foundry-backed proposer authors exact candidate
-> independent reviewer critiques it
-> backend performs pre-approval policy validation
-> human approves
-> backend revalidates policy, approval, and stale state
-> backend applies in sandbox
-> validation passes
-> checkpoint C4 promoted
```

A failed or rejected candidate remains an artifact. It cannot mutate accepted checkpoints.

## Generative Non-Jackson Example

```text
Hibernate/Jakarta failure:
package javax.persistence does not exist

LLM-authored patch:
- import javax.persistence.Entity;
+ import jakarta.persistence.Entity;
```

The backend does not need a fixture-specific repair implementation. It validates attempt binding, checkpoint binding, evidence and policy versions, file checksum, allowed path, sandbox containment, distinct review, exact approval, diff limits, compile, and focused tests. The proposed diff and resulting sandbox diff are persisted separately.

## Reuse Boundaries

Reuse current V2 stage progression, orchestrator runner, F15 gates and artifact revisions, repair flow, reviewer repository, model role router, patch gate/apply, validation/rollback, SQLite UoW, events, and cockpit projections. Add one Azure AI Foundry adapter and explicit DEMO3 aggregates where current concepts are insufficient. Do not add a generic multi-provider router or Copilot runtime path.

## Events and Audit

The recovery engine must emit versioned, redacted events for checkpoint creation/acceptance, attempt lifecycle, recovery requests, evidence/classification/retrieval, diagnosis and candidate revisions, review, policy results, approval, execution, rollback, validation, and promotion. Every event and model/policy audit record must preserve job, checkpoint, attempt, correlation, and causation identifiers without exposing paths, commands, secrets, or raw logs.
