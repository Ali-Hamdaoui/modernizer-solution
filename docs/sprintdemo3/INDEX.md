# DEMO3 Sprint Blueprint

## What DEMO3 Is

DEMO3 turns the AI Migration Control Tower from a mostly linear runner into a governed, checkpointed failure-recovery system. A later-stage failure can reuse an accepted prior-stage result, preserve every attempt, gather immutable evidence, and recover through reviewed and approved repair.

Azure AI Foundry is the only supported AI runtime and LLM provider for DEMO3. The Control Tower backend alone calls the Azure AI Foundry model endpoint through a backend adapter. The cockpit never calls a model provider directly or receives provider credentials. GitHub Copilot is not a product runtime, client dependency, or part of migration execution.

## What We Are Building

The delivery has two mandatory increments:

```text
Foundation 0 = Foundry-only cleanup and Copilot quarantine:
FND-01 Copilot quarantine + FND-02 Foundry adapter + FND-03 public DTO cleanup
+ FND-04 terminology cleanup + FND-05 context-pack enforcement
+ FND-06 legacy compatibility mapping.

MVP-A = execution spine:
Stage 4 + API hardening + StageCheckpoint + StageAttempt + retry from checkpoint.

MVP-B = intelligent recovery:
evidence + classifier + retrieval + repair mode registry + LLM-authored candidate
+ reviewer + backend validators + human approval + sandbox execution
+ validation + checkpoint promotion.
```

Foundation 0 must be complete before MVP-A or MVP-B implementation. MVP-A must work before any LLM-authored repair is executable. MVP-B extends the same stage progression, gates, repair flow, artifact storage, validation, rollback, and proof systems; it must not create a second orchestrator.

## Why It Matters

Accepted work must survive later failures. Operators need exact lineage from input checkpoint through failed and successful attempts, and they need flexible repairs without granting a model execution authority.

## Authority Split

- LLM: authors grounded diagnosis and exact bounded repair candidates.
- Reviewer model: critiques the exact immutable candidate revision.
- Human: accepts, rejects, approves, revises, retries, resumes, forks, continues, or stops.
- Backend: builds controlled context packs, invokes Azure AI Foundry, classifies authoritatively, validates lineage and policy, derives paths and commands, executes in a sandbox, rolls back, persists, and records proof.
- Sandbox plus configured validation: determines whether the repair worked.
- Artifacts and accepted checkpoints: source of truth.

## Non-Static Repair Principle

DEMO3 is not Jackson-only and the backend is not a fixed repair catalog. Registries define failure signatures, retrieval policies, allowed repair modes, and safety envelopes. In generative modes, the LLM may author exact source, POM, configuration, or test diffs that the backend did not know in advance. Generic backend validators still enforce checksums, paths, size limits, review, approval, containment, rollback, and proof.

This extensibility applies to failure and repair policies, not provider selection. DEMO3 has one production model-provider path: Azure AI Foundry. Direct OpenAI, Copilot runtime, multi-provider routing, and model fallback are outside scope.

## Feature List and Build Order

1. [Stage 4 Reconciliation](01-stage4-reconciliation/INDEX.md) — MVP-A
2. [API Hardening](02-api-hardening/INDEX.md) — MVP-A
3. [StageCheckpoint](03-stage-checkpoint/INDEX.md) — MVP-A
4. [StageAttempt](04-stage-attempt/INDEX.md) — MVP-A
5. [Retry / Resume / Fork](05-retry-resume-fork/INDEX.md) — MVP-A
6. [Failure Evidence](06-failure-evidence/INDEX.md) — MVP-B
7. [Failure Classifier Registry](07-failure-classifier-registry/INDEX.md) — MVP-B
8. [Retrieval Pack Builder](08-retrieval-pack-builder/INDEX.md) — MVP-B
9. [Repair Mode Registry](09-repair-mode-registry/INDEX.md) — MVP-B
10. [LLM Repair Candidate Generator](10-llm-repair-candidate-generator/INDEX.md) — MVP-B
11. [Independent Reviewer](11-independent-reviewer/INDEX.md) — MVP-B
12. [Backend Policy Validator](12-backend-policy-validator/INDEX.md) — MVP-B
13. [Human Approval Gate](13-human-approval-gate/INDEX.md) — MVP-B
14. [Sandbox Repair Executor](14-sandbox-repair-executor/INDEX.md) — MVP-B
15. [Validation Runner](15-validation-runner/INDEX.md) — MVP-B
16. [Checkpoint Promoter](16-checkpoint-promoter/INDEX.md) — MVP-B
17. [Cockpit Recovery UX](17-cockpit-recovery-ux/INDEX.md) — MVP-B
18. [E2E Fixtures](18-e2e-fixtures/INDEX.md) — MVP-B

Foundation 0 tasks:

- FND-01 Disable/quarantine Copilot runtime paths.
- FND-02 Azure AI Foundry adapter/config contract.
- FND-03 Remove public provider/config leakage.
- FND-04 UI/report/docs terminology cleanup.
- FND-05 Context-pack enforcement.
- FND-06 Legacy compatibility mapping.

See [ROADMAP.md](ROADMAP.md), [ARCHITECTURE.md](ARCHITECTURE.md), [RISKS.md](RISKS.md), and the [global task board](TASKS.md).
