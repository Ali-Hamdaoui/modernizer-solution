# DEMO3 Global Sprint Task Board

All features start with `Status: not started` and `Owner: TBD`. Suggested paths are not implementation facts; `needs verification` marks uncertain placement.

Global provider constraint: Azure AI Foundry is the only DEMO3 AI runtime. Model invocation, configuration, controlled context selection, credential handling, error mapping, and audit are backend responsibilities. No task may introduce direct OpenAI, Copilot runtime, frontend provider calls, multi-provider routing, or provider fallback.

## F01 — Stage 4 Reconciliation

- Status: not started
- Owner: TBD
- MVP: A
- Depends on: none
- Blocks: F03, F04, F05
- Purpose: bring governed Stage 4 into the active branch without losing F15 gates or artifact bindings.
- Likely future modified files: `v2_stage_progression.py`, `v2_orchestrator_runner.py`, `v2_job_service.py`, FastAPI app, schemas, cockpit contracts/UI, focused progression tests.
- Likely future new files: `tests/control_tower/test_v2_stage4_progression.py`, `tests/control_tower/test_v2_stage4_schema.py`.
- Acceptance summary: Stage 4 consumes accepted Stage 3 output and cannot be entered directly.
- Focused test scope: Stage 3→4 gating, schema, output revision persistence, backend-owned launch.
- Main risks: branch divergence; blind reuse of migration `0046`.

## F02 — API Hardening

- Status: not started
- Owner: TBD
- MVP: A
- Depends on: F01
- Blocks: F05, F13, F14, F17
- Purpose: remove public control over execution details.
- Likely future modified files: FastAPI app, `control_tower/schemas/`, `contracts.ts`, `controlTowerApi.ts`, `MigrationCockpit.tsx`.
- Likely future new files: `test_v2_recovery_api_security.py`, `recoveryApiSecurity.test.ts`.
- Acceptance summary: strict ID-only requests and redacted responses reject extra path/command fields.
- Focused test scope: forbidden fields, extra fields, response leakage, provider credential leakage, and absence of frontend model calls.
- Main risks: compatibility endpoints retaining unsafe fields or legacy Copilot-facing product language.

## F03 — StageCheckpoint

- Status: not started
- Owner: TBD
- MVP: A
- Depends on: F01
- Blocks: F04, F05, F16
- Purpose: represent validated stage output as immutable reusable lineage.
- Likely future modified files: domain package, SQLite UoW/migrations, stage progression, gate action, artifact resolver.
- Likely future new files: `v2_stage_checkpoint.py`, checkpoint service/repository/migration, checkpoint tests.
- Acceptance summary: accepted checkpoints bind job, stage, profile, input, attempt, artifact manifest, validation, and timestamps.
- Focused test scope: domain invariants, repository round trip, acceptance and checksum rules.
- Main risks: treating path or mutable worktree as checkpoint.

## F04 — StageAttempt

- Status: not started
- Owner: TBD
- MVP: A
- Depends on: F03
- Blocks: F05, F06
- Purpose: persist every execution, retry, repair, resume, and fork.
- Likely future modified files: domain package, stage progression, orchestrator runner, SQLite UoW.
- Likely future new files: `v2_stage_attempt.py`, attempt service/repository/migration, attempt tests, and DEMO3 event/audit tests.
- Acceptance summary: every execution has immutable input checkpoint, cause, status, and output/proof refs.
- Focused test scope: state transitions, idempotency, failed-attempt preservation.
- Main risks: conflating gate count with execution attempt.

## F05 — Retry / Resume / Fork

- Status: not started
- Owner: TBD
- MVP: A
- Depends on: F02, F03, F04
- Blocks: all MVP-B features
- Purpose: recover from accepted checkpoints without restarting Stage 1.
- Likely future modified files: stage progression, FastAPI app, frontend API/contracts.
- Likely future new files: recovery action service and focused action/retry tests.
- Acceptance summary: retry reuses the same checkpoint; resume continues an interrupted attempt where valid; fork creates a new lineage branch.
- Focused test scope: compatibility, idempotency, invalid checkpoint, concurrent request.
- Main risks: ambiguous semantics and duplicate commands.

## F06 — Failure Evidence

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F04, F05
- Blocks: F07, F08, F10
- Purpose: persist immutable grounded evidence for a failed attempt and establish the thin generic recovery coordinator.
- Likely future modified files: failure diagnosis, evidence pack builder, repair-loop collector, repair flow.
- Likely future new files: failure evidence service/domain/tests plus `v2_failure_recovery_engine.py` and engine tests.
- Acceptance summary: evidence binds attempt, checkpoint, normalized diagnostics, profile, hashes, results, and prior attempts; `FailureRecoveryEngine` coordinates typed transitions by reusing existing services.
- Focused test scope: immutability, redaction, prompt-injection framing, missing inputs.
- Main risks: path leakage and mutable log references.

## F07 — Failure Classifier Registry

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F06
- Blocks: F08, F09
- Purpose: provide deterministic, versioned, broad failure classification.
- Likely future modified files: classifier agent, repair rule registry, failure diagnosis.
- Likely future new files: signature registry, classification domain, registry/classifier tests.
- Acceptance summary: registered signatures produce evidence-backed classes; unknown/ambiguous cases fail safe.
- Focused test scope: Jackson, non-Jackson, annotation exception, ambiguity, versions.
- Main risks: fixture-specific orchestration or authoritative model classification.

## F08 — Retrieval Pack Builder

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F06, F07
- Blocks: F10, F11
- Purpose: build targeted approved knowledge packs by signature and profile.
- Likely future modified files: failure diagnosis, model schemas.
- Likely future new files: retrieval builder/domain/repository/tests.
- Acceptance summary: packs have provenance, policy version, checksums, and evidence/classification bindings.
- Focused test scope: policy selection, wrong profile, missing knowledge, deterministic fake retrieval.
- Main risks: mixing application evidence with migration guidance.

## F09 — Repair Mode Registry

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F08
- Blocks: F10, F12, F14, F15
- Purpose: choose repair mode and safety envelope without defining every repair.
- Likely future modified files: repair-loop registry, repair flow, repair gate service.
- Likely future new files: repair mode registry/domain/tests.
- Acceptance summary: deterministic and generative modes are versioned, compatible, allowlisted, and fail closed.
- Focused test scope: all required modes, disabled/unknown mode, envelope binding.
- Main risks: registry becoming a static repair catalog.

## F10 — LLM Repair Candidate Generator

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F06, F08, F09
- Blocks: F11, F12, F13
- Purpose: invoke the Azure AI Foundry-backed proposer through one backend provider contract using controlled context packs, then persist strict-schema diagnosis and exact bounded candidates.
- Likely future modified files: repair flow, model schemas, role router, repair gate, backend model gateway/configuration.
- Likely future new files: diagnosis artifact domain/tests, candidate generator/domain/tests, Azure AI Foundry adapter contract tests, and controlled context-pack policy tests.
- Acceptance summary: Azure AI Foundry is the only runtime path; separate immutable diagnosis and candidate artifacts bind exact controlled context; candidate bytes reject commands and revisions are immutable.
- Focused test scope: fake Foundry adapter, malformed output, provider error mapping, secret/context redaction, command rejection, revision loop.
- Main risks: provider ambiguity, context leakage, plan-only output treated as executable, or model authority escalation.

## F11 — Independent Reviewer

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F08, F10
- Blocks: F12, F13
- Purpose: critique the exact candidate with a distinct backend-resolved Azure AI Foundry deployment identity.
- Likely future modified files: reviewer service, role router, reviewer repository.
- Likely future new files: review policy and independence tests.
- Acceptance summary: review binds exact controlled context and same Foundry deployment/model identity fails closed.
- Focused test scope: identity equality, stale candidate/context, mode-specific checks.
- Main risks: deployment aliases masking same identity.

## F12 — Backend Policy Validator

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F09, F10, F11
- Blocks: F13, F14
- Purpose: apply generic safety and applicability checks without knowing the exact fix.
- Likely future modified files: patch gate/apply, repair gate, repair flow.
- Likely future new files: backend, patch, dependency, and config validators plus pre-approval and pre-execution tests.
- Acceptance summary: pre-approval policy rejects stale, escaping, oversized, forbidden, or unreviewed candidates; pre-execution revalidation rejects stale or unapproved state.
- Focused test scope: checksum, traversal, symlink, paths, limits, policies, review/approval.
- Main risks: validation gaps between proposed and actual diff.

## F13 — Human Approval Gate

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F02, F10, F11, F12-T01, F12-T02
- Blocks: F14
- Purpose: bind the human decision to the exact reviewed candidate.
- Likely future modified files: gate action, repair gate, FastAPI app, frontend API/contracts.
- Likely future new files: repair approval service/test.
- Acceptance summary: approve/reject/revise are human actions and stale approvals cannot execute.
- Focused test scope: exact checksums, idempotency, stale revision, actor authority.
- Main risks: reviewer acceptance being mistaken for approval.

## F14 — Sandbox Repair Executor

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F02, F12-T03, F13
- Blocks: F15
- Purpose: apply only exact approved candidates in backend-derived sandboxes.
- Likely future modified files: patch apply, validation runner, repair flow.
- Likely future new files: sandbox executor/test.
- Acceptance summary: original source is unchanged; proposed and actual diffs are separate proof artifacts.
- Focused test scope: containment, exact bytes, actual diff, rollback setup, source immutability.
- Main risks: path escape or apply-time drift.

## F15 — Validation Runner

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F09, F14
- Blocks: F16
- Purpose: use configured deterministic checks as success proof.
- Likely future modified files: validation runner, repair flow, orchestrator runner.
- Likely future new files: validation policy/test.
- Acceptance summary: pass/fail artifacts are immutable; failure rolls back and cannot promote.
- Focused test scope: compile, focused tests, configured alternatives, timeout, rollback.
- Main risks: model assertion or partial command success treated as proof.

## F16 — Checkpoint Promoter

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F03, F04, F15
- Blocks: F17, F18
- Purpose: promote validated output into an accepted checkpoint.
- Likely future modified files: stage progression, gate action, artifact revision service (`needs verification`: no file with this exact name currently exists).
- Likely future new files: checkpoint promoter/test.
- Acceptance summary: promotion is atomic, idempotent, validation-bound, and lineage-complete.
- Focused test scope: pass/fail, duplicate promotion, stale input, artifact checksum.
- Main risks: promoting mutable or unvalidated state.

## F17 — Cockpit Recovery UX

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F02, F05, F13, F16
- Blocks: F18 demo coverage
- Purpose: expose safe lineage, recovery decisions, candidate, review, and proof without a frontend model-provider dependency.
- Likely future modified files: `MigrationCockpit.tsx`, frontend contracts/API.
- Likely future new files: checkpoint, attempt, repair review, and recovery action components plus tests.
- Acceptance summary: operators can act on IDs/checksums while paths, argv, env, commands, secrets, provider credentials/configuration, and raw logs stay hidden; the frontend never calls Foundry.
- Focused test scope: rendering, available actions, stale refresh, redaction, accessibility.
- Main risks: frontend state becoming authority.

## F18 — E2E Fixtures

- Status: not started
- Owner: TBD
- MVP: B
- Depends on: F01–F17
- Blocks: release acceptance
- Purpose: prove deterministic and generative recovery through the same engine and backend Azure AI Foundry contract.
- Likely future modified files: focused backend and frontend test families.
- Likely future new files: Jackson E2E, LLM-authored patch E2E, `tests/fixtures/demo3/`.
- Acceptance summary: both fixtures use fake Azure AI Foundry adapter responses and fake retrieval, require no Copilot or live calls, and promote only after validation.
- Focused test scope: complete lineage, exact candidate bytes, sandbox diff, safe projections, no network/provider credential dependency.
- Main risks: Jackson-specific test harness or backend rule encoding the non-recipe fix.
