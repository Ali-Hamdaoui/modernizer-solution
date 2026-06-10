# AMF-156 - [Control Tower] M2-08 - Fail closed after restart or uncertain active execution

## 1. Issue source
- Jira key: AMF-156
- Jira title: [Control Tower] M2-08 - Fail closed after restart or uncertain active execution
- Jira status: In Progress
- Exact acceptance criteria:
  - Startup reconciliation runs only after singleton ownership acquired.
  - Terminal jobs remain queryable/replayable after restart.
  - Untouched QUEUED command remains eligible for one safe dispatch and cannot launch twice after restart.
  - STARTING, RUNNING, CANCELLING, and uncertain launch states transition to RECOVERY_REQUIRED.
  - Reconciliation uses application transition and audit rules.
  - System does not attach to stored PID or silently relaunch uncertain command.
  - Existing logs, result files, and spool preserved; incomplete closed spool can later be forensic evidence.
  - Public API exposes recovery-required state and non-sensitive reason.
  - UI displays fail-closed recovery message and presents no resume/recover control in M2.
  - Recovery-required job remains nonterminal and occupies active slot.
  - Readiness remains healthy when service works but domain job requires recovery.
  - Browser reconnect after service restart replays public events.
  - Documentation states active-worker reattachment belongs to M3.
- Dependencies: AMF-152, AMF-153, AMF-155
- Non-goals:
  - Heartbeat
  - Lease expiry
  - Orphan threshold
  - Worker reattachment
  - LangGraph checkpoint reconciliation
  - Resume/recover action
- Comments or attached notes: none returned in Jira search

## 2. Current repository context
- Relevant files:
  - `migration_factory/control_tower/application/services.py`
  - `migration_factory/control_tower/application/queries.py`
  - `migration_factory/control_tower/application/dto.py`
  - `migration_factory/control_tower/application/commands.py`
  - `migration_factory/control_tower/adapters/fastapi/app.py`
  - `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
  - `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py`
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql`
  - `tests/control_tower/test_m2_event_replay.py`
  - `tests/control_tower/test_fastapi_diagnostic_queue.py`
  - `tests/control_tower/test_active_job_lock.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_m1_acceptance.py`
- Relevant services/classes:
  - `DiagnosticJobService`
  - `ControlTowerQueryService`
  - `ControlTowerRegistrationService`
  - `SqliteMigrationJobRepository`
  - `SqliteCommandExecutionRepository`
  - `SqliteRunEventRepository`
- Relevant repositories/migrations:
  - `SqliteMigrationJobRepository`
  - `SqliteCommandExecutionRepository`
  - `SqliteRunEventRepository`
  - `SqliteAuditRecordRepository`
  - `0002_m2_queued_diagnostic.sql`
- Relevant FastAPI routes:
  - `GET /v1/jobs/{job_id}`
  - `GET /v1/jobs/{job_id}/events`
  - `GET /v1/jobs/{job_id}/events/stream`
  - `GET /v1/health/ready` if a readiness route is added or already exists in later work
  - no restart-reconciliation route exists yet
- Relevant tests:
  - `tests/control_tower/test_m2_event_replay.py`
  - `tests/control_tower/test_fastapi_diagnostic_queue.py`
  - `tests/control_tower/test_active_job_lock.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_m1_acceptance.py`
- Graphify queries used:
  - `Which services handle command execution lifecycle?`
  - `Which services update command execution state?`
  - `Which tests cover diagnostic worker launch and command execution?`
  - `Which repositories persist command executions and artifacts?`
  - `Which FastAPI routes expose Control Tower command execution?`
  - `WorkerLaunchService -> SqliteControlTowerUnitOfWork`
  - `CommandWorkspaceService`
- What Graphify suggested:
  - The restart problem sits on top of the current job/command/event repositories, not in a new worker-reattachment layer.
  - Event replay and job state projection are already available, so startup reconciliation can reuse them.
  - The singleton-ownership ADR is the gate that decides whether reconciliation is even allowed to start.
- What source inspection confirmed:
  - `JobState` already includes `RECOVERY_REQUIRED`.
  - `parse_public_event_cursor` and `ControlTowerQueryService.replay_run_events` already support browser reconnect semantics.
  - `SqliteMigrationJobRepository` and `SqliteCommandExecutionRepository` expose enough state to identify terminal, queued, and active commands.
  - `app.py` currently creates the FastAPI app without any startup reconciliation or singleton guard.
  - There is no PID attach or worker-resume code in the current repository.

## 3. Relationship to previous M2 work
This slice builds on:

- AMF-151 secure workspace/manifests: restart must preserve the existing mutable files and not invent new workspaces.
- AMF-152 controlled worker launch: restart must not silently relaunch an uncertain worker.
- AMF-153 bounded output: restart must not break reconnect or log window replay.
- AMF-155 cancel/timeout: restart must preserve the authoritative terminal or recovery disposition already recorded.
- existing command execution state: `RECOVERY_REQUIRED` is the domain signal for unsupported active state at startup.
- existing public event replay: browser reconnect after restart should continue from committed public events.

## 4. Implementation strategy
1. Add a startup reconciliation service that runs only after singleton ownership is confirmed.
2. Read the current jobs and active commands through the unit of work and classify each row as terminal, queued, or unsupported active.
3. Leave terminal jobs queryable and replayable without modification.
4. Allow an untouched `QUEUED` command to remain eligible for one safe dispatch, but ensure it cannot launch twice.
5. Transition `STARTING`, `RUNNING`, `CANCELLING`, and uncertain launch states to `RECOVERY_REQUIRED` with an audit trail and a non-sensitive reason.
6. Do not attach to a stored PID and do not reconstruct a Job Object.
7. Preserve logs, result files, and spool as evidence instead of trying to relaunch around them.
8. Make the API return the recovery-required state and reason so the UI can render a fail-closed message.

Likely files:

- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/application/queries.py`
- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/commands.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py`
- `tests/control_tower/test_m2_event_replay.py`
- `tests/control_tower/test_fastapi_diagnostic_queue.py`
- `tests/control_tower/test_active_job_lock.py`
- future restart-focused tests such as `tests/control_tower/test_m2_restart_recovery.py`

## 5. Data model / persistence plan
- Expected schema changes:
  - likely a nullable recovery reason/code field on `migration_jobs`, or a dedicated recovery record table keyed by job
  - if the reason can be expressed entirely in audit/event payloads, keep the schema narrow but still expose the reason in the API projection
  - no PID storage
- Migration naming:
  - if schema changes are required, add a new migration after `0002_m2_queued_diagnostic.sql`
  - name it for the slice, such as `0006_m2_restart_recovery.sql`
- Immutability / retry / recovery rules:
  - terminal jobs remain immutable and queryable
  - untouched queued work can dispatch once, but only once
  - active states that cannot be proven safe must become `RECOVERY_REQUIRED`
  - incomplete closed spool may later be forensic evidence
- Transaction boundaries:
  - startup reconciliation should transition state and append audit/event rows atomically
  - singleton ownership acquisition must happen before any reconciliation write
  - browser replay remains read-only and separate

## 6. API / event contract plan
- Endpoint/event changes:
  - expose recovery-required state through the job projection
  - surface a non-sensitive recovery reason
  - keep event replay and SSE committed-public only
- Public DTO fields:
  - `status`
  - `job_id`
  - `version`
  - `active_command`
  - `recovery_reason`
  - `etag`
- Must not expose:
  - PID
  - raw handles
  - absolute paths
  - secrets
  - resume/recover controls in M2

## 7. Linux behavior
- Linux should run portable restart/replay tests.
- Linux should confirm terminal jobs are still queryable and queued work can still dispatch once.
- Linux should confirm active-state restarts fail closed to `RECOVERY_REQUIRED`.
- Linux should skip Windows-only process-control tests with explicit reasons.

## 8. Windows behavior
- Windows must verify the same fail-closed restart behavior.
- Windows should not attach to a stored PID or silently relaunch an uncertain worker.
- Windows-specific verification should include Job Object provenance surviving the earlier launch slice, but not being reconstructed after restart.

## 9. Security and reliability rules
- Unbounded output: do not re-open live pipes after restart.
- Shell injection: irrelevant here, but do not add shell-based recovery helpers.
- Environment leakage: do not echo process env values in recovery reasons.
- Path leakage: preserve evidence, but do not leak absolute paths to the browser.
- Process orphaning: do not try to orphan-proof by reattaching; fail closed instead.
- Partial persistence: reconciliation state changes must commit atomically.
- Restart ambiguity: this slice is all about removing ambiguity rather than tolerating it.
- Cancellation race: restart must respect already-committed cancel state.
- Timeout race: restart must respect already-committed timeout state.
- Artifact integrity: preserve files and let AMF-154 classify them later if needed.
- Duplicate finalization: do not replay startup transitions twice.
- Replay/idempotency: event replay after restart must continue from committed public events.

## 10. Test plan
- Focused unit tests:
  - terminal job remains unchanged after restart
  - queued job remains dispatchable once
  - active job transitions to `RECOVERY_REQUIRED`
  - recovery reason is non-sensitive
- Service tests:
  - startup reconciliation after singleton ownership
  - no PID attach
  - no silent relaunch
  - active-slot retention for recovery-required jobs
- Repository/migration tests:
  - new recovery metadata columns or table, if added
  - audit/event rows written atomically
- FastAPI tests:
  - restart projection exposes `RECOVERY_REQUIRED`
  - browser reconnect replays public events
  - no resume/recover control appears
- Linux tests:
  - restart after terminal job
  - restart with untouched `QUEUED` command
  - restart with STARTING/RUNNING/CANCELLING
- Windows tests:
  - same restart matrix on Windows
  - no PID attach
  - no Job Object reconstruction
- Negative tests:
  - uncertain launch outcome
  - duplicate dispatch after restart
  - stale state after queued dispatch
- Restart/recovery tests:
  - central to this issue
- Baseline comparison rule:
  - compare failures against clean `origin/DEMO2`
- Exact test commands:
  - `python -m pytest tests/control_tower/test_m2_event_replay.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_active_job_lock.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_m2_diagnostic_queue.py tests/control_tower/test_m1_acceptance.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower -q -rs --tb=short`

## 11. Code snippets / patterns
Reconciliation shape:

```python
def reconcile_on_startup() -> None:
    acquire_singleton()
    for job in list_jobs():
        match job.status:
            case "QUEUED":
                keep_dispatchable_once()
            case "STARTING" | "RUNNING" | "CANCELLING":
                transition_to_recovery_required()
```

Non-sensitive reason:

```python
recovery_reason = "uncertain active execution after restart"
```

No-PID rule:

```python
assert "pid" not in public_payload
assert "handle" not in public_payload
```

Test shape:

```python
def test_restart_with_running_job_fails_closed(tmp_path: Path) -> None:
    ...
```

## 12. Definition of Done
- [ ] Startup reconciliation runs only after singleton ownership.
- [ ] Terminal jobs stay queryable and replayable.
- [ ] Untouched queued work can dispatch once and only once.
- [ ] Unsupported active states become `RECOVERY_REQUIRED`.
- [ ] No PID attach or worker resume happens.
- [ ] Evidence files remain preserved.
- [ ] Recovery reason is exposed without sensitive detail.
- [ ] Browser reconnect replays public events after restart.
- [ ] Regression tests pass.
- [ ] `git diff --check` is clean.

## 13. Pi/Hermes `/goal` prompt
```text
Start from latest DEMO2 on a fresh branch. Use Graphify first, then use $test-discipline. Read AMF-156 and map every acceptance criterion before editing. Implement only AMF-156. Add fail-closed startup reconciliation for terminal, queued, and uncertain active command states, with RECOVERY_REQUIRED for unsupported active work. Do not change Jira status. Do not add unrelated runtime code. Run the restart/replay tests on Linux and the Windows-specific checks if applicable. Commit locally with issue-owned files only. Do not push unless asked. Final report must include branch, base commit, files changed, test commands with exact results, acceptance-criteria status, final git status, and commit hash.
```
