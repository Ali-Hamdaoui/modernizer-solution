# M2 Repository Alignment

Issue: AMF-148 - [Control Tower] M2-00 - Align the repository and freeze M2 contracts

Date inspected: 2026-06-10

Integration base: `DEMO2` at `521d7b4`

Issue branch: `fix/amf-148-150-review-findings`

This document records the current repository state after AMF-149 and AMF-150 tracer bullets. It does not approve future M2 behavior and does not add worker, dispatcher, Job Object, private spool, cancellation, output capture, migration execution, AI, or proof behavior.

## 0. Status and review

Status: Implementation model ready for reviewer approval.

The original horizontal M2 work breakdown is now delivered through Jira tracer-bullet vertical slices:

- AMF-149 owns create/queue API behavior and the minimal frontend create/current-run path.
- AMF-150 owns committed public-event SSE replay and frontend reconnect behavior.
- Later M2 tasks extend these components. They must not create duplicate FastAPI apps, duplicate SSE endpoints, duplicate event-replay tables, or a replacement frontend workspace.
- Worker launch, dispatcher, Windows Job Object, private worker event spool, raw output capture, cancellation, migration execution, AI behavior, repair behavior, and proof behavior remain deferred.

Reviewer decisions remain pending. No approval is claimed by this document.

| Reviewer | Decision | Date | Comments |
|---|---|---|---|
| HAMDAOUI Ali | Pending | Pending | Pending |
| ilyas abarbach | Pending | Pending | Pending |

## 1. Sources inspected

Files and sources inspected:

- Current assigned issues: AMF-148, AMF-149, AMF-150.
- `AGENTS.md`.
- `docs/M1_IMPLEMENTATION_PLAN.md`.
- `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`.
- `docs/PRD_AI_Migration_Control_Tower_v0.3.md`.
- `docs/adr/ADR-M2-01-fastapi-and-sse-adapter-strategy.md`.
- `docs/adr/ADR-M2-02-windows-job-object-and-process-control-strategy.md`.
- `docs/adr/ADR-M2-03-public-event-type-persistence-strategy.md`.
- `docs/adr/ADR-M2-04-nextjs-and-nodejs-workspace-version-strategy.md`.
- `docs/adr/ADR-M2-05-single-control-tower-controller-instance-strategy.md`.
- `pyproject.toml`.
- `migration_factory/control_tower/**`.
- `tests/control_tower/**`.
- `web/control-tower/**`.

No nested `AGENTS.md` files exist under `docs/`, `migration_factory/`, `tests/`, or `web/control-tower/`.

## 2. Current package tree

Current Control Tower backend tree:

```text
migration_factory/control_tower/
  __init__.py
  adapters/
    __init__.py
    fastapi/
      __init__.py
      app.py
  application/
    __init__.py
    commands.py
    dto.py
    ports.py
    queries.py
    services.py
  domain/
    __init__.py
    artifacts.py
    checksums.py
    commands.py
    entities.py
    errors.py
    states.py
    transitions.py
  infrastructure/
    __init__.py
    paths.py
    windows_paths.py
    sqlite/
      __init__.py
      artifact_paths.py
      connection.py
      repositories.py
      unit_of_work.py
      migrations/
        __init__.py
        0001_foundation.sql
        0002_m2_queued_diagnostic.sql
  schemas/
    __init__.py
    common.py
    pipeline_definition.py
    run_configuration.py
    runner_profile.py
```

Current Control Tower tests:

```text
tests/control_tower/
  __init__.py
  _helpers.py
  transition_helpers.py
  test_active_job_lock.py
  test_application_commands_queries.py
  test_artifact_hashing.py
  test_artifact_paths.py
  test_artifact_registry.py
  test_audit_records.py
  test_create_migration_job.py
  test_domain_transitions.py
  test_fastapi_diagnostic_queue.py
  test_m1_acceptance.py
  test_m2_diagnostic_queue.py
  test_m2_event_replay.py
  test_paths.py
  test_pipeline_definition_schema.py
  test_pipeline_registration.py
  test_run_configurations.py
  test_run_events.py
  test_runner_profile_registration.py
  test_runner_profile_schema.py
  test_sqlite_migrations.py
  test_transition_job_state.py
```

Current frontend workspace:

```text
web/control-tower/
  app/
    globals.css
    layout.tsx
    page.tsx
    jobs/
      [jobId]/
        CurrentRunClient.tsx
        StartDiagnosticJobButton.tsx
        page.tsx
      new/
        CreateDiagnosticJobForm.tsx
        page.tsx
  lib/
    contracts.ts
    controlTowerApi.ts
    eventReplay.ts
  tests/
    controlTowerApi.test.ts
  next.config.mjs
  next-env.d.ts
  package.json
  package-lock.json
  tsconfig.json
  vitest.config.ts
```

## 3. Current dependencies

Declared backend dependencies in `pyproject.toml`:

- `jsonschema`.
- `fastapi==0.136.3`.
- `langgraph`.
- `pydantic>=2,<3`.
- `PyYAML`.
- `sse-starlette==3.4.4`.
- `uvicorn==0.38.0`.

Declared backend test extras:

- `jsonschema`.
- `fastapi==0.136.3`.
- `pydantic>=2,<3`.
- `pytest`.
- `sse-starlette==3.4.4`.

Declared Python support remains `>=3.10`.

Verified local runtime:

- `py --version`: `Python 3.14.5`.
- FastAPI: `0.136.3`.
- `sse-starlette`: `3.4.4`.
- Uvicorn: `0.38.0`.
- Starlette: `1.2.1`.
- Pydantic: `2.13.4`.
- `node --version`: `v24.15.0`.
- `npm --version`: `11.12.1`.

Verified SSE import:

```powershell
py -c "from fastapi.sse import EventSourceResponse, ServerSentEvent; print(EventSourceResponse.__module__, ServerSentEvent.__module__)"
```

Output:

```text
fastapi.sse fastapi.sse
```

Frontend dependencies in `web/control-tower/package.json`:

- `next`: `16.2.7`.
- `react`: `19.2.7`.
- `react-dom`: `19.2.7`.
- `@types/node`: `24.10.1`.
- `@types/react`: `19.2.7`.
- `@types/react-dom`: `19.2.3`.
- `typescript`: `5.9.3`.
- `vitest`: `4.1.8`.
- `overrides.postcss`: `8.5.10`.

`web/control-tower/package-lock.json` is the frontend lockfile. No Python lockfile is present.

## 4. Current migrations and persistence

Current SQLite migrations:

- `0001_foundation.sql`.
- `0002_m2_queued_diagnostic.sql`.

`0002_m2_queued_diagnostic.sql` is present and is now baseline M2 schema for later tasks.

Current M2 persistence includes:

- `event_types` catalog.
- `command_executions`.
- `idempotency_records`.
- rebuilt `run_events` event-type FK behavior while preserving job-scoped public sequence.

Later M2 tasks must extend these tables and repositories where needed. They must not recreate another command table, idempotency table, event-type catalog, or public browser replay table.

## 5. Implemented AMF-149 behavior

AMF-149 owns current create/queue vertical slice:

- Domain command states and command execution entities.
- Application create diagnostic job service.
- Application start diagnostic job service.
- Idempotency for create and start.
- One atomic Unit of Work for create-job idempotency, job creation, run configuration, stage row, public event, audit row, and idempotency record.
- FastAPI routes:
  - `GET /v1/runner-profiles`.
  - `GET /v1/pipelines`.
  - `GET /v1/filesystem/roots`.
  - `POST /v1/jobs`.
  - `GET /v1/jobs/{job_id}`.
  - `POST /v1/jobs/{job_id}/start`.
- Minimal frontend create/current-run UI under `web/control-tower/`.

Routes adapt HTTP to application services only. They do not launch subprocesses.

Diagnostic wording remains limited. Diagnostic queue success must not be described as migration success or proof achievement.

## 6. Implemented AMF-150 behavior

AMF-150 owns current committed public-event replay:

- Public event replay queries in `ControlTowerQueryService`.
- Cursor parsing in `parse_public_event_cursor`.
- HTTP replay endpoint:
  - `GET /v1/jobs/{job_id}/events`.
- SSE replay endpoint:
  - `GET /v1/jobs/{job_id}/events/stream`.
- Browser client EventSource bootstrap URL from the last applied public sequence.
- Frontend event application that ignores already-applied public sequences and refetches projections after state-changing public events.

SSE streams only committed public `run_events` rows. It does not expose private worker events, raw log text, absolute paths, process-control IDs, PIDs, or secrets.

## 7. SSE cursor contract

`Last-Event-ID` is authoritative on browser reconnect.

Rules:

- If `Last-Event-ID` is absent, use validated `after_sequence` when provided; otherwise start at `0`.
- If valid `Last-Event-ID` is present, resume after that sequence.
- If both values are present and `after_sequence <= Last-Event-ID`, treat `after_sequence` as stale bootstrap state and use `Last-Event-ID`.
- Reject malformed cursors.
- Reject negative cursors.
- Reject cursors greater than the latest committed public event sequence.
- Reject `after_sequence > Last-Event-ID` because that is not normal browser reconnect behavior and would create ambiguous replay intent.
- Keepalive comments do not carry event IDs.
- Disconnect releases the SSE client slot.

## 8. Existing components to reuse

Reusable current components:

- Canonical JSON/checksum helpers in `domain/checksums.py`.
- Timestamp helpers in `domain/entities.py`.
- M1 state/transition rules in `domain/states.py` and `domain/transitions.py`.
- M2 command state/entity contracts in `domain/commands.py` and `domain/entities.py`.
- Typed errors in `domain/errors.py`.
- Immutable command/read DTOs in `application/commands.py` and `application/dto.py`.
- Repository and Unit of Work ports in `application/ports.py`.
- Query service in `application/queries.py`.
- Application services in `application/services.py`.
- SQLite connection, migration runner, repositories, and Unit of Work under `infrastructure/sqlite/`.
- Artifact path safety helpers in `infrastructure/sqlite/artifact_paths.py`, `infrastructure/paths.py`, and `infrastructure/windows_paths.py`.
- FastAPI app factory in `adapters/fastapi/app.py`.
- Next.js workspace in `web/control-tower/`.

## 9. Future components still deferred

Not implemented yet:

- Durable dispatcher.
- API/controller singleton guard.
- Worker runtime.
- Diagnostic worker subprocess launch.
- Windows Job Object process control.
- Private worker event spool.
- Private event ingestion.
- Process monitor.
- Timeout and cancellation.
- Raw stdout/stderr output capture and log windows.
- Terminal artifact finalization.
- Migration execution.
- AI behavior.
- Repair behavior.
- Proof behavior.

These must be implemented only by later approved M2 issues. They must extend existing AMF-149/150 API, persistence, SSE, and frontend components.

## 10. Later M2 task alignment

Later tasks must align as follows:

- M2 persistence work treats `0002_m2_queued_diagnostic.sql`, `event_types`, `command_executions`, and `idempotency_records` as current baseline.
- Worker/private-event/process-control tasks add deferred runtime behavior without changing browser SSE into a private-event stream.
- FastAPI work extends `migration_factory/control_tower/adapters/fastapi/app.py`.
- SSE work extends the existing committed public-event replay endpoint.
- Frontend work extends `web/control-tower/`.
- Acceptance work verifies AMF-149/150 behavior as baseline.

## 11. Public contracts frozen by current state

Job projection:

- `job.job_id`.
- `job.version`.
- `job.state`.
- `job.created_at`.
- `job.updated_at`.
- `active_command`.
- `etag`.

Command projection:

- `command_id`.
- `job_id`.
- `operation`.
- `status`.
- `created_at`.
- `updated_at`.

Public event envelope:

- `event_id`.
- `job_id`.
- `sequence`.
- `event_type`.
- `actor_type`.
- `actor_id`.
- `correlation_id`.
- `causation_id`.
- `payload`.
- `payload_checksum`.
- `created_at`.

HTTP mutation rules:

- Create job requires `Idempotency-Key`.
- Start job requires `Idempotency-Key`.
- Start job requires `If-Match`.
- Missing `If-Match` returns `428 PRECONDITION_REQUIRED`.
- Stale/mismatched `If-Match` returns `412 JOB_VERSION_CONFLICT`.
- Same idempotency key plus same request checksum replays the stored result.
- Same idempotency key plus different request checksum returns `409 IDEMPOTENCY_CONFLICT`.

## 12. Commands

Backend setup:

```powershell
py -m pip install -e .[test]
```

Backend verification:

```powershell
py -m pytest -q tests/control_tower
py -m pytest -q tests/orchestrator/test_full_sandbox_migration.py::test_read_only_resume_approved_records_decision_and_does_not_run_transform
py -m pytest -q
git diff --check
git diff --cached --check
```

Frontend verification:

```powershell
cd web/control-tower
npm ci
npm run type-check
npm test
npm run build
npm audit --audit-level=moderate
```

## 13. Baseline comparison evidence

Targeted orchestrator test requested by review:

```powershell
py -m pytest -q tests/orchestrator/test_full_sandbox_migration.py::test_read_only_resume_approved_records_decision_and_does_not_run_transform
```

Clean `DEMO2` at `521d7b4`, run from temporary detached worktree:

```text
1 passed in 6.30s
```

Fix branch `fix/amf-148-150-review-findings`:

```text
1 passed in 5.56s
```

Classification: this exact test is not a current failure on either branch. It is neither proven pre-existing nor a branch regression in this environment.

## 14. Conflicts and decisions

Conflict: M2 plan requires Windows Job Object process-control evidence, but this repository has no reusable M0 Job Object implementation or tests.

- Decision: process-control implementation remains deferred. M2-06/M2-08 need reviewer direction before coding Job Object behavior.

Conflict: M2 plan was written as horizontal M2-00 through M2-13 work, but AMF-149/150 have already landed vertical tracer bullets.

- Decision: AMF-149/150 implementations are current baseline. Later M2 tasks extend them and do not duplicate them.

Conflict: repository now has FastAPI/SSE/frontend code, while older M2-00 inventory said they were absent.

- Decision: this document records current repository state. FastAPI/SSE/frontend are implemented and dependency/workspace files are declared.

Conflict: full repository tests may fail outside Control Tower.

- Decision: run and report exact full-suite evidence for this branch. Fix only regressions caused by AMF-148/149/150 review changes.
