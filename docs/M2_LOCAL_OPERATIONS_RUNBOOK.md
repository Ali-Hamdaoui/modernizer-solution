# M2 Local Operations Runbook

Date: 2026-06-11

## Purpose

Run local Control Tower foundation diagnostic slice on loopback only.
This diagnostic proves Control Tower plumbing, not a migrated Spring app.

## Start

Backend:

```powershell
$env:CONTROL_TOWER_DEV_ROOT="$PWD\.control-tower-dev"
py -m uvicorn migration_factory.control_tower.adapters.fastapi.dev_app:app --host 127.0.0.1 --port 8000
```

Frontend:

```powershell
cd web/control-tower
$env:NEXT_PUBLIC_CONTROL_TOWER_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --hostname 127.0.0.1 --port 3000
```

## Ports

- API: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:3000`

Do not mix `localhost` and `127.0.0.1`.

## Health

Check:

```http
GET /v1/health/live
GET /v1/health/ready
GET /v1/health/dependencies
```

Ready means:

- singleton owned
- database available
- migrations current
- required output roots reachable
- dispatcher, ingestor, monitor not fatal
- process-control capability available

`RECOVERY_REQUIRED` job does not make service unready.

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
Forced path does not wait for worker cooperation.
`TerminateJobObject` is the intended Windows behavior.

## Logs and artifacts

- `stdout` / `stderr` views are byte-offset windows.
- Final artifacts appear only after terminal finalization.
- Closed logs/results/spool are hashed and registered.
- Incomplete spool is retained as forensic evidence.

Artifact inspection:

```http
GET /v1/jobs/{job_id}/artifacts
GET /v1/jobs/{job_id}/commands/{command_id}/logs/stdout
GET /v1/jobs/{job_id}/commands/{command_id}/logs/stderr
```

## SSE reconnect

Stream:

```http
GET /v1/jobs/{job_id}/events/stream
```

Use `Last-Event-ID` or `after_sequence`.
Browser reconnect resumes from last committed public sequence.

## Dependency diagnostics

`GET /v1/health/dependencies` reports:

- FastAPI version
- Python version
- sqlite3 module/runtime version
- journal mode
- foreign key status
- busy timeout
- frontend version/build ID
- process-control capability
- singleton ownership
- dispatcher status
- ingestor status
- monitor status

## Troubleshooting

- `SERVICE_INSTANCE_CONFLICT`: second controller instance or singleton conflict.
- `SERVICE_NOT_READY`: backend not ready for background work.
- `ACTIVE_JOB_CONFLICT`: another active job already owns slot.
- `JOB_VERSION_CONFLICT`: reload job before retry.
- `RECOVERY_REQUIRED`: unsupported active state after restart or uncertainty.

## Known limits

- M2 diagnostic is not migration proof.
- No real Maven/OpenRewrite execution.
- No active-worker reattachment.
- No arbitrary command or filesystem endpoint.
- No M3 lease/heartbeat recovery.

