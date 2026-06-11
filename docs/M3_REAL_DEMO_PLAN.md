# M3 Real Demo Plan - AI Migration Control Tower

Date: 2026-06-11

Sources of truth used:

1. `AGENTS.md`
2. `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`
3. `docs/M2_REPOSITORY_ALIGNMENT.md`
4. Current repo code and tests
5. V1 terminal run docs and runbooks
6. Current official docs:
   - FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/
   - FastAPI SSE: https://fastapi.tiangolo.com/tutorial/server-sent-events/
   - Next.js route handlers: https://nextjs.org/docs/app/getting-started/route-handlers
   - LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
   - Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
   - AssignProcessToJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
   - TerminateJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
   - Java ProcessBuilder: https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/lang/ProcessBuilder.html
   - Maven lifecycle: https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html
   - OpenRewrite Spring Boot migration: https://docs.openrewrite.org/running-recipes/popular-recipe-guides/migrate-to-spring-3

## 1. Current M2 Reality

Live today:

- `GET /v1/health/live` and `GET /v1/health/ready` exist in `migration_factory/control_tower/adapters/fastapi/app.py`.
- `POST /v1/jobs` creates a diagnostic job, and `POST /v1/jobs/{jobId}/start` queues a command without launching a worker from the HTTP route.
- `GET /v1/jobs/{jobId}`, `/commands`, `/events`, `/events/stream`, `/artifacts`, `/logs/stdout`, and `/logs/stderr` exist.
- UI surfaces live on `web/control-tower/app/jobs/new/page.tsx` and `web/control-tower/app/jobs/[jobId]/page.tsx`.
- The UI is still a foundation diagnostic slice, not the V1 Spring migration demo.

Current limitation:

- The create-job form still talks in generic source/output terms with `src` and `out` placeholders in `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx`.
- The job page can start/cancel a diagnostic command and show logs, events, and artifacts, but it has no Stage 1 / approval / Stage 2 workflow.
- `health/ready` reports `dispatcher` and `singleton` as `not_configured`.
- The API still exposes internal/manual routes: `/launch`, `/finalize`, `/timeout`.

What the M2 foundation already gives M3:

- durable job identity, optimistic concurrency, idempotency, event replay, SSE, command output windows, artifact listing, and a basic workspace/manifests path;
- a real backend namespace that can be extended instead of replaced;
- a local dev bootstrap in `migration_factory/control_tower/adapters/fastapi/dev_app.py`.

## 2. M2 Section-By-Section Carryover

Legend:

- `done enough for M3` = can be reused as-is for the demo
- `must complete before real demo` = blocking gap for M3
- `can be deferred after demo` = useful, but not required to show the V1 workflow
- `dangerous gap` = unsafe to demo around without explicit design work

| M2 section | Verdict | Exact repo evidence | M3 implication |
|---|---|---|---|
| 0. Readiness Verdict | must complete before real demo | `docs/M2_REPOSITORY_ALIGNMENT.md`, reviewer approval still pending | M3 should not inherit the old M2 readiness claim as proof of demo readiness |
| 1. M2 Purpose | done enough for M3 | `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`, `migration_factory/control_tower/**` | Reuse the Control Tower as the operator surface |
| 2. Locked M2 Architecture | must complete before real demo | `app.py`, `services.py`, `worker_launcher.py`, Next app | M3 must replace the diagnostic-only flow with a real stage workflow |
| 3. Latest Technology Baseline | can be deferred after demo | `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`, `web/control-tower/package.json` | Versions are stable enough for M3 planning; no demo blocker |
| 4. M2-00 Repository Alignment | done enough for M3 | `docs/M2_REPOSITORY_ALIGNMENT.md` | Use it as a frozen evidence base, not as acceptance proof |
| 5. Critical Invariants | must complete before real demo | `states.py`, `test_active_job_lock.py`, `test_m2_diagnostic_queue.py` | M3 needs equivalent invariants for stage execution and approval |
| 6. Domain Contracts | done enough for M3 | `domain/states.py`, `domain/commands.py`, `domain/transitions.py`, `test_domain_transitions.py` | Existing state machinery can carry stage/approval states forward |
| 7. Immutable Manifests | must complete before real demo | `domain/manifests.py`, `test_m2_workspace.py`, `test_m2_worker_launch.py` | V1 stage manifests must be immutable and tied to the real run inputs |
| 8. Persistence Extension | must complete before real demo | migrations `0002`-`0006`, `test_sqlite_migrations.py` | M3 needs stage/approval/evidence persistence extensions |
| 9. Safe Workspace Lifecycle | done enough for M3 | `application/services.py`, `infrastructure/workspace.py`, `test_m2_workspace.py` | Good base for isolated stage workspaces |
| 10. Durable Start and Two-Phase Launch | must complete before real demo | `DiagnosticJobService`, `WorkerLaunchService`, `test_m2_diagnostic_queue.py`, `test_m2_worker_launch.py` | M3 needs this behavior generalized from diagnostic start to real stage execution |
| 11. API Singleton, Dispatcher, Ingestor, Monitor | dangerous gap | no dedicated singleton/dispatcher/ingestor/monitor service | This is the biggest runtime gap before a real demo |
| 12. Diagnostic Worker and Child Operation | must complete before real demo | `worker_launcher.py`, `test_m2_worker_launch.py` | M3 should call the V1 runner modules through a backend-owned worker path |
| 13. Output Capture | done enough for M3 | `test_m2_command_output.py`, `GET /logs/stdout`, `GET /logs/stderr` | Reuse the bounded log window model for stage commands |
| 14. Worker Event Spool | dangerous gap | no private spool writer/reader/receipt pipeline yet | Must exist before demoing approval/resume as durable state |
| 15. Event Ingestion and Late-Event Rules | dangerous gap | `test_m2_event_replay.py` only proves public replay | Private worker events still need durable ingestion rules |
| 16. Terminal Finalization and Forensic Artifacts | must complete before real demo | `CommandFinalizationService`, `test_m2_terminal_artifacts.py` | Needed for stage evidence and final verification artifacts |
| 17. Cancellation and Timeout | must complete before real demo | `CancelService`, `TimeoutService`, `test_m2_cancellation.py` | Demo needs pause/abort controls that work on staged runs |
| 18. Startup and Crash Semantics | dangerous gap | `ReconciliationService`, `test_m2_restart_recovery.py` | Demo cannot claim reliability without restart/crash semantics for stage runs |
| 19. HTTP API Contract | done enough for M3 | `app.py`, `queries.py`, `controlTowerApi.ts`, `test_fastapi_diagnostic_queue.py` | The contract can be extended rather than replaced |
| 20. Optimistic Concurrency and Idempotency | done enough for M3 | `test_m2_diagnostic_queue.py`, `test_m2_cancellation.py` | Keep these semantics for every stage/approval mutation |
| 21. Native SSE Contract | done enough for M3 | `eventReplay.ts`, `test_m2_event_replay.py` | Real demo should keep SSE and browser reconnect behavior |
| 22. Local Security | must complete before real demo | `app.py`, current route surface, `tests/control_tower/test_fastapi_diagnostic_queue.py` | Need explicit local-only and allowlist behavior for a real operator demo |
| 23. Next.js Implementation | done enough for M3 | `web/control-tower/app/**`, `web/control-tower/tests/controlTowerApi.test.ts` | UI shell is usable; workflow needs redesign |
| 24. Initial M2 Limits | can be deferred after demo | event/log limits in `app.py` and tests | Keep the bounds, but they do not block the demo |
| 25. Standard Error Contract | done enough for M3 | `_error`, `_raise_http_error` in `app.py` | Good enough to preserve while adding new demo errors |
| 26. Observability | can be deferred after demo | minimal structured payloads only | Nice to have, not the first M3 blocker |
| 27. Jira Work Breakdown | can be deferred after demo | `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md` | M3 needs its own issue breakdown, not M2's |
| 28. Test Strategy | must complete before real demo | `tests/control_tower/**`, `tests/orchestrator/**`, `web/control-tower/tests/**` | Add stage/approval/happy-path/crash-window coverage |
| 29. Acceptance Criteria | must complete before real demo | current docs and tests stop short of real V1 demo | M3 acceptance must be redefined around the real workflow |
| 30. Definition of Done | must complete before real demo | current repo state does not meet real demo DoD | Demo can only ship with explicit evidence and local commit discipline |
| 31. Final Implementation Order | must complete before real demo | current source tree and docs | M3 should be ordered around the operator demo, not the old M2 slice |

## 3. V1 Terminal Workflow Analysis

The real V1 flow is documented in `docs/system/09-how-to-run.md`, `docs/system/03-orchestrator-flow.md`, `docs/system/04-profiles-ai-hub.md`, `docs/system/07-runtime-build-test-validation.md`, and `docs/system/10-new-agent-handoff.md`.

Environment used for the validated path:

- `PYTHONPATH=.`
- `JAVA_HOME=C:\Program Files\Java\jdk-21.0.10`
- `MAVEN_CMD=C:\Tools\apache-maven-3.9.15\bin\mvn.cmd`
- `AI_MIGRATION_COPILOT_REQUIRED=true`
- `AI_MIGRATION_COPILOT_PROVIDER=copilot_cli`
- `AI_MIGRATION_COPILOT_MODEL=gpt-5-mini`
- `AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS=false`
- `AI_MIGRATION_H2_STARTUP_REQUIRED=false`
- `AI_MIGRATION_SKIP_ENDPOINT_SMOKE=true`
- `AI_MIGRATION_PROOF_LEVEL=build_test_verified`

Run layout:

- Stage 1 profile: `springboot-2.1.6-to-2.7-java11`
- Stage 2 profile: `springboot-2.7-to-3.5-java17`
- Stage 1 run id: `v1-stage1-216-to-27-watchonly-20260602-233409`
- Stage 2 run id: `v1-stage2-27-to-35-watchonly-20260602-233720`

Behavior:

1. `migration_factory.orchestrator.runner` starts a LangGraph run with `read_only_assessment` or `full_sandbox_migration`.
2. The first invocation reaches the approval interrupt and writes `orchestration/approval_interrupt_state.json`.
3. `migration_factory.orchestrator.resume` records `approved`, `rejected`, or `replan_required`.
4. When approved in `full_sandbox_migration`, the flow continues into sandbox transform and then build/test validation.
5. Stage 1 proves the upgrade from Boot 2.1.6 to 2.7 in a sandbox.
6. Stage 2 uses the Stage 1 sandbox output as the new legacy input and proves the Boot 2.7 to 3.5 hop.
7. Final manual verification is an explicit `mvn clean test -DskipITs` in the Stage 2 sandbox.

Evidence produced:

- analysis, planning, assessment, approval interrupt snapshot, approval decision, sandbox ledger, build/test outputs, orchestration summary, and final report artifacts;
- Stage 1 and Stage 2 both reached `TRANSFORM_APPLIED_IN_SANDBOX`, `BUILD_PASSED_IN_SANDBOX`, and `PASS_WITH_WARNINGS`;
- final manual verification returned exit code `0` for `mvn clean test -DskipITs`.

Important nuance:

- V1 is build/test verified, not runtime/H2 verified.
- Do not treat the final approval interrupt itself as failure; it is a deliberate pause point.

## 4. M3 Product Goal

M3 goal:

Run the existing V1 two-stage Spring Boot migration from the Control Tower UI with honest states, manual approval gates, logs, events, and final evidence.

M3 must:

- never fake proof;
- preserve M2 safety rules;
- reuse the existing V1 runner modules where sensible;
- make the approval pause/resume a first-class Control Tower state;
- only say "completed" when final verification actually passes.

## 5. Frontend UX Plan

Replace the generic diagnostic UX with a real migration operator flow:

- top-level job card should show legacy application root, output workspace root, AI Hub path, and selected route;
- make the migration route explicit: Boot 2.1.6 -> 2.7 -> 3.5;
- show JDK and Maven readiness before launch;
- show Stage 1 and Stage 2 as separate visual bands with their own status, logs, approvals, and evidence;
- show the approval pause with `approved`, `rejected`, and `replan_required` actions;
- surface the current command, current run directory, and the exact stage-specific evidence paths;
- show final evidence only after build/test verification passes;
- never render "migration completed" until the final Maven check succeeds.

UI copy should stop saying "foundation diagnostic" and instead speak in the user's domain terms:

- Legacy application
- Output workspace
- AI Hub
- Stage 1
- Stage 2
- Approval required
- Build/test evidence
- Final verification

The `/jobs/new` flow should collect:

- legacy app path or root selector;
- output workspace root;
- AI Hub path;
- profile selection for Stage 1 and Stage 2;
- JDK/Maven readiness;
- demo notes such as run id and operator name.

The `/jobs/[jobId]` page should show:

- current phase;
- stage history;
- approval state;
- event replay;
- stdout/stderr windows;
- artifact list;
- final verification result;
- links to run directories relative to the workspace.

## 6. Backend/API Plan

Proposed M3 contract shape:

- `POST /v2/migration-jobs`
  - creates a real migration job with legacy path, output workspace, AI Hub path, stage profiles, and operator metadata;
- `POST /v2/migration-jobs/{jobId}/stages/{stageId}/start`
  - starts Stage 1 or Stage 2;
- `GET /v2/migration-jobs/{jobId}/approval-interrupt`
  - returns the persisted approval interrupt snapshot;
- `POST /v2/migration-jobs/{jobId}/approval-decision`
  - records `approved`, `rejected`, or `replan_required`;
- `POST /v2/migration-jobs/{jobId}/stages/{stageId}/verify`
  - runs or records the final Maven verification for the approved stage;
- `GET /v2/migration-jobs/{jobId}/logs`
  - returns command logs and byte offsets;
- `GET /v2/migration-jobs/{jobId}/events`
  - returns committed public events;
- `GET /v2/migration-jobs/{jobId}/artifacts`
  - returns evidence metadata;
- `POST /v2/migration-jobs/{jobId}/cancel`
  - cancels the active stage safely;
- `POST /v2/migration-jobs/{jobId}/timeout`
  - marks an overdue stage as timed out.

Mutation rules:

- use `Idempotency-Key` on create/start/decision/cancel/timeout;
- require `If-Match` for state transitions that depend on the current job version;
- return `409` for active-command conflicts or idempotency mismatches;
- return `412` for stale versions;
- return `428` when preconditions are missing;
- return `404` for unknown jobs or stages.

Request fields should include:

- `legacy_app_path`
- `output_workspace_root`
- `ai_hub_path`
- `stage_1_profile_id`
- `stage_2_profile_id`
- `source_jdk_home`
- `target_jdk_home`
- `maven_cmd`
- `approved_by`
- `comments`
- `expected_version`

## 7. Execution Architecture

The safe wrapper model should be:

1. HTTP routes persist intent only.
2. A dispatcher claims queued stage commands.
3. A worker executes backend-owned operations only.
4. The worker may call existing V1 runner modules, but not from the route handler.
5. Immutable manifests must contain the exact V1 runner inputs and stage metadata.
6. Approval interrupt state becomes Control Tower state, not a terminal failure.

Architecture rules:

- no subprocess launch inside HTTP routes;
- no raw shell execution from the browser or the API surface;
- worker-owned process execution only;
- use durable state for stage progress and resume;
- keep public events separate from private worker spool content;
- preserve the current M2 path isolation and artifact immutability.

The worker process control should follow the Windows Job Object model already used in the repo:

- create suspended;
- assign to job object before resume;
- close-on-job-close termination;
- non-inheritable handles;
- record process identity, not raw handles.

## 8. Data/Persistence Plan

Already present and reusable:

- `migration_jobs`
- `run_configurations`
- `stage_runs`
- `command_executions`
- `run_events`
- `artifacts`
- `audit_records`
- `idempotency_records`

New or extended for M3:

- `stage_runs`
  - add stage identity, V1 run directory reference, stage outcome, approval state, and stage timing fields;
- `command_executions`
  - add command kind for Stage 1, approval resume, Stage 2, and final verification;
  - add links to V1 run directory and evidence paths;
- `approval_records`
  - decision, decided_by, comments, interrupt snapshot reference, timestamp, version;
- `migration_stage_evidence`
  - build status, test status, command line, exit code, report paths, and proof level;
- `migration_run_references`
  - Stage 1 run dir, Stage 2 run dir, sandbox dir, and relative evidence links;
- `proof_status_history`
  - if proof level changes should be auditable over time.

M3 should prefer extending existing tables over inventing duplicate event stores.

## 9. Safety/Security Plan

- allowlist all filesystem paths against the selected roots;
- keep the legacy source tree unchanged;
- isolate output under a run-specific `.migration/runs/<runId>` tree;
- never let the browser provide executable args or environment variables;
- treat `JAVA_HOME`, `MAVEN_CMD`, and approved Copilot env as backend-owned inputs only;
- never put secrets or tokens in public payloads, events, or artifacts;
- keep local-only binding and origin restrictions explicit;
- block arbitrary shell commands;
- validate Java/Maven commands before execution;
- guard the sandbox transform with the approved profile and guarded transform override where required;
- do not claim runtime/H2 proof unless it is explicitly collected.

Process execution references:

- Java `ProcessBuilder` supports explicit redirection and stream control, which is safer than ad hoc shell composition. https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/lang/ProcessBuilder.html
- Windows Job Objects are the correct Windows-level termination boundary for grouped processes. https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects

## 10. Test Strategy

Unit/domain:

- job and stage state transitions;
- approval decision normalization;
- manifest checksum and path allowlist rules.

API contract:

- create job;
- start stage;
- approval interrupt fetch;
- approval decision submit;
- event replay;
- logs/artifacts endpoints.

Worker integration:

- claim command;
- build stage manifest;
- launch worker;
- terminate worker safely;
- persist process metadata.

Approval interrupt/resume:

- emit interrupt;
- persist snapshot;
- resume approved;
- resume rejected;
- resume replan required.

Two-stage happy path:

- Stage 1 start -> approval -> Stage 2 start -> final Maven verification.

Cancel/timeout:

- cancel queued/running stage;
- timeout overdue stage.

Crash windows:

- crash before launch;
- crash after launch before event persist;
- restart with stale active command;
- restart with unresolved approval snapshot.

Frontend manual tests:

- create job from UI;
- inspect Stage 1 pause;
- approve;
- inspect Stage 2;
- inspect final evidence.

Regression commands:

```powershell
py -m pytest tests/control_tower -q
py -m pytest tests/orchestrator -q
py -m pytest tests/tui -q
py -m pytest tests/agents/planning_agent -q
py -m pytest tests/assessment -q
cd web/control-tower
npm run typecheck
npm test
npm run build
```

Focused M3 commands to add once implementation exists:

```powershell
py -m pytest tests/orchestrator/test_full_sandbox_migration.py -q
py -m pytest tests/orchestrator/test_runner.py tests/orchestrator/test_resume.py -q
py -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py tests/control_tower/test_m2_event_replay.py -q
py -m pytest tests/control_tower/test_m2_worker_launch.py tests/control_tower/test_m2_terminal_artifacts.py -q
```

## 11. Jira Work Breakdown

### M3-00 - Define M3 control plane contract

- Goal: define the real migration job and stage lifecycle contract.
- Scope: job model, stage states, approval states, and public API shape.
- Acceptance criteria: API and UI vocabulary no longer describe a fake diagnostic run.
- Likely files: `migration_factory/control_tower/**`, `web/control-tower/lib/contracts.ts`, `web/control-tower/lib/controlTowerApi.ts`.
- Tests: API contract and domain transition tests.
- Depends on: M2 persistence and existing job/event contracts.

### M3-01 - Add stage execution and approval persistence

- Goal: persist Stage 1/Stage 2 execution, approval records, and evidence links.
- Scope: new tables or table extensions for stage runs, approval records, and evidence metadata.
- Acceptance criteria: approval pause/resume survives restart and is queryable.
- Likely files: SQLite migrations, repositories, DTOs.
- Tests: migration tests, persistence tests, restart-recovery tests.
- Depends on: M3-00.

### M3-02 - Implement worker-owned V1 stage execution

- Goal: launch the existing V1 runner modules from a backend-owned worker path.
- Scope: dispatcher claim, worker launcher, process ownership, run directory mapping.
- Acceptance criteria: routes never launch subprocesses directly; worker records real stage progress.
- Likely files: `migration_factory/control_tower/application/services.py`, `migration_factory/control_tower/infrastructure/worker_launcher.py`, new worker orchestration module.
- Tests: worker integration, Windows Job Object, cancel/timeout.
- Depends on: M3-00, M3-01.

### M3-03 - Wire approval interrupt and resume

- Goal: make the approval gate a first-class Control Tower state.
- Scope: approval interrupt fetch, decision submit, resume path, state transitions.
- Acceptance criteria: Stage 1 stops at approval, approved resumes Stage 2, rejected/replan_required stop cleanly.
- Likely files: backend API, orchestrator wrapper, UI job page.
- Tests: approval interrupt/resume, idempotency, stale version, crash window.
- Depends on: M3-01, M3-02.

### M3-04 - Rework the job UI for the real demo

- Goal: replace diagnostic UI language with real migration workflow language.
- Scope: create-job form, job page, stage timeline, approval controls, log and evidence panels.
- Acceptance criteria: operator can run the two-stage demo from the browser without reading internal concepts.
- Likely files: `web/control-tower/app/jobs/new/*`, `web/control-tower/app/jobs/[jobId]/*`, `web/control-tower/lib/*`.
- Tests: Vitest UI contract tests plus manual browser walkthrough.
- Depends on: M3-00, M3-03.

### M3-05 - Add final verification and evidence reporting

- Goal: show final Maven evidence without faking proof.
- Scope: final `mvn clean test` execution or verification record, build/test status, artifact references, final summary.
- Acceptance criteria: UI shows final verification only when the Stage 2 sandbox evidence is real.
- Likely files: backend evidence service, final report integration, UI evidence panel.
- Tests: final verification, artifact listing, summary generation.
- Depends on: M3-02, M3-03.

### M3-06 - Harden safety, limits, and crash recovery

- Goal: keep the demo honest under failure.
- Scope: path allowlist, local-only restrictions, crash/restart recovery, timeout/cancel, event replay, secret redaction.
- Acceptance criteria: no secret leakage, no source-tree mutation, no unbounded route execution.
- Likely files: backend API, worker, query service, security helpers.
- Tests: crash windows, replay limits, cancellation, timeout, security contract.
- Depends on: M3-00 through M3-05.

## 12. Demo Runbook

Expected operator flow:

1. Start FastAPI on loopback.
2. Start Next.js on loopback.
3. Open `/jobs/new`.
4. Create a real migration job with legacy app path, output workspace, AI Hub path, Stage 1 profile, and Stage 2 profile.
5. Open the job page.
6. Start Stage 1.
7. Watch the approval interrupt appear with the real interrupt snapshot and logs.
8. Approve Stage 1 with `approved_by` and comments.
9. Confirm Stage 2 starts from the Stage 1 output sandbox.
10. Watch Stage 2 finish and run the final Maven verification.
11. Show final evidence to managers: stage history, run IDs, build/test status, logs, artifacts, and final verification result.

Suggested operator commands behind the scenes:

```powershell
$env:CONTROL_TOWER_DEV_ROOT="$PWD\.control-tower-dev"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000

cd web/control-tower
$env:NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

The UI should point the operator at the real run directory structure and the final Maven validation command, not at an abstract diagnostic job.

## 13. Risks and Decisions Needed

- Exact Windows path picker strategy for legacy source and output workspace.
- Whether the UI should expose raw paths, root IDs, or both.
- JDK handling for Stage 1, Stage 2, and final verification.
- Whether the backend should own Maven invocation directly or only record/launch a worker-owned command.
- How Copilot/Azure model env should be surfaced without leaking secrets.
- Whether runtime/H2 smoke belongs in M3 or remains a later proof layer.
- Whether M3 must land the full M2 private spool/dispatcher/monitor stack first, or can demo with a narrower but still durable worker loop.
- Whether proof level naming should stay `build_test_verified` or get a more explicit M3 label.

## References

- FastAPI lifespan and startup/shutdown hooks: https://fastapi.tiangolo.com/advanced/events/
- FastAPI Server-Sent Events: https://fastapi.tiangolo.com/tutorial/server-sent-events/
- Next.js Route Handlers: https://nextjs.org/docs/app/getting-started/route-handlers
- LangGraph interrupts and resume behavior: https://docs.langchain.com/oss/python/langgraph/interrupts
- Windows Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- AssignProcessToJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
- TerminateJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
- Java ProcessBuilder API: https://docs.oracle.com/en/java/javase/11/docs/api/java.base/java/lang/ProcessBuilder.html
- Maven lifecycle and preferred test entrypoints: https://maven.apache.org/guides/introduction/introduction-to-the-lifecycle.html
- OpenRewrite Spring Boot migration guidance: https://docs.openrewrite.org/running-recipes/popular-recipe-guides/migrate-to-spring-3
