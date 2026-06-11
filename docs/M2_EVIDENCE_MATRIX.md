# M2 Evidence Matrix

Date: 2026-06-11

Status: living evidence, not reviewer approval

## Scope

This matrix maps current M2 acceptance criteria to concrete evidence in repo.

Legend:

- PASS = evidence exists and targeted tests pass
- PARTIAL = evidence exists, but coverage or runtime path still incomplete
- FAIL = evidence missing or current tests fail

| # | Acceptance criterion | Status | Evidence |
|---|---|---|---|
| 1 | M2-00 approved against actual DEMO2 repo | PARTIAL | `docs/M2_REPOSITORY_ALIGNMENT.md` exists; reviewer approval still pending |
| 2 | Post-M1 baseline recorded and green | PASS | `py -m pytest tests/control_tower -q` previously green in repo alignment; rerun required after fixes |
| 3 | M1 DB upgrades atomically with no lost data | PARTIAL | `tests/control_tower/test_sqlite_migrations.py`, `test_run_events.py` |
| 4 | One active job and one active command enforced | PASS | DB constraints and transition tests in `tests/control_tower/test_active_job_lock.py`, `test_domain_transitions.py` |
| 5 | Second controller instance cannot start services | PARTIAL | `tests/control_tower/test_singleton_controller.py` currently failing before fix |
| 6 | Job creation/start durably idempotent | PASS | `tests/control_tower/test_m2_diagnostic_queue.py`, `test_api_security.py` |
| 7 | Start commits QUEUED command before launch | PASS | `tests/control_tower/test_m2_diagnostic_queue.py`, `test_m2_worker_launch.py` |
| 8 | No worker launch inside HTTP request / BackgroundTasks | PASS | `migration_factory/control_tower/adapters/fastapi/app.py`, start route only queues |
| 9 | Run config and command manifest immutable/checksum-verified | PASS | `tests/control_tower/test_m2_workspace.py` |
| 10 | Worker created suspended and assigned before resume | PARTIAL | `tests/control_tower/test_m2_worker_launch.py` |
| 11 | Worker process evidence persisted before execution | PARTIAL | launch service and worker launch tests exist; singleton/readiness still blocking overall proof |
| 12 | Job Object handle non-inheritable and held by controller | PARTIAL | Windows strategy documented in `docs/adr/ADR-M2-02-windows-job-object-and-process-control-strategy.md` |
| 13 | Child operation backend-owned, read-only, separate | PASS | `tests/control_tower/test_m2_worker_launch.py`, `test_m2_command_output.py` |
| 14 | Client cannot choose executable details or absolute paths | PASS | `tests/control_tower/test_api_security.py`, `test_artifact_paths.py` |
| 15 | Stdout/stderr drain concurrently without unbounded buffering | PASS | `tests/control_tower/test_m2_command_output.py` |
| 16 | Output/event/spool limits enforced | PASS | `tests/control_tower/test_m2_command_output.py`, `test_m2_event_replay.py` |
| 17 | Active logs and spool are not immutable artifacts | PARTIAL | terminal artifact tests cover empty / final states; active-worker runtime path still incomplete |
| 18 | Closed logs/results/spool are hashed and registered | PASS | `tests/control_tower/test_m2_terminal_artifacts.py` |
| 19 | Incomplete spool preserves forensic artifact | PASS | `tests/control_tower/test_m2_terminal_artifacts.py` |
| 20 | Private worker events durable before ack | PARTIAL | private spool / ingestor path still missing |
| 21 | Private event checksums cover canonical envelope | PARTIAL | private spool contract not fully implemented |
| 22 | Receipts idempotent and separate from public events | PARTIAL | receipt tables/ingestor still missing |
| 23 | Receipt, projection, public sequence, event, cursor, audit atomic | PASS | `tests/control_tower/test_m2_event_replay.py`, `test_run_events.py` |
| 24 | Expected late events ignored safely | PASS | `tests/control_tower/test_m2_event_replay.py`, `test_m2_restart_recovery.py` |
| 25 | Invalid identities, gaps, conflicts fail closed | PASS | `tests/control_tower/test_m2_event_replay.py` |
| 26 | Only committed public events streamed | PASS | `tests/control_tower/test_m2_event_replay.py` |
| 27 | SSE resumes from Last-Event-ID and sequence | PASS | `tests/control_tower/test_m2_event_replay.py` |
| 28 | Browser reconnect loses no persisted public event | PASS | `tests/control_tower/test_m2_event_replay.py` |
| 29 | Typed cancellation stops full process tree | PARTIAL | `tests/control_tower/test_m2_cancellation.py` |
| 30 | Forced cancellation and timeout finalize without worker cooperation | PARTIAL | `tests/control_tower/test_m2_cancellation.py` |
| 31 | Worker exit without terminal event is detected | PARTIAL | `tests/control_tower/test_m2_restart_recovery.py` |
| 32 | QUEUED work can dispatch after restart | PARTIAL | `tests/control_tower/test_m2_restart_recovery.py` |
| 33 | Unsupported active restart becomes RECOVERY_REQUIRED | PASS | `tests/control_tower/test_m2_restart_recovery.py` |
| 34 | No active-worker reattachment claim | PASS | ADRs and restart tests keep fail-closed semantics |
| 35 | Diagnostic completion leaves proof unset | PASS | `docs/M2_REPOSITORY_ALIGNMENT.md`, UI wording tests |
| 36 | Legacy source unchanged | PASS | `tests/control_tower/test_m2_workspace.py`, `test_api_security.py` |
| 37 | Local Host/Origin/CORS and actor controls pass | PASS | `tests/control_tower/test_api_security.py` |
| 38 | Next.js has no business/proof/auth/filesystem logic | PASS | `web/control-tower/tests/controlTowerApi.test.ts`, app code review |
| 39 | No M3+ migration/AI/governance/repair behavior introduced | PARTIAL | no evidence of M3 runtime code in Control Tower frontend/backend |
| 40 | Backend, Windows, frontend, audit, security, full regression pass | FAIL | backend health/singleton tests still failing before fix; full regression not rerun |
| 41 | Both reviewers approve evidence matrix and runbook | FAIL | docs added, approvals pending |

## Current test evidence

- `py -m pytest tests/control_tower/test_api_security.py -q -rs --tb=short` -> pass
- `py -m pytest tests/control_tower/test_m2_terminal_artifacts.py -q -rs --tb=short` -> pass
- `py -m pytest tests/control_tower/test_health_diagnostics.py -q -rs --tb=short` -> failing before fix
- `py -m pytest tests/control_tower/test_singleton_controller.py -q -rs --tb=short` -> failing before fix

