# M2 Repository Alignment and Manual Vertical Slice Evidence

Date inspected: 2026-06-11

Integration base: `DEMO2` at `fc0bb49`

Issue branch: `DEMO2`

Working feature frozen for this pass: **Foundation Diagnostic Run from UI**

This document compares `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md` sections 0 through 31 against the current repository. It also records the manual-testable slice now available through the Next.js UI and FastAPI API. Graphify was used first for repository exploration, then all findings were confirmed against source and tests.

## 1. Source Of Truth Files

Inspected sources, in priority order:

- `AGENTS.md`
- `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`
- `docs/M2_REPOSITORY_ALIGNMENT.md`
- `docs/adr/ADR-M2-01-fastapi-and-sse-adapter-strategy.md`
- `docs/adr/ADR-M2-02-windows-job-object-and-process-control-strategy.md`
- `docs/adr/ADR-M2-03-public-event-type-persistence-strategy.md`
- `docs/adr/ADR-M2-04-nextjs-and-nodejs-workspace-version-strategy.md`
- `docs/adr/ADR-M2-05-single-control-tower-controller-instance-strategy.md`
- `migration_factory/control_tower/**`
- `tests/control_tower/**`
- `web/control-tower/**`

No nested `AGENTS.md` files were found under `docs/`, `migration_factory/`, `tests/`, or `web/control-tower/`.

## 2. Repository Evidence Snapshot

Implemented backend files found:

- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/application/commands.py`
- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/application/queries.py`
- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/domain/commands.py`
- `migration_factory/control_tower/domain/entities.py`
- `migration_factory/control_tower/domain/errors.py`
- `migration_factory/control_tower/domain/manifests.py`
- `migration_factory/control_tower/domain/states.py`
- `migration_factory/control_tower/domain/transitions.py`
- `migration_factory/control_tower/infrastructure/worker_launcher.py`
- `migration_factory/control_tower/infrastructure/workspace.py`
- `migration_factory/control_tower/adapters/fastapi/dev_app.py`
- `migration_factory/control_tower/infrastructure/sqlite/connection.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0003_m2_workspace_and_manifests.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0004_m2_controlled_worker_launch.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0005_m2_command_output.sql`
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0006_m2_terminal_artifacts.sql`

Implemented frontend files found:

- `web/control-tower/app/page.tsx`
- `web/control-tower/app/jobs/new/page.tsx`
- `web/control-tower/app/jobs/new/CreateDiagnosticJobForm.tsx`
- `web/control-tower/app/jobs/[jobId]/page.tsx`
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx`
- `web/control-tower/app/jobs/[jobId]/StartDiagnosticJobButton.tsx`
- `web/control-tower/app/globals.css`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/lib/eventReplay.ts`
- `web/control-tower/package.json`
- `web/control-tower/package-lock.json`

Tests found:

- `tests/control_tower/test_fastapi_diagnostic_queue.py`
- `tests/control_tower/test_m2_diagnostic_queue.py`
- `tests/control_tower/test_m2_event_replay.py`
- `tests/control_tower/test_m2_workspace.py`
- `tests/control_tower/test_m2_worker_launch.py`
- `tests/control_tower/test_m2_command_output.py`
- `tests/control_tower/test_m2_cancellation.py`
- `tests/control_tower/test_m2_restart_recovery.py`
- `tests/control_tower/test_m2_terminal_artifacts.py`
- `tests/control_tower/test_sqlite_migrations.py`
- `web/control-tower/tests/controlTowerApi.test.ts`

## 3. Frozen Manual-Test Feature

Feature name: **Foundation Diagnostic Run from UI**

Smallest useful flow now available:

1. User opens Next.js at `http://127.0.0.1:3000`.
2. User opens `/jobs/new`.
3. UI loads runner profiles, pipelines, and safe root IDs from FastAPI.
4. User submits profile, pipeline, source relative path, and output relative path.
5. FastAPI persists a diagnostic job and immutable M1 run configuration through application services.
6. User opens `/jobs/{jobId}`.
7. User starts the job.
8. FastAPI persists a queued backend-owned `foundation_diagnostic` command and returns without launching a worker.
9. UI shows job state, ETag/version, active command, event stream connection status, public event timeline, stdout/stderr windows with byte offsets, cancel button, and artifact metadata panel.
10. UI wording uses `Foundation diagnostic` and never claims `Migration completed`, `Build verified`, `Spring Boot upgraded`, or `Proof achieved`.

Important limitation:

- A durable dispatcher/ingestor process is not wired into FastAPI lifespan yet. The existing `/v1/jobs/{job_id}/launch` and `/v1/jobs/{job_id}/finalize` routes are internal/manual non-production routes. They are not used by the frontend and remain documented as a gap until M2 dispatcher/ingestor ownership is implemented.

## 4. FastAPI Endpoint Readiness

Current required endpoint status:

| Endpoint | Status | Evidence |
|---|---|---|
| `GET /v1/health/live` | Implemented | `migration_factory/control_tower/adapters/fastapi/app.py` |
| `GET /v1/health/ready` | Partially implemented | Checks database; reports dispatcher/singleton as `not_configured` |
| `GET /v1/runner-profiles` | Implemented | Existing query over registered profiles |
| `GET /v1/pipelines` | Implemented | Existing query over registered pipelines |
| `POST /v1/jobs` | Implemented | `DiagnosticJobService.create_diagnostic_job` |
| `GET /v1/jobs` | Implemented | Lists persisted jobs through `ControlTowerQueryService` |
| `GET /v1/jobs/{job_id}` | Implemented | Returns projection and ETag |
| `POST /v1/jobs/{job_id}/start` | Implemented | Queues command, no worker launch in route |
| `POST /v1/jobs/{job_id}/cancel` | Implemented | Uses `CancelService` |
| `GET /v1/jobs/{job_id}/commands` | Implemented | Lists command executions for a job |
| `GET /v1/jobs/{job_id}/commands/{command_id}/logs/stdout` | Implemented | Alias for bounded stdout window |
| `GET /v1/jobs/{job_id}/commands/{command_id}/logs/stderr` | Implemented | Alias for bounded stderr window |
| `GET /v1/jobs/{job_id}/events` | Implemented | Committed public event replay |
| `GET /v1/jobs/{job_id}/events/stream` | Implemented | SSE replay of committed public events |
| `GET /v1/jobs/{job_id}/artifacts` | Implemented | Lists registered artifact metadata |

Existing internal/non-production endpoints:

- `POST /v1/jobs/{job_id}/launch`
- `POST /v1/jobs/{job_id}/finalize`
- `POST /v1/jobs/{job_id}/timeout`

These routes are useful for internal/manual development but do not satisfy the durable dispatcher requirement because route handlers can invoke lifecycle services directly.

## 5. Section-By-Section M2 Status

| Plan section | Repo status | Exact files found | Exact tests found | Next work required |
|---|---|---|---|---|
| 0. Readiness Verdict | Partially implemented, conflicting with older alignment text because production files now exist | `docs/M2_REPOSITORY_ALIGNMENT.md`, ADRs, Control Tower source | `tests/control_tower/**` | Reviewer approval and updated evidence matrix still required |
| 1. M2 Purpose | Partially implemented | FastAPI, SQLite, Next.js, command services, workspace, launch, logs, artifacts | `test_fastapi_diagnostic_queue.py`, `test_m2_worker_launch.py`, `test_m2_command_output.py`, `test_m2_terminal_artifacts.py` | Durable dispatcher, private event ingestion, worker completion path |
| 2. Locked M2 Architecture | Partially implemented | `app.py`, services, SQLite UoW, `worker_launcher.py`, Next app | Same as section 1 | Add dispatcher, ingestor, monitor, singleton ownership |
| 3. Latest Technology Baseline | Partially implemented | `pyproject.toml`, `web/control-tower/package.json` | frontend build/typecheck, backend suite | Confirm runtime dependency diagnostics endpoint |
| 4. M2-00 Repository Alignment | Implemented as living evidence, but reviewer approval pending | This document, ADRs | Control Tower and frontend checks | Keep this document current after each M2 slice |
| 5. Critical Invariants | Partially implemented | `states.py`, `commands.py`, `services.py`, SQLite migrations | `test_active_job_lock.py`, `test_m2_diagnostic_queue.py`, `test_m2_worker_launch.py` | API singleton guard and full persist-before-resume acceptance evidence |
| 6. Domain Contracts | Implemented for job/command states used so far | `domain/states.py`, `domain/commands.py`, `domain/transitions.py` | `test_domain_transitions.py`, `test_m2_cancellation.py` | Complete late-event authority via private ingestor |
| 7. Immutable Manifests | Partially implemented | `domain/manifests.py`, `CommandWorkspaceService` | `test_m2_workspace.py`, `test_m2_worker_launch.py` | Wire manifest creation into dispatcher path |
| 8. Persistence Extension | Partially implemented | migrations `0002` through `0006`, repositories, UoW | `test_sqlite_migrations.py`, M2 tests | Add worker event stream and receipt tables |
| 9. Safe Workspace Lifecycle | Implemented for current workspace/manifest service | `application/services.py`, `infrastructure/workspace.py` | `test_m2_workspace.py` | Validate with full dispatcher and crash-window cases |
| 10. Durable Start and Two-Phase Launch | Partially implemented | `DiagnosticJobService`, `WorkerLaunchService` | `test_m2_diagnostic_queue.py`, `test_m2_worker_launch.py` | Durable dispatcher claim loop and route-free launch path |
| 11. API Singleton, Dispatcher, Ingestor, Monitor | Missing/partial | Reconciliation exists; no singleton/dispatcher/ingestor service found | `test_m2_restart_recovery.py` | Implement process-lifetime singleton, dispatcher, ingestor, monitor |
| 12. Diagnostic Worker and Child Operation | Partially implemented | `infrastructure/worker_launcher.py` inline diagnostic worker | `test_m2_worker_launch.py` | Replace inline diagnostic with durable worker module and child operation contract |
| 13. Output Capture | Partially implemented | output query windows and migrations | `test_m2_command_output.py` | Connect real worker stdout/stderr capture and offset advancement |
| 14. Worker Event Spool | Mostly missing | terminal artifact code can preserve spool files | `test_m2_terminal_artifacts.py` | Implement private JSONL envelope, writer, reader, checksums, receipts |
| 15. Event Ingestion and Late-Event Rules | Mostly missing | public event tables and replay exist | `test_m2_event_replay.py`, `test_m2_cancellation.py` | Implement private event ingestor and late-event disposition rules |
| 16. Terminal Finalization and Forensic Artifacts | Partially implemented | `CommandFinalizationService`, artifact registry | `test_m2_terminal_artifacts.py` | Wire finalization to monitor/ingestor instead of manual route |
| 17. Cancellation and Timeout | Partially implemented | `CancelService`, `TimeoutService`, terminator ports | `test_m2_cancellation.py` | Integrate with real process monitor and Job Object termination evidence |
| 18. Startup and Crash Semantics | Partially implemented | `ReconciliationService` | `test_m2_restart_recovery.py` | Cover full crash windows and unsupported active restart policy |
| 19. HTTP API Contract | Partially implemented and improved in this pass | `app.py`, `queries.py`, frontend API client | FastAPI tests and frontend tests | Add artifact metadata-by-id and dependency health if required |
| 20. Optimistic Concurrency and Idempotency | Implemented for create/start/cancel surface used now | `DiagnosticJobService`, `CancelService`, `app.py` | `test_m2_diagnostic_queue.py`, `test_m2_cancellation.py` | Verify every mutation follows same contract |
| 21. Native SSE Contract | Implemented for committed public event replay | `app.py`, `queries.py`, `eventReplay.ts` | `test_m2_event_replay.py`, frontend tests | Add max-client/dependency diagnostics evidence to runbook |
| 22. Local Security | Partially implemented | strict request models, safe roots, no frontend command construction | FastAPI queue/event tests | Bind/Host/Origin/CORS guard not yet evident in app factory |
| 23. Next.js Implementation | Partially implemented and improved in this pass | `web/control-tower/app/**`, `lib/**` | `web/control-tower/tests/controlTowerApi.test.ts` | Generated OpenAPI/shared contracts are still absent |
| 24. Initial M2 Limits | Partially implemented | SSE config, log max bytes query limits | `test_m2_event_replay.py`, `test_m2_command_output.py` | Centralize all limits and boundary tests |
| 25. Standard Error Contract | Partially implemented | `_error`, `_raise_http_error` | FastAPI tests | Redact all internal/manual route errors and add correlation IDs |
| 26. Observability | Mostly missing | some structured payload fields exist | No dedicated observability tests found | Add dependency diagnostics, counters, structured logs |
| 27. Jira Work Breakdown | Partially implemented across vertical slices | M2 source/tests listed above | M2 tests | Continue through dispatcher, ingestion, monitor, frontend acceptance |
| 28. Test Strategy | Partially implemented | tests listed in section 2 | 316 Control Tower tests | Add missing spool/ingestion/security/crash-window/browser acceptance tests |
| 29. Acceptance Criteria | Not fully met | Many components exist | Current tests pass | Full M2 acceptance still blocked by dispatcher/ingestor/singleton/private spool |
| 30. Definition of Done | Not met | Evidence in this document | Current verification below | Reviewer approval, full suite, runbook, audits, missing M2 services |
| 31. Final Implementation Order | Partially followed, now vertical-slice driven | current source tree | current tests | Freeze generated contracts and finish backend runtime before claiming M2 |

## 6. Manual Test Steps

Start FastAPI on loopback:

```powershell
$env:CONTROL_TOWER_DEV_ROOT="$PWD\.control-tower-dev"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000
```

The dev ASGI module applies pending SQLite migrations and seeds a local runner profile and pipeline when the configured dev database is empty. Do not bind to `0.0.0.0`.

Start Next.js on loopback:

```powershell
cd web/control-tower
$env:NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open:

```text
http://127.0.0.1:3000/jobs/new
```

Manual UI flow:

1. Select runner profile.
2. Select pipeline.
3. Select source root and output root.
4. Enter source relative path such as `src`.
5. Enter output relative path such as `out`.
6. Create the foundation diagnostic job.
7. On `/jobs/{jobId}`, confirm ETag/version, status cards, SSE connection status, and public events.
8. Click `Start`.
9. Confirm command state becomes `QUEUED`, public events advance, stdout/stderr panes remain offset-aware, and artifacts panel is empty until terminal finalization.
10. Click `Cancel` while the command is active to exercise the cancellation API.

Internal/manual backend-only routes that are not production dispatcher behavior:

```http
POST /v1/jobs/{job_id}/launch
POST /v1/jobs/{job_id}/finalize
POST /v1/jobs/{job_id}/timeout
```

## 7. Verification Results

Baseline before edits:

```text
python -m pytest tests/control_tower -q
```

Result:

```text
python : The term 'python' is not recognized as the name of a cmdlet, function, script file, or operable program.
```

Windows launcher fallback:

```text
py -m pytest tests/control_tower -q
316 passed, 2 skipped, 1 warning in 34.65s
```

Focused backend verification after edits:

```text
py -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py tests/control_tower/test_m2_command_output.py -q
22 passed, 1 warning in 3.62s
```

Dev ASGI bootstrap compile check:

```text
py -m py_compile migration_factory/control_tower/adapters/fastapi/dev_app.py
```

Focused FastAPI verification after adding the dev bootstrap:

```text
py -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py -q
2 passed, 1 warning in 0.50s
```

Required backend verification after edits:

```text
py -m pytest tests/control_tower -q
316 passed, 2 skipped, 1 warning in 25.83s
```

Frontend install:

```text
npm install
up to date, audited 68 packages in 2s
found 0 vulnerabilities
```

Frontend typecheck:

```text
npm run typecheck
> @modernizer/control-tower-web@0.1.0 typecheck
> tsc --noEmit
```

Frontend tests:

```text
npm test
Test Files  1 passed (1)
Tests  5 passed (5)
Duration  657ms
```

Frontend build:

```text
npm run build
Next.js 16.2.7 (Turbopack)
Compiled successfully
Route (app)
┌ ○ /
├ ○ /_not-found
├ ƒ /jobs/[jobId]
└ ƒ /jobs/new
```

## 8. Remaining Gaps Vs M2 Plan

M2 is not complete. Remaining gaps:

- No production durable dispatcher loop in FastAPI lifespan.
- No API/controller singleton guard.
- No private worker event spool schema, writer, reader, receipt, and ingestor path.
- No process monitor that owns timeout/finalization after worker exit.
- No generated OpenAPI TypeScript contracts; frontend uses local TypeScript contract definitions.
- Host, Origin, exact CORS, and mutation client-header enforcement are not evident in the FastAPI app factory.
- Dependency diagnostics endpoint is not implemented.
- `GET /v1/jobs/{job_id}/artifacts/{artifact_id}/metadata` is still missing, though `GET /v1/jobs/{job_id}/artifacts` is implemented.
- Internal `/launch`, `/finalize`, and `/timeout` routes must not be treated as the production M2 runtime path.
- Full private/public event separation is not proven until private events and receipts exist.
- Full Windows Job Object acceptance evidence depends on Windows-only tests and reviewer approval.
- Full repository suite beyond `tests/control_tower` was not run in this pass.

## 9. Files Changed In This Pass

- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/adapters/fastapi/dev_app.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/application/queries.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `tests/control_tower/test_fastapi_diagnostic_queue.py`
- `web/control-tower/app/globals.css`
- `web/control-tower/app/jobs/[jobId]/CurrentRunClient.tsx`
- `web/control-tower/lib/contracts.ts`
- `web/control-tower/lib/controlTowerApi.ts`
- `web/control-tower/lib/eventReplay.ts`
- `web/control-tower/package.json`
- `docs/M2_REPOSITORY_ALIGNMENT.md`

## 10. Commit Recommendation

Do not commit automatically unless explicitly requested by the user. Recommended local commit subject if approved:

```text
feat(m2): expose foundation diagnostic manual slice
```

Nothing has been pushed.
