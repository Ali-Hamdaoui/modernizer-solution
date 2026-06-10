# AMF-155 - [Control Tower] M2-07 - Cancel or time out the complete process tree

## 1. Issue source
- Jira key: AMF-155
- Jira title: [Control Tower] M2-07 - Cancel or time out the complete process tree
- Jira status: In Progress
- Exact acceptance criteria:
  - Cancel requires expected job version; missing/stale If-Match follows approved contract.
  - Cancellation is state-idempotent and transitions job/active command to CANCELLING atomically with event/audit.
  - Browser confirmation card identifies exact job, command, and impact.
  - Controller publishes cooperative signal; diagnostic worker/child can stop cooperatively.
  - Controller waits configured grace period, then uses owned Job Object for forced termination.
  - Worker, child, and test grandchild are terminated and exit verified.
  - Forced cancellation succeeds without worker terminal event; process monitor authors terminal result when required.
  - Timeout uses controller-owned monotonic deadline and produces command TIMED_OUT/job FAILED.
  - Output-limit breach uses approved forced-termination path and failure code.
  - Completion-before-cancel and cancel-before-late-success races preserve correct authority; late success stored as IGNORED_STALE; duplicate terminal event stored as DUPLICATE.
  - Expected late events do not automatically create RECOVERY_REQUIRED.
  - Job Object handles closed after terminal verification.
  - Terminal logs/spool follow M2-06 finalization rules.
  - UI displays CANCELLING, CANCELLED, timeout, and cancellation failure correctly.
  - Normal UI/API does not expose PIDs, handles, or absolute paths.
  - Windows process-tree tests pass.
- Dependencies: AMF-152, AMF-153
- Non-goals:
  - Generic Maven cancellation
  - Active-process reattachment
  - Worker heartbeat/lease
  - Repair rollback
- Comments or attached notes: none returned in Jira search

## 2. Current repository context
- Relevant files:
  - `migration_factory/control_tower/application/services.py`
  - `migration_factory/control_tower/application/commands.py`
  - `migration_factory/control_tower/application/dto.py`
  - `migration_factory/control_tower/application/ports.py`
  - `migration_factory/control_tower/adapters/fastapi/app.py`
  - `migration_factory/control_tower/infrastructure/worker_launcher.py`
  - `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql`
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_transition_job_state.py`
  - `tests/control_tower/test_active_job_lock.py`
  - `tests/control_tower/test_m2_event_replay.py`
- Relevant services/classes:
  - `DiagnosticJobService`
  - `WorkerLaunchService`
  - `CommandWorkspaceService`
  - `ControlTowerQueryService`
  - `WindowsWorkerLauncher`
  - `SqliteCommandExecutionRepository`
- Relevant repositories/migrations:
  - `SqliteCommandExecutionRepository`
  - `SqliteMigrationJobRepository`
  - `SqliteRunEventRepository`
  - `SqliteAuditRecordRepository`
  - `0002_m2_queued_diagnostic.sql`
- Relevant FastAPI routes:
  - `POST /v1/jobs`
  - `GET /v1/jobs/{job_id}`
  - `POST /v1/jobs/{job_id}/start`
  - `POST /v1/jobs/{job_id}/launch`
  - `GET /v1/jobs/{job_id}/events`
  - `GET /v1/jobs/{job_id}/events/stream`
  - no cancel route exists yet
- Relevant tests:
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_transition_job_state.py`
  - `tests/control_tower/test_active_job_lock.py`
  - `tests/control_tower/test_m2_event_replay.py`
- Graphify queries used:
  - `Which services handle command execution lifecycle?`
  - `Which services update command execution state?`
  - `Which tests cover diagnostic worker launch and command execution?`
  - `Which repositories persist command executions and artifacts?`
  - `Which FastAPI routes expose Control Tower command execution?`
  - `WorkerLaunchService -> SqliteControlTowerUnitOfWork`
  - `WorkerLaunchService`
- What Graphify suggested:
  - The cancellation slice sits on top of the worker-launch and command-execution surface, not in the workspace helper alone.
  - The repository graph already centers process identity in `command_executions`, which is the natural place to hang cancellation/timeout metadata.
  - Windows-specific process control remains the critical edge.
- What source inspection confirmed:
  - `WindowsWorkerLauncher` already creates the worker suspended, assigns it to a Job Object, and then resumes it.
  - `CommandState` already contains `CANCELLING`, `TIMED_OUT`, and `CANCELLED`.
  - `SqliteCommandExecutionRepository` currently stores launch/process identity, but no explicit cancellation request or terminal-reason columns are exposed in code yet.
  - There is no cancel route or process-monitor service in the current FastAPI adapter.

## 3. Relationship to previous M2 work
This slice builds on:

- AMF-151 secure workspace/manifests: cancellation must respect the prepared manifest and working directory.
- AMF-152 controlled worker launch: cancellation terminates the process tree that was launched there.
- AMF-153 bounded output: cancellation and timeout must not break output draining or truncate the final offset notification.
- AMF-154 terminal artifact finalization: once the command stops, the terminal files must still be finalized safely.
- existing command execution state: this is the slice that consumes `CANCELLING`, `TIMED_OUT`, `FAILED`, and `CANCELLED` in a durable way.

## 4. Implementation strategy
1. Add a cancel command and a timeout command or timeout path in the application layer.
2. Add a controller-owned process-monitor service that can publish a cooperative stop, wait the grace period, and then force-kill the Job Object on Windows.
3. Make the transition to `CANCELLING` atomic with audit and event writes before any forced termination happens.
4. Record enough durable cancellation/timeout metadata so a retry can tell whether the command is already in progress or already terminal.
5. Ensure late success and duplicate terminal events are written with the correct disposition instead of reopening the state machine.
6. Keep the public API free of raw PIDs, handles, or absolute paths.
7. Wire the FastAPI route to return a browser-confirmation payload before the state change and a durable terminal projection after the stop completes.

Likely files:

- `migration_factory/control_tower/application/commands.py`
- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/infrastructure/worker_launcher.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `tests/control_tower/test_m2_worker_launch.py`
- `tests/control_tower/test_transition_job_state.py`
- `tests/control_tower/test_active_job_lock.py`
- future cancellation-focused tests such as `tests/control_tower/test_m2_cancellation.py`

## 5. Data model / persistence plan
- Expected schema changes:
  - likely extend `command_executions` with cancellation/timeout metadata and terminal reason fields
  - if the current row cannot safely hold the extra state, add a narrow command-control table keyed by `command_id`
  - keep process handles out of the database
- Migration naming:
  - if schema changes are required, add a new migration after `0002_m2_queued_diagnostic.sql`
  - name it for the slice, such as `0005_m2_command_cancellation.sql`
- Immutability / retry / recovery rules:
  - cancellation must be idempotent
  - timeout must use the controller-owned monotonic deadline, not wall-clock drift
  - late worker success after cancellation stays late and must not reopen the command
  - duplicate terminal events must be recorded as duplicates, not new progress
- Transaction boundaries:
  - state change to `CANCELLING`, event append, and audit append stay atomic
  - forced termination happens after that commit
  - terminal outcome recording must be durable even if the worker never cooperates

## 6. API / event contract plan
- Endpoint/event changes:
  - add `POST /v1/jobs/{job_id}/cancel`
  - expose a durable command-level terminal result for cancel and timeout outcomes
  - add or reuse events for `command_cancelled`, `command_timed_out`, and related terminal dispositions
- Public DTO fields:
  - `status`
  - `job_id`
  - `command_id`
  - `reason`
  - `failure_code`
  - `deadline_at` if exposed at all
  - `terminal_at`
- Must not expose:
  - PIDs
  - raw handles
  - absolute paths
  - secret environment values
  - unbounded output

## 7. Linux behavior
- Linux should run portable state-transition and idempotency tests.
- Linux should verify the API returns fail-closed behavior when the platform cannot own the required process-control mechanism.
- Linux should skip Windows Job Object kill-path tests with explicit reasons.
- Linux should never fake Windows process-tree support.

## 8. Windows behavior
- Windows must run the real Job Object termination and process-tree tests.
- Windows should verify create-suspended -> assign-to-job -> resume behavior remains intact.
- Windows should verify the worker, child, and test grandchild all exit.
- Windows-specific verification should include handle lifecycle and cleanup on failure.

## 9. Security and reliability rules
- Unbounded output: kill paths must still flush or finalize the last safe output view.
- Shell injection: do not introduce shell-based cancellation helpers.
- Environment leakage: do not print env values in cancel responses.
- Path leakage: do not expose workspace paths in UI or API payloads.
- Process orphaning: a forced cancel must terminate the process tree, not just the root worker.
- Partial persistence: cancel/timeout state must not commit half a transition.
- Restart ambiguity: if state is uncertain, fail closed rather than relaunching.
- Cancellation race: late success after cancel must stay late, not win authority.
- Timeout race: timeout and cancel must resolve with one authoritative terminal path.
- Artifact integrity: terminal logs/spool still need AMF-154 finalization rules.
- Duplicate finalization: repeated cancel requests must not spawn repeated terminal records.
- Replay/idempotency: repeated cancel requests should be safe to replay.

## 10. Test plan
- Focused unit tests:
  - cancel precondition checks
  - timeout deadline calculation
  - late-success disposition
  - duplicate terminal event disposition
- Service tests:
  - state-idempotent `CANCELLING`
  - cooperative stop path
  - forced stop path after grace period
  - timeout path
- Repository/migration tests:
  - new cancellation metadata columns or table, if added
  - atomic transition and rollback
  - no raw handle persistence
- FastAPI tests:
  - cancel route precondition handling
  - confirmation payload
  - terminal response shape
- Linux tests:
  - portable cancel validation and fail-closed behavior
- Windows tests:
  - Job Object termination
  - child/grandchild exit verification
  - handle lifecycle
- Negative tests:
  - stale If-Match
  - missing If-Match
  - late success after cancel
  - duplicate terminal event
  - timeout after output-limit breach
- Restart/recovery tests:
  - not the focus here, but cancel state must remain authoritative across reconnect
- Baseline comparison rule:
  - compare failures against clean `origin/DEMO2`
- Exact test commands:
  - `python -m pytest tests/control_tower/test_transition_job_state.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_active_job_lock.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_m2_diagnostic_queue.py tests/control_tower/test_m2_event_replay.py -q -rs --tb=short`
  - `py -m pytest tests/control_tower/test_m2_worker_launch.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower -q -rs --tb=short`

## 11. Code snippets / patterns
State transition shape:

```python
def cancel_command(job_id: str, command_id: str, expected_version: int) -> None:
    transition_to_cancelling()
    publish_cooperative_stop()
    maybe_terminate_job_object()
```

Timeout path:

```python
deadline = started_at + timeout_seconds
if monotonic_now() >= deadline:
    mark_timed_out()
    force_terminate()
```

Race handling:

```python
if late_event and terminal_state_already_committed:
    store_disposition("IGNORED_STALE")
```

Windows cleanup pattern:

```python
try:
    ...
finally:
    close_job_handle()
```

## 12. Definition of Done
- [ ] Cancel requires current job version and follows the If-Match contract.
- [ ] Cancellation is atomic and idempotent.
- [ ] Cooperative stop and forced Job Object termination both work.
- [ ] Worker, child, and test grandchild exit is verified on Windows.
- [ ] Timeout uses monotonic deadline and produces `TIMED_OUT` / `FAILED`.
- [ ] Late success and duplicate terminal events use the right disposition.
- [ ] No PID, handle, or absolute-path leak appears in the public API.
- [ ] Terminal logs/spool still obey AMF-154 rules.
- [ ] Regression tests pass.
- [ ] `git diff --check` is clean.

## 13. Pi/Hermes `/goal` prompt
```text
Start from latest DEMO2 on a fresh branch. Use Graphify first, then use $test-discipline. Read AMF-155 and map every acceptance criterion before editing. Implement only AMF-155. Add cancel and timeout behavior for the complete command tree, with atomic CANCELLING transitions, grace-period termination, and Windows Job Object kill behavior. Do not change Jira status. Do not add unrelated runtime code. Run Linux validation tests and the Windows Job Object/process-tree tests as applicable. Commit locally with issue-owned files only. Do not push unless asked. Final report must include branch, base commit, files changed, test commands with exact results, acceptance-criteria status, final git status, and commit hash.
```
