# ADR-M2-05 Single Control Tower controller-instance strategy

Status: Ready for reviewer approval

Date: 2026-06-10

## Context

M1 enforces one active migration job in SQLite through `migration_jobs.active_slot` and partial unique index `ux_one_active_job`.

M2 adds background controller responsibilities: dispatcher, ingestor, process monitor, notifier, singleton-owned process-control handles, and durable command execution.

Configuration alone is not sufficient to prevent two controller instances from racing over the same database and process-control resources.

## Decision

M2 should implement a process-lifetime singleton guard before starting controller-owned services.

Preferred Windows strategy:

- Local named mutex.
- Mutex key based on the normalized Control Tower database path.
- Mutex is owned by the controller/API process lifetime.
- Mutex automatically releases when the owning process exits.

Second instance behavior:

- Startup fails with `SERVICE_INSTANCE_CONFLICT`, or readiness remains failed with `SERVICE_NOT_READY`.
- Dispatcher, ingestor, process monitor, and notifier must not start without singleton ownership.

## Non-Windows development/test strategy

Non-Windows tests may use a file lock or in-process fake that preserves the same semantics:

- only one owner for a normalized database path;
- second owner rejected;
- ownership released on close/process exit simulation;
- background services start only after ownership.

## Consequences

M2-06 owns singleton implementation and tests.

M2-10 FastAPI lifespan must acquire singleton ownership before starting background services.

Readiness must report singleton ownership status.

## Approval

| Reviewer | Decision | Date | Comments |
|---|---|---|---|
| HAMDAOUI Ali | Pending | Pending | Pending |
| ilyas abarbach | Pending | Pending | Pending |
