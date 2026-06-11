# M2 Local Operations Runbook

Date: 2026-06-11

## Purpose

Run local Control Tower foundation diagnostic slice on loopback only.
This diagnostic proves Control Tower plumbing, not a migrated Spring app.

M2 diagnostic is **not migration proof**. No Maven, OpenRewrite, LangGraph, or
real migration operations are executed. The `FOUNDATION_DIAGNOSTIC` operation
is a read-only backend-owned diagnostic proof.

Windows process-control verification (Job Object, named mutex, process-tree
kill, suspended-process launch) **must be run on Windows**. This runbook
documents Linux portable operations and notes where Windows verification
is still required.

## Start

### Backend (Linux)

```bash
export CONTROL_TOWER_DEV_ROOT="$PWD/.control-tower-dev"
python -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app \
  --host 127.0.0.1 --port 8000
```

### Backend (Windows PowerShell)

```powershell
$env:CONTROL_TOWER_DEV_ROOT="$PWD\.control-tower-dev"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd web/control-tower
export NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

Windows PowerShell alternative:

```powershell
cd web/control-tower
$env:NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## Ports

- API: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:3000`

Do not mix `localhost` and `127.0.0.1`. The security layer rejects `localhost`.

## Health

```bash
curl http://127.0.0.1:8000/v1/health/live
curl http://127.0.0.1:8000/v1/health/ready
curl http://127.0.0.1:8000/v1/health/dependencies
```

Live means the ASGI process is accepting connections.

Ready means:
- singleton owned (lock file on Linux, Windows named mutex on Windows)
- database available
- migrations current
- required output roots reachable
- dispatcher, ingestor, monitor not fatal
- **Windows only**: process-control capability available (worker_launcher + worker_terminator configured)

On Linux, the `process_control` readiness check is automatically satisfied
(because Windows process control is genuinely unavailable). The service correctly
reports `ready` without configured worker launcher/terminator.

`RECOVERY_REQUIRED` job does not make service unready.

### Dependency diagnostics

`GET /v1/health/dependencies` reports:
- FastAPI version
- Python version
- sqlite3 module/runtime version
- Origins (api, frontend)
- DB migration status
- Process control status
- Service loop status

## Create job

Use `/jobs/new` in frontend.

Required fields:
- runner profile
- pipeline
- source root + relative path
- output root + relative path

Mutation requests use JSON, `Idempotency-Key`, and `If-Match` where required.

## Start and cancel

On `/jobs/[jobId]`:
- Start queues backend-owned diagnostic command.
- Cancel moves job to cancellation flow.
- Missing `If-Match` returns `428`.
- Stale `If-Match` returns `412`.

## Timeout and forced cancel

Backend timeout and cancellation paths may terminate the process tree.

**Windows**: `TerminateJobObject` is the intended behavior.
**Linux**: subprocess cancellation uses `SIGTERM`/`SIGKILL` on the process group.
Full forced-cancellation evidence with Windows Job Object `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
requires Windows verification.

## Logs and artifacts

- `stdout` / `stderr` views are byte-offset windows.
- Final artifacts appear only after terminal finalization.
- Closed logs/results/spool are hashed and registered.
- Incomplete spool is retained as forensic evidence.

Artifact inspection:

```bash
curl http://127.0.0.1:8000/v1/jobs/{job_id}/artifacts
curl http://127.0.0.1:8000/v1/jobs/{job_id}/commands/{command_id}/logs/stdout
curl http://127.0.0.1:8000/v1/jobs/{job_id}/commands/{command_id}/logs/stderr
```

## SSE reconnect

Stream:

```http
GET /v1/jobs/{job_id}/events/stream
```

Use `Last-Event-ID` or `after_sequence`.
Browser reconnect resumes from last committed public sequence.

## Troubleshooting

| Error | Meaning |
|---|---|
| `SERVICE_INSTANCE_CONFLICT` | second controller instance or singleton conflict |
| `SERVICE_NOT_READY` | backend not ready for background work |
| `ACTIVE_JOB_CONFLICT` | another active job already owns slot |
| `JOB_VERSION_CONFLICT` | reload job before retry |
| `RECOVERY_REQUIRED` | unsupported active state after restart or uncertainty |

## Known limits

- M2 diagnostic is not migration proof.
- No real Maven/OpenRewrite execution.
- No active-worker reattachment.
- No arbitrary command or filesystem endpoint.
- No M3 lease/heartbeat recovery.
- **Windows process-control verification must run on Windows.** This runbook's health/ready section documents a platform-aware readiness check; the process_control check is automatically green on Linux but must be verified with real worker_launcher/worker_terminator on Windows.
- Internal `/v1/jobs/{job_id}/launch`, `/v1/jobs/{job_id}/finalize`, and `/v1/jobs/{job_id}/timeout` endpoints exist for dev/testing. They are not the production durable dispatcher path.
