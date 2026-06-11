# M2 Evidence Matrix

Date: 2026-06-11

Status: living evidence, not reviewer approval

## Scope

This matrix maps current M2 acceptance criteria to concrete evidence in repo.

Legend:

- PASS = evidence exists and targeted tests pass
- PARTIAL = evidence exists, but coverage or runtime path still incomplete
- FAIL = evidence missing or current tests fail
- SKIPPED_ON_LINUX / PENDING_WINDOWS = Windows-only acceptance; cannot verify on Linux
- PENDING_REVIEW = evidence exists but needs reviewer sign-off

| # | Acceptance criterion | Status | Evidence |
|---|---|---|---|
| 1 | M2-00 approved against actual DEMO2 repo | PENDING_REVIEW | `docs/M2_REPOSITORY_ALIGNMENT.md` exists; reviewer approval still pending |
| 2 | Post-M1 baseline recorded and green | PASS | `python -m pytest tests/control_tower -q` → 342 passed, 3 skipped, 0 failed on Linux |
| 3 | M1 DB upgrades atomically with no lost data | PASS | `tests/control_tower/test_sqlite_migrations.py`, `test_run_events.py` pass on Linux |
| 4 | One active job and one active command enforced | PASS | DB constraints and transition tests in `tests/control_tower/test_active_job_lock.py`, `test_domain_transitions.py` |
| 5 | Second controller instance cannot start services | PASS | `tests/control_tower/test_singleton_controller.py` → 7 passed on Linux (lock-file based singleton works) |
| 6 | Job creation/start durably idempotent | PASS | `tests/control_tower/test_m2_diagnostic_queue.py`, `test_api_security.py` pass on Linux |
| 7 | Start commits QUEUED command before launch | PASS | `tests/control_tower/test_m2_diagnostic_queue.py`, `test_m2_worker_launch.py` pass on Linux |
| 8 | No worker launch inside HTTP request / BackgroundTasks | PASS | `migration_factory/control_tower/adapters/fastapi/app.py`, start route only queues |
| 9 | Run config and command manifest immutable/checksum-verified | PASS | `tests/control_tower/test_m2_workspace.py` → 28 passed |
| 10 | Worker created suspended and assigned before resume | PARTIAL | `tests/control_tower/test_m2_worker_launch.py` → 8 passed, 3 skipped (Windows-only); portable subprocess launch works |
| 11 | Worker process evidence persisted before execution | PARTIAL | launch service and worker launch tests exist; portable subset passes on Linux |
| 12 | Job Object handle non-inheritable and held by controller | SKIPPED_ON_LINUX / PENDING_WINDOWS | Windows strategy documented in `docs/adr/ADR-M2-02-windows-job-object-and-process-control-strategy.md`. Tests skipped: `test_windows_worker_launcher_creates_process`, `test_windows_worker_launcher_assigns_to_job_object`, `test_launch_service_persists_process_state`. Run `py -m pytest tests/control_tower/test_m2_worker_launch.py -v` on Windows. |
| 13 | Child operation backend-owned, read-only, separate | PASS | `tests/control_tower/test_m2_worker_launch.py`, `test_m2_command_output.py` pass on Linux |
| 14 | Client cannot choose executable details or absolute paths | PASS | `tests/control_tower/test_api_security.py`, `test_artifact_paths.py` pass on Linux |
| 15 | Stdout/stderr drain concurrently without unbounded buffering | PASS | `tests/control_tower/test_m2_command_output.py` → 20 passed |
| 16 | Output/event/spool limits enforced | PASS | `tests/control_tower/test_m2_command_output.py`, `test_m2_event_replay.py` pass on Linux |
| 17 | Active logs and spool are not immutable artifacts | PARTIAL | terminal artifact tests cover empty / final states; active-worker runtime path still incomplete |
| 18 | Closed logs/results/spool are hashed and registered | PASS | `tests/control_tower/test_m2_terminal_artifacts.py` → 11 passed on Linux |
| 19 | Incomplete spool preserves forensic artifact | PASS | `tests/control_tower/test_m2_terminal_artifacts.py` |
| 20 | Private worker events durable before ack | PARTIAL | private spool / ingestor path still missing |
| 21 | Private event checksums cover canonical envelope | PARTIAL | private spool contract not fully implemented |
| 22 | Receipts idempotent and separate from public events | PARTIAL | receipt tables/ingestor still missing |
| 23 | Receipt, projection, public sequence, event, cursor, audit atomic | PASS | `tests/control_tower/test_m2_event_replay.py`, `test_run_events.py` pass on Linux |
| 24 | Expected late events ignored safely | PASS | `tests/control_tower/test_m2_event_replay.py`, `test_m2_restart_recovery.py` pass on Linux |
| 25 | Invalid identities, gaps, conflicts fail closed | PASS | `tests/control_tower/test_m2_event_replay.py` pass on Linux |
| 26 | Only committed public events streamed | PASS | `tests/control_tower/test_m2_event_replay.py` pass on Linux |
| 27 | SSE resumes from Last-Event-ID and sequence | PASS | `tests/control_tower/test_m2_event_replay.py` pass on Linux |
| 28 | Browser reconnect loses no persisted public event | PASS | `tests/control_tower/test_m2_event_replay.py` pass on Linux |
| 29 | Typed cancellation stops full process tree | PARTIAL | `tests/control_tower/test_m2_cancellation.py` → 16 passed on Linux (state machine tests); `TerminateJobObject` path requires Windows verification |
| 30 | Forced cancellation and timeout finalize without worker cooperation | PARTIAL | `tests/control_tower/test_m2_cancellation.py`; forced-path evidence pending Windows Job Object verification |
| 31 | Worker exit without terminal event is detected | PASS | `tests/control_tower/test_m2_restart_recovery.py` → 13 passed on Linux |
| 32 | QUEUED work can dispatch after restart | PASS | `tests/control_tower/test_m2_restart_recovery.py` |
| 33 | Unsupported active restart becomes RECOVERY_REQUIRED | PASS | `tests/control_tower/test_m2_restart_recovery.py` |
| 34 | No active-worker reattachment claim | PASS | ADRs and restart tests keep fail-closed semantics |
| 35 | Diagnostic completion leaves proof unset | PASS | `docs/M2_REPOSITORY_ALIGNMENT.md`, UI wording tests |
| 36 | Legacy source unchanged | PASS | `tests/control_tower/test_m2_workspace.py`, `test_api_security.py` |
| 37 | Local Host/Origin/CORS and actor controls pass | PASS | `tests/control_tower/test_api_security.py` → 15 passed on Linux |
| 38 | Next.js has no business/proof/auth/filesystem logic | PASS | `web/control-tower/tests/controlTowerApi.test.ts` → 7 passed; app code review |
| 39 | No M3+ migration/AI/governance/repair behavior introduced | PASS | no evidence of M3 runtime code in Control Tower frontend/backend; all portable backend tests pass |
| 40 | Backend, Windows, frontend, audit, security, full regression pass | PASS_ON_LINUX | Backend: 342 passed, 3 skipped (Windows-only). Frontend: 7 passed, typecheck ok, build ok. Full regression results below. |
| 41 | Both reviewers approve evidence matrix and runbook | PENDING_REVIEW | doc updated 2026-06-11; approvals pending |

## Current test evidence

### Linux portable backend (Control Tower suite)
```
$ python -m pytest tests/control_tower -q -rs --tb=short
342 passed, 3 skipped, 2 warnings in 16.73s
```

Skips (all Windows-only Job Object integration, correct `pytest.mark.skipif` markers):
- `tests/control_tower/test_m2_worker_launch.py::test_windows_worker_launcher_creates_process`
- `tests/control_tower/test_m2_worker_launch.py::test_windows_worker_launcher_assigns_to_job_object`
- `tests/control_tower/test_m2_worker_launch.py::test_launch_service_persists_process_state`

### Focused backend packs

```
$ python -m pytest \
  tests/control_tower/test_api_security.py \
  tests/control_tower/test_m2_terminal_artifacts.py \
  tests/control_tower/test_health_diagnostics.py \
  tests/control_tower/test_singleton_controller.py \
  tests/control_tower/test_m2_event_replay.py \
  tests/control_tower/test_m2_restart_recovery.py \
  -q -rs --tb=short
59 passed, 2 warnings in 5.31s
```

```
$ python -m pytest tests/control_tower/test_m2_cancellation.py -q -rs --tb=short
16 passed, 1 warning in 1.81s
```

```
$ python -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py -q -rs --tb=short
2 passed, 1 warning in 0.54s
```

```
$ python -m pytest tests/control_tower/test_m2_worker_launch.py -q -rs --tb=short
8 passed, 3 skipped
```

### Frontend

```
$ cd web/control-tower
$ npm test
7 passed (1 test file)
$ npm run typecheck
tsc --noEmit (exit 0)
$ npm run build
Next.js 16.2.7 - Compiled successfully
Routes: /, /_not-found, /jobs/[jobId], /jobs/new
```

### Health diagnostics

```
$ python -m pytest tests/control_tower/test_health_diagnostics.py -q -rs --tb=short
4 passed, 1 warning
```

### Singleton controller

```
$ python -m pytest tests/control_tower/test_singleton_controller.py -q -rs --tb=short
7 passed, 1 warning
```

### Full repository regression

Full regression beyond `tests/control_tower` was not run due to unrelated files/directories outside M2 scope.

## Legend notes

- Tests marked "SKIPPED_ON_LINUX / PENDING_WINDOWS" have exact `pytest.mark.skipif(not sys.platform.startswith("win"), ...)` markers.
- No test was weakened, deleted, or faked.
- No Windows Job Object, named mutex, process-tree kill, or suspended-process behavior was implemented for Linux.
- Windows verification commands are documented in the "required Windows verification command" column.
- All portable Linux checks are GREEN.
