# Governed LLM Migration Supervisor

## Executive Summary

The Governed LLM Migration Supervisor is an additive V2 feature set for the existing AI Migration Control Tower. It is not a replacement for OpenRewrite, Maven, build, test, sandbox transform, patch gates, validation reruns, rollback, approval gates, or final reporting.

Product claim:

```text
LLM fits naturally into migration because it receives real migration evidence, creates typed repair/proposal/review/action objects, supports human steering, and routes approved work into backend-owned sandbox execution and validation.
```

Final verdict:

```text
We are not building "an LLM that fixes everything." We are building an active, governed LLM migration supervisor on top of the existing migration agents, artifacts, repair loop, and approval gates.
```

## Current Repo Reality

The repo already contains the important primitives this plan must reuse:

- V2 strict model schemas and token budgets: `migration_factory/control_tower/application/v2_model_schemas.py` with `PlanProposal`, `RepairProposal`, `ReviewerCritique`, `ActionRequest`, `AssistantAnswer`, `ContextPack`, `ContextPackBuilder`, and schema validation helpers.
- Persisted context-pack manifests: `migration_factory/control_tower/application/context_packs.py` and redaction in `context_pack_redaction.py`.
- Assistant messages and draft actions: `migration_factory/control_tower/application/v2_assistant_service.py` with `AssistantMessage`, `PendingActionDraft`, `FORBIDDEN_CAPABILITIES`, and `ALLOWED_TOOLS`.
- Azure-backed assistant calls with deterministic fallback: `migration_factory/control_tower/application/v2_assistant_model_client.py`.
- V2 repair proposal records: `migration_factory/control_tower/application/v2_repair_flow.py`.
- Checksum approval cards and resume commands: `migration_factory/control_tower/application/v2_approval_mapping.py`.
- Checksum review pattern for plan revisions: `migration_factory/control_tower/application/plan_reviews.py`.
- Backend-owned command/event runner: `migration_factory/control_tower/application/v2_orchestrator_runner.py`.
- Existing repair lifecycle: `migration_factory/repair_loop/evidence_collector.py`, `patch_gate.py`, `rule_registry.py`, `patch_apply.py`, `validation_runner.py`, and `ledger.py`.
- Copilot repair request/response primitives: `migration_factory/copilot_repair/request_builder.py`, `response_validator.py`, and `adapter.py`.
- Failure classification: `migration_factory/agents/failure_classifier/agent.py`.
- Maven/POM helpers: `migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py`, `migration_factory/agents/transformation_agent/pom_patches.py`, and `migration_factory/agents/build_agent/detection.py`.
- Final-report context/report generation: `migration_factory/final_report/context_builder.py`, `writer.py`, and `copilot.py`.
- Cockpit UI and API clients: `web/control-tower/app/migrations/[jobId]/MigrationCockpit.tsx`, `web/control-tower/app/jobs/[jobId]/AssistantPanel.tsx`, `web/control-tower/lib/contracts.ts`, and `web/control-tower/lib/controlTowerApi.ts`.

UNCERTAIN: there is a V2 `ContextPack` dataclass and a separate persisted V1 context-pack manifest service. Assumption: implementation should extend both the V2 runtime pack dict and persisted manifest/DTO shape as needed, preserving compatibility for older manifests.

UNCERTAIN: no durable `ai_diagnosis_created` record type was found. Assumption: add it as a V2 event plus a persisted proposal/diagnosis record instead of storing only frontend state.

## New Workflow

```text
failure event
-> collect existing evidence
-> build redacted extended ContextPack
-> route event to prompt and strict schema
-> LLM creates diagnosis/proposal/action object
-> reviewer critique
-> human approval card
-> existing repair_loop safety lifecycle
-> sandbox patch apply
-> validation rerun
-> ledger/proof
-> cockpit trace
-> final report AI trace
```

## Human Supervision Model

- LLM owns: create actionable diagnosis, repair proposal, POM patch intent, proposal revision, reviewer critique, approval preparation request, validation rerun request, and report summary objects.
- Human owns: approve, reject, ask for revision, decide whether to continue.
- Backend owns: state resolution, sandbox binding, checksum attachment, apply, validation, proof persistence, unsafe action blocking.
- Deterministic engine owns: OpenRewrite, Maven, build, test, sandbox transform, patch gate, validation rerun, rollback, final report.

Core rule:

```text
LLM creates actionable migration intents. Backend resolves state and executes. Human approves. Sandbox only. Proof gates stay.
```

## LLM Operational Role

The LLM is allowed to create actionable migration objects:

- diagnosis
- repair proposal
- POM patch intent
- proposal revision
- reviewer critique
- approval preparation request
- validation rerun request

These objects are not direct execution. They become backend-owned workflow inputs. Backend resolves the job, stage, command, sandbox, checksum, patch gate, validation, rollback, and ledger.

## LLM Authority Matrix

| Capability | LLM allowed? | How it works |
|---|---:|---|
| Explain failure | Yes | Uses ContextPack evidence. |
| Diagnose build/test/transform failure | Yes | Produces structured diagnosis/proposal. |
| Propose POM fix | Yes | Recommends deterministic rule or patch intent. |
| Revise proposal from chat | Yes | Creates a new RepairProposal revision. |
| Request reviewer critique | Yes | Creates review_requested action. |
| Prepare approval request | Yes | Backend creates checksum approval card. |
| Prepare sandbox repair | Indirect only | Backend binds job/stage/command/sandbox. |
| Request validation rerun after apply | Indirect only | Backend runs validation after approved apply. |
| Apply patch in sandbox | Indirect only | Backend applies after human approval. |
| Approve decision | No | Human only. |
| Choose random sandbox/path | No | Backend resolver only. |
| Modify legacy source | No | Never. |

## Feature Map

1. [ContextPack Extension](01-contextpack-extension.md)
2. [Automatic Failure Diagnosis](02-automatic-failure-diagnosis.md)
3. [Event-Based Prompt Router](03-event-based-prompt-router.md)
4. [POM Intelligence Summary](04-pom-intelligence-summary.md)
5. [Chatbot Proposal Steering](05-chatbot-proposal-steering.md)
6. [Sandbox Action Resolver](06-sandbox-action-resolver.md)
7. [Reviewer Before Apply](07-reviewer-before-apply.md)
8. [V2 to Repair Loop Bridge](08-v2-to-repair-loop-bridge.md)
9. [Cockpit Supervision Panels](09-cockpit-supervision-panels.md)
10. [Final Report AI Trace](10-final-report-ai-trace.md)

## Build Order

1. Extend existing ContextPack metadata.
2. Add artifact/evidence resolver using existing artifact refs and redaction.
3. Add event-based prompt/schema router.
4. Wire `build_failed`/`test_failed`/`transform_failed` to automatic LLM diagnosis.
5. Add `PomContextSummary` from existing Maven/POM tools.
6. Add chatbot proposal steering as `ActionRequest` -> `RepairProposal` revision.
7. Add `V2AssistantActionResolver` for correct command/stage/sandbox binding.
8. Add `ReviewerCritique` only for repair/POM proposals first.
9. Bridge approved V2 proposals into existing `repair_loop` safety lifecycle.
10. Add cockpit panels consuming real backend records.
11. Add final report AI trace.

## First Demo Slice

```text
build_failed
-> backend collects evidence
-> LLM diagnoses failure
-> LLM creates RepairProposal with POM/dependency repair intent
-> user says in chat: "don't touch Java source, make it POM-only"
-> LLM revises proposal
-> backend resolves correct sandbox and binding checksum
-> reviewer LLM critiques proposal
-> human approves approval card
-> backend converts approved proposal into repair_loop attempt
-> patch_gate validates
-> backend applies patch in sandbox
-> Maven/test validation reruns
-> cockpit shows diagnosis, proposal, reviewer, approval, apply, validation, ledger
```

## Anti-Duplication Rules

Do not rebuild:

- context pack system
- artifact store
- failure evidence collector
- failure classifier
- repair request schema
- repair response schema
- repair safety gate
- patch apply
- rollback
- validation runner
- repair ledger
- POM parser
- POM patch helpers
- approval cards
- checksum approval logic
- assistant guardrails
- event stream/projection layer
- reviewer schema

Do not let chatbot bypass backend-owned gates to:

- execute commands directly
- write files directly
- approve decisions
- modify legacy source
- override failed proof
- choose random sandbox
- change migration stage directly
- choose Maven goals/deployments

## Web-Checked Technical Basis

- OpenAI Codex documents `AGENTS.md` as persistent repository guidance for Codex: [OpenAI Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md).
- OpenAI Structured Outputs require schema-constrained outputs and `additionalProperties: false`: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- OpenAI function/tool calling is an application-mediated flow: the model produces a tool call and application code executes the function, which matches the backend-owned execution boundary: [OpenAI Function Calling](https://developers.openai.com/api/docs/guides/function-calling).
- Azure OpenAI Structured Outputs support a subset of JSON Schema and require `additionalProperties: false` on objects: [Azure OpenAI Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).
- Azure OpenAI JSON mode guarantees valid JSON but not schema adherence; structured outputs are required for schema guarantees: [Azure OpenAI JSON mode](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/json-mode).
- OpenRewrite Spring Boot 3 migration recipes can migrate Boot 2.x to Boot 3.5 and can be run by Maven command line or build configuration: [OpenRewrite Spring Boot 3 guide](https://docs.openrewrite.org/running-recipes/popular-recipe-guides/migrate-to-spring-3).
- OpenRewrite Boot 3.5 recipe modifies build files and framework API usage: [OpenRewrite UpgradeSpringBoot_3_5](https://docs.openrewrite.org/recipes/java/spring/boot3/upgradespringboot_3_5-community-edition).
- Maven dependency management centralizes dependency versions in a parent/BOM: [Maven dependency mechanism](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html).
- Spring Boot parent/BOM manages common dependency versions and compiler defaults: [Spring Boot Maven plugin using guide](https://docs.spring.io/spring-boot/maven-plugin/using.html).

## Open Questions Before Implementation

- What durable table/record should own `ai_diagnosis_created`: V2 assistant records, V2 repair proposals, V2 events, or a new append-only AI trace table?
- Should ContextPack metadata be stored as explicit columns, `metadata_json`, or both?
- Should `PomContextSummary` be a new V2 schema in `v2_model_schemas.py`, a context-pack payload, or an artifact record?
- Should reviewer critique be mandatory before approval card creation, or can approval cards show `review_pending`?
- What is the canonical binding from V2 `command_id` to run directory and sandbox when the failure came from resume rather than initial stage command?
- Should approved repair attempts be modeled as V2 repair records that mirror `repair_loop/repair_ledger.json`, or should the ledger be the only attempt source of truth with V2 projections over it?
