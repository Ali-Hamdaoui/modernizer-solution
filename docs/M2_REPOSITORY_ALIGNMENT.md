# M2 Repository Alignment

Issue: AMF-148 - [Control Tower] M2-00 - Align the repository and freeze M2 contracts

Date inspected: 2026-06-10

Integration base: `DEMO2` at `f899c8c`

Issue branch: `AMF-148-control-tower-m2-00`

Working tree at start: `git status --short` printed only `warning: could not open directory '.pytest_cache/': Permission denied`; no changed paths were listed.

This document records the actual repository state for M2 planning. It does not add runtime behavior, migrations, FastAPI routes, SSE, worker code, dispatcher code, process-control code, Next.js features, or migration-engine changes.

## 1. Exact source-of-truth files

Files and sources inspected:

- Jira issue `AMF-148`, summary `[Control Tower] M2-00 - Align the repository and freeze M2 contracts`.
- `AGENTS.md`.
- `docs/M1_IMPLEMENTATION_PLAN.md`.
- `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md`.
- `docs/PRD_AI_Migration_Control_Tower_v0.3.md`.
- `pyproject.toml`.
- `migration_factory/control_tower/__init__.py`.
- `migration_factory/control_tower/domain/states.py`.
- `migration_factory/control_tower/domain/transitions.py`.
- `migration_factory/control_tower/domain/entities.py`.
- `migration_factory/control_tower/domain/errors.py`.
- `migration_factory/control_tower/domain/checksums.py`.
- `migration_factory/control_tower/domain/artifacts.py`.
- `migration_factory/control_tower/application/commands.py`.
- `migration_factory/control_tower/application/dto.py`.
- `migration_factory/control_tower/application/ports.py`.
- `migration_factory/control_tower/application/queries.py`.
- `migration_factory/control_tower/application/services.py`.
- `migration_factory/control_tower/schemas/common.py`.
- `migration_factory/control_tower/schemas/runner_profile.py`.
- `migration_factory/control_tower/schemas/pipeline_definition.py`.
- `migration_factory/control_tower/schemas/run_configuration.py`.
- `migration_factory/control_tower/infrastructure/paths.py`.
- `migration_factory/control_tower/infrastructure/windows_paths.py`.
- `migration_factory/control_tower/infrastructure/sqlite/connection.py`.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/__init__.py`.
- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql`.
- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py`.
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`.
- `migration_factory/control_tower/infrastructure/sqlite/artifact_paths.py`.
- `tests/control_tower/*.py`.
- Existing docs under `docs/system/` when checking CLI/TUI and orchestration boundaries.

No nested `AGENTS.md` files exist under `docs/`, `migration_factory/`, or `tests/`.

No ADR convention exists in the repository today. M2-00 therefore creates `docs/adr/`.

No M0 Windows Job Object implementation or test file was found in repository code. Only planning references to Windows Job Object behavior were found in PRD/M2 plan documents.

No frontend workspace file was found. There is no `package.json`, lockfile, Next.js app, or React dependency in the repository.

## 2. Current package tree

Current M2-relevant backend tree:

```text
migration_factory/control_tower/
  __init__.py
  application/
    __init__.py
    commands.py
    dto.py
    ports.py
    queries.py
    services.py
  domain/
    __init__.py
    artifacts.py
    checksums.py
    entities.py
    errors.py
    states.py
    transitions.py
  infrastructure/
    __init__.py
    paths.py
    windows_paths.py
    sqlite/
      __init__.py
      artifact_paths.py
      connection.py
      repositories.py
      unit_of_work.py
      migrations/
        __init__.py
        0001_foundation.sql
  schemas/
    __init__.py
    common.py
    pipeline_definition.py
    run_configuration.py
    runner_profile.py
```

Current Control Tower tests:

```text
tests/control_tower/
  __init__.py
  _helpers.py
  transition_helpers.py
  test_active_job_lock.py
  test_application_commands_queries.py
  test_artifact_hashing.py
  test_artifact_paths.py
  test_artifact_registry.py
  test_audit_records.py
  test_create_migration_job.py
  test_domain_transitions.py
  test_m1_acceptance.py
  test_paths.py
  test_pipeline_definition_schema.py
  test_pipeline_registration.py
  test_runner_profile_registration.py
  test_runner_profile_schema.py
  test_run_configurations.py
  test_run_events.py
  test_sqlite_migrations.py
  test_transition_job_state.py
```

SQLite infrastructure exists under `migration_factory/control_tower/infrastructure/sqlite/`.

Application layer exists under `migration_factory/control_tower/application/` with command DTOs, read DTOs, repository/UoW ports, query service, and application services.

Domain layer exists under `migration_factory/control_tower/domain/` with states, transitions, entities, errors, checksum helpers, and artifact hash result contracts.

Adapters do not exist for FastAPI, SSE, workers, dispatcher, process monitor, or frontend.

No frontend workspace exists.

No reusable process-control utility exists for M2. Existing subprocess usage is limited to legacy engine/agent utilities outside `migration_factory/control_tower/`, for example transformation agent execution, Copilot CLI adapters, and TUI runner adapters.

## 3. Current dependency versions

Declared dependency files:

- `pyproject.toml`.

Lock files:

- None found: no `poetry.lock`, `uv.lock`, `requirements*.txt`, `package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock`.

Dependency-lock strategy:

- No lockfile strategy is currently enforced by the repository.
- M2 dependency work must add and commit an approved lock strategy in the later dependency-owning issue, not in M2-00.

Declared Python support:

- `pyproject.toml`: `requires-python = ">=3.10"`.

Declared Python dependencies:

- `jsonschema`.
- `langgraph`.
- `pydantic>=2,<3`.
- `PyYAML`.
- Optional test dependencies: `jsonschema`, `pydantic>=2,<3`, `pytest`.

Runtime diagnostics on this workstation:

- Python: `3.13.9 (tags/v3.13.9:8183fa5, Oct 14 2025, 14:09:13) [MSC v.1944 64 bit (AMD64)]`.
- Python `sqlite3` module: `2.6.0`.
- SQLite runtime used by Python: `3.50.4`.
- Pydantic: `2.13.4`.
- pytest: `9.0.3`.
- jsonschema: `4.26.0`.
- langgraph: `1.2.0`.
- FastAPI: not installed and not declared.
- Starlette: not installed and not declared.
- Uvicorn: not installed and not declared.
- Node.js: `v24.15.0`.
- Next.js: not present.
- React: not present.

SQLite compile options were recorded with `PRAGMA compile_options`. Notable values include `THREADSAFE=1`, `MUTEX_W32`, `ENABLE_FTS5`, `ENABLE_RTREE`, `MAX_VARIABLE_NUMBER=32766`, and `DEFAULT_SYNCHRONOUS=2`.

FastAPI `0.136.3`, Next.js `16.2.7`, React `19.2.7`, and Node 24 LTS remain planning candidates only. They are not installed by this repository today.

## 4. Current post-M1 baseline

Commands run:

```powershell
git status --short
git branch --show-current
git rev-parse --short HEAD
python -m pytest -q tests/control_tower
python -m pytest -q
python -c "import sys, sqlite3; ..."
python -c "import importlib.metadata as m; ..."
node --version
python -c "from migration_factory.control_tower.infrastructure.sqlite.migrations import discover_migrations; ..."
python -c "import sqlite3; PRAGMA compile_options"
```

Focused Control Tower test result:

```text
195 passed, 1 skipped in 5.78s
```

Full backend test result:

```text
4 failed, 808 passed, 4 skipped, 4 subtests passed in 72.77s
```

Full backend failures:

- `tests/test_copilot_failure_mvp.py::test_copilot_feature_probe_requires_required_flags`.
- `tests/test_final_report.py::test_copilot_documentation_cli_timeout_records_status_and_falls_back`.
- `tests/test_final_report.py::test_copilot_documentation_cli_success_uses_generated_docs`.
- `tests/test_final_report.py::test_copilot_documentation_cli_outside_write_is_rejected_and_falls_back`.

Failure classification:

- The failing tests are Copilot/final-report related and outside `migration_factory/control_tower/`.
- The failures appear unrelated to M2-00 documentation and unrelated to Control Tower M1 code.
- Because M2-00 makes no production-code changes, these are recorded as baseline failures pending separate investigation.

Frontend checks:

- No frontend workspace exists.
- No install consistency, audit, type-check, unit test, or production build command can be run.

SQLite/schema diagnostics:

- `discover_migrations()` found `0001_foundation`.
- `0001_foundation` checksum: `c6a3bd68cc1174632bb2e8a64087cc9fbc4563e62bfea3eab91bd3142c727c88`.
- Temporary repo-local schema migration result: `pending=0001_foundation`.
- `PRAGMA foreign_key_check`: `[]`.
- `PRAGMA journal_mode`: `delete`.
- `PRAGMA foreign_keys`: `1`.
- `PRAGMA busy_timeout`: `5000`.
- Audit triggers found: `audit_records_no_delete`, `audit_records_no_update`.

Output location:

- Command output was captured in the terminal session for this M2-00 implementation. No persistent log file was created by this documentation-only issue.

## 5. Existing components to reuse

Reusable existing components:

- Canonical JSON helpers: `migration_factory/control_tower/domain/checksums.py` provides `canonical_json_text`, `canonical_json`, and `canonical_json_bytes`.
- Checksum helpers: `sha256_hex`, `sha256_canonical_json`, `sha256_checksum`, and `stream_sha256`.
- Timestamp helpers: `utc_now_text` and `utc_now`.
- ID generation pattern: `application/services.py` uses `uuid4()` directly. No dedicated ID helper exists.
- SQLite connection helpers: `connect_control_tower` and `configure_control_tower_journal_mode`.
- Migration runner: `migrate_control_tower`, `apply_pending_migrations`, `discover_migrations`, migration splitting, safety validation, checksum verification, and `foreign_key_check`.
- Unit of Work: `SqliteControlTowerUnitOfWork` uses `BEGIN IMMEDIATE`, `COMMIT`, and rollback on exception.
- Repositories: SQLite repositories for runner profiles, pipeline definitions, migration jobs, run configurations, stage runs, run events, artifacts, and audit records.
- DTOs: immutable dataclass DTOs in `application/dto.py`.
- Commands: immutable dataclass command DTOs in `application/commands.py`.
- Typed errors: `domain/errors.py`.
- Event append logic: `SqliteRunEventRepository.insert`, `append_job_state_changed_event`, and service-level event creation.
- Audit append logic: `SqliteAuditRecordRepository.insert`, `append_global_audit`, `append_job_state_changed_audit`, and audit triggers.
- Artifact registration helpers: `ArtifactRegistryService`, `ArtifactHashResult`, `validate_registered_artifact_path`, `hash_registered_artifact`, and path normalization.
- Path safety helpers: `infrastructure/sqlite/artifact_paths.py`, `infrastructure/paths.py`, and `infrastructure/windows_paths.py`.
- Configuration schemas: Pydantic schemas for runner profile, pipeline definition, and run configuration.
- Existing CLI/TUI boundaries: current CLI/TUI and orchestrator code remain outside Control Tower and must not be changed for M2-00.

Not present:

- FastAPI scaffolding.
- SSE adapter.
- Dispatcher.
- Event ingestor.
- Process monitor.
- Windows Job Object implementation.
- Private worker spool.
- Frontend scaffolding.

## 6. Existing components to extend

- `migration_factory/control_tower/domain/states.py`
  - Current behavior: M1 job, stage, and target proof state enums.
  - Missing M2 behavior: command state contract and receipt/disposition values.
  - Later issue: M2-01.

- `migration_factory/control_tower/domain/transitions.py`
  - Current behavior: M1 job lifecycle transitions.
  - Missing M2 behavior: command transition rules and late completion/cancellation semantics.
  - Later issue: M2-01.

- `migration_factory/control_tower/domain/errors.py`
  - Current behavior: M1 typed errors.
  - Missing M2 behavior: standard M2 API/domain error codes such as `ACTIVE_COMMAND_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `SERVICE_INSTANCE_CONFLICT`, and worker/process errors.
  - Later issue: M2-01 and M2-10.

- `migration_factory/control_tower/application/commands.py`
  - Current behavior: M1 create job, register configuration, transition job, and register artifact commands.
  - Missing M2 behavior: start command, cancel command, idempotency request DTOs, command execution DTOs.
  - Later issue: M2-01 and M2-06.

- `migration_factory/control_tower/application/dto.py`
  - Current behavior: M1 read DTOs for jobs, run events, audit records, run configs, stage runs, artifacts, runner profiles, and pipelines.
  - Missing M2 behavior: job mutation projection, command projection, public event envelope, log-window response, idempotency results.
  - Later issue: M2-01 and M2-10.

- `migration_factory/control_tower/application/ports.py`
  - Current behavior: repository and UoW protocols for M1 tables.
  - Missing M2 behavior: ports for command executions, worker event streams, worker event receipts, idempotency records, public event queries, workspace, process control, notifier, dispatcher, and ingestor.
  - Later issue: M2-02 through M2-11.

- `migration_factory/control_tower/application/services.py`
  - Current behavior: registration, job creation, job transition, and artifact registration services.
  - Missing M2 behavior: durable start, cancellation, command projection updates, idempotency handling, private event ingestion, artifact finalization.
  - Later issue: M2-06, M2-07, M2-08, M2-09.

- `migration_factory/control_tower/application/queries.py`
  - Current behavior: read-only M1 queries.
  - Missing M2 behavior: command queries, public event cursor queries, log window queries, health/dependency projections.
  - Later issue: M2-02, M2-10, M2-11.

- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
  - Current behavior: M1 SQLite repositories.
  - Missing M2 behavior: repositories for M2 tables and event-type catalog if selected.
  - Later issue: M2-02.

- `migration_factory/control_tower/infrastructure/sqlite/unit_of_work.py`
  - Current behavior: single UoW owns M1 repositories.
  - Missing M2 behavior: M2 repository attributes under the same transaction boundary.
  - Later issue: M2-02.

- `migration_factory/control_tower/infrastructure/sqlite/artifact_paths.py`
  - Current behavior: registered-root path validation and stable file hashing.
  - Missing M2 behavior: secure command workspace creation, atomic manifest publishing, closed-file finalization checks.
  - Later issue: M2-03 and M2-09.

- `migration_factory/control_tower/infrastructure/sqlite/migrations/__init__.py`
  - Current behavior: migration discovery, checksums, safety checks, transactions, and `foreign_key_check`.
  - Missing M2 behavior: no engine changes are currently required; M2-02 should reuse it unchanged unless a documented schema requirement proves otherwise.
  - Later issue: M2-02.

## 7. New components genuinely required

Planning inventory only:

- Command contracts: M2-01.
- Command transition rules: M2-01.
- Private worker event envelope: M2-01.
- Public event DTOs/envelope: M2-01.
- Idempotency DTOs: M2-01.
- Settings/limits contracts: M2-01.
- M2 persistence migration: M2-02.
- `command_executions` table: M2-02.
- `worker_event_streams` table: M2-02.
- `worker_event_receipts` table: M2-02.
- `idempotency_records` table: M2-02.
- Event-type catalog and `run_events` rebuild strategy: M2-02.
- Secure command workspace: M2-03.
- Immutable command manifest: M2-03.
- Immutable run configuration materialization: M2-03.
- Private worker event spool: M2-04.
- Diagnostic worker: M2-05.
- Fixed diagnostic child operation: M2-05.
- Windows singleton: M2-06.
- Durable dispatcher: M2-06.
- Windows process controller: M2-06/M2-08.
- Event ingestor: M2-07.
- Process monitor: M2-08.
- Cancellation runtime: M2-08.
- Artifact finalization service: M2-09.
- FastAPI adapter: M2-10.
- Local security middleware/configuration: M2-10.
- SSE adapter: M2-11.
- Minimal Next.js workspace and vertical slice: M2-12.
- Acceptance evidence matrix and runbook: M2-13.

No production code for these components is added in M2-00.

## 8. Exact M2 migration strategy

Current migration files:

- `migration_factory/control_tower/infrastructure/sqlite/migrations/0001_foundation.sql`.

No later M1 migrations exist.

Current migration runner behavior:

- Discovers `*.sql` files named with `NNNN_name.sql`.
- Rejects invalid names, duplicate versions, and nonascending versions.
- Calculates SHA-256 over migration file bytes.
- Loads applied migrations from `schema_migrations`.
- Rejects applied checksum mismatches.
- Splits SQL into statements with trigger-body support.
- Rejects transaction-control statements and blocked PRAGMAs.
- Applies each migration inside `BEGIN IMMEDIATE`.
- Runs `PRAGMA foreign_key_check` before committing each migration and after pending migrations.
- Inserts schema history row in the same transaction.
- Rolls back failed migration transactions.

Current migration checksum behavior:

- `0001_foundation` checksum is `c6a3bd68cc1174632bb2e8a64087cc9fbc4563e62bfea3eab91bd3142c727c88`.
- M1 migration bytes must not be edited because already-applied checksums would no longer match.

Current `migration_jobs` schema:

- Primary key `job_id`.
- `version INTEGER NOT NULL CHECK (version >= 1)`.
- `status TEXT NOT NULL` with closed M1 job-state `CHECK`.
- `active_slot INTEGER CHECK (active_slot IS NULL OR active_slot = 1)`.
- `last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0)`.
- Runner/pipeline foreign keys, proof fields, source/output refs, timestamps, and creator.
- Partial unique index `ux_one_active_job` on `active_slot` where `active_slot = 1`.

Current `run_events` schema:

- Primary key `event_id`.
- `job_id`, `sequence`, `event_type`, actor fields, correlation/causation fields, payload JSON, payload checksum, created timestamp.
- Foreign key to `migration_jobs(job_id)`.
- Unique `(job_id, sequence)`.
- Closed `CHECK` constraint on `event_type` with exactly `job_created`, `job_state_changed`, `artifact_registered`.

Current `audit_records` schema:

- Primary key `audit_id`.
- Optional `job_id` with foreign key to `migration_jobs`.
- Actor, action, prior/new state, job version, correlation/causation, payload JSON, created timestamp.
- Triggers `audit_records_no_update` and `audit_records_no_delete` make records append-only.

Event-type strategy:

- Because `run_events.event_type` has a closed `CHECK`, M2 should introduce an `event_types` catalog table and rebuild `run_events` so `event_type` references catalog rows.
- M1 event types must be inserted into the catalog first: `job_created`, `job_state_changed`, `artifact_registered`.
- M2 event types should be inserted as catalog rows by the M2 migration.
- Future event additions should insert catalog rows, avoiding repeated table rebuilds for every new event type.

Table rebuild requirement:

- A `run_events` rebuild is required in M2-02 if SQLite cannot alter the existing `CHECK` constraint in place.
- The rebuild must preserve all M1 rows, `event_id`, `job_id`, `sequence`, payloads, checksums, and timestamps.
- The existing unique `(job_id, sequence)` invariant must be preserved.

M1 data preservation:

- M2-02 migration tests must create a representative M1 database, insert runner/pipeline/job/run configuration/stage/run event/artifact/audit rows, apply M2 migration, then assert all M1 rows and checksums remain unchanged.

M1 checksum preservation:

- Do not edit `0001_foundation.sql`.
- M2 adds a new migration file, likely `0002_m2_foundation.sql`, with its own checksum history row.

Audit trigger preservation:

- M2 migration must leave `audit_records_no_update` and `audit_records_no_delete` intact or recreate equivalent triggers if any audit table rebuild ever occurs.

Foreign key verification:

- M2-02 migration must rely on the existing runner `PRAGMA foreign_key_check` and add explicit tests asserting no violations after upgrade.

Failure/rollback tests for M2-02:

- Inject a failing M2 migration after at least one M2 DDL statement and assert no partial M2 schema/history remains.
- Assert `schema_migrations` has no M2 row after failure.
- Assert M1 tables and rows remain queryable after rollback.
- Assert `foreign_key_check` failures abort migration before commit.

## 9. Exact public contracts to freeze

M2-00 freezes these documentation contracts from the M2 plan and current repository evidence. These are not implemented in M2-00.

Job mutation projection:

- `job_id`.
- `version`.
- `state`.
- Active command summary if present.
- Configuration references.
- Proof target and achieved summary.
- Current event cursor/head sequence.
- ETag format: `"job-<job_id>-v<version>"`.

Command projection:

- `command_id`.
- `job_id`.
- `operation`.
- `status`: `QUEUED`, `STARTING`, `RUNNING`, `CANCELLING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT`, `CANCELLED`.
- `worker_id`.
- `launch_attempt`.
- `created_at`, `started_at`, `finished_at`.
- `deadline_at`.
- `failure_code`.
- `exit_code`.
- `timed_out`.
- `cancelled`.
- stdout/stderr/result/spool artifact links after finalization.

Private worker event envelope:

- Worker-owned delivery sequence is `worker_sequence`.
- Includes `schema_version`, `job_id`, `command_id`, `worker_id`, `event_type`, payload, created timestamp, and checksum.
- Worker never writes Control Tower database.
- Envelope checksum covers canonical event content.

Public event envelope:

- Database-owned sequence is the job-scoped public `sequence` from `run_events`.
- Includes `event_id`, `job_id`, `sequence`, `event_type`, actor fields, correlation/causation, typed payload JSON, payload checksum, and created timestamp.
- SSE streams only committed public database events.
- Raw private worker events and log text are never SSE payloads.

Worker event receipt/disposition values:

- `APPLIED`.
- `DUPLICATE`.
- `IGNORED_STALE`.
- `REJECTED_CONFLICT`.

Standard error schema:

```json
{
  "error": {
    "code": "JOB_VERSION_CONFLICT",
    "message": "The job changed after the client loaded it.",
    "details": {
      "expected_version": 4,
      "actual_version": 5
    },
    "correlation_id": "uuid"
  }
}
```

M2 error codes to reserve:

- `ACTIVE_JOB_CONFLICT`.
- `ACTIVE_COMMAND_CONFLICT`.
- `IDEMPOTENCY_CONFLICT`.
- `PRECONDITION_REQUIRED`.
- `JOB_VERSION_CONFLICT`.
- `INVALID_JOB_TRANSITION`.
- `COMMAND_NOT_FOUND`.
- `WORKER_PREPARATION_FAILED`.
- `WORKER_LAUNCH_FAILED`.
- `WORKER_EXITED_WITHOUT_TERMINAL_EVENT`.
- `WORKER_EVENT_INVALID`.
- `WORKER_EVENT_SEQUENCE_GAP`.
- `WORKER_EVENT_CONFLICT`.
- `OUTPUT_LIMIT_EXCEEDED`.
- `COMMAND_TIMED_OUT`.
- `CANCELLATION_FAILED`.
- `ARTIFACT_FINALIZATION_FAILED`.
- `SERVICE_INSTANCE_CONFLICT`.
- `SERVICE_NOT_READY`.

ETag and If-Match rules:

- State-changing job mutations require `If-Match`.
- Missing `If-Match` returns `428 PRECONDITION_REQUIRED`.
- Stale `If-Match` returns `412 PRECONDITION_FAILED`.
- Adapter extracts expected version and calls the application command.
- Browser SSE does not require custom mutation headers.

Idempotency rules:

- Job creation and start require `Idempotency-Key`.
- Persist operation, idempotency key, canonical request checksum, resource type, resource ID, original status code, and created timestamp.
- Same key plus same checksum returns the original resource reference/current representation.
- Same key plus different checksum returns `409 IDEMPOTENCY_CONFLICT`.
- Cancellation is state-idempotent; optional idempotency key may be accepted.

SSE cursor rules:

- SSE supports `Last-Event-ID`.
- SSE supports explicit `after_sequence`.
- Header/query cursor conflicts are rejected.
- Negative or malformed cursors are rejected.
- Future cursor behavior must be documented and tested in M2-11.
- Replay is bounded in batches.
- Keepalive comments do not carry event IDs.
- Disconnect releases resources.

Log-window response:

```json
{
  "command_id": "command-id",
  "stream": "stdout",
  "requested_offset": 0,
  "start_offset": 0,
  "next_offset": 4096,
  "data": "decoded text",
  "encoding": "utf-8",
  "replacement_characters_used": false,
  "truncated": false,
  "terminal": false,
  "artifact_id": null
}
```

Offsets are byte offsets.

Diagnostic wording rules:

- Allowed wording: `Foundation diagnostic completed`, `Command succeeded`, `Event replay connected`.
- Forbidden wording: `Migration completed`, `Build verified`, `Spring Boot upgraded`, `Proof achieved`.
- M2 diagnostic success must never be described as migration success or proof.
- Diagnostic completion leaves achieved migration proof unset and target reached false.

## 10. Exact targeted and full verification commands

Backend full test command:

```powershell
python -m pytest -q
```

Control Tower focused command:

```powershell
python -m pytest -q tests/control_tower
```

Migration test command:

```powershell
python -m pytest -q tests/control_tower/test_sqlite_migrations.py
```

Artifact/path focused commands:

```powershell
python -m pytest -q tests/control_tower/test_artifact_paths.py tests/control_tower/test_artifact_hashing.py tests/control_tower/test_artifact_registry.py
```

Application command/query focused command:

```powershell
python -m pytest -q tests/control_tower/test_create_migration_job.py tests/control_tower/test_transition_job_state.py tests/control_tower/test_application_commands_queries.py
```

Windows/process-control test command:

```text
No command exists today because no process-control package or tests exist.
```

Frontend commands:

```text
No frontend workspace exists today. No npm/pnpm/yarn install, audit, type-check, test, or build command can be run.
```

Dependency diagnostic commands:

```powershell
python -c "import sys, sqlite3; print(sys.version); print(sqlite3.sqlite_version); print(sqlite3.version)"
python -c "import importlib.metadata as m; ..."
node --version
```

SQLite diagnostic commands:

```powershell
python -c "from migration_factory.control_tower.infrastructure.sqlite.migrations import discover_migrations; ..."
python -c "import sqlite3; con=sqlite3.connect(':memory:'); [print(row[0]) for row in con.execute('PRAGMA compile_options')]"
python -c "from migration_factory.control_tower.infrastructure.sqlite.migrations import migrate_control_tower; ..."
```

Post-edit documentation checks:

```powershell
git diff --check
git status --short
```

## 11. Conflicts and decisions

Conflict: Jira asks for implementation map through M2-10, but the hardened M2 plan and M2-00 prompt require M2-01 through M2-13.

- Evidence: Jira AMF-148 acceptance says `M2-01 through M2-10`; `docs/M2_IMPLEMENTATION_PLAN_HARDENED_v0.4.md` defines M2-00 through M2-13 and final implementation order through M2-13.
- Options: limit to Jira M2-10, or document through M2-13 to match the approved plan.
- Decision: document M2-01 through M2-13. Reviewer should confirm Jira acceptance should be updated.
- Later M2 issue affected: M2-11, M2-12, M2-13.

Conflict: M2 plan says M0 process-control evidence must be accepted, but no M0 Windows Job Object implementation or tests exist in this repository.

- Evidence: code search found no `JobObject`, `TerminateJobObject`, Windows process-control package, or M0 tests.
- Options: block M2 coding until evidence is supplied, or implement new process-control in M2 with extra review.
- Decision: mark evidence missing and require reviewer decision before M2-06/M2-08 implementation.
- Later M2 issue affected: M2-06 and M2-08.

Conflict: M2 plan recommends native FastAPI SSE imports from `fastapi.sse`, but FastAPI is not installed and compatibility is unverified.

- Evidence: `fastapi=NOT_INSTALLED`, `starlette=NOT_INSTALLED`, `uvicorn=NOT_INSTALLED`.
- Options: add FastAPI candidate later and verify native SSE, or select an alternate SSE dependency after compatibility testing.
- Decision: no dependency change in M2-00. M2-10/M2-11 must verify installed FastAPI support before coding SSE.
- Later M2 issue affected: M2-10 and M2-11.

Conflict: M2 plan prefers frontend candidates Next.js 16.2.7, React 19.2.7, and Node 24 LTS, but there is no frontend workspace.

- Evidence: no `package.json` or frontend tree found; `node --version` reports `v24.15.0`.
- Options: create a new frontend workspace in M2-12, or defer frontend until a separate workspace decision.
- Decision: approve new workspace location `web/control-tower/` for M2-12 unless reviewers choose a different repo convention.
- Later M2 issue affected: M2-12 and M2-13.

Conflict: M1 run events use a closed `CHECK`, while M2 requires new event types.

- Evidence: `run_events.event_type` constraint only allows `job_created`, `job_state_changed`, `artifact_registered`.
- Options: rebuild `run_events` with a larger closed check, or introduce `event_types` catalog and foreign key.
- Decision: introduce `event_types` catalog and rebuild `run_events` in M2-02.
- Later M2 issue affected: M2-02 and future event-adding issues.

Conflict: Full backend baseline is not green.

- Evidence: `python -m pytest -q` reports 4 failures in Copilot/final-report tests outside Control Tower.
- Options: fix unrelated tests now, ignore failures, or record baseline failures and proceed with documentation-only issue.
- Decision: record baseline failures as unrelated/pre-existing for M2-00. No unrelated code fixes in this issue.
- Later M2 issue affected: M2-13 full acceptance requires either green baseline or approved exception.

Conflict: Repository has no lockfile, while M2 later requires exact dependencies locked.

- Evidence: no Python or frontend lock files found.
- Options: introduce lock strategy in M2-00, or defer to dependency-owning implementation issue.
- Decision: defer. M2-00 documents the absence only.
- Later M2 issue affected: M2-10, M2-12, M2-13.

## 12. Updated file-by-file implementation map

M2-01 - Add command, event, idempotency, and limit contracts

- Expected files to add: `migration_factory/control_tower/domain/commands.py`, `migration_factory/control_tower/domain/events.py`, `migration_factory/control_tower/application/idempotency.py`, `migration_factory/control_tower/application/limits.py`, tests under `tests/control_tower/`.
- Expected files to change: `domain/errors.py`, `application/commands.py`, `application/dto.py`, `application/ports.py`, package `__init__.py` files if exports are used.
- Files that must not be touched: `0001_foundation.sql`, migration engine behavior, AI Hub profile.
- Dependencies: M2-00.
- Tests to add: command state values, command transitions, event envelope validation, idempotency checksum behavior, limits.
- Tests to run: `python -m pytest -q tests/control_tower`.

M2-02 - Add M2 persistence migration

- Expected files to add: `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_foundation.sql`, M2 repository tests.
- Expected files to change: `application/ports.py`, `infrastructure/sqlite/repositories.py`, `infrastructure/sqlite/unit_of_work.py`.
- Files that must not be touched: `0001_foundation.sql`, migration runner safety behavior unless a reviewed defect is found.
- Dependencies: M2-01.
- Tests to add: upgrade actual M1 database, preserve M1 rows/checksums, rebuild `run_events`, event-type catalog, rollback, `foreign_key_check`, one active command, idempotency uniqueness.
- Tests to run: `python -m pytest -q tests/control_tower/test_sqlite_migrations.py tests/control_tower`.

M2-03 - Add secure workspace and immutable manifests

- Expected files to add: `migration_factory/control_tower/infrastructure/workspace.py`, `migration_factory/control_tower/application/manifests.py`, focused tests.
- Expected files to change: `application/ports.py`, `application/services.py`, possibly `infrastructure/sqlite/artifact_paths.py`.
- Files that must not be touched: migration engine, AI Hub profile, frontend.
- Dependencies: M2-01, M2-02.
- Tests to add: canonical run configuration materialization, command manifest checksum, atomic publish, path traversal rejection, idempotent preparation.
- Tests to run: Control Tower focused tests plus artifact path tests.

M2-04 - Add durable private event spool

- Expected files to add: `migration_factory/control_tower/infrastructure/worker_spool.py`, event spool tests.
- Expected files to change: `application/ports.py` if spool ports are introduced.
- Files that must not be touched: public `run_events` semantics except through M2-07.
- Dependencies: M2-01, M2-03.
- Tests to add: JSONL writer, flush/fsync, partial line handling, envelope checksum, limit enforcement, cursor parsing.
- Tests to run: new spool tests and `python -m pytest -q tests/control_tower`.

M2-05 - Add diagnostic worker and child runtime

- Expected files to add: `migration_factory/control_tower/worker/__init__.py`, `migration_factory/control_tower/worker/diagnostic.py`, `migration_factory/control_tower/worker/runtime.py`, tests.
- Expected files to change: package metadata only if entry points are required.
- Files that must not be touched: existing migration execution engine, Maven/OpenRewrite runtime.
- Dependencies: M2-01, M2-03, M2-04.
- Tests to add: manifest verification, fixed child operation, fresh environment, bounded stdout/stderr capture, cooperative cancellation marker.
- Tests to run: worker tests and Control Tower focused tests.

M2-06 - Add API singleton and durable dispatcher

- Expected files to add: `migration_factory/control_tower/infrastructure/singleton.py`, `migration_factory/control_tower/application/dispatcher.py`, `migration_factory/control_tower/infrastructure/process_control.py`, tests.
- Expected files to change: `application/services.py`, `application/ports.py`, repositories if command claim methods are needed.
- Files that must not be touched: FastAPI routes, SSE adapter, Next.js workspace.
- Dependencies: M2-02, M2-03, M2-05, reviewer decision on missing M0 evidence.
- Tests to add: named mutex behavior, second instance conflict, queued command claim, no launch before persistence, suspended launch evidence.
- Tests to run: Control Tower focused tests and Windows/process-control tests once present.

M2-07 - Add event ingestion and projections

- Expected files to add: `migration_factory/control_tower/application/ingestion.py`, `migration_factory/control_tower/application/projections.py`, tests.
- Expected files to change: `application/ports.py`, repositories, `application/dto.py`.
- Files that must not be touched: worker subprocess launch and FastAPI routes.
- Dependencies: M2-02, M2-04, M2-06.
- Tests to add: receipt/cursor transaction, duplicate/late/conflict dispositions, public sequence allocation, projection atomicity, recovery-required handling.
- Tests to run: ingestion tests and `python -m pytest -q tests/control_tower`.

M2-08 - Add process monitor, timeout, and cancellation

- Expected files to add: `migration_factory/control_tower/application/process_monitor.py`, cancellation tests, Windows Job Object tests.
- Expected files to change: `infrastructure/process_control.py`, services/repositories for cancellation state.
- Files that must not be touched: SSE and frontend.
- Dependencies: M2-06, M2-07, reviewer decision on M0 evidence.
- Tests to add: normal worker exit, exit without terminal event, graceful cancellation, forced cancellation, timeout, completion/cancel race, descendants terminated.
- Tests to run: Windows process-control tests and full Control Tower tests.

M2-09 - Add terminal artifact finalization

- Expected files to add: `migration_factory/control_tower/application/artifact_finalization.py`, tests.
- Expected files to change: `application/services.py`, `application/ports.py`, repositories if command artifact links are persisted.
- Files that must not be touched: active log/spool registration before closure.
- Dependencies: M2-03, M2-04, M2-07, M2-08.
- Tests to add: closed-file verification, stream hashing, retry after DB failure, forensic spool registration, atomic metadata linking.
- Tests to run: artifact tests and Control Tower focused tests.

M2-10 - Add FastAPI adapter and local security

- Expected files to add: `migration_factory/control_tower/adapters/fastapi/__init__.py`, app factory, route modules, error translation, security middleware, tests.
- Expected files to change: dependency files and lockfile strategy after reviewer approval.
- Files that must not be touched: dispatcher implementation except via application ports; worker launch from routes is prohibited.
- Dependencies: M2-01 through M2-09 as needed for endpoints.
- Tests to add: app factory/lifespan, jobs/start/cancel, logs/events/artifacts metadata, ETag/If-Match, idempotency, Host/Origin/CORS, actor provider, health.
- Tests to run: FastAPI adapter tests, Control Tower tests, dependency diagnostics.

M2-11 - Add native persisted SSE replay

- Expected files to add: `migration_factory/control_tower/adapters/fastapi/sse.py`, SSE tests.
- Expected files to change: FastAPI app/router wiring from M2-10.
- Files that must not be touched: worker spool direct exposure is prohibited.
- Dependencies: M2-07, M2-10, verified FastAPI SSE compatibility.
- Tests to add: `Last-Event-ID`, `after_sequence`, header/query conflict, malformed cursor, bounded replay, keepalive without ID, disconnect cleanup, only committed events.
- Tests to run: SSE tests, FastAPI adapter tests, Control Tower tests.

M2-12 - Add minimal Next.js vertical slice

- Expected files to add: `web/control-tower/package.json`, lockfile, Next.js app files, generated or shared contract types, frontend tests.
- Expected files to change: repository docs for frontend commands if needed.
- Files that must not be touched: backend business rules, proof rules, authorization rules, filesystem access.
- Dependencies: M2-10, M2-11.
- Tests to add: no-store initial fetch, Server/Client boundary, EventSource bootstrap, duplicate sequence ignored, 412 refresh, byte-offset log pagination, no false migration/proof wording.
- Tests to run: package manager install consistency check, audit, type-check, unit tests, production build once workspace exists.

M2-13 - Complete M2 acceptance and documentation

- Expected files to add: M2 evidence matrix, operational runbook, acceptance documentation.
- Expected files to change: docs only unless small test harness adjustments are approved.
- Files that must not be touched: M1 behavior, AI Hub profile, migration engine.
- Dependencies: M2-01 through M2-12.
- Tests to add: success/failure/timeout/cancel scenarios, crash-window suite, Windows process-tree suite, SSE reconnect suite, security/adversarial tests.
- Tests to run: backend full suite, Control Tower suite, Windows/process-control suite, frontend audit/type-check/test/build, dependency audits, SQLite diagnostics.
