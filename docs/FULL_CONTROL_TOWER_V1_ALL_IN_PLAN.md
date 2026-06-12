# Full AI Migration Control Tower V1 All-In Plan

Status: planning only  
Branch analyzed: `DEMO2`  
Generated: 2026-06-11  
Allowed change for this task: this document only

## 1. Executive Summary

Full AI Migration Control Tower V1 is the product plan for running the real existing migration system from the web UI through a persisted, audited, worker-owned backend flow:

```text
Next.js UI
-> FastAPI adapter
-> Control Tower application layer
-> persisted job/stage/approval/repair/tool state
-> Windows worker/supervisor
-> migration_factory.orchestrator.runner/resume
-> LangGraph/OpenRewrite/Maven
-> Azure Foundry / Azure OpenAI models
-> sandbox-only migration/repair/tool execution
-> deterministic proof/report
```

The current repository already has a strong M1/M2 Control Tower foundation: FastAPI routes, application services, SQLite persistence, jobs, runner profiles, pipeline definitions, run configurations, command executions, events, artifacts, worker launch, bounded command output, cancellation/timeout handling, terminal artifacts, SSE replay, and a diagnostic Next.js UI. V1 must extend this foundation instead of creating a parallel control plane.

The V1 target is not a small M3/M4 split. It is a single all-in product architecture implemented later through controlled issues. The key changes are:

- Replace diagnostic-only Control Tower behavior with real three-stage migration execution.
- Lock the supported route to Spring Boot `2.1.6 -> 2.7.18 -> 3.5.6`, Java `8/11 -> 17 -> 21`, with Spring Boot `4` excluded.
- Make stage switching backend-owned through immutable pipeline snapshots and a stage-chain ledger.
- Move manual PowerShell environment and commands into backend-owned runner, pipeline, model, and action policies.
- Introduce Azure-backed/provider-neutral model registry, model health checks, model-call audit, context packs, assistant sessions, plan amendments, repair proposals, reviewer critiques, and privileged action approvals.
- Keep all mutation inside the current stage sandbox; legacy source remains untouched.
- Require explicit developer approval for exact plan, patch, command/action, and checksum before source-changing or shell/Maven work.
- Treat deterministic Maven/tests/proof gates as the only technical truth.

## 2. Current Repository Findings

### 2.1 Source files and docs analyzed

This plan was based on direct source/doc inspection plus focused Graphify queries. Graphify was used only as navigation; implementation decisions below are based on actual files.

Analyzed repository files include:

- `AGENTS.md`
- `docs/PRD_AI_Migration_Control_Tower_v0.3.md`
- `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`
- `docs/M2_REPOSITORY_ALIGNMENT.md`
- `docs/M3_REAL_DEMO_PLAN.md` from `HEAD` only because it is deleted in the current worktree
- `docs/system/04-profiles-ai-hub.md`
- `docs/system/09-how-to-run.md`
- `docs/system/10-new-agent-handoff.md`
- `docs/system/11-current-problems-and-v2-roadmap.md`
- `modernizer-solution-ai-hub/profiles/*.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/*.yaml`
- `modernizer-solution-ai-hub/policies/*.yaml`
- `modernizer-solution-ai-hub/schemas/*.json`
- `migration_factory/orchestrator/runner.py`
- `migration_factory/orchestrator/resume.py`
- `migration_factory/transform_v1_after_approval.py`
- `migration_factory/repair_loop/**`
- `migration_factory/copilot_assist/**`
- `migration_factory/copilot_repair/**`
- `migration_factory/contracts/schemas/**`
- `migration_factory/final_report/**`
- `migration_factory/control_tower/**`
- `web/control-tower/**`
- `tests/control_tower/**`

### 2.2 Current Control Tower reality

Verified current implementation:

- `migration_factory/control_tower/domain/entities.py` defines records for runner profiles, pipeline definitions, migration jobs, run configurations, stage runs, artifacts, events, audit records, command executions, and idempotency.
- `migration_factory/control_tower/domain/states.py` defines job and command state concepts, target proof levels, and related enums.
- `migration_factory/control_tower/domain/transitions.py` owns current state transitions.
- `migration_factory/control_tower/application/commands.py`, `dto.py`, `ports.py`, `services.py`, and `queries.py` provide the application boundary for registration, job creation, diagnostics, command workspace preparation, worker launch, cancellation, timeout, finalization, reconciliation, artifacts, and events.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql` through `0006_m2_terminal_artifacts.sql` implement the current persistence foundation.
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py` and `unit_of_work.py` implement the SQLite adapter.
- `migration_factory/control_tower/infrastructure/worker_launcher.py` launches a controlled Windows worker for diagnostic command execution.
- `migration_factory/control_tower/infrastructure/workspace.py` prepares command workspaces and manifests.
- `migration_factory/control_tower/adapters/fastapi/app.py` exposes current `/v1` APIs for health, runner profiles, pipelines, filesystem roots/entries/validation, jobs, diagnostic jobs, command launch/finalization/cancel, logs, events/SSE, and artifacts.
- `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx` and `web/control-tower/app/jobs/[jobId]/*` implement a diagnostic UI, not the final migration cockpit.
- `web/control-tower/lib/contracts.ts`, `controlTowerApi.ts`, and `eventReplay.ts` define current client contracts and SSE behavior.

Current Control Tower gaps for V1:

- No persisted model profiles or Azure model registry.
- No model health checks or model-call audit.
- No context-pack persistence.
- No assistant threads/messages/tool calls.
- No plan revision/amendment store.
- No reviewer critique store.
- No repair instruction/proposal/attempt store in Control Tower.
- No privileged action store/policy/executor.
- No stage-chain ledger linking Stage 1 -> Stage 2 -> Stage 3.
- No backend-owned real runner/resume execution for migration stages.
- No UI for full migration job creation, stage timeline, plan amendment, repair approval, privileged action approval, proof, or assistant.

### 2.3 Current orchestrator reality

Verified source:

- `migration_factory/orchestrator/runner.py` accepts `--run-id`, `--legacy`, `--modernized`, `--ai-hub`, `--profile`, and `--mode`.
- `migration_factory/orchestrator/resume.py` accepts `--run-id`, `--run-dir`, `--decision`, `--approved-by`, and `--comments`.
- `migration_factory/orchestrator/graph.py` builds a LangGraph flow around analysis, planning, assessment, approval, transform, and final report.
- `migration_factory/orchestrator/approval.py` writes/reads filesystem approval artifacts.
- `migration_factory/orchestrator/checkpointing.py` uses checkpointing for graph continuity.
- `migration_factory/orchestrator/state.py` parses Copilot-related environment config and stores run state.
- `migration_factory/transform_v1_after_approval.py` participates in approved transform execution.

V1 should not reimplement the orchestrator. It should wrap it in a worker-owned command model with persisted Control Tower stage state and approvals.

### 2.4 Current repair/Copilot/final-report reality

Verified source:

- `migration_factory/repair_loop/**` already has bounded evidence collection, failure classification, patch apply/gate behavior, validation runner, ledger, fallback planner, rule registry, and rollback-oriented concepts.
- `migration_factory/copilot_repair/**` already has request building, response validation, feature probing, evidence sessions, and adapter code.
- `migration_factory/copilot_assist/**` already has assistant/context/provider concepts.
- `migration_factory/final_report/**` builds final reports and redacts secret-like values.
- `migration_factory/contracts/schemas/*.json` already includes schemas for repair, assist, approval, migration plan, approved plan lock, final/report/test/assessment contexts.

V1 should reuse these pieces where they are sound, but must rename or wrap final architecture as provider-neutral/Azure-backed. Copilot CLI is not the final provider.

### 2.5 Current tests

Current Control Tower tests include:

- `tests/control_tower/test_m1_acceptance.py`
- `tests/control_tower/test_health_diagnostics.py`
- `tests/control_tower/test_fastapi_diagnostic_queue.py`
- `tests/control_tower/test_domain_transitions.py`
- `tests/control_tower/test_paths.py`
- `tests/control_tower/test_pipeline_registration.py`
- `tests/control_tower/test_pipeline_definition_schema.py`
- `tests/control_tower/test_runner_profile_registration.py`
- `tests/control_tower/test_runner_profile_schema.py`
- `tests/control_tower/test_run_configurations.py`
- `tests/control_tower/test_run_events.py`
- `tests/control_tower/test_artifact_registry.py`
- `tests/control_tower/test_artifact_paths.py`
- `tests/control_tower/test_artifact_hashing.py`
- `tests/control_tower/test_audit_records.py`
- `tests/control_tower/test_api_security.py`
- `tests/control_tower/test_active_job_lock.py`
- `tests/control_tower/test_application_commands_queries.py`
- `tests/control_tower/test_create_migration_job.py`
- `tests/control_tower/test_transition_job_state.py`
- `tests/control_tower/test_sqlite_migrations.py`
- `tests/control_tower/test_singleton_controller.py`
- `tests/control_tower/test_m2_diagnostic_queue.py`
- `tests/control_tower/test_m2_workspace.py`
- `tests/control_tower/test_m2_worker_launch.py`
- `tests/control_tower/test_m2_command_output.py`
- `tests/control_tower/test_m2_event_replay.py`
- `tests/control_tower/test_m2_cancellation.py`
- `tests/control_tower/test_m2_restart_recovery.py`
- `tests/control_tower/test_m2_terminal_artifacts.py`

These are the baseline for extending V1 without regressing M2.

### 2.6 Contradictions found

The plan must resolve these before implementation:

- Some docs and older demo material mention Spring Boot `3.5.14`; current locked product decision and AI Hub profile files target Spring Boot `3.5.6`.
- The older M3 demo plan from `HEAD` discusses a two-stage route or optional Stage C; the locked V1 route is three stages and ends with Java 21.
- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` targets Spring Boot `3.5.6`, but the catalog/profile relationship contains a post-patch from `3.5.14` to `3.5.6`, while one referenced OpenRewrite catalog forbids apply goals. This needs normalization in a separate implementation issue.
- Current manual docs use `JAVA_HOME=JAVA21_HOME` globally. V1 must choose `JAVA_HOME` and `PATH` per stage command.
- Current Copilot environment variables and Copilot-named modules are compatibility points only. V1 target is Azure Foundry / Azure OpenAI with provider-neutral service names.
- Current Control Tower UI says "foundation diagnostic job". V1 must replace that user-facing concept with full AI migration job creation and cockpit flows.

## 3. Confirmed Target Decisions

Locked decisions for V1:

- Official Spring Boot target is `3.5.6`, not `3.5.14`.
- Supported route is exactly:
  - Stage 1: `springboot-2.1.6-to-2.7-java11`
  - Stage 2: `springboot-2.7-to-3.5-java17`
  - Stage 3: `springboot-3.5-java17-to-java21`
- Stage 1 target is Spring Boot `2.7.18`, Java `11`.
- Stage 2 target is Spring Boot `3.5.6`, Java `17`.
- Stage 3 target keeps Spring Boot `3.5.6`, Java `21`.
- Spring Boot 4 profiles/catalogs are excluded from the supported route.
- Profile switching is controlled by immutable pipeline definition and stage-chain ledger.
- Stage 2 input is Stage 1 sandbox output.
- Stage 3 input is Stage 2 sandbox output.
- Legacy source remains untouched.
- All mutation happens only in the current stage sandbox.
- No HTTP route runs migration work directly.
- Browser/model cannot provide executable paths, raw shell args, Maven goals, model IDs, arbitrary env variables, or arbitrary working directories.
- UI selects only profile IDs, root IDs, and pipeline IDs.
- Backend owns command construction, JDK/Maven/env/profile/model resolution.
- Azure Foundry / Azure OpenAI API is the target LLM provider.
- Copilot CLI is not the final provider.
- Worker/proposer model role: `gpt-5-mini`.
- Reviewer/critique model role: `Mistral-Large-3`.
- Fallback model role: `Llama-3.3-70B-Instruct`, configured but disabled.
- Generic automatic fallback is disabled.
- DeepSeek, Qwen, and Spring Boot 4 are excluded unless later policy changes.
- LLM is active where state permits: analysis, plan generation, plan amendment, approval explanation, build/test failure diagnosis, OpenRewrite failure diagnosis, repair proposal, developer-guided repair revision, validation-plan proposal, chatbot explanation, and evidence navigation.
- LLM cannot approve, change proof, access secrets, choose arbitrary folders, or mutate legacy source.
- LLM may request privileged actions only as Control Tower pending actions.
- Privileged actions require explicit developer confirmation and backend policy validation.
- Developer approval is required for exact plan/patch/action checksum before source-changing or shell/Maven work.
- Deterministic Maven/tests/proof gates are the only technical truth.

## 4. Profile and OpenRewrite Catalog Inventory

### 4.1 Supported profiles

Verified files:

- `modernizer-solution-ai-hub/profiles/springboot-2.1.6-to-2.7-java11.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-3.5-java17-to-java21.yaml`

Target profile expectations:

| Stage | Profile ID | Input | Target Spring Boot | Target Java | JDK env |
| --- | --- | --- | --- | --- | --- |
| 1 | `springboot-2.1.6-to-2.7-java11` | legacy source | `2.7.18` | `11` | `JAVA11_HOME` |
| 2 | `springboot-2.7-to-3.5-java17` | Stage 1 sandbox | `3.5.6` | `17` | `JAVA17_HOME` |
| 3 | `springboot-3.5-java17-to-java21` | Stage 2 sandbox | `3.5.6` | `21` | `JAVA21_HOME` |

### 4.2 Supported catalogs

Verified catalog files include:

- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-2.1.6-to-2.7-java11.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-2.7-to-3.5-java17.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-3.5-java17-to-java21.yaml`

Target rules:

- Stage catalogs must be referenced through immutable profile snapshots.
- OpenRewrite apply behavior must be controlled by backend policy, not browser/model input.
- Stage 2 must normalize every `3.5.14` artifact/doc/reference that affects execution to `3.5.6`, or explicitly document it as historical compatibility if still required.
- Stage 3 Java 21 must use the Java 21 migration recipe set and backend-owned Maven/OpenRewrite commands.

Official reference: OpenRewrite documents `org.openrewrite.java.migrate.UpgradeToJava21` as the Java 21 composite recipe that updates Java source/target and compatible plugins where applicable: https://docs.openrewrite.org/recipes/java/migrate/upgradetojava21

### 4.3 Excluded profiles/catalogs

Verified Spring Boot 4-related files exist:

- `modernizer-solution-ai-hub/profiles/springboot-2-java8-to-boot4-java21.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-4-java21-sandbox.yaml`

These must not be offered in the V1 supported pipeline selector. They can remain in the repository but must be excluded by pipeline policy and UI filtering.

## 5. Three-Stage Pipeline Definition

Proposed pipeline ID:

```text
springboot-216-to-356-java21-three-stage
```

Pipeline definition:

```yaml
id: springboot-216-to-356-java21-three-stage
version: 1
target:
  spring_boot: 3.5.6
  java: 21
proof_level: build_test_verified
stages:
  - index: 1
    profile_id: springboot-2.1.6-to-2.7-java11
    source_kind: legacy_source
    target_spring_boot: 2.7.18
    target_java: 11
    jdk_id: java11
  - index: 2
    profile_id: springboot-2.7-to-3.5-java17
    source_kind: previous_stage_sandbox
    previous_stage_index: 1
    target_spring_boot: 3.5.6
    target_java: 17
    jdk_id: java17
  - index: 3
    profile_id: springboot-3.5-java17-to-java21
    source_kind: previous_stage_sandbox
    previous_stage_index: 2
    target_spring_boot: 3.5.6
    target_java: 21
    jdk_id: java21
```

Rules:

- The pipeline definition is snapshotted at job creation.
- Stage entries store profile version/checksum and catalog checksum.
- Stage N cannot start until Stage N-1 passes continuation policy.
- Users cannot switch profiles mid-command.
- Any change to profile/stage behavior requires a new plan revision and explicit approval.
- Pipeline IDs are selected by UI; full execution details are backend-owned.

## 6. Manual PowerShell Flow Mapped to Control Tower Flow

### 6.1 Current manual environment

The manual flow sets:

- `PYTHONPATH=.`
- `MAVEN_CMD=C:\Tools\apache-maven-3.9.15\bin\mvn.cmd`
- `JAVA11_HOME`
- `JAVA17_HOME`
- `JAVA21_HOME`
- `JAVA_HOME=JAVA21_HOME`
- `AI_MIGRATION_COPILOT_*`
- proof and smoke-test flags
- legacy and modernized stage output folders
- AI Hub path
- stage profile IDs

### 6.2 V1 backend-owned equivalent

V1 must convert manual values into persisted backend-owned configuration:

- Runner profile inventory:
  - `java11.home_env = JAVA11_HOME`
  - `java17.home_env = JAVA17_HOME`
  - `java21.home_env = JAVA21_HOME`
  - `maven.command_ref = maven-3.9.15`
  - `pythonpath = .`
  - allowed env allowlist
  - allowed roots
  - output timeout/byte limits
- Pipeline profile:
  - selected pipeline ID only
  - immutable three-stage stage definitions
  - selected profile/catalog checksums
- Model profile:
  - Azure endpoint env ref
  - API key env ref or Entra credential mode
  - API version
  - deployment IDs for `gpt-5-mini`, `Mistral-Large-3`, and disabled fallback
- Run configuration:
  - legacy source root ref and relative path
  - parent output root ref
  - generated Stage 1/2/3 output roots
  - proof level `build_test_verified`
  - policies selected by ID/version/checksum

`JAVA_HOME` must be set per stage command:

- Stage 1: `JAVA_HOME=%JAVA11_HOME%`; prepend `%JAVA11_HOME%\bin`
- Stage 2: `JAVA_HOME=%JAVA17_HOME%`; prepend `%JAVA17_HOME%\bin`
- Stage 3: `JAVA_HOME=%JAVA21_HOME%`; prepend `%JAVA21_HOME%\bin`

`MAVEN_CMD` remains backend-owned. The browser and model never submit it.

### 6.3 Manual commands replaced by persisted commands

Manual Stage 1 runner/resume becomes:

- Create `stage_chain_ledger` row for Stage 1.
- Create backend command `RUN_ORCHESTRATOR_STAGE` with sanitized argv:
  - module: `migration_factory.orchestrator.runner`
  - args from immutable run config and stage ledger
  - `--legacy` = registered legacy source path
  - `--modernized` = Stage 1 output root
  - `--ai-hub` = registered AI Hub root
  - `--profile` = Stage 1 profile ID
  - `--mode full_sandbox_migration`
- Worker launches command under Windows process control.
- LangGraph approval interrupt creates `approval_required` state in Control Tower.
- User approval creates a persisted approval record.
- Resume command is created by backend:
  - module: `migration_factory.orchestrator.resume`
  - `--run-id` from ledger
  - `--run-dir` from ledger
  - `--decision approved`
  - `--approved-by` actor ID
  - `--comments` from immutable approval artifact

Manual Stage 2 replacement:

- Stage 2 `legacy` input is not user input. It is Stage 1 ledger `sandbox_dir`.
- Stage 2 output root is generated under parent output root.
- Stage 2 profile/JDK are selected by pipeline ledger.

Manual Stage 3 replacement:

- Stage 3 `legacy` input is Stage 2 ledger `sandbox_dir`.
- Stage 3 output root is generated under parent output root.
- Stage 3 profile/JDK are selected by pipeline ledger.

## 7. Runner Profile and Environment Design

Runner profiles should be persisted and health-checked, extending current `runner_profile.py` and registration flows.

Required runner profile fields:

- `id`
- `display_name`
- `version`
- `checksum`
- `python_executable_ref`
- `pythonpath`
- `maven_command_ref`
- `jdk_inventory`
  - `java11`: env ref `JAVA11_HOME`, expected major `11`
  - `java17`: env ref `JAVA17_HOME`, expected major `17`
  - `java21`: env ref `JAVA21_HOME`, expected major `21`
- `ai_hub_root_ref`
- `allowed_source_roots`
- `allowed_output_roots`
- `allowed_env_keys`
- `redacted_env_keys`
- `command_timeout_policy`
- `output_limit_policy`
- `windows_job_object_policy`
- `shell_enabled`
- `shell_template_allowlist`

Health checks:

- Python module import check for `migration_factory.orchestrator.runner` and `resume`.
- Maven command exists and `mvn --version` works under backend timeout.
- `JAVA11_HOME`, `JAVA17_HOME`, `JAVA21_HOME` exist and report expected major versions.
- Stage-specific Maven execution uses selected JDK, not global `JAVA_HOME`.
- AI Hub root exists and required profile/catalog/schema files exist.
- Output root is writable.

Official reference: Maven Toolchains allow builds to use a selected JDK independently of the JRE running Maven, and Maven plugins can consume toolchain configuration: https://maven.apache.org/guides/mini/guide-using-toolchains.html

V1 can start with backend-set `JAVA_HOME/PATH` per stage and later add generated `toolchains.xml` if needed. The important invariant is that browser/model input never chooses raw executable paths.

## 8. Azure Foundry Model Registry Design

Add a provider-neutral model registry with Azure as the target provider.

Model profile:

```yaml
id: azure-foundry-v1
provider: azure_openai
endpoint_env: AZURE_OPENAI_ENDPOINT
credential:
  mode: api_key_or_entra
  api_key_env: AZURE_OPENAI_API_KEY
api_version_env: AZURE_OPENAI_API_VERSION
fallback_enabled: false
roles:
  proposer:
    model: gpt-5-mini
    deployment_id_ref: backend-controlled
    structured_outputs_required: true
  reviewer:
    model: Mistral-Large-3
    deployment_id_ref: backend-controlled
    structured_outputs_required: true
  fallback:
    model: Llama-3.3-70B-Instruct
    deployment_id_ref: backend-controlled
    enabled: false
```

Environment:

- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_API_KEY` or Microsoft Entra ID credential
- `AZURE_OPENAI_API_VERSION`
- Backend-controlled deployment IDs, stored outside browser/model input

Rules:

- No Azure secret is shown in UI, logs, events, artifacts, context packs, model calls, or final reports.
- Model IDs/deployment IDs are selected by model profile, not user/model free text.
- Generic fallback is disabled. Disabled fallback may be health-checked as configured but cannot be invoked automatically.
- DeepSeek/Qwen are not in the registry unless a future policy change adds them.

Official reference: Azure OpenAI structured outputs use JSON Schema to constrain model responses to a supplied schema: https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs

## 9. Model Readiness and Health-Check Design

Endpoints:

```http
GET  /v1/model-profiles
GET  /v1/model-profiles/{id}
POST /v1/model-profiles/{id}/health-check
```

Alternative: surface model health inside runner profile health checks, but model profile endpoints are clearer because AI readiness is independently blockable.

Readiness checks:

- Endpoint env present.
- Credential present and redacted.
- API version present and supported by configured client.
- Proposer deployment call works.
- Reviewer deployment call works.
- Structured output schema test passes for proposer.
- Structured output schema test passes for reviewer.
- Streaming test passes for assistant if streaming is enabled.
- Latency and timeout are within policy.
- Quota/auth/rate-limit errors are classified.
- Fallback disabled flag is verified.

Artifacts:

- `control/model_health.json`
- Contains only profile ID, provider, deployment IDs, status, latency, schema result, redacted error classification, timestamp.
- Contains no endpoint secrets, API keys, bearer tokens, prompts, full model responses, or filesystem secrets.

UI states:

- `READY`: required proposer/reviewer checks pass.
- `DEGRADED`: non-blocking checks fail, such as assistant streaming, while required structured calls pass.
- `BLOCKED`: required model profile config or calls fail.

Blocking rule:

- Existing deterministic job state can still be viewed/cancelled without AI.
- AI-required plan/repair steps block if readiness is not passing.
- Privileged actions cannot bypass model/readiness/policy failures.
- No silent fallback.

## 10. LLM Session and Model-Call Persistence

Add model-call persistence for auditability and replay-safe debugging.

Persist:

- `model_calls`
  - role: proposer, reviewer, assistant, classifier
  - model profile ID/checksum
  - deployment ID
  - provider
  - request schema ID/checksum
  - response schema ID/checksum
  - context pack ID/checksum
  - prompt manifest refs, not raw secrets
  - structured output checksum
  - token estimate and actual tokens when available
  - latency
  - finish status
  - redacted error classification
- `context_packs`
  - manifest of selected evidence
  - source artifact refs
  - file/log windows with offsets
  - checksums
  - estimated tokens
  - budget
  - redaction/filter results
- `assistant_threads`
- `assistant_messages`
- `tool_calls`

Never persist secrets, full hidden environment, full arbitrary logs, or unrestricted file dumps.

## 11. LLM Participation Across All Stages and Steps

LLM should participate where state allows, not only in initial planning:

- Analyze current stage evidence.
- Generate plan proposal.
- Revise plan after user amendment.
- Explain approval-ready plan and risks.
- Diagnose build/test failure.
- Diagnose OpenRewrite failure.
- Propose repair.
- Revise repair after developer instruction.
- Propose validation plan.
- Explain proof gates and final report evidence.
- Answer assistant questions through controlled read tools.
- Request privileged actions as pending actions.

LLM cannot:

- Approve anything.
- Execute actions directly.
- Mutate source.
- Access secrets.
- Choose arbitrary folders.
- Change proof.
- Override deterministic failures.
- Select arbitrary model/deployment/command.

Official references:

- LangGraph interrupts pause graph execution and wait for external input, supporting human-in-the-loop behavior: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph persistence/checkpointers support human-in-the-loop and fault-tolerant graph state: https://docs.langchain.com/oss/python/langgraph/persistence
- LangChain tools support runtime/dynamic tool selection based on authentication, permissions, feature flags, or conversation stage: https://docs.langchain.com/oss/python/langchain/tools

## 12. Context Builder Design and Token-Budget Strategy

Context Builder must be a backend service, not ad hoc prompt assembly.

Rules:

- Never send the full repo by default.
- Never send full logs by default.
- Never send full chat history by default.
- Run deterministic failure classification first.
- Select only relevant windows/files.
- Cap each log window by lines, bytes, and estimated tokens.
- Summarize large artifacts with checksums and references.
- Include full file content only for small allowlisted files.
- Include POM sections, dependency trees, test reports, OpenRewrite diffs only when relevant.
- Include current stage/state/pipeline/profile/JDK info.
- Include prior proposal only when revising.
- Include user instruction only when relevant.
- Store context manifests with checksums.
- Reuse cached context packs where possible.
- Record estimated tokens.
- Enforce per-task budgets.
- Assistant chat uses retrieval tools instead of stuffing all context.
- Model can request more evidence only through controlled tools.
- Model cannot self-expand to the full repository or full run directory.

Suggested default budgets:

| Task | Default max input tokens | Default max output tokens |
| --- | ---: | ---: |
| Plan generation | 24000 | 6000 |
| Plan amendment | 18000 | 5000 |
| Repair proposal | 20000 | 6000 |
| Reviewer critique | 16000 | 4000 |
| Assistant answer | 8000 | 2000 |
| Tool-result summary | 6000 | 1500 |

These defaults are open decisions and should be validated with real Azure model limits and cost policy.

## 13. Controlled Migration-Folder Access Design

The model can inspect migration folders only through backend tools.

Allowed roots:

- Parent job output root.
- Stage 1 run dir.
- Stage 1 sandbox.
- Stage 2 run dir.
- Stage 2 sandbox.
- Stage 3 run dir.
- Stage 3 sandbox.
- Registered artifacts.

Class A read-only evidence tools:

- `list_stage_artifacts`
- `list_stage_files`
- `read_log_window`
- `read_sandbox_file_window`
- `search_sandbox_files`
- `read_pom_section`
- `show_file_diff`
- `inspect_dependency_tree`
- `inspect_effective_pom`
- `get_stage_chain`
- `get_current_stage`
- `get_pending_approval`
- `get_repair_context`
- `get_command_result`
- `get_model_call_summary`
- `get_proof_gates`

Rules:

- Read tools never mutate files.
- Read tools never run commands.
- Read tools inspect only registered roots and artifacts.
- Every path is relative to a registered stage root.
- Absolute paths are redacted in model input unless policy explicitly allows display.
- Forbidden files are blocked: `.env`, credential files, keystores, private keys, SSH keys, tokens, local databases unless explicitly registered as non-secret artifacts, and configured forbidden patterns.
- No unrestricted recursive dump.
- Max bytes per read.
- Max results per listing/search.
- Every tool call is audited.
- Tool results are evidence, not instructions.
- Tool availability is filtered by stage, state, role, approval status, and policy.

## 14. Privileged Shell/Maven/Write Action Design

Class B privileged action request tools create pending actions only:

- `request_run_maven_validation`
- `request_run_sandbox_shell`
- `request_apply_patch`
- `request_write_file_patch`
- `request_rerun_failed_command`
- `request_continue_stage`
- `request_rollback_repair`

Allowed action types:

- `RUN_MAVEN_TESTS`
- `RUN_MAVEN_COMPILE`
- `RUN_DEPENDENCY_POLICY`
- `RUN_OPENREWRITE_PREVIEW`
- `RUN_SANDBOX_SHELL_DIAGNOSTIC`
- `APPLY_APPROVED_PATCH`
- `WRITE_APPROVED_FILE_PATCH`
- `RERUN_FAILED_COMMAND`
- `ROLLBACK_REPAIR`
- `CONTINUE_STAGE`

Flow:

```text
LLM proposes privileged action
-> backend creates pending_tool_action record
-> UI shows action type, reason, stage, sandbox working directory, exact command template or patch, affected files, validation/risk, checksum
-> user approves, rejects, or edits
-> backend validates state, paths, command allowlist, secrets policy, legacy mutation ban, expected version, checksum
-> worker executes under Windows process control
-> logs/artifacts/events are persisted
-> result returns to LLM as evidence
```

Forbidden:

- Arbitrary interactive PowerShell.
- Arbitrary command outside sandbox/run roots.
- Reading secrets.
- Writing legacy source.
- Deleting arbitrary folders.
- Changing machine-wide config.
- Installing software.
- `git push` or deployment.
- Changing proof manually.
- Unapproved model/deployment.
- Browser/model-supplied arbitrary Maven goals.

Shell policy:

- Shell is disabled by default or restricted to backend-defined diagnostic templates.
- Shell always requires developer approval.
- Shell command is non-interactive.
- Timeout and output limits are mandatory.
- Working directory must be current stage sandbox or run dir.
- Environment is allowlisted.
- No unrestricted `cmd`, `powershell`, or arbitrary script execution unless a later explicit security decision accepts that risk.

Maven policy:

- Maven actions are typed operations, not raw strings.
- Supported typed operations include compile, test, dependency tree, effective POM, dependency policy, and approved validation commands.
- Stage JDK comes from runner profile and stage ledger.
- Maven result becomes evidence, not model proof.

Write policy:

- LLM cannot stream arbitrary writes.
- LLM proposes exact patch or file-write action.
- Backend validates path scope and file type.
- UI shows exact diff/content and checksum.
- Developer approves exact checksum.
- Worker writes only in sandbox.
- Applied checksum must equal approved checksum.

## 15. Plan Amendment Workflow

Flow:

```text
User instruction
-> immutable plan amendment artifact
-> context pack includes instruction, current stage evidence, and prior proposal only when revising
-> GPT-5-mini generates structured plan proposal
-> UI shows proposal
-> if user rejects/edits, store new instruction and regenerate with previous proposal plus new instruction
-> if user accepts candidate, send candidate to Mistral-Large-3 critique
-> backend policy validates candidate
-> UI shows exact candidate, critique, policy result, and checksum
-> user approves exact checksum
-> worker executes/resumes
```

Invariants:

- User sees the proposal before final approval.
- User changes become immutable artifacts.
- Previous proposal plus new instruction are included in the next context pack.
- No silent mutation of plan content.
- Final approval is for an exact checksum.

## 16. Repair Workflow With Developer-Guided Instructions

Flow:

```text
Build/test/OpenRewrite command fails
-> classify failure
-> create bounded failure context pack
-> GPT-5-mini proposes structured repair
-> UI shows proposal
-> user approves candidate, rejects, or gives repair instruction
-> if user gives instruction, store immutable repair instruction and regenerate from previous proposal + instruction + evidence
-> if user approves candidate, send candidate to Mistral-Large-3 critique
-> backend policy validates
-> UI shows exact diff + validation plan + checksum
-> user approves exact checksum
-> worker snapshots sandbox
-> worker applies exact approved patch only in sandbox
-> worker runs approved validation plan
-> if validation passes, continue migration
-> if validation fails, rollback / another repair / escalate
```

Required safety:

- No mutation before exact developer approval.
- Patch applies only under current stage sandbox.
- Approved patch checksum equals applied patch checksum.
- Validation plan checksum equals executed plan unless user-approved additions exist.
- Legacy source checksum remains unchanged.
- Privileged shell/Maven/write actions use the same pending-action and approval model.

## 17. Reviewer Critique and Backend Policy Gate

Reviewer role:

- Uses `Mistral-Large-3`.
- Critiques plan proposals and repair proposals.
- Produces structured critique: accept/reject/revise, risks, missing evidence, unsafe assumptions, policy concerns.
- Does not approve or execute.

Backend policy gate:

- Validates schema.
- Validates stage state.
- Validates profile/pipeline compatibility.
- Validates path containment.
- Validates command/action allowlist.
- Validates patch scope and checksums.
- Validates no legacy mutation.
- Validates forbidden files not included.
- Validates model profile readiness.
- Validates expected job/stage version.

Only after reviewer and backend policy succeed should UI show the exact final candidate for developer checksum approval.

## 18. Stage-Chain Ledger Schema

Add durable ledger table `stage_chain_ledger`.

Required fields:

- `id`
- `parent_job_id`
- `stage_index`
- `stage_id`
- `profile_id`
- `profile_version`
- `profile_checksum`
- `pipeline_id`
- `pipeline_version`
- `pipeline_checksum`
- `source_kind`
- `input_run_dir`
- `input_sandbox_ref`
- `output_root`
- `run_id`
- `run_dir`
- `sandbox_dir`
- `selected_jdk_id`
- `maven_command_ref`
- `approval_ids_json`
- `privileged_action_ids_json`
- `command_ids_json`
- `stage_status`
- `continuation_policy_result_json`
- `proof_gates_json`
- `artifact_refs_json`
- `source_checksum_before`
- `source_checksum_after`
- `sandbox_checksum_checkpoints_json`
- `created_at`
- `started_at`
- `finished_at`
- `version`

Rules:

- Stage N cannot start unless Stage N-1 satisfies continuation policy.
- Stage switching is automatic and backend-owned.
- User cannot change stage profile mid-command.
- Profile/stage amendment requires new plan revision and explicit approval.
- Ledger is immutable except append-only or versioned status/evidence fields.
- Privileged action execution cannot alter the stage chain except through approved state transitions.

Indexes:

- Unique `(parent_job_id, stage_index)`.
- Unique `(stage_id)`.
- Index `(parent_job_id, stage_status)`.
- Index `(run_id)`.

Migration: `0007_v1_stage_chain_ledger.sql`.

Tests:

- Stage order validation.
- Stage 2 blocked before Stage 1 pass.
- Stage 3 blocked before Stage 2 pass.
- Previous-stage sandbox source binding.
- Immutable profile checksum.

## 19. Stage/Profile Switching Rules

Rules:

- `/jobs/new` selects a pipeline ID and runner profile ID.
- Backend snapshots pipeline, profile, catalog, policy, and model config.
- Stage profile is selected by ledger only.
- Running command cannot change profile.
- User cannot choose Stage 2 input; it is Stage 1 sandbox.
- User cannot choose Stage 3 input; it is Stage 2 sandbox.
- Any change to profile or stage sequence creates a new plan revision and requires explicit approval before future commands.
- Spring Boot 4 is filtered out for this pipeline.

## 20. Sandbox-Only Mutation and Approval Checksum Rules

Rules:

- Legacy source checksum is captured before Stage 1 and rechecked after every stage/action.
- Stage mutation root is current stage sandbox only.
- Patches are stored as artifacts with checksum.
- Approval references exact checksum.
- Worker recomputes checksum before applying.
- Applied patch checksum is persisted after applying.
- If checksum differs, execution fails closed.
- Validation plan checksum is persisted and compared before execution.
- If user adds approved validation commands, a new validation plan revision is created.
- Final proof is generated from deterministic artifacts only.

## 21. Migration Assistant Chatbot Design

The right-side assistant is active across all stages.

Capabilities:

- Explain status, current stage, current node, and current command.
- Explain failures and proof gates.
- Inspect registered evidence through controlled read tools.
- Draft plan amendments and repair instructions.
- Request privileged pending actions.
- Navigate logs/artifacts/diffs without dumping everything.

Limits:

- Cannot execute privileged actions directly.
- Cannot approve actions or plans.
- Cannot patch files directly.
- Cannot run Maven or shell directly.
- Cannot change proof.
- Cannot access secrets.
- Cannot read arbitrary files.
- When user says "ok do it", chat creates a typed pending action that still requires approval, policy validation, and state validation.

Assistant endpoints:

```http
GET  /v1/jobs/{job_id}/assistant/messages
POST /v1/jobs/{job_id}/assistant/messages
GET  /v1/jobs/{job_id}/assistant/stream
GET  /v1/jobs/{job_id}/assistant/actions
POST /v1/jobs/{job_id}/assistant/actions/{action_id}/confirm
POST /v1/jobs/{job_id}/assistant/actions/{action_id}/reject
```

## 22. API Design

Configuration:

```http
GET  /v1/runner-profiles
GET  /v1/runner-profiles/{id}
POST /v1/runner-profiles/{id}/health-check
GET  /v1/model-profiles
GET  /v1/model-profiles/{id}
POST /v1/model-profiles/{id}/health-check
GET  /v1/pipelines
GET  /v1/pipelines/{id}
GET  /v1/filesystem/roots
GET  /v1/filesystem/entries
POST /v1/filesystem/validate
```

Jobs/stages:

```http
POST /v1/jobs
GET  /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/start
POST /v1/jobs/{job_id}/cancel
GET  /v1/jobs/{job_id}/stages
GET  /v1/jobs/{job_id}/stages/{stage_id}
POST /v1/jobs/{job_id}/stages/{stage_id}/start
```

Approvals/plans:

```http
GET  /v1/jobs/{job_id}/plans
GET  /v1/jobs/{job_id}/plans/{revision_id}
POST /v1/jobs/{job_id}/plan-amendments
POST /v1/jobs/{job_id}/approvals/{approval_id}/approve
POST /v1/jobs/{job_id}/approvals/{approval_id}/reject
```

Repairs:

```http
GET  /v1/jobs/{job_id}/repairs
GET  /v1/jobs/{job_id}/repairs/{repair_id}
POST /v1/jobs/{job_id}/repairs/{repair_id}/instructions
POST /v1/jobs/{job_id}/repairs/{repair_id}/approve
POST /v1/jobs/{job_id}/repairs/{repair_id}/reject
POST /v1/jobs/{job_id}/repairs/{repair_id}/rollback
```

Privileged actions:

```http
GET  /v1/jobs/{job_id}/actions
GET  /v1/jobs/{job_id}/actions/{action_id}
POST /v1/jobs/{job_id}/actions
POST /v1/jobs/{job_id}/actions/{action_id}/approve
POST /v1/jobs/{job_id}/actions/{action_id}/reject
POST /v1/jobs/{job_id}/actions/{action_id}/execute
```

Events/logs/artifacts/proof/report:

```http
GET /v1/jobs/{job_id}/events
GET /v1/jobs/{job_id}/events/stream
GET /v1/jobs/{job_id}/commands
GET /v1/jobs/{job_id}/logs
GET /v1/jobs/{job_id}/artifacts
GET /v1/jobs/{job_id}/proof
GET /v1/jobs/{job_id}/report.md
GET /v1/jobs/{job_id}/report.json
```

All state-changing APIs require:

- Idempotency key where applicable.
- `If-Match` expected job version.
- Actor attribution.
- Audit record.
- Clear error code.

Official references:

- FastAPI recommends `lifespan` for startup/shutdown lifecycle management: https://fastapi.tiangolo.com/advanced/events/
- Starlette documents `EventSourceResponse` for Server-Sent Events: https://www.starlette.io/responses/
- Next.js App Router route handlers use Web Request/Response APIs in the `app` directory: https://nextjs.org/docs/app/getting-started/route-handlers
- Next.js Server and Client Components should separate server data work from interactive browser UI: https://nextjs.org/docs/app/getting-started/server-and-client-components

## 23. Persistence/Data Model Changes

Prefer extending current Control Tower SQLite persistence over duplicate stores.

### 23.1 Proposed migrations

- `0007_v1_model_registry.sql`
- `0008_v1_context_and_model_calls.sql`
- `0009_v1_assistant.sql`
- `0010_v1_stage_chain_ledger.sql`
- `0011_v1_plan_approvals.sql`
- `0012_v1_repairs.sql`
- `0013_v1_privileged_actions.sql`
- `0014_v1_proof_reports.sql`

### 23.2 Tables/extensions

`model_profiles`

- Purpose: backend-owned Azure/provider-neutral model configuration.
- Columns: `id`, `provider`, `endpoint_env`, `auth_mode`, `api_key_env`, `api_version_env`, `deployment_roles_json`, `fallback_enabled`, `checksum`, `created_at`, `updated_at`.
- Invariants: fallback disabled for V1; secrets stored as env refs only.
- Indexes: unique `id`.
- Tests: load/list/get profile, redaction, fallback disabled.

`model_health_checks`

- Purpose: readiness evidence.
- Columns: `id`, `model_profile_id`, `status`, `checks_json`, `latency_ms`, `error_classification`, `artifact_id`, `created_at`.
- Invariants: no secrets in `checks_json`.
- Indexes: `(model_profile_id, created_at)`.
- Tests: success/failure/quota/auth/schema failure.

`model_calls`

- Purpose: audit model usage.
- Columns: `id`, `job_id`, `stage_id`, `role`, `model_profile_id`, `deployment_id`, `context_pack_id`, `request_schema_checksum`, `response_schema_checksum`, `status`, `input_tokens_estimated`, `input_tokens_actual`, `output_tokens_actual`, `latency_ms`, `response_checksum`, `error_classification`, `created_at`.
- Invariants: no raw secrets; structured output stored as artifact/ref.
- Indexes: `(job_id, stage_id)`, `(role, created_at)`.
- Tests: audit creation, redaction, schema checksum.

`context_packs`

- Purpose: bounded evidence manifests for model calls.
- Columns: `id`, `job_id`, `stage_id`, `purpose`, `budget_tokens`, `estimated_tokens`, `manifest_json`, `checksum`, `created_at`.
- Invariants: forbidden files filtered; windows bounded.
- Indexes: `(job_id, stage_id, purpose)`.
- Tests: token budget, filtering, checksums.

`assistant_threads`

- Purpose: one or more assistant sessions per job.
- Columns: `id`, `job_id`, `status`, `created_by`, `created_at`, `updated_at`.
- Invariants: tied to job.
- Indexes: `(job_id)`.
- Tests: create/list/messages.

`assistant_messages`

- Purpose: persisted chat messages.
- Columns: `id`, `thread_id`, `actor`, `role`, `content_redacted`, `model_call_id`, `tool_call_ids_json`, `created_at`.
- Invariants: no secrets; no raw unbounded context.
- Indexes: `(thread_id, created_at)`.
- Tests: storage, redaction, streaming resume.

`pipeline_definitions` / pipeline snapshots

- Purpose: extend existing pipeline definitions with immutable snapshots.
- Columns/extensions: `version`, `checksum`, `stages_json`, `policy_refs_json`, `is_supported`, `created_at`.
- Invariants: supported V1 pipeline excludes Boot 4.
- Indexes: unique `(id, version)`.
- Tests: V1 pipeline schema, excludes Boot 4.

`stage_chain_ledger`

- Purpose: durable parent-to-stage linkage.
- Columns: see Section 18.
- Tests: stage order, previous sandbox source, status transitions.

`plan_revisions`

- Purpose: structured plan proposals and accepted candidates.
- Columns: `id`, `job_id`, `stage_id`, `revision_number`, `source_context_pack_id`, `model_call_id`, `status`, `proposal_artifact_id`, `checksum`, `created_by`, `created_at`.
- Invariants: append-only revisions.
- Indexes: `(job_id, stage_id, revision_number)`.
- Tests: immutable revisions, checksum approval.

`plan_amendments`

- Purpose: user instructions for plan changes.
- Columns: `id`, `job_id`, `stage_id`, `plan_revision_id`, `instruction_artifact_id`, `actor`, `created_at`.
- Invariants: immutable artifact.
- Indexes: `(job_id, stage_id)`.
- Tests: instruction artifact included in next context pack.

`reviewer_critiques`

- Purpose: reviewer model critique.
- Columns: `id`, `job_id`, `stage_id`, `target_type`, `target_id`, `model_call_id`, `critique_artifact_id`, `policy_result_json`, `status`, `created_at`.
- Invariants: cannot approve.
- Indexes: `(target_type, target_id)`.
- Tests: blocking critique, policy fail.

`approvals`

- Purpose: extend current approval/audit concepts for exact checksum approval.
- Columns/extensions: `approval_type`, `target_id`, `target_checksum`, `actor`, `decision`, `comments_artifact_id`, `expected_job_version`, `created_at`, `decided_at`.
- Invariants: approve exact checksum only.
- Indexes: `(job_id, status)`, `(target_type, target_id)`.
- Tests: stale version, checksum mismatch.

`repair_attempts`

- Purpose: stage repair lifecycle.
- Columns: `id`, `job_id`, `stage_id`, `failure_command_id`, `status`, `failure_classification`, `created_at`, `finished_at`.
- Invariants: tied to failed command and stage.
- Indexes: `(job_id, stage_id, status)`.
- Tests: failure -> repair state.

`repair_instructions`

- Purpose: developer repair guidance.
- Columns: `id`, `repair_attempt_id`, `instruction_artifact_id`, `actor`, `created_at`.
- Invariants: immutable.
- Indexes: `(repair_attempt_id)`.
- Tests: instruction included in regeneration.

`repair_proposals`

- Purpose: structured repair candidate.
- Columns: `id`, `repair_attempt_id`, `context_pack_id`, `model_call_id`, `patch_artifact_id`, `validation_plan_id`, `checksum`, `status`, `created_at`.
- Invariants: no mutation before approval.
- Indexes: `(repair_attempt_id, status)`.
- Tests: proposal lifecycle.

`privileged_actions`

- Purpose: pending shell/Maven/write/action requests.
- Columns: `id`, `job_id`, `stage_id`, `requested_by`, `action_type`, `reason`, `payload_json`, `checksum`, `status`, `policy_result_json`, `approval_id`, `command_id`, `created_at`, `decided_at`, `executed_at`.
- Invariants: pending action does not execute; approval required.
- Indexes: `(job_id, stage_id, status)`, `(action_type)`.
- Tests: pending creation, approval required, unsafe rejection.

`tool_calls`

- Purpose: read tools and action-request tools audit.
- Columns: `id`, `job_id`, `stage_id`, `thread_id`, `model_call_id`, `tool_name`, `tool_class`, `input_manifest_json`, `result_artifact_id`, `status`, `created_at`.
- Invariants: read tools bounded; action tools create pending actions.
- Indexes: `(job_id, stage_id)`, `(tool_name)`.
- Tests: read containment, action request only.

`patch_artifacts`

- Purpose: patch content/diff metadata.
- Columns: `id`, `job_id`, `stage_id`, `artifact_id`, `affected_paths_json`, `checksum`, `status`, `created_at`.
- Invariants: relative paths only; sandbox only.
- Indexes: `(job_id, stage_id)`.
- Tests: exact checksum apply.

`validation_plans`

- Purpose: approved validation operations.
- Columns: `id`, `job_id`, `stage_id`, `operations_json`, `checksum`, `status`, `created_at`.
- Invariants: typed Maven/shell operations only.
- Indexes: `(job_id, stage_id)`.
- Tests: checksum and JDK selection.

`worker_leases`

- Purpose: durable process ownership if current command execution process fields are insufficient.
- Columns: `id`, `command_id`, `worker_id`, `pid`, `job_object_ref`, `lease_expires_at`, `heartbeat_at`, `status`.
- Invariants: one active lease per command.
- Indexes: `(command_id)`, `(status, lease_expires_at)`.
- Tests: restart recovery, fail-closed unclear state.

`proof_gates`

- Purpose: deterministic proof status.
- Columns: `id`, `job_id`, `stage_id`, `gate_type`, `command_id`, `artifact_id`, `status`, `checksum`, `created_at`.
- Invariants: model cannot write proof.
- Indexes: `(job_id, stage_id, gate_type)`.
- Tests: proof from command artifacts only.

`final_reports`

- Purpose: final markdown/json report refs.
- Columns: `id`, `job_id`, `report_md_artifact_id`, `report_json_artifact_id`, `proof_summary_json`, `checksum`, `created_at`.
- Invariants: no secrets; deterministic evidence refs.
- Indexes: `(job_id)`.
- Tests: redaction, final report includes three-stage chain.

## 24. Worker/Supervisor/Process-Control Changes

Current `worker_launcher.py` is diagnostic-only. V1 needs a worker-owned command model for real orchestrator runner/resume and approved actions.

Required changes:

- Add typed command construction for `RUN_ORCHESTRATOR_STAGE`, `RESUME_ORCHESTRATOR_STAGE`, `RUN_MAVEN_OPERATION`, `RUN_OPENREWRITE_OPERATION`, `APPLY_APPROVED_PATCH`, `RUN_SANDBOX_SHELL_DIAGNOSTIC`, and `ROLLBACK_REPAIR`.
- Preserve command manifest verification.
- Preserve Windows Job Object launch/cancel behavior.
- Persist worker lease/process refs.
- Ensure every worker command has:
  - immutable argv
  - backend-owned env
  - selected JDK
  - working directory root
  - timeout
  - output limits
  - artifact/output capture
  - event emission
- On restart, reconcile unclear process state fail-closed.
- No HTTP route directly executes work.

Official reference: Windows Job Objects can associate processes with a job and `TerminateJobObject` terminates processes in the job; nested jobs affect process-tree handling: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

## 25. UI Design

### 25.1 `/jobs/new`

Replace diagnostic job creation with full migration job creation.

Controls:

- Title: `Create full AI migration job`
- Legacy source root selector.
- Legacy relative path.
- Parent output root selector.
- Optional output folder preview for Stage 1/2/3 auto-created outputs.
- Pipeline selector: `springboot-216-to-356-java21-three-stage`.
- Runner profile selector.
- Azure model profile readiness panel.
- JDK/Maven readiness panel.
- Target proof level: `build_test_verified`.
- Policy display/toggles, backend-controlled only.
- Create button disabled when required readiness is blocked.

No browser-provided raw paths outside registered roots, env vars, executables, Maven goals, model IDs, or shell args.

### 25.2 `/jobs/[jobId]`

Replace diagnostic job page with cockpit:

- Stage timeline: Stage 1, Stage 2, Stage 3, final report.
- Current LangGraph node.
- Current command.
- Current model activity.
- Approval cards.
- Plan amendment panel.
- Repair panel.
- Developer-guided repair instruction panel.
- Privileged action approval cards.
- Exact patch diff viewer.
- Validation plan viewer.
- Shell/Maven action preview and result viewer.
- Logs/events/artifacts.
- Proof gates.
- Final report.
- Right-side Migration Assistant chatbot.

### 25.3 UI contracts

Update:

- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/lib/eventReplay.ts`
- `web/control-tower/app/jobs/new/**`
- `web/control-tower/app/jobs/[jobId]/**`

Events should remain replayable and should distinguish job, stage, command, model call, approval, repair, action, proof, and report events.

## 26. Events/Logs/Artifacts/Proof/Reporting Design

Events:

- Persist every state transition.
- Include monotonic event ID for SSE replay.
- Event types:
  - job created/started/cancelled/failed/completed
  - stage queued/running/approval-required/repairing/passed/failed
  - command queued/running/output/finalized/cancelled/timed-out
  - model readiness checked
  - model call started/completed/failed
  - context pack created
  - plan proposal/revision/amendment
  - reviewer critique
  - privileged action pending/approved/rejected/executed/failed
  - repair proposal/instruction/apply/validation/rollback
  - proof gate updated
  - final report created

Artifacts:

- Reuse artifact registry.
- Store checksums for plan proposals, amendments, context packs, critiques, patches, validation plans, command output, model health, proof, final reports.
- Redact absolute paths and secrets for model/UI display where policy requires.

Proof:

- Only deterministic commands can create proof gates.
- Model summaries can reference proof but cannot create or override it.
- `build_test_verified` requires persisted Maven/test command evidence and matching stage chain.

Reports:

- Extend current final report to parent job:
  - stage chain
  - profile/catalog checksums
  - source/sandbox checksum checkpoints
  - approvals
  - repair attempts
  - privileged actions
  - proof gates
  - model-call summaries without secrets
  - final deterministic outcome

## 27. Security and Trust Model

Trust boundaries:

- Browser is untrusted for executable paths, raw commands, env vars, model IDs, and working directories.
- Model is untrusted for execution authority.
- Backend policy is the authority for state, path, command, model, and approval validation.
- Worker executes only backend-approved commands.
- Deterministic artifacts are the proof authority.

Controls:

- Registered roots only.
- Relative paths under registered roots.
- No legacy mutation.
- Forbidden file filtering.
- Exact checksum approvals.
- Idempotency keys.
- Expected job/stage version.
- Audit records for every state-changing API.
- Secrets redaction in UI/logs/events/artifacts/context packs/model calls/reports.
- Model fallback disabled.
- Shell disabled by default or heavily allowlisted.
- Windows process tree cancellation via Job Objects.
- Restart reconciliation fail-closed when worker state is unclear.

## 28. Test Strategy

Required tests:

- Profile schema validation.
- Pipeline stage order and previous-stage source.
- Stage 2 cannot start before Stage 1 passes.
- Stage 3 cannot start before Stage 2 passes.
- JDK selection per stage.
- Azure model readiness success/failure.
- Structured output schema validation.
- Fallback disabled behavior.
- Context pack token budget and forbidden file filtering.
- Controlled read tools cannot escape sandbox/run roots.
- Privileged action request creates pending action, not execution.
- Privileged action requires approval.
- Privileged action policy rejects unsafe shell/paths/secrets.
- Approved Maven action runs with correct stage JDK.
- Approved shell action runs only in sandbox/run root if enabled.
- Approved write action applies only exact checksum.
- Plan amendment creates immutable artifact.
- Repair instruction creates immutable artifact.
- User sees proposal before reviewer/policy/final approval.
- Exact checksum approval.
- Patch applies only to sandbox.
- Legacy source checksum unchanged.
- Validation pass continues migration.
- Validation failure offers rollback/escalation.
- Assistant cannot execute arbitrary commands.
- Assistant can request pending actions but cannot approve them.
- Browser cannot provide env/executable/model IDs.
- SSE replay and event persistence still work.
- Windows process-tree cancellation.

Regression suites:

- Existing `tests/control_tower/*`.
- Orchestrator tests around runner/resume/state/approval.
- Repair loop tests.
- Final report tests.
- Web contract/unit tests.

Do not weaken existing M1/M2 tests.

## 29. Implementation Issue Breakdown

### Issue 1: Plan/contracts freeze

- Goal: Freeze V1 contracts before implementation.
- Scope: API schemas, event names, state machines, pipeline ID, model profile contract.
- Out of scope: executing real migrations.
- Files likely touched: `docs/*`, `migration_factory/control_tower/application/dto.py`, `web/control-tower/lib/contracts.ts`, `migration_factory/contracts/schemas/**`.
- Acceptance criteria: V1 contracts documented and schema tests pass.
- Tests: contract serialization/deserialization tests.
- Dependencies: human decisions in Open Questions.

### Issue 2: Profile normalization to Spring Boot 3.5.6

- Goal: Normalize supported profiles/catalogs/docs to `3.5.6`.
- Scope: supported profiles/catalogs and validation.
- Out of scope: Boot 4 support.
- Files likely touched: `modernizer-solution-ai-hub/profiles/*.yaml`, `modernizer-solution-ai-hub/catalogs/openrewrite/*.yaml`, related tests/docs.
- Acceptance criteria: supported route is exactly three stages to Boot `3.5.6` Java `21`.
- Tests: profile/catalog schema and route tests.
- Dependencies: Issue 1.

### Issue 3: Azure model registry and health checks

- Goal: Add model profiles and readiness.
- Scope: persistence, application services, FastAPI endpoints, health artifact.
- Out of scope: assistant UI.
- Files likely touched: `application/model_registry.py`, `infrastructure/azure_models.py`, `sqlite/migrations/0007_v1_model_registry.sql`, `app.py`.
- Acceptance criteria: health checks classify ready/degraded/blocked; no secrets leaked.
- Tests: success/failure/redaction/fallback disabled.
- Dependencies: Issue 1.

### Issue 4: Context Builder and model-call audit

- Goal: Add bounded context packs and model call persistence.
- Scope: context builder, model call audit, token budgets.
- Out of scope: repair execution.
- Files likely touched: `application/context_builder.py`, `application/ports.py`, `sqlite/repositories.py`, `contracts/schemas/**`.
- Acceptance criteria: bounded context manifests with checksums and token estimates.
- Tests: forbidden files, budget, checksums.
- Dependencies: Issue 3.

### Issue 5: Controlled tool and privileged action architecture

- Goal: Implement read tools and pending privileged action creation.
- Scope: `application/tools.py`, `application/privileged_actions.py`, policy validator, persistence.
- Out of scope: full UI.
- Files likely touched: `application/tools.py`, `application/privileged_actions.py`, `infrastructure/tool_execution.py`, migrations.
- Acceptance criteria: read tools bounded; action tools create pending records only.
- Tests: containment, pending not executed, unsafe rejection.
- Dependencies: Issue 4.

### Issue 6: Three-stage pipeline/stage-chain ledger

- Goal: Persist parent job stage chain.
- Scope: stage ledger, pipeline snapshots, stage transition policy.
- Out of scope: worker execution.
- Files likely touched: `domain/entities.py`, `domain/states.py`, `domain/transitions.py`, `application/services.py`, migrations.
- Acceptance criteria: Stage 2/3 cannot start early; stage inputs from previous sandbox.
- Tests: stage order, immutable snapshots.
- Dependencies: Issue 2.

### Issue 7: Real worker-owned stage execution

- Goal: Execute real `runner.py` through worker command model.
- Scope: command construction, JDK env, worker launch, events/logs/artifacts.
- Out of scope: repair loop.
- Files likely touched: `worker_launcher.py`, `workspace.py`, `application/services.py`, `orchestrator/runner.py` only if minimal adapter hooks are needed.
- Acceptance criteria: Stage 1 command is worker-owned and no HTTP route runs work.
- Tests: command manifest, env, worker launch, cancellation.
- Dependencies: Issue 6.

### Issue 8: Approval interrupt/resume integration

- Goal: Map LangGraph approval interrupt to Control Tower approvals and resume.
- Scope: approval-required state, approval record, backend resume command.
- Out of scope: plan amendments.
- Files likely touched: `orchestrator/approval.py`, `orchestrator/resume.py`, `application/services.py`, `app.py`.
- Acceptance criteria: approval interrupt persists, UI/API approval resumes exact run.
- Tests: approve/reject/stale version/checksum.
- Dependencies: Issue 7.

### Issue 9: Plan amendment workflow

- Goal: Add user instruction -> proposal -> critique -> checksum approval.
- Scope: plan revisions, amendments, context pack integration.
- Out of scope: repair patches.
- Files likely touched: `application/context_builder.py`, `model_registry.py`, `services.py`, migrations, `app.py`.
- Acceptance criteria: user sees proposal before final approval; amendments immutable.
- Tests: revision chain, previous proposal included on revise.
- Dependencies: Issues 3, 4, 8.

### Issue 10: Repair context and GPT-5-mini proposal

- Goal: Convert failures into structured repair proposals.
- Scope: failure context, proposer call, proposal persistence.
- Out of scope: applying patch.
- Files likely touched: `repair_loop/**`, `copilot_repair/**`, `application/context_builder.py`, `contracts/schemas/**`.
- Acceptance criteria: failed command creates bounded repair proposal.
- Tests: failure classification, schema validation, no mutation.
- Dependencies: Issue 4.

### Issue 11: Mistral critique and backend policy gate

- Goal: Add reviewer critique and policy validation for plans/repairs.
- Scope: reviewer model call, critique persistence, policy gate.
- Out of scope: UI polish.
- Files likely touched: `application/model_registry.py`, `application/privileged_actions.py`, `contracts/schemas/**`.
- Acceptance criteria: unsafe proposals blocked before approval.
- Tests: critique fail/pass, policy fail/pass.
- Dependencies: Issues 9, 10.

### Issue 12: Exact patch approval/apply/validate/rollback

- Goal: Apply only exact approved repair patches in sandbox.
- Scope: patch artifacts, snapshots, apply, validation, rollback.
- Out of scope: arbitrary writes.
- Files likely touched: `repair_loop/patch_apply.py`, `repair_loop/patch_gate.py`, `repair_loop/validation_runner.py`, `application/privileged_actions.py`.
- Acceptance criteria: checksum approved equals checksum applied; rollback works.
- Tests: path escape, checksum mismatch, rollback.
- Dependencies: Issue 11.

### Issue 13: Approved Maven/shell/write action execution

- Goal: Execute approved typed actions only.
- Scope: Maven operations, optional shell diagnostics, write patch actions.
- Out of scope: unrestricted shell.
- Files likely touched: `infrastructure/tool_execution.py`, `worker_launcher.py`, `application/privileged_actions.py`.
- Acceptance criteria: approved actions execute only in stage sandbox/run root with selected JDK.
- Tests: unsafe shell rejection, Maven JDK, write scope.
- Dependencies: Issue 5.

### Issue 14: Migration Assistant chatbot

- Goal: Add assistant messages, streaming, tools, and pending action requests.
- Scope: assistant endpoints/UI panel/model calls/tool integration.
- Out of scope: direct execution.
- Files likely touched: `application/tools.py`, `application/context_builder.py`, `app.py`, `web/control-tower/app/jobs/[jobId]/**`.
- Acceptance criteria: assistant can explain and request pending actions but cannot approve/execute.
- Tests: tool filtering, pending action flow, SSE stream.
- Dependencies: Issues 4, 5.

### Issue 15: UI cockpit

- Goal: Build full job creation and cockpit UI.
- Scope: `/jobs/new`, `/jobs/[jobId]`, contracts, event views, approval cards.
- Out of scope: new backend behavior beyond contracts.
- Files likely touched: `web/control-tower/app/jobs/new/**`, `web/control-tower/app/jobs/[jobId]/**`, `web/control-tower/lib/**`.
- Acceptance criteria: user can create V1 job, view stages, approve plans/actions, inspect evidence.
- Tests: component/contract/e2e smoke tests.
- Dependencies: Issues 6, 8, 13, 14.

### Issue 16: Final proof/report

- Goal: Produce parent job proof and final report.
- Scope: proof gates, final reports, stage-chain summary.
- Out of scope: model as proof.
- Files likely touched: `final_report/**`, `application/services.py`, `contracts/schemas/**`.
- Acceptance criteria: final report contains deterministic proof and no secrets.
- Tests: redaction, proof source, three-stage report.
- Dependencies: Issues 6, 7, 12.

### Issue 17: Security/recovery/cancellation hardening

- Goal: Harden restart, cancellation, process-tree termination, and audit.
- Scope: worker leases, reconciliation, fail-closed states, process control.
- Out of scope: feature expansion.
- Files likely touched: `worker_launcher.py`, `application/services.py`, `sqlite/repositories.py`, `app.py`.
- Acceptance criteria: unclear worker state fails closed; cancellation terminates process tree; audit complete.
- Tests: restart recovery, timeout, cancellation, stale version.
- Dependencies: Issues 7, 13.

## 30. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Docs and catalogs conflict on `3.5.6` vs `3.5.14` | Wrong migration target | Normalize profiles/catalogs before real execution |
| Stage 2/3 source binding wrong | Mutates wrong source or skips prior output | Stage-chain ledger and tests |
| Global `JAVA_HOME=JAVA21_HOME` leaks into Stage 1/2 | Invalid builds | Per-stage env construction and tests |
| Model readiness flaky or unavailable | AI-required states block | Explicit READY/DEGRADED/BLOCKED and no silent fallback |
| LLM sees secrets through context | Credential leak | forbidden filters, redaction, context manifests |
| Privileged shell too broad | Remote/local code execution risk | disabled by default, templates only, approval required |
| Browser/model supplies command/model IDs | Policy bypass | backend-owned registries only |
| Patch checksum mismatch | Unapproved mutation | fail closed before apply |
| Windows process tree not fully killed | Orphaned Maven/OpenRewrite process | Job Objects plus restart reconciliation |
| Current diagnostic UI contracts conflict with V1 | UI/backend mismatch | contract freeze issue first |
| Existing Copilot code assumes CLI provider | Architecture drift | provider-neutral adapter and Azure implementation |
| Token costs too high | Slow/expensive AI steps | bounded context packs and budgets |

## 31. Open Questions

Human decisions required:

1. Confirm final pipeline ID name: `springboot-216-to-356-java21-three-stage`.
2. Confirm whether Stage 3 is always required or optional based on target proof.
3. Confirm exact Azure auth mode: API key vs Microsoft Entra ID.
4. Confirm exact Azure API version to use.
5. Confirm whether existing Copilot env names should remain as compatibility aliases.
6. Confirm model health check is mandatory before job creation or before first AI-required step.
7. Confirm whether Mistral critique is blocking for every plan/repair or can be deferred for first demo.
8. Confirm token budget defaults.
9. Confirm forbidden file patterns for context tools.
10. Confirm whether assistant chat can submit typed pending actions or only draft instructions.
11. Confirm whether sandbox shell is allowed at all in V1.
12. Confirm shell allowlist and forbidden commands.
13. Confirm whether Maven actions require approval every time or can be pre-approved as part of validation plan.
14. Confirm whether approved file writes must always be patches or can include full-file replacement for small files.
15. Confirm whether privileged action approval can be triggered from chat or only from dedicated approval cards.

## 32. Suggested First Implementation Slice

Suggested first slice:

```text
Plan/contracts freeze + profile normalization + stage-chain ledger skeleton
```

Why this first:

- It resolves the `3.5.6`/`3.5.14` and two-stage/three-stage contradictions before worker execution depends on them.
- It creates the immutable pipeline/stage contract that every later issue needs.
- It is testable without Azure access or real long-running migrations.
- It reduces risk before adding model calls, privileged actions, and UI complexity.

Files likely touched in first slice:

- `modernizer-solution-ai-hub/profiles/*.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/*.yaml`
- `modernizer-solution-ai-hub/schemas/*.json`
- `migration_factory/control_tower/schemas/pipeline_definition.py`
- `migration_factory/control_tower/schemas/runner_profile.py`
- `migration_factory/control_tower/schemas/run_configuration.py`
- `migration_factory/control_tower/domain/entities.py`
- `migration_factory/control_tower/domain/states.py`
- `migration_factory/control_tower/domain/transitions.py`
- `migration_factory/control_tower/application/commands.py`
- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/application/queries.py`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/*.sql`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `tests/control_tower/*`

Recommended next action:

Confirm the open decisions in Section 31, especially pipeline ID, Stage 3 requirement, Azure auth/API version, Mistral blocking policy, token budgets, and whether sandbox shell is allowed.

Do not implement until these decisions are confirmed.

Proposed first implementation branch name:

```text
amf/full-control-tower-v1-contracts-ledger
```
