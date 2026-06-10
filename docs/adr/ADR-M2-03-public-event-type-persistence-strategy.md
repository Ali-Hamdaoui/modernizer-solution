# ADR-M2-03 Public event-type persistence strategy

Status: Proposed for review

Date: 2026-06-10

## Context

The current M1 `run_events` table is defined in `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql`.

Current `run_events.event_type` behavior:

- Column: `event_type TEXT NOT NULL`.
- Constraint: closed `CHECK`.
- Allowed values: `job_created`, `job_state_changed`, `artifact_registered`.
- Public sequence is job scoped through unique `(job_id, sequence)`.

M2 needs additional public event types for command, worker, cancellation, output, artifact finalization, and diagnostic lifecycle events.

## Decision

M2 should introduce an `event_types` catalog table in M2-02 and rebuild `run_events` so `event_type` references the catalog.

M2 should not keep expanding a closed `CHECK` list for every new event type.

## Migration strategy

- Add `event_types` catalog.
- Insert M1 event types first: `job_created`, `job_state_changed`, `artifact_registered`.
- Insert M2 event types required by the M2 contract.
- Rebuild `run_events` to remove the closed `CHECK` and use an FK to `event_types`.
- Preserve all M1 rows, event IDs, job IDs, sequences, payload JSON, payload checksums, actor data, correlation/causation IDs, and timestamps.
- Preserve unique `(job_id, sequence)`.
- Preserve M1 migration checksum by not editing `0001_foundation.sql`.
- Verify with `PRAGMA foreign_key_check`.

## Consequences

Future public event additions become catalog inserts rather than table rebuilds.

M2-02 must include upgrade tests from an actual M1 database and rollback tests for failed rebuilds.
