# PRD — AI Migration Control Tower
**Version:** 0.1 — DRAFT  
**Status:** In Review  
**Owner:** ABDELILAH MORTAKI 


**Last Updated:** 2026-06-06  
**Reviewers:** ABDELILAH MORTAKI · HAMDAOUI Ali · ilyas abarbach

---

## 0. Document Map

| Section | What it answers |
|---|---|
| 1. Context | Why does this exist? |
| 2. Problem | What pain does it solve? |
| 3. Goal & Success | How do we know it works? |
| 4. Users | Who uses it and how? |
| 5. Scope | What is V1? What is not? |
| 6. Functional Requirements | What must it do? |
| 7. Non-Functional Requirements | How well must it do it? |
| 8. Architecture Constraints | What are the hard technical rules? |
| 9. Open Questions | What is still unresolved? |
| 10. Milestones | In what sequence will it be built? |
| 11. Appendix | Decisions, flows, states, entities, APIs, references |

---

## 1. Context

### 1.1 Product summary

**Product name:** AI Migration Control Tower  
**Type:** Internal developer tool — enterprise Java/Spring Boot migration governance platform  
**Primary user:** Developer / Migration Engineer  
**Current baseline:** AI Migration Factory V1 using LangGraph, OpenRewrite, Maven, dependency-policy checks, repair/fallback foundations, and a Textual TUI  
**Validated migration path:** Spring Boot 2.1.6 → 2.7 → 3.5 / Java 17  
**Validated proof level:** Build + test verified  
**Target operating model:** Local-first on a developer-managed Windows workstation

The existing migration factory is a capable migration engine with a limited operational layer. Developers currently launch and control migrations mainly through terminal commands and a Textual TUI. The system produces useful run artifacts, build/test results, dependency-policy reports, repair proposals, and final reports, but it does not yet provide a unified live web interface, durable event history, conversational interaction, governed plan amendments, or developer-approved AI repair execution.

The AI Migration Control Tower is the governance and operational layer over the existing engine. It does not replace OpenRewrite, Maven, LangGraph, or the current migration policies. It exposes them through a developer-first web experience with live visibility, approval gates, bounded AI assistance, evidence, and truthful proof reporting.

### 1.2 Current validated baseline

The validated real-application migration currently requires two migration stages:

```text
Stage 1
Spring Boot 2.1.6 → Spring Boot 2.7
Target Java: 11

Stage 2
Spring Boot 2.7 → Spring Boot 3.5
Target Java: 17
```

Current validated outcome:

```text
Legacy source preserved
Migration performed in sandbox workspace
Final Java version: 17
Final Spring Boot version: 3.5.14
Maven clean test: passed
Dependency risks: reported
Proof level: build_test_verified
```

The following are explicitly **not** currently proven:

```text
Runtime/H2 startup
Endpoint smoke tests
SQL Server integration
JWT/keystore/common-utils runtime configuration
Production readiness
```

### 1.3 Current implementation reality

| Capability | Current status |
|---|---|
| LangGraph migration orchestration | Implemented |
| Analysis, planning, assessment | Implemented |
| Human approval interrupt | Implemented, limited |
| OpenRewrite transformation | Implemented |
| Maven build/test validation | Implemented |
| Dependency-policy reporting | Implemented |
| Copilot/LLM repair proposal foundation | Implemented |
| Deterministic fallback repair plan | Implemented |
| Patch gate / rollback foundations | Implemented |
| Textual TUI | Implemented |
| True live OpenRewrite output | Partial |
| Governed plan amendment loop | Not implemented |
| Next.js dashboard | Not implemented |
| FastAPI control plane | Not implemented |
| Persistent Control Tower event store | Not implemented |
| Worker supervisor and heartbeat | Not implemented |
| Run-scoped chatbot | Not implemented |
| Context Builder / RAG | Not implemented |
| Developer-approved general AI repair path | Not implemented |
| Parent two-stage migration job | Not implemented |

---

## 2. Problem Statement

### 2.1 Core pains

| # | Pain | Current evidence |
|---|---|---|
| P1 | No unified live visibility during migration execution | Terminal/TUI-oriented workflow; several subprocesses still capture output until completion |
| P2 | No complete structured approval workflow | Existing approval supports approve/reject/replan states, but plan amendment and regeneration are not implemented |
| P3 | No AI assistant during a live run | Developers cannot ask grounded questions, request diagnosis, or approve AI repair proposals through one run-scoped interface |
| P4 | No durable, queryable operational history | Artifacts exist in run folders, but events, decisions, approvals, chat actions, and worker state are not unified in a Control Tower database |
| P5 | Incomplete proof governance | Build/test proof exists, but requested proof and achieved proof are not centrally modelled across all execution paths |
| P6 | Two-stage migrations are operated as separate runs | The successful 2.1.6 → 2.7 → 3.5 path is not yet represented as one parent migration job |
| P7 | AI repair is not fully governed end-to-end | Proposal and fallback foundations exist, but the developer cannot review, approve, apply, validate, and roll back a general AI patch from the UI |
| P8 | Configuration is terminal-centric | Java, Maven, AI Hub, paths, profiles, and policy flags are currently prepared through PowerShell environment variables |
| P9 | Run recovery is incomplete | No Control Tower worker lease, heartbeat, orphan detection, or API-startup reconciliation exists |
| P10 | Context sent to LLMs could become oversized or stale | No Context Builder currently creates bounded, task-specific evidence packs |

### 2.2 Root cause

The migration engine was developed before the operational product layer. The current solution is artifact-driven and terminal-driven rather than control-plane-driven.

### 2.3 Product opportunity

Create a web-based Control Tower where the migration engine remains deterministic-first, while the developer gains:

- live pipeline visibility;
- structured approvals;
- plan amendment and regeneration;
- one run-scoped Migration Assistant;
- governed diagnostic and validation tools;
- developer-approved sandbox repair;
- complete evidence and proof reporting.

---

## 3. Goals & Success Metrics

### 3.1 Primary goal

> A developer can configure, start, observe, interact with, approve, repair, validate, and complete a full two-stage Spring Boot migration from a web dashboard, with all actions, decisions, evidence, and proof levels recorded.

### 3.2 Product principles

1. **Deterministic first:** OpenRewrite and deterministic policies remain the primary migration mechanisms.
2. **AI assists, humans authorize:** AI may diagnose, propose, critique, and invoke controlled tools; it may not self-approve source changes.
3. **Evidence over claims:** Build, tests, policy checks, runtime checks, and endpoint checks determine achieved proof.
4. **One source of truth:** Dashboard, chatbot, worker, event stream, artifacts, and reports operate on the same run state.
5. **Local-first:** V1 runs on the developer’s Windows machine.
6. **One active migration:** V1 supports exactly one nonterminal migration job.
7. **Bounded context:** Models receive only task-relevant, retrieved evidence.
8. **Trace everything:** Every approval, patch, command, validation result, and proof decision is auditable.

### 3.3 Success metrics — V1

| Metric | Target |
|---|---|
| Developer can configure and start a migration from the web UI | Required |
| No terminal setup required for normal Control Tower operation after runner profile registration | Required |
| Live structured stage progress visible without page refresh | Required |
| Browser reconnect replays persisted events without losing run state | Required |
| Plan review, amendment, regeneration, critique, and final approval work end-to-end | Required |
| Migration Assistant accessible during the live run | Required |
| Failure diagnosis is grounded in registered evidence | Required |
| Repair proposal shows evidence, proposed diff, critique, and validation plan | Required |
| No AI-generated source change occurs without explicit developer approval | Required |
| Approved repair can be applied, validated, and rolled back | Required |
| Final proof report is generated and downloadable | Required |
| Parent job executes the supported two-stage migration path | Required |
| Backend prevents two nonterminal migrations | Required |
| False achieved-proof claims | 0 |
| Mean time to understand a supported build failure with the assistant | < 3 minutes |
| Structured event delivery latency on local setup | p95 < 1 second |
| Worker crash detection | Within one configured lease-expiry window |
| Invalid or unauthorized tool executions | 0 accepted |

### 3.4 Measurement notes

The `< 3 minutes` failure-understanding metric will be measured against an initial supported benchmark set:

- Tomcat 9 override under Spring Boot 3;
- old Zalando dependency;
- incomplete `javax` → `jakarta` migration;
- missing `caching.time-out`;
- invalid test-profile configuration;
- migration-profile mismatch requiring a two-stage path.

### 3.5 Out of scope for V1 success measurement

- role-specific manager, architect, or client dashboards;
- multiple simultaneous migrations;
- remote runner agents;
- production deployment;
- production-readiness proof;
- multi-user real-time collaboration;
- autonomous AI source modification.

---

## 4. Users

### 4.1 Primary user — Developer / Migration Engineer

**Context:** Runs the Control Tower on a local Windows workstation with access to the legacy source, Java, Maven, the migration repository, and Azure model endpoints.

**Primary goal:** Configure, execute, monitor, approve, repair, validate, and close a migration with confidence.

**Key jobs-to-be-done:**

- start a migration without recreating PowerShell environment setup;
- select a legacy source and migration pipeline safely;
- understand exactly which stage is running;
- review analysis and the generated plan;
- add instructions before transformation begins;
- approve, reject, or amend the plan;
- ask why a build, test, dependency-policy, or runtime stage failed;
- inspect the exact evidence and affected files;
- review a proposed patch and critique;
- approve or reject a sandbox change;
- run controlled build, test, and diagnostic operations;
- roll back a failed repair;
- understand target proof versus achieved proof;
- download and share the final report.

### 4.2 Secondary users — visibility only in V1

#### Team Lead / Architect

Needs to view:

- current run state;
- approved plan;
- risk findings;
- proposed and accepted repairs;
- validation evidence;
- achieved proof level.

The Team Lead / Architect does not receive a separate role-specific dashboard in V1.

#### Project Manager

Needs to view:

- migration status;
- stage completion;
- blockers;
- target versus achieved proof;
- final report availability.

The Project Manager does not operate the pipeline in V1.

### 4.3 Permissions — V1

V1 assumes a trusted local developer environment and one authenticated operator identity.

| Action | Developer | Visibility-only user |
|---|---:|---:|
| View run, events, logs, artifacts | Yes | Yes |
| Start migration | Yes | No |
| Amend plan | Yes | No |
| Approve/reject plan | Yes | No |
| Ask assistant questions | Yes | Optional read-only |
| Approve repair | Yes | No |
| Run validation tools | Yes | No |
| Cancel migration | Yes | No |
| Download final report | Yes | Yes |

Authentication and enterprise role integration are deferred unless required by the local deployment environment.

---

## 5. Scope

### 5.1 V1 — in scope

```text
Local-first Windows deployment
Next.js developer dashboard
FastAPI control plane
Separate Python migration worker process
Backend-powered allowlisted folder picker
Runner profiles and immutable run configuration
Exactly one nonterminal migration job
Parent two-stage migration job
Persistent job, event, artifact, approval, repair, and chat state
Live pipeline visualization using SSE
Replayable structured event history
Live Maven/OpenRewrite/test logs
Plan review, amendment, regeneration, critique, and final approval
One run-scoped Migration Assistant beside the dashboard
Bounded Context Builder
Typed diagnostic and validation tools
GPT-5-mini primary worker model
Mistral-Large-3 primary reviewer/critique model
Disabled Llama-3.3-70B-Instruct fallback reviewer
Developer-approved AI patch workflow
Change-aware validation
Repair rollback
Build/test/dependency-policy proof
Optional runtime and endpoint gates controlled by policy
Target-versus-achieved proof reporting
Downloadable final proof report
SQLite persistence
Per-run LangGraph checkpoint persistence
Textual TUI retained as a fallback client
```

### 5.2 V1 — explicitly out of scope

```text
Multiple concurrent or paused nonterminal migrations
Remote or distributed runner agents
Cloud/SaaS deployment
Production deployment
Git push or artifact publication automation
Automatic AI source modification without developer confirmation
Unrestricted shell, PowerShell, or arbitrary Maven execution
Use of DeepSeek models
Use of Qwen models
Use of gpt-oss-20b
Manager/architect/client-specific dashboard variants
Real-time multi-user collaboration
Production-readiness certification
Untrusted public repository execution
Full machine-level security sandboxing
```

### 5.3 Trust boundary

V1 is designed for trusted internal source repositories.

The migration workspace protects the legacy source from direct modification, but it is not a complete machine-security sandbox. Maven plugins, tests, OpenRewrite, and Java processes still execute with the worker account’s operating-system permissions.

Future hardening may include:

- dedicated low-privilege Windows account;
- dedicated virtual machine;
- containerized or isolated build worker;
- restricted network access;
- controlled Maven repository mirror.

---

## 6. Functional Requirements

Priority definitions:

- **P0:** Required for V1 acceptance.
- **P1:** Required for a complete V1 experience but may follow the first usable vertical slice.
- **P2:** Desirable enhancement.

### 6.1 Migration Configuration

| ID | Requirement | Priority |
|---|---|---|
| F-CFG-01 | Developer selects the legacy source via a backend-powered folder picker limited to allowlisted roots | P0 |
| F-CFG-02 | Developer selects the output root, runner profile, and migration pipeline | P0 |
| F-CFG-03 | Developer configures typed policy settings, including LLM usage, runtime gate, endpoint gate, dependency fixes, and target proof | P0 |
| F-CFG-04 | System validates that source and output paths differ and that output is not inside the legacy source | P0 |
| F-CFG-05 | System detects traversal, symlink, and junction escapes outside allowlisted roots | P0 |
| F-CFG-06 | System generates immutable `control/run_configuration.json` before the worker starts | P0 |
| F-CFG-07 | Secrets and model credentials remain server-side and are never returned to the frontend or written to normal run artifacts | P0 |
| F-CFG-08 | `PYTHONPATH=.` is not exposed as a user setting; the backend runs from an installed project environment | P1 |
| F-CFG-09 | Runner profile health check validates Python, Java, Maven, AI Hub, and model endpoint availability | P0 |
| F-CFG-10 | Unsupported or unavailable pipeline profiles block run creation with a clear explanation | P0 |

#### Runner profile fields

```yaml
id: local-windows-java21
name: Windows Local — Java 21 / Maven 3.9
python_executable: ...
java_home: ...
maven_cmd: ...
ai_hub_path: ...
allowed_source_roots: [...]
allowed_output_roots: [...]
```

#### Migration request fields

```yaml
legacy_source_path: ...
output_root: ...
runner_profile_id: local-windows-java21
pipeline_id: springboot-216-to-35-java17
mode: full_sandbox_migration
policy:
  llm_enabled: true
  auto_apply_repairs: false
  h2_startup_required: false
  endpoint_smoke_required: false
  apply_dependency_policy_fixes: false
  target_proof_level: build_test_verified
```

---

### 6.2 Job Lifecycle & Concurrency

| ID | Requirement | Priority |
|---|---|---|
| F-JOB-01 | Exactly one nonterminal migration job may exist at a time | P0 |
| F-JOB-02 | Backend and database enforce the single-job rule transactionally | P0 |
| F-JOB-03 | Starting a second job while one is nonterminal returns a conflict response | P0 |
| F-JOB-04 | `PAUSED_FOR_PLAN_APPROVAL` and `PAUSED_FOR_REPAIR` remain nonterminal and block another job | P0 |
| F-JOB-05 | Worker PID, start time, heartbeat, exit code, and lease state are persisted | P0 |
| F-JOB-06 | A stale worker lease moves the job to `ORPHANED` | P0 |
| F-JOB-07 | API startup reconciles nonterminal jobs with real worker state | P0 |
| F-JOB-08 | Developer can request cancellation from the UI | P0 |
| F-JOB-09 | Cancellation terminates the complete worker command process tree, including Maven/Java child processes | P0 |
| F-JOB-10 | The supported two-stage migration is represented as one parent job with ordered child stage runs | P0 |
| F-JOB-11 | Stage 2 receives the validated Stage 1 sandbox as its source | P0 |
| F-JOB-12 | Stage 2 cannot start unless Stage 1 satisfies its configured continuation policy | P0 |
| F-JOB-13 | Completed, failed, rejected, and cancelled jobs remain queryable as history | P0 |

#### Job state model

```text
CREATED
  ↓
QUEUED
  ↓
STARTING
  ↓
RUNNING
  ├── PAUSED_FOR_PLAN_APPROVAL
  ├── PAUSED_FOR_REPAIR
  ├── RESUMING
  ├── CANCELLING
  ├── ORPHANED
  ├── COMPLETED
  ├── FAILED
  ├── REJECTED
  └── CANCELLED
```

---

### 6.3 Live Pipeline Visualization

| ID | Requirement | Priority |
|---|---|---|
| F-VIS-01 | Dashboard displays the current parent job, stage run, graph node, status, elapsed time, and proof status | P0 |
| F-VIS-02 | Structured events, not raw log matching, drive stage state | P0 |
| F-VIS-03 | Worker emits events before and after each material graph node and command | P0 |
| F-VIS-04 | FastAPI streams persisted events to the browser through SSE | P0 |
| F-VIS-05 | SSE events include stable event IDs for replay and reconnection | P0 |
| F-VIS-06 | Browser refresh or temporary disconnect replays missing events from the event store | P0 |
| F-VIS-07 | Maven stdout/stderr, OpenRewrite output, tests, and runtime logs are viewable in the dashboard | P0 |
| F-VIS-08 | Raw logs are stored as files; the database stores metadata and references | P0 |
| F-VIS-09 | Developer can filter logs by stage, command, channel, severity, and time | P1 |
| F-VIS-10 | Disabled gates appear as `SKIPPED_BY_POLICY`, not as passed | P0 |
| F-VIS-11 | The final report stage is visible even when the run finishes with warnings or failure | P0 |

#### Target visible graph

```text
prepare_sandbox
↓
openrewrite_preview
↓
openrewrite_apply
↓
capture_diff
↓
review_diff_risk
↓
maven_build
↓
unit_tests
↓
dependency_policy
↓
repair_decision
↓
runtime_smoke
↓
endpoint_smoke
↓
final_report
```

Runtime and endpoint nodes may be skipped by policy. A skipped gate cannot contribute to achieved proof.

---

### 6.4 Plan Review & Amendment

| ID | Requirement | Priority |
|---|---|---|
| F-PLN-01 | Migration pauses after analysis and initial planning | P0 |
| F-PLN-02 | Dashboard displays source analysis, target profile, migration units, risks, allowed actions, forbidden actions, and validation plan | P0 |
| F-PLN-03 | Developer can approve, reject, or submit amendment instructions | P0 |
| F-PLN-04 | Amendment instructions are persisted as an immutable artifact | P0 |
| F-PLN-05 | Amendment triggers plan regeneration rather than direct transformation changes | P0 |
| F-PLN-06 | Mistral-Large-3 critiques the regenerated plan without approval authority | P0 |
| F-PLN-07 | Backend deterministic policy validates the regenerated plan | P0 |
| F-PLN-08 | Developer performs final approval before transformation starts | P0 |
| F-PLN-09 | Every plan version, critique, amendment, and decision remains queryable | P0 |
| F-PLN-10 | Rejection terminates the run with a recorded reason | P0 |

#### Required artifacts

```text
planning/plan_revision_001.yaml
planning/developer_amendment_001.json
planning/plan_revision_002.yaml
planning/reviewer_critique_002.json
planning/policy_validation_002.json
planning/final_approved_plan.yaml
planning/plan_revision_history.json
```

---

### 6.5 AI Migration Assistant

| ID | Requirement | Priority |
|---|---|---|
| F-AST-01 | One Migration Assistant panel is visible beside the live pipeline | P0 |
| F-AST-02 | Each parent migration job has one run-scoped assistant conversation | P0 |
| F-AST-03 | Assistant reads only state and artifacts registered to the selected job, except approved shared RAG sources | P0 |
| F-AST-04 | Assistant can explain current stage, status, risks, blockers, plans, diffs, and proof | P0 |
| F-AST-05 | Assistant cites registered evidence references in operational answers | P0 |
| F-AST-06 | Assistant can navigate the developer to plans, logs, diffs, reviewer findings, and reports | P1 |
| F-AST-07 | Assistant invokes only typed backend tools | P0 |
| F-AST-08 | No generic `execute_shell`, `execute_powershell`, or free-form Maven-goals tool exists | P0 |
| F-AST-09 | Tool authorization checks run ID, current state, user permission, working directory, operation type, timeout, and retry limit | P0 |
| F-AST-10 | All model calls, tool proposals, tool executions, and results are auditable | P0 |
| F-AST-11 | Assistant may answer that evidence is insufficient and request human escalation | P0 |
| F-AST-12 | Assistant chat streaming is independent from migration SSE events | P1 |

#### Allowed assistant capabilities

```text
Explain status
Summarize a stage
Explain a failure
Inspect registered logs and reports
Inspect sandbox files within policy
Inspect stored diffs
Retrieve RAG evidence
Draft a plan amendment
Propose a repair
Propose a validation plan
Invoke approved diagnostic tools
Invoke approved validation tools
Prepare a confirmation card
```

#### Prohibited assistant capabilities

```text
Modify the legacy source
Escape the run workspace
Run unrestricted shell or PowerShell
Select arbitrary Maven goals/plugins/properties
Install software
Change machine-wide Java or Maven
Access secrets
Deploy
Push or publish code
Self-approve a modification
Mark proof as achieved without validation evidence
```

---

### 6.6 Context Builder & RAG

| ID | Requirement | Priority |
|---|---|---|
| F-CTX-01 | Every model call receives a bounded task-specific context pack | P0 |
| F-CTX-02 | Context pack includes system policy, run snapshot, current stage/failure summary, approved plan, developer constraints, retrieved evidence, compact chat summary, and recent messages | P0 |
| F-CTX-03 | Entire repositories, full logs, all previous runs, and full chat history are not injected by default | P0 |
| F-CTX-04 | Large logs are retrieved by relevant window or reference | P0 |
| F-CTX-05 | Source code is retrieved at semantic boundaries such as class, method, POM section, or configuration block | P1 |
| F-CTX-06 | Older conversation history is summarized while recent messages remain verbatim | P1 |
| F-CTX-07 | Retrieved repository content is treated as untrusted evidence, never as system instruction | P0 |
| F-CTX-08 | Shared RAG sources are versioned and identify their origin | P1 |
| F-CTX-09 | RAG retrieval records query, selected chunks, scores, and source IDs | P1 |
| F-CTX-10 | Embedding model is configurable through the backend model registry | P1 |

#### Shared RAG sources

```text
AI Hub profiles
Migration policies
OpenRewrite recipes
Company architecture and coding standards
Approved previous migration cases
Approved previous repairs
Known failure patterns
Official Spring, Maven, OpenRewrite, and platform documentation
```

#### Run-specific sources

```text
Current events
Analysis report
Current and previous plans
Developer constraints
OpenRewrite results
Diffs
Build/test reports
Dependency-policy reports
Runtime/endpoint results
Repair attempts
Final proof state
```

---

### 6.7 Typed Diagnostic & Validation Tools

| ID | Requirement | Priority |
|---|---|---|
| F-TOL-01 | Backend exposes named typed operations rather than arbitrary commands | P0 |
| F-TOL-02 | Backend owns executable path, working directory, goals, flags, timeout, and environment | P0 |
| F-TOL-03 | Standard output and error are drained concurrently and streamed live | P0 |
| F-TOL-04 | Every command has a stable command ID and registered log artifacts | P0 |
| F-TOL-05 | Commands run only inside the approved sandbox workspace | P0 |
| F-TOL-06 | Repository-local Maven Wrapper is disabled by default unless separately trusted and validated | P1 |
| F-TOL-07 | Validation operation results include exit code, duration, timeout, cancellation state, and evidence references | P0 |

#### Initial typed tool catalog

```text
get_run_status
get_current_stage
get_pending_approval
search_run_artifacts
read_log_window
read_sandbox_file
show_file_diff
list_changed_files
search_shared_migration_knowledge
find_similar_failure

inspect_dependency_tree
inspect_effective_pom
run_openrewrite_preview
run_compile
run_targeted_test
run_full_unit_tests
run_dependency_policy
run_runtime_smoke
run_endpoint_smoke

draft_plan_amendment
submit_confirmed_plan_amendment
draft_repair
submit_confirmed_repair
request_resume
request_cancellation
request_rollback
```

#### Execution categories

| Category | Examples | Confirmation rule |
|---|---|---|
| Artifact inspection | read logs, reports, diffs | No additional confirmation |
| Controlled diagnostics | dependency tree, effective POM, OpenRewrite preview | Allowed if requested or in approved plan |
| Validation execution | compile, tests, runtime smoke | Allowed if requested or part of approved validation plan |
| Source-changing operation | apply patch, write-mode OpenRewrite, rollback | Explicit developer confirmation required |
| External/machine-impacting | deploy, publish, install, machine config | Blocked in V1 |

---

### 6.8 LLM Worker and Reviewer

| ID | Requirement | Priority |
|---|---|---|
| F-LLM-01 | GPT-5-mini is the primary worker model | P0 |
| F-LLM-02 | Mistral-Large-3 is the primary reviewer/critique model | P0 |
| F-LLM-03 | Llama-3.3-70B-Instruct remains configured as a disabled fallback reviewer | P1 |
| F-LLM-04 | gpt-oss-20b is not used or considered unless explicitly reintroduced by team decision | P0 |
| F-LLM-05 | DeepSeek and Qwen models are prohibited by company policy | P0 |
| F-LLM-06 | The worker creates diagnosis, proposal, patch, tool plan, and validation plan | P0 |
| F-LLM-07 | The reviewer receives original evidence, constraints, proposal, and diff—not only the worker explanation | P0 |
| F-LLM-08 | The reviewer has no execution tools and no approval authority | P0 |
| F-LLM-09 | Backend validates model output against a typed schema | P0 |
| F-LLM-10 | Unsupported schema capability on a provider is handled by backend validation and retry/failure policy | P0 |
| F-LLM-11 | Model deployment IDs are backend-controlled and cannot be supplied arbitrarily by the frontend | P0 |
| F-LLM-12 | Model usage, latency, token counts, and estimated cost are recorded by run and task | P1 |

#### Model configuration

```yaml
primary_worker:
  provider: azure
  model: gpt-5-mini
  roles:
    - developer_chat
    - failure_diagnosis
    - tool_selection
    - repair_proposal
    - plan_amendment
    - validation_plan

primary_reviewer:
  provider: azure
  model: Mistral-Large-3
  roles:
    - critique_patch
    - detect_unrelated_changes
    - verify_constraints
    - review_validation_plan
  tools: none

fallback_reviewer:
  provider: azure
  model: Llama-3.3-70B-Instruct
  enabled: false
  tools: none
```

#### Decision authority

```text
GPT-5-mini
    proposes

Mistral-Large-3
    critiques

Backend policy gate
    authorizes scope and operation

Developer
    approves or rejects source changes

Build/tests/policy/runtime evidence
    determines technical result
```

---

### 6.9 Repair Workflow

| ID | Requirement | Priority |
|---|---|---|
| F-RPR-01 | Supported failures move the migration to `PAUSED_FOR_REPAIR` | P0 |
| F-RPR-02 | Context Builder creates a bounded failure evidence package | P0 |
| F-RPR-03 | GPT-5-mini produces a structured diagnosis and repair proposal | P0 |
| F-RPR-04 | Mistral-Large-3 critiques the proposal against original evidence and constraints | P0 |
| F-RPR-05 | Backend validates path scope, file types, policy rules, allowed operation, and validation plan | P0 |
| F-RPR-06 | Chatbot shows root cause, evidence, proposed diff, critique, risk, and validation plan | P0 |
| F-RPR-07 | Developer can approve, edit instructions, or reject | P0 |
| F-RPR-08 | No file is modified before explicit developer confirmation | P0 |
| F-RPR-09 | Approved patch applies only to the sandbox | P0 |
| F-RPR-10 | Snapshot is captured before patch application | P0 |
| F-RPR-11 | Validation is selected based on changed file type and risk | P0 |
| F-RPR-12 | Failed validation offers rollback and another repair attempt or human escalation | P0 |
| F-RPR-13 | Rollback result is validated and recorded | P0 |
| F-RPR-14 | Maximum repair attempts and premium/model retry limits are configurable | P1 |
| F-RPR-15 | Assistant may conclude `INSUFFICIENT_EVIDENCE` | P0 |

#### Repair lifecycle

```text
Detect failure
↓
Classify failure
↓
Collect evidence
↓
Retrieve relevant knowledge
↓
Generate repair proposal
↓
Critique proposal
↓
Validate proposal against backend policy
↓
Present evidence + diff + validation plan
↓
Developer approves / edits / rejects
↓
Snapshot sandbox
↓
Apply approved patch
↓
Run change-aware validation
↓
Accept and continue OR roll back and escalate
```

#### Required repair artifacts

```text
repairs/{repair_id}/failure_context.json
repairs/{repair_id}/retrieved_evidence.json
repairs/{repair_id}/worker_proposal.json
repairs/{repair_id}/proposed.patch
repairs/{repair_id}/reviewer_critique.json
repairs/{repair_id}/policy_validation.json
repairs/{repair_id}/developer_decision.json
repairs/{repair_id}/application_result.json
repairs/{repair_id}/validation_result.json
repairs/{repair_id}/rollback_result.json
```

#### Initial supported repair cases

```text
POM dependency resolution failure
Explicit version conflict with Spring Boot BOM
Compilation failure after OpenRewrite
Incomplete javax → jakarta migration
Removed or changed Spring API
Failing unit tests
Invalid profile or configuration
Missing runtime property
Dependency-policy warning despite passing build
Unexpected or overly broad OpenRewrite diff
Wrong migration profile
Insufficient evidence requiring escalation
```

---

### 6.10 Change-Aware Validation

| ID | Requirement | Priority |
|---|---|---|
| F-VAL-01 | Validation planner selects checks based on changed files and repair type | P0 |
| F-VAL-02 | Validation plan is shown before source-changing repair approval | P0 |
| F-VAL-03 | Validation plan is immutable once the developer approves `Apply and validate` | P0 |
| F-VAL-04 | Additional validation may be added after failure but not silently removed | P0 |
| F-VAL-05 | Validation results update achieved proof only through deterministic rules | P0 |

#### Initial mapping

| Change type | Required validation |
|---|---|
| `pom.xml` / dependency change | Compile + full unit tests + dependency policy |
| Java production source | Compile + targeted tests where available + full unit tests |
| Test-only source | Targeted test + full unit tests |
| Configuration | Build/test + relevant runtime gate when enabled |
| OpenRewrite write execution | Diff risk review + build + tests + dependency policy |
| Runtime-only smoke configuration | Build/test unchanged + runtime smoke |

---

### 6.11 Proof & Reporting

| ID | Requirement | Priority |
|---|---|---|
| F-PRF-01 | Developer selects a target proof level | P0 |
| F-PRF-02 | System calculates achieved proof from completed gates | P0 |
| F-PRF-03 | Target proof and achieved proof are stored separately | P0 |
| F-PRF-04 | Disabled or unexecuted gates cannot count as passed | P0 |
| F-PRF-05 | Final report lists passed, warned, failed, skipped, and missing gates | P0 |
| F-PRF-06 | Final report includes plan history, approvals, transformation summary, repair history, dependency risks, and artifact references | P0 |
| F-PRF-07 | `final/report_context.json` is generated for every terminal run state | P0 |
| F-PRF-08 | Final report is downloadable as Markdown and JSON | P0 |
| F-PRF-09 | Report generation runs even when migration finishes with warnings or failure | P0 |
| F-PRF-10 | Assistant cannot claim an achieved proof level not present in deterministic run state | P0 |

#### Proof hierarchy

```text
analyzed
planned
transformed
build_test_verified
runtime_verified
endpoint_verified
production_ready   # explicitly out of scope for V1
```

#### Example

```json
{
  "target_proof_level": "runtime_verified",
  "achieved_proof_level": "build_test_verified",
  "target_reached": false,
  "missing_gates": [
    "runtime_startup"
  ]
}
```

---

### 6.12 History & Audit

| ID | Requirement | Priority |
|---|---|---|
| F-AUD-01 | Every state transition has timestamp, actor, previous state, new state, and reason | P0 |
| F-AUD-02 | Every plan approval, rejection, amendment, and repair decision records the developer identity | P0 |
| F-AUD-03 | Every model call records provider, deployment, role, token counts, latency, and result status | P1 |
| F-AUD-04 | Every tool execution records requested operation, validated arguments, command ID, result, and evidence refs | P0 |
| F-AUD-05 | Audit records are append-only through normal application APIs | P0 |
| F-AUD-06 | Completed runs remain viewable without restarting the worker | P0 |
| F-AUD-07 | TUI and web dashboard read the same run and audit data | P1 |

---

## 7. Non-Functional Requirements

### 7.1 Performance

| ID | Requirement |
|---|---|
| NFR-PERF-01 | Structured SSE events delivered to the local browser with p95 latency under 1 second after persistence |
| NFR-PERF-02 | Dashboard initial run page loads latest persisted run state within 2 seconds on the local environment |
| NFR-PERF-03 | Log viewer supports incremental loading and does not load complete large logs into browser memory |
| NFR-PERF-04 | Assistant response streaming begins within 5 seconds for normal Azure availability, excluding model queueing incidents |
| NFR-PERF-05 | Model context pack remains within configured per-task token budget |

### 7.2 Reliability

| ID | Requirement |
|---|---|
| NFR-REL-01 | Worker crash is detected within one lease-expiry window |
| NFR-REL-02 | API restart does not lose persisted job, event, approval, artifact, chat, or repair state |
| NFR-REL-03 | Browser reconnect recovers missing events using stable event sequence IDs |
| NFR-REL-04 | A failed report-generation path cannot erase prior run evidence |
| NFR-REL-05 | Worker process and child process exit codes are recorded |
| NFR-REL-06 | Source-changing repair failure triggers rollback or explicit unresolved state |

### 7.3 Security

| ID | Requirement |
|---|---|
| NFR-SEC-01 | No arbitrary path traversal, symlink escape, or junction escape |
| NFR-SEC-02 | Legacy source is never modified |
| NFR-SEC-03 | Secrets never reach the frontend or normal artifacts |
| NFR-SEC-04 | No unrestricted terminal tool is exposed to models |
| NFR-SEC-05 | Backend validates every model-generated tool call |
| NFR-SEC-06 | Retrieved repository content is treated as untrusted data |
| NFR-SEC-07 | Source-changing actions require explicit developer confirmation |
| NFR-SEC-08 | Artifact access uses registered IDs, not arbitrary paths |
| NFR-SEC-09 | Worker uses a controlled environment rather than blindly inheriting all API-process variables |
| NFR-SEC-10 | V1 is limited to trusted internal repositories |

### 7.4 Persistence

| ID | Requirement |
|---|---|
| NFR-PST-01 | Control Tower operational data persists in SQLite |
| NFR-PST-02 | LangGraph execution state persists in a per-run checkpoint database |
| NFR-PST-03 | Large raw logs are append-only files referenced by artifact metadata |
| NFR-PST-04 | SQLite foreign keys are enabled |
| NFR-PST-05 | SQLite busy timeout is configured |
| NFR-PST-06 | WAL mode is evaluated and enabled where compatible with the local filesystem and backup strategy |
| NFR-PST-07 | Database migrations are versioned |

### 7.5 Recoverability

| ID | Requirement |
|---|---|
| NFR-REC-01 | API startup reconciles stored nonterminal state with worker PID and heartbeat |
| NFR-REC-02 | Paused approval states survive API and browser restart |
| NFR-REC-03 | Orphaned jobs expose recovery guidance and do not silently resume |
| NFR-REC-04 | Repair snapshot and rollback evidence survive process restart |
| NFR-REC-05 | Event stream can replay from a supplied last event ID |

### 7.6 Auditability

| ID | Requirement |
|---|---|
| NFR-AUD-01 | All decisions and state-changing actions are timestamped and attributed |
| NFR-AUD-02 | Approved patch exactly matches the patch applied |
| NFR-AUD-03 | Approved validation plan exactly matches operations executed unless an additional developer-approved action is recorded |
| NFR-AUD-04 | Final report references source artifacts by ID |
| NFR-AUD-05 | Model critique is labelled advisory and never represented as proof |

### 7.7 Compatibility

| ID | Requirement |
|---|---|
| NFR-CMP-01 | Windows 10/11 local execution |
| NFR-CMP-02 | JDK 21 worker environment supporting Java 17 migration target |
| NFR-CMP-03 | Maven 3.9.x |
| NFR-CMP-04 | Existing AI Hub profiles remain supported |
| NFR-CMP-05 | Existing CLI and TUI remain functional during migration to the control-plane architecture |
| NFR-CMP-06 | Azure model deployment identifiers are configurable without changing migration logic |

### 7.8 Maintainability

| ID | Requirement |
|---|---|
| NFR-MNT-01 | Frontend, control plane, worker, migration engine, model providers, and persistence remain separate modules |
| NFR-MNT-02 | Typed request/response schemas are shared or generated where practical |
| NFR-MNT-03 | Provider-specific model code is behind an adapter |
| NFR-MNT-04 | Commands use one shared execution abstraction |
| NFR-MNT-05 | New graph stages can emit events without frontend-specific code |
| NFR-MNT-06 | Model prompts, schemas, policies, and evaluation cases are version-controlled |

### 7.9 Cost control

| ID | Requirement |
|---|---|
| NFR-CST-01 | Every model call records token usage and estimated cost |
| NFR-CST-02 | Per-run maximum model calls, repair attempts, and token budget are configurable |
| NFR-CST-03 | Reviewer is invoked only for plan revisions and source-changing repair proposals |
| NFR-CST-04 | Deterministic parsing, diffing, classification rules, and validation are preferred over LLM calls |
| NFR-CST-05 | Full repository and full log prompts are prohibited by default |
| NFR-CST-06 | Azure spending alerts are configured outside the application for the development subscription |

---

## 8. Architecture Constraints (Non-negotiable)

```text
Frontend:
    Next.js App Router
    UI plus optional thin BFF/proxy only
    No migration execution

Control Plane:
    FastAPI
    HTTP commands, typed APIs, SSE, authorization, persistence access
    Does not execute full migrations inside request handlers

Worker:
    Separate Python process
    One active worker in V1
    Process isolation is operational isolation, not a full security sandbox

Orchestration:
    LangGraph
    Persisted checkpoints
    Human interrupts for plan and repair approval

Transformation:
    OpenRewrite
    Deterministic-first
    LLM repair only where deterministic transformation or validation is insufficient

Build and validation:
    Maven
    Unit tests
    Dependency policy
    Optional runtime and endpoint gates

Live transport:
    Server-Sent Events
    Events replayed from persistent event store
    Raw logs referenced as artifacts

Persistence:
    Control Tower SQLite database
    Per-run LangGraph checkpoint database
    Append-only log and artifact files

Concurrency:
    Exactly one nonterminal migration job

Primary worker model:
    GPT-5-mini via Azure

Primary reviewer:
    Mistral-Large-3 via Azure

Fallback reviewer:
    Llama-3.3-70B-Instruct
    Disabled

Prohibited models:
    DeepSeek
    Qwen
    gpt-oss-20b unless explicitly reintroduced

Modification authority:
    AI proposes
    Backend validates
    Developer approves
    Worker applies
    Deterministic validation decides outcome

Command authority:
    Typed backend tools only
    No unrestricted shell
    No arbitrary Maven goal list
```

### 8.1 Target component architecture

```text
┌──────────────────────────────────────────────────────────┐
│ Next.js Control Tower                                    │
│                                                          │
│ Configuration | Pipeline | Logs | Plans | Diffs | Chat   │
└───────────────────────────┬──────────────────────────────┘
                            │ HTTP + SSE
                            ▼
┌──────────────────────────────────────────────────────────┐
│ FastAPI Control Plane                                    │
│                                                          │
│ Jobs | Events | Artifacts | Approvals | Chat | Repairs   │
│ Single-job lock | Worker supervisor | Tool authorization │
└───────────────────────────┬──────────────────────────────┘
                            │ launches / supervises
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Migration Worker                                         │
│                                                          │
│ LangGraph | OpenRewrite | Maven | Tests | Policy | LLM   │
└───────────────────────────┬──────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│ Persistence                                              │
│                                                          │
│ Control Tower DB | Checkpoints | Logs | Artifacts        │
└──────────────────────────────────────────────────────────┘
```

### 8.2 Frontend rendering rules

- Server Components load initial run data, report metadata, and non-interactive views.
- Client Components handle SSE, chat streaming, stateful controls, approvals, and interactive diff/log viewers.
- Frontend never receives Azure credentials, Java/Maven environment secrets, or unrestricted filesystem access.

### 8.3 Worker execution rules

- Worker loads immutable run configuration.
- Worker constructs a controlled child-process environment.
- Worker emits structured events before and after material operations.
- Worker drains stdout and stderr concurrently.
- Worker supports timeout, cancellation, and process-tree termination.
- Worker registers every artifact before exposing it to the UI.
- Worker cannot modify the legacy source path.

---

## 9. Open Questions

| # | Question | Owner | Due |
|---|---|---|---|
| OQ-01 | Finalize RAG embedding model; current candidate is `text-embedding-3-small` | [Owner] | Before M14 |
| OQ-02 | Store runner profiles in versioned YAML, database, or both? | [Owner] | Before M1 |
| OQ-03 | Final heartbeat interval, lease expiry, and orphan threshold | [Owner] | Before M3 |
| OQ-04 | Which Windows source and output roots are allowlisted for V1? | [Owner] | Before M6 |
| OQ-05 | Confirm Azure deployment availability and quota for Mistral-Large-3 | [Owner] | Before M11 |
| OQ-06 | Confirm GPT-5-mini Azure API surface and structured-output configuration used by the worker adapter | [Owner] | Before M10 |
| OQ-07 | Should the Llama fallback remain configuration-only or be deployed but disabled? | [Owner] | Before M11 |
| OQ-08 | Which identity mechanism is required for local V1: local user, company SSO, or no authentication on loopback only? | [Owner] | Before M6 |
| OQ-09 | Exact continuation policy between Stage 1 and Stage 2 | [Owner] | Before M5 |
| OQ-10 | Which runtime and endpoint smoke implementations are supported in V1 versus shown as future/skipped stages? | [Owner] | Before M5 |
| OQ-11 | Should OpenRewrite preview be mandatory before every write execution or only for repair-triggered executions? | [Owner] | Before M5 |
| OQ-12 | Maximum repair attempts and per-run Azure token/cost budget | [Owner] | Before M10 |
| OQ-13 | Which Maven Wrapper trust policy applies to internal repositories? | [Owner] | Before M4 |
| OQ-14 | Which artifact retention and cleanup policy applies to completed local runs? | [Owner] | Before M2 |
| OQ-15 | Is SQLite WAL acceptable on the selected Windows filesystem and backup workflow? | [Owner] | Before M2 |
| OQ-16 | Final supported proof-level hierarchy and whether `transformed` is externally displayed | [Owner] | Before M13 |
| OQ-17 | Should a read-only visibility user be included in V1 authentication or deferred entirely? | [Owner] | Before M7 |
| OQ-18 | Which company standards and official documentation are approved for RAG ingestion? | [Owner] | Before M14 |

---

## 10. Milestones (Build Sequence)

The sequence is dependency-driven. Calendar dates will be assigned after sizing.

| # | Deliverable | Exit criteria | Depends on |
|---|---|---|---|
| M1 | Typed RunConfiguration + runner profiles | Validated immutable run configuration; runner health check | — |
| M2 | Control Tower SQLite DB | Jobs, runs, stages, events, locks, artifacts, approvals; schema migrations | M1 |
| M3 | Worker supervisor | PID, heartbeat, lease, crash detection, cancellation, startup reconciliation | M2 |
| M4 | Shared live command executor | Concurrent stdout/stderr, timeout, cancellation, artifact logs | M3 |
| M5 | Split LangGraph into visible stages + parent two-stage job | Durable stage boundaries; Stage 1 → Stage 2 handoff | M4 |
| M6 | FastAPI control plane + SSE | Typed job APIs; persistent replayable event stream | M5 |
| M7 | Next.js live dashboard | Configure run, see state, stages, logs, artifacts, and proof | M6 |
| M8 | Plan review and amendment | Amend → regenerate → critique → final developer approval | M7 |
| M9 | Read-only Migration Assistant | Run-scoped chat; grounded explanations; artifact navigation | M8 |
| M10 | GPT-5-mini worker integration | Typed diagnosis, tool selection, plan/repair proposals | M9 |
| M11 | Mistral-Large-3 critique integration | Isolated critique schema; no tools; no approval authority | M10 |
| M12 | Developer-approved repair application | Show diff; approve; snapshot; apply; audit | M11 |
| M13 | Change-aware validation, rollback, proof report | Validation mapping; rollback; target/achieved proof; final report | M12 |
| M14 | RAG and context summarization | Bounded Context Builder; approved shared knowledge; retrieval audit | M13 |
| M15 | Migration-specific LLM evaluations | Benchmark suite, quality/cost metrics, release thresholds | M14 |
| M16 | TUI migration to shared control plane | TUI reads same jobs/events and invokes same APIs/services | M6 |

> **Constraint:** Frontend styling and polish must not become the critical path before M6. The first frontend goal is an operational vertical slice over stable worker, event, and API foundations.

### 10.1 Suggested vertical slices

#### Slice A — Live deterministic migration

```text
Run configuration
→ worker
→ events
→ FastAPI
→ minimal Next.js pipeline
```

No chatbot and no AI repair yet.

#### Slice B — Governed planning

```text
Analysis
→ plan
→ developer amendment
→ regeneration
→ critique
→ approval
```

#### Slice C — Read-only assistant

```text
Chat
→ Context Builder
→ run evidence
→ explanations and navigation
```

#### Slice D — Governed repair

```text
Failure
→ worker proposal
→ reviewer critique
→ developer approval
→ patch
→ validation
→ rollback/continue
```

---

## 11. Appendix

### 11.1 Decisions locked — do not revisit without explicit team decision

- Product name: **AI Migration Control Tower**
- Primary user: **Developer / Migration Engineer**
- Core job: **govern the migration**
- Primary UI: **Next.js web dashboard**
- Secondary UI: **Textual TUI retained**
- Control plane: **FastAPI**
- Migration execution: **separate Python worker process**
- Orchestration: **LangGraph**
- Primary transformation engine: **OpenRewrite**
- Concurrency: **one nonterminal migration**
- Deployment model: **local-first on Windows**
- Live transport: **SSE from persistent event store**
- Source-changing AI actions require developer approval
- Models do not receive unrestricted shell access
- Models use typed backend tools
- LLM does not replace OpenRewrite
- Reviewer is advisory and cannot approve
- Primary worker model: **GPT-5-mini**
- Primary reviewer model: **Mistral-Large-3**
- Disabled fallback reviewer: **Llama-3.3-70B-Instruct**
- Excluded models: **DeepSeek, Qwen, gpt-oss-20b**
- Requested proof and achieved proof are separate
- Build/tests/policies determine technical truth
- Legacy source must remain untouched
- V1 is for trusted internal repositories

### 11.2 Key rejected designs

```text
TUI-only final product
Next.js directly executing Maven/OpenRewrite
FastAPI request handler running the full migration
Terminal log parsing as the only source of truth
Multiple active migrations
New migration while another waits for approval
Multiple visible chatbots
One unlimited context prompt
Unrestricted PowerShell or shell tool
Arbitrary Maven goal/property tool
Silent AI patching
AI self-approval
LLM-declared proof
Production deployment in V1
```

### 11.3 Main developer flow

```text
1. Open Control Tower
2. Select trusted legacy source
3. Select runner and two-stage pipeline
4. Set target proof and policies
5. Start job
6. Watch analysis live
7. Review generated plan
8. Add amendment if needed
9. Review regenerated plan and critique
10. Approve final plan
11. Watch OpenRewrite and validation
12. Ask assistant questions at any stage
13. On failure, inspect grounded diagnosis
14. Review patch, critique, and validation plan
15. Approve or reject
16. Watch repair validation
17. Continue or roll back
18. Review target versus achieved proof
19. Download final report
```

### 11.4 Suggested core entities

#### `migration_jobs`

```text
job_id
pipeline_id
legacy_source_ref
output_root_ref
runner_profile_id
target_proof_level
achieved_proof_level
status
created_at
started_at
finished_at
created_by
```

#### `stage_runs`

```text
stage_run_id
job_id
stage_index
profile_id
source_ref
workspace_ref
status
started_at
finished_at
```

#### `run_events`

```text
event_id
job_id
stage_run_id
sequence
event_type
phase
status
payload_json
created_at
```

#### `worker_leases`

```text
lock_id
job_id
worker_pid
acquired_at
heartbeat_at
lease_expires_at
worker_status
exit_code
```

#### `artifacts`

```text
artifact_id
job_id
stage_run_id
type
relative_path
content_type
size_bytes
checksum
created_at
```

#### `approvals`

```text
approval_id
job_id
approval_type
subject_ref
decision
comments
actor
created_at
```

#### `plan_revisions`

```text
revision_id
job_id
revision_number
plan_artifact_id
amendment_artifact_id
critique_artifact_id
policy_result_artifact_id
status
created_at
```

#### `repair_attempts`

```text
repair_id
job_id
stage_run_id
failure_type
status
proposal_artifact_id
patch_artifact_id
critique_artifact_id
developer_decision
validation_artifact_id
rollback_artifact_id
created_at
finished_at
```

#### `assistant_threads`

```text
thread_id
job_id
summary
created_at
updated_at
```

#### `assistant_messages`

```text
message_id
thread_id
role
content
evidence_refs_json
tool_call_refs_json
created_at
```

### 11.5 Initial API surface

#### Configuration

```http
GET  /v1/runner-profiles
GET  /v1/pipelines
GET  /v1/filesystem/roots
GET  /v1/filesystem/entries
POST /v1/filesystem/validate
```

#### Jobs

```http
POST /v1/jobs
GET  /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/cancel
POST /v1/jobs/{job_id}/recover
```

#### Events and logs

```http
GET /v1/jobs/{job_id}/events
GET /v1/jobs/{job_id}/logs
GET /v1/jobs/{job_id}/logs/{log_id}
```

#### Plans and approvals

```http
GET  /v1/jobs/{job_id}/plans
POST /v1/jobs/{job_id}/plan-amendments
POST /v1/jobs/{job_id}/approvals
```

#### Artifacts

```http
GET /v1/jobs/{job_id}/artifacts
GET /v1/jobs/{job_id}/artifacts/{artifact_id}
```

#### Assistant

```http
GET  /v1/jobs/{job_id}/assistant/messages
POST /v1/jobs/{job_id}/assistant/messages
POST /v1/jobs/{job_id}/assistant/actions/{action_id}/confirm
POST /v1/jobs/{job_id}/assistant/actions/{action_id}/reject
```

#### Repairs

```http
GET  /v1/jobs/{job_id}/repairs
GET  /v1/jobs/{job_id}/repairs/{repair_id}
POST /v1/jobs/{job_id}/repairs/{repair_id}/approve
POST /v1/jobs/{job_id}/repairs/{repair_id}/reject
POST /v1/jobs/{job_id}/repairs/{repair_id}/rollback
```

#### Reports

```http
GET /v1/jobs/{job_id}/report
GET /v1/jobs/{job_id}/report.md
GET /v1/jobs/{job_id}/report.json
```

### 11.6 Initial structured event types

```text
job_created
job_queued
worker_starting
worker_started
worker_heartbeat
stage_started
stage_completed
stage_failed
command_started
command_output_available
command_completed
artifact_created
analysis_completed
plan_generated
plan_amendment_submitted
plan_regeneration_started
plan_regenerated
reviewer_critique_completed
approval_required
approval_recorded
openrewrite_preview_started
openrewrite_apply_started
diff_captured
build_started
build_completed
tests_started
tests_completed
dependency_policy_completed
repair_required
repair_proposed
repair_critique_completed
repair_approval_required
repair_applied
repair_validation_started
repair_validation_completed
repair_rolled_back
runtime_smoke_completed
endpoint_smoke_completed
proof_updated
report_generated
cancellation_requested
job_orphaned
job_completed
job_failed
job_cancelled
```

### 11.7 Initial LLM output schemas

#### Worker repair proposal

```json
{
  "failure_classification": "DEPENDENCY_CONFLICT",
  "root_cause": "string",
  "evidence_refs": ["artifact-id"],
  "affected_files": ["pom.xml"],
  "proposed_patch_ref": "artifact-id",
  "risk": "LOW|MEDIUM|HIGH",
  "developer_constraints_checked": ["string"],
  "validation_plan": [
    {
      "operation": "COMPILE"
    },
    {
      "operation": "FULL_UNIT_TESTS"
    },
    {
      "operation": "DEPENDENCY_POLICY"
    }
  ],
  "confidence": 0.0,
  "requires_human_escalation": false
}
```

#### Reviewer critique

```json
{
  "decision": "ACCEPTABLE|NEEDS_REVISION|INSUFFICIENT_EVIDENCE",
  "findings": [
    {
      "severity": "INFO|WARNING|BLOCKER",
      "message": "string",
      "evidence_refs": ["artifact-id"]
    }
  ],
  "unrelated_changes": ["string"],
  "constraint_violations": ["string"],
  "validation_gaps": ["string"]
}
```

The backend remains responsible for schema validation, policy checks, and authorization.

### 11.8 Current V1 proof statement

Use this wording until additional gates are implemented and validated:

> V1 is complete as a build/test-verified migration candidate. Runtime/H2, endpoint smoke, SQL Server, JWT/keystore/common-utils runtime configuration, and production readiness are not claimed in V1 and remain later gates.

### 11.9 References

#### Project sources

- AI Migration Factory — Full Chat Handoff, generated 2026-06-03
- Uploaded `modernizer-solution-copilotfull-integration` repository snapshot
- AI Migration Control Tower decision discussion, 2026-06-06

#### Official technical references

- Next.js App Router:  
  https://nextjs.org/docs/app

- Next.js Server and Client Components:  
  https://nextjs.org/docs/app/getting-started/server-and-client-components

- FastAPI Server-Sent Events:  
  https://fastapi.tiangolo.com/tutorial/server-sent-events/

- FastAPI Background Tasks:  
  https://fastapi.tiangolo.com/tutorial/background-tasks/

- LangGraph Interrupts:  
  https://docs.langchain.com/oss/python/langgraph/interrupts

- LangGraph Persistence:  
  https://docs.langchain.com/oss/python/langgraph/persistence

- OpenRewrite Maven Plugin:  
  https://docs.openrewrite.org/reference/rewrite-maven-plugin

- Python asyncio subprocesses:  
  https://docs.python.org/3/library/asyncio-subprocess.html

- Azure Structured Outputs:  
  https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs

- Azure AI Model Inference API:  
  https://learn.microsoft.com/en-us/rest/api/aifoundry/modelinference/

- SQLite WAL:  
  https://sqlite.org/wal.html

---

## Approval

| Reviewer | Decision | Date | Comments |
|---|---|---|---|
| ABDELILAH MORTAKI | Pending | — | — |
| HAMDAOUI Ali | Pending | — | — |
| ilyas abarbach | Pending | — | — |
