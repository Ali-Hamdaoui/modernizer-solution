# M1 Implementation Plan — AI Migration Control Tower

**Version:** 1.0 — FINAL  
**Date:** 2026-06-08  
**Status:** READY  
**Scope:** M1 — Domain, Persistence & Application Foundation  
**Owner:** ABDELILAH MORTAKI  
**Reviewers:** HAMDAOUI Ali · ilyas abarbach  
**Validated baseline:** `617 passed, 3 skipped, 4 subtests passed`

---

## 0. Executive Summary

M1 builds the reliable operational foundation of the AI Migration Control Tower.

It does **not** execute migrations, run Maven, invoke OpenRewrite, start LangGraph workflows, expose FastAPI endpoints, stream SSE events, render Next.js pages, or call LLMs.

M1 creates the system that can reliably answer:

- What is a migration job?
- Which states can it enter?
- Which state changes are valid?
- Which runner and pipeline configuration was selected?
- How is that configuration frozen for the lifetime of the job?
- How is exactly one active migration enforced?
- How are events, artifacts, and audit records stored?
- How are invalid or concurrent updates rejected?
- How can future CLI, TUI, FastAPI, and Next.js clients reuse the same application rules?

At the end of M1, the repository will contain a new isolated package:

```text
migration_factory/control_tower/
```

The current migration engine remains unchanged and fully operational.

### Locked M1 decisions

| Decision | Final choice |
|---|---|
| Persistence | stdlib `sqlite3` |
| Schema migration model | ordered SQL files executed statement-by-statement inside explicit transactions |
| Database location | `%LOCALAPPDATA%/AI-Migration-Control-Tower/control_tower.sqlite3` with overrides |
| Configuration validation | `pydantic>=2,<3` |
| Default SQLite journal mode | `DELETE` |
| One-active-job enforcement | partial unique index + checks + repository invariants |
| Run events | strictly job-scoped |
| Global registrations | audit-only, no `run_events` row |
| Artifact storage reference | registered root ID + original/normalized relative path |
| Target Spring Boot version | `3.5.14` for the Control Tower contract |
| Existing historical runs | not imported in M1 |
| LangGraph checkpoints | remain separate from Control Tower operational state |

---

## 1. M1 Goal

> Build a backend-only domain, persistence, and application layer that can create and store a migration job, enforce its lifecycle, freeze its configuration, register artifacts, append events and audits atomically, and prevent more than one nonterminal job.

M1 creates no user-facing interface. It creates the reusable core that future interfaces will call.

### M1 success statement

M1 is successful when the test suite can demonstrate:

```text
Register runner profile
→ register generic pipeline definition
→ create one migration job
→ freeze its run configuration
→ create its stage rows
→ append job_created event
→ append audit record
→ reject a second active job
→ transition the first job using optimistic concurrency
→ append state event and audit atomically
→ register a safe artifact
→ persist all state across process restart
```

---

## 2. Scope

### 2.1 Included

#### Domain contracts

- `JobState`
- `StageState`
- `TargetProofLevel`
- job transition rules
- terminal/nonterminal helpers
- typed errors
- optimistic version semantics
- immutable domain records

#### Operational persistence

- SQLite database
- database path resolution
- connection configuration
- ordered schema migrations
- migration checksums
- schema-history tracking
- foreign-key enforcement
- one-active-job enforcement
- append-only audit protection

#### Configuration contracts

- runner profiles
- registered filesystem roots
- Maven and JDK inventory
- network policy
- AI profile references without secrets
- generic pipeline definitions
- immutable per-job run configurations

#### Application commands

- register runner profile
- register pipeline definition
- create migration job
- transition migration job state
- register artifact

#### Application queries

- get/list migration jobs
- get active migration job
- get run configuration
- get/list runner profiles
- get/list pipeline definitions
- list stage runs
- list run events
- list artifacts
- list audit records

#### Persisted evidence

- job-scoped events
- immutable artifact metadata
- append-only audit records

#### Tests and documentation

- unit tests
- SQLite integration tests
- concurrency tests
- path-security tests
- migration rollback tests
- restart/persistence tests
- baseline regression verification

### 2.2 Deferred

The following are explicitly outside M1:

```text
Worker launching
Maven execution
OpenRewrite execution
LangGraph workflow execution
Command-execution rows
Node-execution rows
Worker leases and heartbeat
Windows process-tree cancellation
SSE streaming
FastAPI endpoints
Next.js UI
Chatbot
LLM calls
Skills registry
Repair workflow
Patch application
Rollback execution
Proof-gate execution
Approval persistence
Historical-run import
Runtime or endpoint smoke tests
```

---

## 3. Current Repository Baseline

### 3.1 Existing engine boundaries

The current engine remains authoritative for migration execution.

| Existing area | Current responsibility | M1 action |
|---|---|---|
| `migration_factory/orchestrator/state.py` | LangGraph mutable workflow state | Do not modify |
| `migration_factory/orchestrator/graph.py` | Existing workflow graph | Do not modify |
| `migration_factory/orchestrator/checkpointing.py` | LangGraph continuation checkpoints | Keep separate |
| `migration_factory/orchestrator/runner.py` | Current CLI run entry point | Do not modify |
| `migration_factory/orchestrator/resume.py` | Current approval resume entry point | Do not modify |
| `migration_factory/approval/artifacts.py` | Existing approval artifacts and locks | Reuse patterns only |
| `migration_factory/agents/transformation_agent/workspace.py` | Sandbox path safety | Reuse lessons, not API directly |
| `migration_factory/tui/history.py` | TUI artifact resolution | Do not copy unchanged |
| `migration_factory/contracts/schema_validation.py` | JSON Schema artifact validation | Leave intact |

### 3.2 State ownership

```text
Control Tower database
    Jobs
    Stages
    Run configurations
    Events
    Artifact metadata
    Audit records

LangGraph checkpoint database
    Internal graph continuation state
    Node-local values
    Interrupt/resume position

Filesystem
    Logs
    Reports
    Diffs
    Plans
    Other large artifacts
```

The browser, CLI, TUI, or future FastAPI layer must never become the source of operational truth.

### 3.3 Spring Boot target alignment

The Control Tower contract uses:

```text
Spring Boot 3.5.14
```

The current AI Hub profile still contains references to `3.5.6`.

M1 must not change the AI Hub profile. A separate reviewed task must align the execution profile before the Control Tower starts real migration execution.

Generic pipeline schema work is not blocked by that external alignment task.

---

## 4. Domain Model

## 4.1 Enum implementation rule

The repository supports Python `>=3.10`.

Use:

```python
class JobState(str, Enum):
    ...
```

Do not require `StrEnum`.

Persist:

```python
state.value
```

Never persist:

```python
str(state)
```

---

## 4.2 JobState

```text
CREATED
QUEUED
STARTING
RUNNING
PAUSED_FOR_PLAN_APPROVAL
PAUSED_FOR_REPAIR
RESUMING
CANCELLING
ORPHANED
RECOVERY_REQUIRED
COMPLETED
FAILED
REJECTED
CANCELLED
```

Terminal states:

```text
COMPLETED
FAILED
REJECTED
CANCELLED
```

All other states are nonterminal and occupy the single active-job slot.

### Allowed transitions

| Current state | Allowed next states |
|---|---|
| `CREATED` | `QUEUED`, `REJECTED`, `CANCELLED` |
| `QUEUED` | `STARTING`, `CANCELLING`, `FAILED` |
| `STARTING` | `RUNNING`, `CANCELLING`, `FAILED`, `ORPHANED`, `RECOVERY_REQUIRED` |
| `RUNNING` | `PAUSED_FOR_PLAN_APPROVAL`, `PAUSED_FOR_REPAIR`, `CANCELLING`, `COMPLETED`, `FAILED`, `ORPHANED`, `RECOVERY_REQUIRED` |
| `PAUSED_FOR_PLAN_APPROVAL` | `RESUMING`, `REJECTED`, `CANCELLING`, `RECOVERY_REQUIRED` |
| `PAUSED_FOR_REPAIR` | `RESUMING`, `FAILED`, `CANCELLING`, `RECOVERY_REQUIRED` |
| `RESUMING` | `RUNNING`, `FAILED`, `CANCELLING`, `RECOVERY_REQUIRED` |
| `CANCELLING` | `CANCELLED`, `FAILED`, `RECOVERY_REQUIRED` |
| `ORPHANED` | `RECOVERY_REQUIRED`, `FAILED`, `CANCELLED` |
| `RECOVERY_REQUIRED` | `RESUMING`, `FAILED`, `CANCELLED` |
| Terminal state | No normal outgoing transitions |

### Reference implementation

```python
from enum import Enum


class JobState(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED_FOR_PLAN_APPROVAL = "PAUSED_FOR_PLAN_APPROVAL"
    PAUSED_FOR_REPAIR = "PAUSED_FOR_REPAIR"
    RESUMING = "RESUMING"
    CANCELLING = "CANCELLING"
    ORPHANED = "ORPHANED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.REJECTED,
        JobState.CANCELLED,
    }
)


def is_terminal_job_state(state: JobState) -> bool:
    return state in TERMINAL_JOB_STATES
```

---

## 4.3 StageState

M1 persists stage rows but does not execute stages.

```text
PENDING
READY
RUNNING
PAUSED
PASSED
PASSED_WITH_WARNINGS
FAILED
SKIPPED_BY_POLICY
BLOCKED
CANCELLED
```

M1 defines stable values only. The stage transition table belongs to the deterministic execution milestone.

---

## 4.4 TargetProofLevel

M1 persists and validates the requested proof target.

```text
ANALYZED
PLANNED
TRANSFORMED
BUILD_TEST_VERIFIED
RUNTIME_VERIFIED
ENDPOINT_VERIFIED
```

`PRODUCTION_READY` is excluded from V1.

`TargetProofLevel` is different from the future `ProofGateState`:

- `TargetProofLevel` describes the requested final outcome.
- `ProofGateState` will later describe the status of individual validation gates.

```python
class TargetProofLevel(str, Enum):
    ANALYZED = "ANALYZED"
    PLANNED = "PLANNED"
    TRANSFORMED = "TRANSFORMED"
    BUILD_TEST_VERIFIED = "BUILD_TEST_VERIFIED"
    RUNTIME_VERIFIED = "RUNTIME_VERIFIED"
    ENDPOINT_VERIFIED = "ENDPOINT_VERIFIED"
```

---

## 4.5 Deferred state contracts

Do not implement placeholder enums in M1.

Future milestones must use the PRD vocabularies for:

- command state;
- approval state;
- repair state;
- proof-gate state.

---

## 4.6 Optimistic concurrency

`migration_jobs.version` starts at `1`.

Every transition command includes:

```text
job_id
expected_version
target_state
actor
reason
correlation_id
```

The repository updates using:

```sql
UPDATE migration_jobs
SET
  status = ?,
  version = version + 1,
  active_slot = ?,
  updated_at = ?
WHERE job_id = ?
  AND version = ?;
```

If zero rows are changed:

1. Re-read the job.
2. If it no longer exists, raise `NotFoundError`.
3. Otherwise raise `StaleVersionError` or `ConcurrencyConflictError`.

---

## 5. Package Architecture

```text
migration_factory/
  control_tower/
    __init__.py

    domain/
      __init__.py
      states.py
      transitions.py
      entities.py
      errors.py
      checksums.py

    application/
      __init__.py
      commands.py
      queries.py
      dto.py
      ports.py
      services.py

    schemas/
      __init__.py
      common.py
      runner_profile.py
      pipeline_definition.py
      run_configuration.py

    infrastructure/
      __init__.py
      paths.py
      windows_paths.py

      sqlite/
        __init__.py
        connection.py
        migrations.py
        unit_of_work.py
        repositories.py
        artifact_paths.py

        migrations/
          0001_foundation.sql

tests/
  control_tower/
    conftest.py
    test_paths.py
    test_domain_transitions.py
    test_sqlite_migrations.py
    test_active_job_lock.py
    test_run_configurations.py
    test_run_events.py
    test_artifact_registry.py
    test_audit_records.py
    test_runner_profile_schema.py
    test_pipeline_definition_schema.py
    test_application_commands_queries.py
```

### Dependency rules

```text
domain
    imports only Python standard library

application
    imports domain and schema contracts
    does not import SQLite, LangGraph, FastAPI, TUI, CLI, or Next.js

schemas
    imports Pydantic and standard library
    contains no persistence behavior

infrastructure
    implements application ports
    may import sqlite3 and platform-specific helpers
```

`application/ports.py` owns repository and Unit of Work protocols.

SQLite implementations live under `infrastructure/sqlite/`.

---

## 6. SQLite Persistence Design

## 6.1 Database location

Default on Windows:

```text
%LOCALAPPDATA%/
  AI-Migration-Control-Tower/
    control_tower.sqlite3
```

Resolution order:

```text
1. Explicit path provided by application configuration
2. CONTROL_TOWER_DB_PATH
3. %LOCALAPPDATA%/AI-Migration-Control-Tower/control_tower.sqlite3
4. XDG_STATE_HOME/ai-migration-control-tower/control_tower.sqlite3
5. ~/.local/state/ai-migration-control-tower/control_tower.sqlite3
```

Tests always use a temporary directory.

The operational database must not be placed under one migration output folder.

---

## 6.2 Connection policy

```python
def connect_control_tower(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        db_path,
        isolation_level=None,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection
```

Rules:

- enable foreign keys on every connection;
- use explicit transactions;
- do not set journal mode on every connection;
- initialize journal mode once;
- allow only approved values;
- default to `DELETE` in M1.

```python
ALLOWED_JOURNAL_MODES = frozenset({"DELETE", "WAL"})
```

`WAL` remains unused in M1.

---

## 6.3 Timestamp contract

All persisted timestamps use UTC RFC 3339 with microsecond precision and a `Z` suffix.

```text
2026-06-08T16:25:43.123456Z
```

```python
from datetime import datetime, timezone


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
```

---

## 6.4 Checksum contract

For runner profiles, pipeline definitions, run configurations, and event payloads:

```text
SHA-256(canonical JSON bytes)
```

Canonical JSON:

- UTF-8;
- sorted object keys;
- compact separators;
- no timestamps generated by persistence;
- no creator metadata generated by persistence;
- no checksum field inside the checksummed payload;
- no database-generated key unless it belongs to the actual domain payload.

---

## 6.5 M1 tables

```text
schema_migrations
runner_profiles
pipeline_definitions
migration_jobs
run_configurations
stage_runs
run_events
artifacts
audit_records
```

Deferred:

```text
node_executions
command_executions
worker_leases
approvals
repair_attempts
proof_gates
assistant_threads
assistant_messages
skills
model_calls
```

---

## 6.6 Foundation schema

The following is the intended logical schema. The final migration SQL may adjust formatting but must preserve these constraints.

```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE runner_profiles (
    runner_profile_id TEXT NOT NULL,
    runner_profile_version TEXT NOT NULL,
    display_name TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (runner_profile_id, runner_profile_version)
);

CREATE TABLE pipeline_definitions (
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    display_name TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    graph_state_schema_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    PRIMARY KEY (pipeline_id, pipeline_version)
);

CREATE TABLE migration_jobs (
    job_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK (version >= 1),
    status TEXT NOT NULL,
    active_slot INTEGER CHECK (active_slot IS NULL OR active_slot = 1),
    last_event_sequence INTEGER NOT NULL DEFAULT 0
        CHECK (last_event_sequence >= 0),

    runner_profile_id TEXT NOT NULL,
    runner_profile_version TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,

    target_proof_level TEXT NOT NULL,
    achieved_proof_level TEXT,

    legacy_source_ref TEXT NOT NULL,
    output_root_ref TEXT NOT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    created_by TEXT NOT NULL,

    FOREIGN KEY (runner_profile_id, runner_profile_version)
        REFERENCES runner_profiles(
            runner_profile_id,
            runner_profile_version
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (pipeline_id, pipeline_version)
        REFERENCES pipeline_definitions(
            pipeline_id,
            pipeline_version
        )
        ON DELETE RESTRICT,

    CHECK (
        status IN (
            'CREATED',
            'QUEUED',
            'STARTING',
            'RUNNING',
            'PAUSED_FOR_PLAN_APPROVAL',
            'PAUSED_FOR_REPAIR',
            'RESUMING',
            'CANCELLING',
            'ORPHANED',
            'RECOVERY_REQUIRED',
            'COMPLETED',
            'FAILED',
            'REJECTED',
            'CANCELLED'
        )
    ),

    CHECK (
        target_proof_level IN (
            'ANALYZED',
            'PLANNED',
            'TRANSFORMED',
            'BUILD_TEST_VERIFIED',
            'RUNTIME_VERIFIED',
            'ENDPOINT_VERIFIED'
        )
    ),

    CHECK (
        achieved_proof_level IS NULL
        OR achieved_proof_level IN (
            'ANALYZED',
            'PLANNED',
            'TRANSFORMED',
            'BUILD_TEST_VERIFIED',
            'RUNTIME_VERIFIED',
            'ENDPOINT_VERIFIED'
        )
    ),

    CHECK (
        (
            status IN (
                'COMPLETED',
                'FAILED',
                'REJECTED',
                'CANCELLED'
            )
            AND active_slot IS NULL
        )
        OR
        (
            status NOT IN (
                'COMPLETED',
                'FAILED',
                'REJECTED',
                'CANCELLED'
            )
            AND active_slot = 1
        )
    )
);

CREATE UNIQUE INDEX ux_one_active_job
ON migration_jobs(active_slot)
WHERE active_slot = 1;

CREATE INDEX ix_migration_jobs_status
ON migration_jobs(status);

CREATE INDEX ix_migration_jobs_created_at
ON migration_jobs(created_at);

CREATE TABLE run_configurations (
    run_configuration_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,

    schema_version TEXT NOT NULL,
    runner_profile_id TEXT NOT NULL,
    runner_profile_version TEXT NOT NULL,
    pipeline_id TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,

    target_proof_level TEXT NOT NULL,
    enabled_gates_json TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (job_id)
        REFERENCES migration_jobs(job_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (runner_profile_id, runner_profile_version)
        REFERENCES runner_profiles(
            runner_profile_id,
            runner_profile_version
        )
        ON DELETE RESTRICT,

    FOREIGN KEY (pipeline_id, pipeline_version)
        REFERENCES pipeline_definitions(
            pipeline_id,
            pipeline_version
        )
        ON DELETE RESTRICT,

    CHECK (
        target_proof_level IN (
            'ANALYZED',
            'PLANNED',
            'TRANSFORMED',
            'BUILD_TEST_VERIFIED',
            'RUNTIME_VERIFIED',
            'ENDPOINT_VERIFIED'
        )
    )
);

CREATE TABLE stage_runs (
    stage_run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index >= 1),
    stage_id TEXT NOT NULL,
    status TEXT NOT NULL,
    input_source_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,

    FOREIGN KEY (job_id)
        REFERENCES migration_jobs(job_id)
        ON DELETE RESTRICT,

    UNIQUE (job_id, stage_index),

    CHECK (
        status IN (
            'PENDING',
            'READY',
            'RUNNING',
            'PAUSED',
            'PASSED',
            'PASSED_WITH_WARNINGS',
            'FAILED',
            'SKIPPED_BY_POLICY',
            'BLOCKED',
            'CANCELLED'
        )
    )
);

CREATE TABLE run_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    correlation_id TEXT,
    causation_id TEXT,
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (job_id)
        REFERENCES migration_jobs(job_id)
        ON DELETE RESTRICT,

    UNIQUE (job_id, sequence),

    CHECK (
        event_type IN (
            'job_created',
            'job_state_changed',
            'artifact_registered'
        )
    )
);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_run_id TEXT,

    artifact_type TEXT NOT NULL,
    registered_root_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    normalized_relative_path TEXT NOT NULL,

    content_type TEXT,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    checksum_algorithm TEXT NOT NULL,
    checksum TEXT NOT NULL,

    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,

    FOREIGN KEY (job_id)
        REFERENCES migration_jobs(job_id)
        ON DELETE RESTRICT,

    FOREIGN KEY (stage_run_id)
        REFERENCES stage_runs(stage_run_id)
        ON DELETE RESTRICT,

    UNIQUE (
        job_id,
        registered_root_id,
        normalized_relative_path
    )
);

CREATE TABLE audit_records (
    audit_id TEXT PRIMARY KEY,
    job_id TEXT,

    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,

    prior_state TEXT,
    new_state TEXT,
    job_version INTEGER,

    correlation_id TEXT,
    causation_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,

    FOREIGN KEY (job_id)
        REFERENCES migration_jobs(job_id)
        ON DELETE RESTRICT
);

CREATE INDEX ix_stage_runs_job_id
ON stage_runs(job_id);

CREATE INDEX ix_run_events_job_sequence
ON run_events(job_id, sequence);

CREATE INDEX ix_artifacts_job_id
ON artifacts(job_id);

CREATE INDEX ix_audit_records_job_created_at
ON audit_records(job_id, created_at);

CREATE TRIGGER audit_records_no_update
BEFORE UPDATE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records are append-only');
END;

CREATE TRIGGER audit_records_no_delete
BEFORE DELETE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records are append-only');
END;
```

### Stage runner resolution

M1 does not duplicate runner-profile IDs on `stage_runs`.

```text
stage_run
→ migration_job
→ run_configuration
→ runner_profile
```

A stage-level runner override may be added later only if remote or heterogeneous runners become a real requirement.

---

## 6.7 One-active-job enforcement

Use all three layers:

1. Partial unique index.
2. Database check tying state to `active_slot`.
3. Repository logic derived from typed `JobState`.

```python
def active_slot_for(state: JobState) -> int | None:
    return None if is_terminal_job_state(state) else 1
```

Do not convert every `sqlite3.IntegrityError` into an active-job conflict.

On job-creation failure:

1. Query for the active job.
2. If an active job exists, raise `ConcurrencyConflictError`.
3. Otherwise preserve or wrap the actual integrity error.

---

## 6.8 Job-scoped event sequencing

`run_events` is strictly job-scoped.

M1 event types:

```text
job_created
job_state_changed
artifact_registered
```

Global runner-profile and pipeline registration operations create audit records only.

Sequence allocation:

```text
BEGIN IMMEDIATE
→ update migration_jobs.last_event_sequence += 1
→ read new sequence
→ insert event
→ perform related audit write
→ commit
```

Do not use:

```sql
SELECT MAX(sequence) + 1
```

---

## 7. Migration Runner Design

## 7.1 Why `executescript()` is not used

Versioned migrations must not use `sqlite3.executescript()` inside an assumed outer transaction.

The migration runner must control exactly when the transaction begins, commits, and rolls back.

---

## 7.2 Migration file rules

Directory:

```text
migration_factory/control_tower/infrastructure/sqlite/migrations/
  0001_foundation.sql
  0002_...
```

Filename contract:

```text
NNNN_description.sql
```

Rules:

- integer version prefix;
- no duplicate versions;
- strict ascending order;
- exact file-byte SHA-256 checksum;
- applied migration files are immutable;
- changed checksum for an applied version is fatal.

---

## 7.3 Statement execution

The runner accumulates SQL until:

```python
sqlite3.complete_statement(buffer)
```

returns true.

Important:

- `complete_statement()` is only a completeness signal;
- it is not a SQL parser;
- the completed buffer must represent exactly one top-level statement;
- `connection.execute()` must receive one statement;
- two top-level statements in one completed buffer are rejected;
- comments and quoted semicolons must work;
- trigger bodies with internal semicolons must work.

Reject migration statements that control transactions or connection policy:

```text
BEGIN
COMMIT
ROLLBACK
SAVEPOINT
RELEASE
PRAGMA foreign_keys
PRAGMA journal_mode
PRAGMA locking_mode
```

---

## 7.4 Transaction order

For each unapplied migration:

```text
BEGIN IMMEDIATE
→ execute all approved statements individually
→ PRAGMA foreign_key_check
→ fail and roll back if violations exist
→ insert schema_migrations row
→ COMMIT
```

The schema changes and schema-history row are one atomic unit.

A final `foreign_key_check` may run after all versions as defense in depth.

### Illustrative runner

```python
def apply_one_migration(
    connection: sqlite3.Connection,
    migration: MigrationFile,
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in split_sql_statements(migration.sql):
            reject_forbidden_migration_statement(statement)
            connection.execute(statement)

        violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise MigrationIntegrityError(violations)

        connection.execute(
            """
            INSERT INTO schema_migrations (
                version,
                name,
                checksum,
                applied_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                migration.version,
                migration.name,
                migration.checksum,
                utc_now(),
            ),
        )

        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
```

---

## 8. Configuration Schemas

M1 adds:

```text
pydantic>=2,<3
```

Every external configuration model uses:

```python
ConfigDict(
    extra="forbid",
    frozen=True,
    strict=True,
)
```

---

## 8.1 Runner profile

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class RegisteredRoot(StrictModel):
    root_id: str
    kind: Literal["source", "output"]
    path: str


class FilesystemPolicy(StrictModel):
    roots: tuple[RegisteredRoot, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def root_ids_are_unique(self) -> "FilesystemPolicy":
        ids = [root.root_id for root in self.roots]
        if len(ids) != len(set(ids)):
            raise ValueError("registered root IDs must be unique")
        return self


class MavenConfig(StrictModel):
    executable_path: str
    expected_version: str
    allow_wrapper: bool = False


class JdkConfig(StrictModel):
    jdk_id: str
    java_home: str
    expected_major: int
    role: Literal["source", "target", "runtime", "optional"]


class NetworkPolicy(StrictModel):
    mode: Literal["offline", "allowlisted"]
    allowed_hosts: tuple[str, ...] = ()


class AIProfileReference(StrictModel):
    profile_id: str


class RunnerProfile(StrictModel):
    schema_version: str
    runner_profile_id: str
    runner_profile_version: str
    display_name: str
    python_executable: str
    ai_hub_path: str
    maven: MavenConfig
    jdks: tuple[JdkConfig, ...] = Field(min_length=1)
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    ai_profile: AIProfileReference | None = None

    @model_validator(mode="after")
    def jdk_ids_are_unique(self) -> "RunnerProfile":
        ids = [jdk.jdk_id for jdk in self.jdks]
        if len(ids) != len(set(ids)):
            raise ValueError("JDK IDs must be unique")
        return self
```

Runner profiles must not contain:

```text
API keys
Passwords
OAuth tokens
Private keys
Connection secrets
Raw Azure credentials
```

They may reference named environment variables or provider profiles.

---

## 8.2 Pipeline definition

```python
class PipelineTarget(StrictModel):
    spring_boot: str | None = None
    java: int


class PipelineInputSource(StrictModel):
    kind: Literal["legacy_source", "previous_stage"]
    previous_stage_index: int | None = None


class PipelineStage(StrictModel):
    stage_index: int
    stage_id: str
    profile_id: str
    command_jdk: str
    input_source: PipelineInputSource
    continuation_policy_id: str
    target: PipelineTarget


class PipelineDefinition(StrictModel):
    schema_version: str
    pipeline_id: str
    pipeline_version: str
    display_name: str
    graph_version: str
    graph_state_schema_version: str
    stages: tuple[PipelineStage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_stages(self) -> "PipelineDefinition":
        indexes = [stage.stage_index for stage in self.stages]

        if indexes != list(range(1, len(self.stages) + 1)):
            raise ValueError(
                "stage indexes must be contiguous and start at 1"
            )

        if self.stages[0].input_source.kind != "legacy_source":
            raise ValueError(
                "stage 1 must read the legacy source"
            )

        for stage in self.stages[1:]:
            if stage.input_source.kind != "previous_stage":
                raise ValueError(
                    "stage 2+ must explicitly read a previous stage"
                )

        return self
```

Standalone pipeline validation checks:

- schema shape;
- contiguous indexes;
- input-source rules;
- nonempty JDK identifier;
- known continuation policy;
- immutable ID/version contract.

Cross-model compatibility belongs to the application service.

When creating a job, verify:

```text
Every pipeline stage command_jdk
exists in the selected runner profile JDK inventory
```

---

## 8.3 Run configuration

The run configuration is immutable and authoritative.

```python
class RunPolicy(StrictModel):
    continue_after_warning: bool = False
    enable_runtime_gate: bool = False
    enable_endpoint_gate: bool = False


class RunConfiguration(StrictModel):
    schema_version: str
    run_configuration_id: str
    job_id: str

    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str

    target_proof_level: TargetProofLevel
    enabled_gates: tuple[str, ...]
    policy: RunPolicy
```

The persistence layer calculates and stores the payload checksum. The checksum is not included in its own checksum input.

---

## 9. Application Commands

## 9.1 RegisterRunnerProfile

Atomic behavior:

```text
Validate strict schema
→ canonicalize payload
→ calculate checksum
→ insert when new
→ same ID/version/checksum = idempotent success
→ same ID/version/different checksum = conflict
→ append global audit record
→ commit
```

No `run_events` row is created.

---

## 9.2 RegisterPipelineDefinition

Atomic behavior:

```text
Validate strict generic schema
→ canonicalize payload
→ calculate checksum
→ insert when new
→ same ID/version/checksum = idempotent success
→ same ID/version/different checksum = conflict
→ append global audit record
→ commit
```

No `run_events` row is created.

The generic pipeline schema may be implemented immediately.

AI Hub execution-profile alignment remains a separate task.

---

## 9.3 CreateMigrationJob

Required inputs:

```text
actor
legacy_source_ref
output_root_ref
runner_profile ID/version
pipeline ID/version
target proof level
enabled gates
run policy
correlation ID
```

Atomic behavior:

```text
BEGIN IMMEDIATE
→ load runner profile
→ load pipeline definition
→ validate pipeline/runner JDK compatibility
→ validate target proof
→ claim active slot through job insert
→ create immutable run configuration
→ create stage rows in PENDING
→ allocate event sequence 1
→ insert job_created event
→ insert audit record
→ COMMIT
```

Failure anywhere rolls back everything.

---

## 9.4 TransitionJobState

Atomic behavior:

```text
BEGIN IMMEDIATE
→ load job
→ verify expected version
→ validate domain transition
→ update status/version/active_slot
→ allocate next event sequence
→ insert job_state_changed event
→ insert audit record
→ COMMIT
```

No state transition can occur without its event and audit record.

---

## 9.5 RegisterArtifact

Filesystem validation and hashing occur before the database transaction.

Database behavior after validation:

```text
BEGIN IMMEDIATE
→ verify job still exists
→ insert or idempotently confirm artifact metadata
→ allocate next event sequence
→ insert artifact_registered event
→ insert audit record
→ COMMIT
```

The filesystem and database cannot be one atomic transaction.

If hashing succeeds but the DB transaction fails:

- the file remains on disk;
- no artifact record is created;
- retry is allowed.

---

## 10. Queries

Queries are read-only and never create audit or event records.

Required queries:

```text
GetMigrationJob
GetActiveMigrationJob
ListMigrationJobs
GetRunConfiguration
ListStageRuns
ListRunEvents
ListArtifacts
ListAuditRecords
GetRunnerProfile
ListRunnerProfiles
GetPipelineDefinition
ListPipelineDefinitions
```

Application queries return DTOs, not raw SQLite rows.

---

## 11. Artifact Registry Security

## 11.1 Registered-root resolution

A registered root is stored inside the selected immutable runner profile:

```yaml
filesystem:
  roots:
    - root_id: migration-sources
      kind: source
      path: C:/migration/sources

    - root_id: migration-runs
      kind: output
      path: C:/migration/runs
```

Artifact registration resolves:

```text
job
→ run configuration
→ runner profile
→ registered_root_id
→ backend-only root path
```

The artifact table stores:

```text
registered_root_id
relative_path
normalized_relative_path
```

It does not expose unrestricted absolute paths.

---

## 11.2 Relative-path normalization

The normalized key must:

- reject absolute paths;
- reject UNC paths;
- reject drive-qualified relative paths;
- reject `..`;
- normalize separators;
- remove safe `.` segments;
- apply Windows case normalization when appropriate;
- produce a stable database uniqueness key.

Uniqueness:

```text
(job_id, registered_root_id, normalized_relative_path)
```

---

## 11.3 Symlink, junction, and reparse policy

`pathlib.Path.resolve()` alone is insufficient for the full Windows trust boundary.

M1 must implement a platform helper that:

- inspects every existing path component;
- rejects symlinks escaping the registered root;
- rejects junction/reparse-point components that cannot be proven safe;
- rejects cross-drive changes;
- rejects UNC targets;
- uses conservative rejection when Windows identity cannot be verified.

---

## 11.4 Streaming hashing

Do not use `Path.read_bytes()`.

Use chunked SHA-256:

```python
digest = hashlib.sha256()
size = 0

while chunk := handle.read(1024 * 1024):
    digest.update(chunk)
    size += len(chunk)
```

Capture before and after:

```text
resolved path
file identity
size
mtime_ns
```

Reject registration if any value changes during the read.

---

## 12. File-by-File Implementation Plan

| Order | File | Action | Purpose |
|---:|---|---|---|
| 1 | `migration_factory/control_tower/__init__.py` | Create | Package marker |
| 1 | `domain/states.py` | Create | `JobState`, `StageState`, `TargetProofLevel` |
| 1 | `domain/transitions.py` | Create | Job transition table and validation |
| 1 | `domain/errors.py` | Create | Typed domain/application errors |
| 1 | `tests/control_tower/test_domain_transitions.py` | Create | Domain contract tests |
| 2 | `domain/entities.py` | Create | Immutable domain records |
| 2 | `domain/checksums.py` | Create | Canonical JSON and streaming SHA-256 |
| 2 | `schemas/common.py` | Create | Strict Pydantic base |
| 2 | `schemas/runner_profile.py` | Create | Runner/JDK/root/network contracts |
| 2 | `schemas/pipeline_definition.py` | Create | Generic pipeline contract |
| 2 | `schemas/run_configuration.py` | Create | Frozen run snapshot |
| 2 | schema test files | Create | Validation and conflict tests |
| 3 | `infrastructure/paths.py` | Create | DB path resolution |
| 3 | `infrastructure/windows_paths.py` | Create | Windows path/reparse helpers |
| 3 | `sqlite/connection.py` | Create | SQLite connection policy |
| 3 | `sqlite/migrations.py` | Create | Safe migration runner |
| 3 | `sqlite/migrations/0001_foundation.sql` | Create | M1 schema |
| 3 | `tests/control_tower/test_sqlite_migrations.py` | Create | Migration atomicity |
| 4 | `application/ports.py` | Create | Repository and UoW protocols |
| 4 | `sqlite/unit_of_work.py` | Create | Transaction implementation |
| 4 | `sqlite/repositories.py` | Create | SQLite repositories |
| 4 | persistence test files | Create | Lock, event, config, audit tests |
| 5 | `application/commands.py` | Create | Command DTOs |
| 5 | `application/services.py` | Create | Atomic handlers |
| 5 | `application/queries.py` | Create | Read-only query services |
| 5 | application tests | Create | Command/query behavior |
| 6 | `sqlite/artifact_paths.py` | Create | Artifact path and identity validation |
| 6 | artifact tests | Create | Windows and hashing security |
| 7 | documentation updates | Modify | Setup, schema, transitions |
| 8 | full regression | Run | Verify existing engine unchanged |

---

## 13. Test Plan

## 13.1 Domain

```text
test_job_state_values_are_stable
test_stage_state_values_match_prd
test_target_proof_level_values_match_prd
test_production_ready_is_not_selectable_in_v1
test_every_allowed_job_transition_passes
test_terminal_states_have_no_outgoing_transitions
test_representative_forbidden_transitions_raise
test_enum_values_are_persisted_with_value
```

## 13.2 Paths and connection

```text
test_explicit_database_path_wins
test_environment_database_path_override
test_windows_local_appdata_default
test_non_windows_state_path_fallback
test_foreign_keys_enabled_on_every_connection
test_busy_timeout_configured
test_delete_is_default_journal_mode
test_unsupported_journal_mode_rejected
```

## 13.3 Schema migrations

```text
test_empty_database_creates_all_m1_tables
test_migration_is_idempotent
test_applied_checksum_change_is_rejected
test_failed_migration_rolls_back_schema
test_failed_migration_leaves_no_history_row
test_schema_and_history_are_atomic
test_foreign_key_check_runs_before_commit
test_foreign_key_violation_rolls_back
test_multiple_top_level_statements_are_rejected
test_trigger_body_with_semicolons_is_supported
test_quoted_semicolon_is_supported
test_transaction_control_statement_is_rejected
test_forbidden_pragma_is_rejected
test_upgrade_from_n_minus_one
```

## 13.4 Active job and concurrency

```text
test_first_nonterminal_job_claims_slot
test_second_nonterminal_job_is_rejected
test_terminal_transition_releases_slot
test_new_job_after_terminal_state_succeeds
test_unknown_job_status_is_rejected_by_database
test_active_slot_matches_status
test_integrity_error_without_active_job_is_preserved
test_concurrent_job_creation_allows_exactly_one
test_stale_job_version_is_rejected
```

## 13.5 Configuration

```text
test_valid_runner_profile
test_unknown_runner_field_rejected
test_duplicate_jdk_ids_rejected
test_duplicate_root_ids_rejected
test_secret_fields_rejected
test_valid_generic_pipeline
test_stage_indexes_contiguous
test_stage_one_uses_legacy_source
test_later_stage_uses_previous_stage
test_unknown_continuation_policy_rejected
test_pipeline_runner_jdk_compatibility_checked_on_job_creation
test_same_id_version_checksum_is_idempotent
test_same_id_version_different_checksum_is_conflict
test_run_configuration_is_immutable
test_checksum_excludes_checksum_and_persistence_metadata
```

## 13.6 Events and audit

```text
test_job_created_event_sequence_is_one
test_transition_increments_event_sequence
test_event_sequence_unique_per_job
test_event_sequence_allocation_is_atomic
test_concurrent_sequence_allocation_is_unique
test_profile_registration_creates_global_audit_only
test_pipeline_registration_creates_global_audit_only
test_event_failure_rolls_back_state_change
test_audit_failure_rolls_back_state_change
test_audit_cannot_be_updated
test_audit_cannot_be_deleted
test_audit_repository_exposes_no_mutation_api
```

## 13.7 Artifact registry

```text
test_registered_root_resolved_from_run_configuration
test_absolute_path_rejected
test_unc_path_rejected
test_drive_escape_rejected
test_parent_traversal_rejected
test_case_aliases_share_normalized_key
test_symlink_escape_rejected
test_junction_escape_rejected
test_unknown_reparse_point_rejected
test_large_artifact_hashed_in_chunks
test_file_change_during_hash_rejected
test_path_replacement_during_hash_rejected
test_idempotent_same_artifact_registration
test_same_normalized_path_different_checksum_conflicts
test_absolute_path_not_exposed_by_query
test_artifact_event_and_audit_atomic
```

## 13.8 Regression

```powershell
py -m pytest -q tests/control_tower
py -m pytest -q
```

The existing suite must remain green.

---

## 14. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| M1-AC-01 | Domain enums match approved values |
| M1-AC-02 | Every allowed job transition passes |
| M1-AC-03 | Invalid job transitions are rejected |
| M1-AC-04 | Empty database migrates to the latest M1 schema |
| M1-AC-05 | Failed migration leaves no partial schema/history |
| M1-AC-06 | Exactly one nonterminal job is allowed |
| M1-AC-07 | Terminal transition releases the active slot |
| M1-AC-08 | Stale job version is rejected |
| M1-AC-09 | Job creation writes job, run config, stages, event, and audit atomically |
| M1-AC-10 | State transition writes state, event sequence, event, and audit atomically |
| M1-AC-11 | Configuration IDs/versions are immutable |
| M1-AC-12 | Same configuration version with changed checksum is rejected |
| M1-AC-13 | Artifact escapes are rejected |
| M1-AC-14 | Large artifacts are streamed, not loaded fully into memory |
| M1-AC-15 | Audit records cannot be changed or deleted |
| M1-AC-16 | State survives database close and process restart |
| M1-AC-17 | Control Tower tests pass |
| M1-AC-18 | Existing `617`-test baseline remains green or increases only through new passing tests |

---

## 15. Definition of Done

M1 is done only when:

- [ ] All M1 package files are implemented.
- [ ] `pydantic>=2,<3` is declared and locked.
- [ ] Database path resolution is tested.
- [ ] SQLite connection policy is tested.
- [ ] `0001_foundation.sql` creates the full approved schema.
- [ ] Migration transaction tests prove rollback and history atomicity.
- [ ] Job and stage states match the plan.
- [ ] `TargetProofLevel` excludes production readiness.
- [ ] One-active-job enforcement passes concurrent tests.
- [ ] Optimistic concurrency passes.
- [ ] Events are strictly job-scoped.
- [ ] Global registrations create audit-only records.
- [ ] Artifact root and normalized path rules pass.
- [ ] Artifact hashing is streamed.
- [ ] Audit triggers reject update/delete.
- [ ] All Control Tower tests pass.
- [ ] Full repository regression suite passes.
- [ ] No worker, FastAPI, SSE, Next.js, chatbot, or migration-execution behavior was added.
- [ ] No current orchestrator behavior was changed.

---

## 16. Implementation Sequence

### Unit 1 — Domain

```text
states.py
transitions.py
errors.py
test_domain_transitions.py
```

Expected result:

- stable state contracts;
- valid transition table;
- target proof contract;
- no persistence dependency.

### Unit 2 — Configuration schemas

```text
common.py
runner_profile.py
pipeline_definition.py
run_configuration.py
schema tests
```

Expected result:

- strict immutable configuration objects;
- generic pipeline validation;
- no DB yet.

### Unit 3 — SQLite foundation

```text
paths.py
connection.py
migrations.py
0001_foundation.sql
migration tests
```

Expected result:

- safe DB initialization;
- versioned schema;
- atomic migration history.

### Unit 4 — Ports and repositories

```text
application/ports.py
sqlite/unit_of_work.py
sqlite/repositories.py
repository tests
```

Expected result:

- infrastructure implements application contracts;
- active lock and event sequencing work.

### Unit 5 — Application commands and queries

```text
commands.py
services.py
queries.py
application tests
```

Expected result:

- create and transition operations are atomic;
- queries are read-only.

### Unit 6 — Artifact registry

```text
windows_paths.py
artifact_paths.py
artifact registration service
artifact tests
```

Expected result:

- secure root-based artifact registration;
- streamed hashing;
- event/audit integration.

### Unit 7 — Documentation and full verification

```text
docs
Control Tower test suite
full repository suite
```

Expected result:

- M1 accepted;
- existing migration engine unchanged.

---

## 17. Risks and Controls

| Risk | Control |
|---|---|
| New state vocabulary conflicts with current LangGraph state | Separate package and explicit mapping later |
| SQLite write contention | One active job, short `BEGIN IMMEDIATE` transactions |
| Invalid migration script commits partially | Statement-based execution and rollback tests |
| Event sequence collision | Job-row sequence counter in same transaction |
| Artifact path escapes on Windows | Registered roots, normalization, reparse checks |
| Large log consumes memory | Chunked hashing |
| Configuration silently accepts unknown keys | Pydantic `extra="forbid"` |
| Audit is modified later | No update/delete port plus DB triggers |
| AI Hub target remains inconsistent | Separate alignment task before execution milestone |
| M1 grows into execution/UI work | Explicit out-of-scope list and acceptance checks |

---

## 18. References

- Python `sqlite3` documentation: transaction and script-execution behavior.
- SQLite foreign-key documentation: connection-level enforcement.
- SQLite partial-index documentation: unique indexes over selected rows.
- Pydantic configuration documentation: strict validation, frozen models, and forbidden extra fields.
- AI Migration Control Tower PRD v0.3.
- Existing repository baseline and architecture documentation.

---

# Final Readiness

M1 is approved for implementation.

```text
READY
```

The first coding unit is:

```text
migration_factory/control_tower/domain/states.py
migration_factory/control_tower/domain/transitions.py
migration_factory/control_tower/domain/errors.py
tests/control_tower/test_domain_transitions.py
```
