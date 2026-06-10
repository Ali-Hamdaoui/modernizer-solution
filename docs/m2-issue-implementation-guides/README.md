# M2 Issue Implementation Dossiers

This folder holds implementation dossiers for the remaining M2 Control Tower issues:

1. AMF-153 - Stream bounded command output
2. AMF-154 - Finalize terminal command artifacts
3. AMF-155 - Cancel or time out the complete command
4. AMF-156 - Fail closed after restart or uncertain active execution

Purpose:

- give Pi/Hermes one issue-specific source of truth before `/goal`
- keep the implementation order aligned with M2 dependencies
- separate planning from runtime code
- keep each branch and goal to one issue only

## Issue order

Recommended sequence:

1. AMF-153
2. AMF-154
3. AMF-155
4. AMF-156

Direct Jira blockers:

- AMF-153 is blocked by AMF-152.
- AMF-154 is blocked by AMF-153.
- AMF-155 is blocked by AMF-152 and AMF-153.
- AMF-156 is blocked by AMF-152, AMF-153, and AMF-155.

Practical dependency note:

- AMF-154 should usually land before AMF-155 because cancellation and timeout need terminal artifact rules.
- AMF-156 should be treated as the last slice because it depends on the previous terminal and cancellation semantics being trustworthy.

## Shared M2 context

After AMF-152, the repo already has the core M2 foundation:

- `DiagnosticJobService` creates the diagnostic job and queues the active command.
- `CommandWorkspaceService` prepares the run workspace and command manifest.
- `WorkerLaunchService` launches the worker and persists process identity.
- `ControlTowerQueryService` replays committed public events.
- `SqliteControlTowerUnitOfWork` wires the SQLite repositories together.
- `run_events` already uses the `event_types` catalog from `0002_m2_queued_diagnostic.sql`.
- FastAPI already exposes `/v1/jobs`, `/v1/jobs/{job_id}/start`, `/v1/jobs/{job_id}/launch`, `/v1/jobs/{job_id}/events`, and `/v1/jobs/{job_id}/events/stream`.
- `WindowsWorkerLauncher` already creates a suspended worker and assigns it to a Job Object on Windows.

What is still missing for these four issues:

- bounded stdout/stderr streaming endpoints
- terminal artifact finalization
- cancel and timeout control
- startup reconciliation that fails closed on uncertain state

## Shared test matrix

Linux-focused regression:

```powershell
python -m pytest tests/control_tower/test_m2_diagnostic_queue.py tests/control_tower/test_m2_event_replay.py tests/control_tower/test_m2_workspace.py tests/control_tower/test_artifact_registry.py tests/control_tower/test_sqlite_migrations.py -q -rs --tb=short
```

Windows-focused regression:

```powershell
py -m pytest tests/control_tower/test_m2_worker_launch.py -q -rs --tb=short
```

Cross-platform final check:

```powershell
python -m pytest tests/control_tower -q -rs --tb=short
```

Use the clean `origin/DEMO2` baseline if a failure needs branch-vs-baseline proof.

## Shared safety rules

- One issue per branch.
- One issue per Pi goal.
- Do not add runtime code outside the active issue.
- Do not update Jira status.
- Do not push unless asked.
- Do not expose secrets, raw handles, PIDs, absolute unsafe paths, or unbounded output in public API payloads.
- Do not use `communicate()` for unbounded output.
- Do not keep a database transaction open while waiting on a worker, hashing files, or streaming SSE.
- Do not attach to an uncertain worker after restart.
- Do not silently relaunch active work after a restart if state is unclear.
- Do not weaken skip/xfail rules to hide missing platform support.

## Official references checked

These were used to confirm platform behavior while writing the dossiers:

- Python subprocess: https://docs.python.org/3/library/subprocess.html
- Python pathlib: https://docs.python.org/3/library/pathlib.html
- FastAPI SSE: https://fastapi.tiangolo.com/tutorial/server-sent-events/
- FastAPI streaming/custom responses: https://fastapi.tiangolo.com/advanced/stream-data/
- pytest tmp_path: https://docs.pytest.org/en/stable/how-to/tmp_path.html
- pytest skip/xfail reference: https://docs.pytest.org/en/stable/reference/reference.html
- Microsoft Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
- AssignProcessToJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
- TerminateJobObject: https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject
- EventSource / SSE: https://developer.mozilla.org/en-US/docs/Web/API/EventSource

## How Pi/Hermes should use a dossier

1. Read the Jira issue first.
2. Read the matching dossier before editing.
3. Map each acceptance criterion to code, tests, and verification evidence.
4. Implement only the named issue.
5. Run the platform-appropriate tests.
6. Commit locally before stopping.
7. Report exact commands, results, and any gaps.

## Pi goal warning

Keep one issue per branch and one issue per `/goal`. Do not bundle slices together just because they share files.
