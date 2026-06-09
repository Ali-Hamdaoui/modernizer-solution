# M2 Implementation Plan — AI Migration Control Tower

**Version:** 0.4 — HARDENED ENGINEERING DRAFT  
**Date:** 2026-06-09  
**Status:** READY FOR M2-00 REPOSITORY ALIGNMENT; CODING BLOCKED UNTIL M2-00 IS APPROVED  
**Milestone:** M2 — Foundation Vertical Slice  
**Dependency:** M1 fully accepted and merged into `DEMO2`  
**Owner:** ABDELILAH MORTAKI  
**Reviewers:** HAMDAOUI Ali · ilyas abarbach  

---

## 0. Readiness Verdict

M2 is architecturally ready to begin **M2-00 repository alignment**.

It is not yet safe to begin production coding because the current repository tree, exact M1 SQL, dependency locks, M0 Windows process-control spike, and post-M1 test baseline have not been verified against this plan.

Readiness assessment:

```text
Product scope and milestone boundary:       READY
Domain and persistence design:              READY, pending schema verification
Worker/event architecture:                  READY
Windows process-control design:             READY, pending M0 code/proof verification
FastAPI/SSE design:                          READY
Next.js design:                              READY, pending workspace verification
Exact files and dependency changes:          NOT VERIFIED
Exact database migration SQL:                NOT VERIFIED
Actual regression baseline:                  NOT VERIFIED
```

Target confidence:

```text
Before M2-00:       approximately 96–97% architecture confidence
After M2-00:        target ≥99% implementation readiness
```

No agent may create production files before M2-00 records the exact current repository state and resolves conflicts.

---

## 1. M2 Purpose

M2 proves the Control Tower’s operational plumbing. It does not execute or certify a real migration.

The required path is:

```text
Create a Control Tower job
→ persist immutable M1 configuration
→ persist a queued command
→ return from the HTTP request
→ claim work through a durable dispatcher
→ materialize immutable run and command manifests
→ create the worker suspended
→ assign the worker to a Windows Job Object
→ persist process identity before execution
→ resume the worker
→ launch one backend-owned diagnostic child process
→ capture bounded stdout and stderr
→ append durable private worker events
→ ingest private events idempotently
→ update projections and append committed public events
→ replay public events through SSE
→ display the current run in minimal Next.js
→ complete, fail, time out, or cancel the entire process tree
→ finalize closed files as immutable artifacts
```

M2 does not prove:

```text
LangGraph orchestration
OpenRewrite transformation
Maven migration/build/test execution
per-command JDK selection
two-stage migration
proof gates
terminal migration reporting
plan approval
assistant or LLM behavior
repair or rollback
active-worker reattachment after API failure
```

A successful M2 diagnostic means:

> The local Control Tower execution, persistence, event, streaming, UI, and cancellation path works.

It must never mean:

> The selected Spring Boot application was migrated or verified.

---

## 2. Locked M2 Architecture

```text
Next.js
    rendering and interaction only

FastAPI adapter
    HTTP, validation, SSE, error translation, loopback policy

Control Tower application layer
    commands, queries, transitions, idempotency, projection rules

Control Tower SQLite database
    durable operational truth

Dispatcher
    claims durable QUEUED commands and prepares launch

Windows process controller
    owns the Job Object and process handles

Migration worker process
    loads immutable manifests and supervises one child operation

Diagnostic child process
    performs the fixed read-only M2 operation

Worker event spool
    private durable worker-to-Control-Tower delivery

Event ingestor
    validates private events and creates public domain events

Artifact filesystem
    configuration, manifests, logs, results, and spool

SSE endpoint
    streams committed public database events only
```

Ownership rule:

```text
Worker:
    never writes the Control Tower database

Browser:
    never reads the worker spool or filesystem directly

FastAPI:
    never owns lifecycle or authorization rules

Next.js:
    never owns lifecycle, proof, authorization, or command construction
```

---

## 3. Latest Technology Baseline

### 3.1 FastAPI

Preferred candidate when repository compatibility is confirmed:

```text
FastAPI 0.136.3
Pydantic 2.x compatible with the repository
repository-supported Python version
```

M2-00 must resolve and lock the exact compatible versions. `0.136.3` is a candidate, not an unconditional architecture requirement.

Use:

```python
from fastapi.sse import EventSourceResponse, ServerSentEvent
```

Rules:

```text
Use native FastAPI SSE when the verified FastAPI version supports it.
Use FastAPI lifespan for dispatcher, ingestor, notifier, and singleton-lock ownership.
Do not use deprecated startup/shutdown decorators.
Do not use FastAPI BackgroundTasks for durable command execution.
Do not start subprocesses directly from routes.
Do not run multiple API application processes in M2.
Do not use Uvicorn --workers > 1.
Do not use --reload in acceptance or production-like M2 execution.
```

When native SSE cannot be adopted without destabilizing existing dependencies, M2-00 must produce a written compatibility decision before selecting an alternative.

### 3.2 Next.js and Node.js

For a new frontend workspace, preferred candidates at planning time:

```text
Next.js 16.2.7
React 19.2.7
Node.js 24 LTS
```

Important correction:

```text
Next.js technically accepts Node.js >=20.9.0.
Node.js 20 is end-of-life in June 2026.
A new M2 frontend must use an actively supported LTS release, preferably Node 24 LTS.
```

For an existing frontend:

```text
Do not force a major-version migration inside M2.
Upgrade to the latest secure patch in the existing supported line.
Commit the lockfile.
Run audit, type-check, unit tests, and production build.
```

Next.js responsibilities:

```text
Server Components:
    initial non-cached projection and page shell

Client Components:
    EventSource connection
    event application
    bounded log windows
    start and cancellation interaction
```

### 3.3 SQLite

Official SQLite release at planning time:

```text
3.53.2
```

This does not mean Python embeds that version.

M2 rules:

```text
Keep M1 journal_mode=DELETE.
Do not enable WAL in M2.
Record sqlite3.sqlite_version and compile options in dependency diagnostics.
Use the actual Python runtime SQLite library.
Enable foreign_keys on every connection.
Configure busy_timeout on every connection.
Use short BEGIN IMMEDIATE write transactions.
Use the existing safe M1 connection/UoW ownership pattern.
Never hold a transaction while waiting, hashing, launching, reading pipes, or streaming SSE.
```

The recent WAL-reset corruption fixes reinforce the decision not to introduce WAL casually. M2 does not need WAL to prove its local single-job slice.

### 3.4 Windows process control

Required behavior:

```text
Create a Windows Job Object.
Apply JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
Do not allow breakaway.
Keep the Job Object handle owned by the API/controller process.
Make the Job Object handle non-inheritable.
Create the worker process suspended.
Assign the worker to the Job Object.
Persist process identity and launch evidence.
Resume only after persistence succeeds.
Allow child processes to remain in the same job.
Use TerminateJobObject for forced cancellation.
Verify process exit explicitly.
```

Do not persist a raw Windows HANDLE. Persist only:

```text
process_control_id
worker_pid
worker_process_creation_time or process-instance nonce
launch_attempt
diagnostic metadata
```

M2 must reuse an approved M0 implementation if one exists.

---

## 4. M2-00 — Mandatory Repository Alignment

Before code changes, inspect:

```text
current assigned Jira issue
root and nested AGENTS.md files
current DEMO2 branch state
git status and current baseline commit
Python packaging and lock files
supported Python version
current test configuration and test count
actual migration_factory/control_tower package
actual application ports, DTOs, services, UoW, repositories
actual 0001 foundation migration
actual run_events definition and constraints
actual artifact validation and hashing API
actual canonical JSON/checksum API
actual timestamp and ID helpers
existing subprocess/streaming/cancellation utilities
M0 Windows Job Object spike and tests
existing FastAPI dependency or scaffolding
existing web/Next.js workspace
current CLI/TUI execution boundaries
```

Required output:

```text
docs/M2_REPOSITORY_ALIGNMENT.md
```

Required contents:

```text
1. Exact source-of-truth files
2. Current package tree
3. Current dependency versions
4. Current post-M1 baseline
5. Existing components to reuse
6. Existing components to extend
7. New components that are genuinely required
8. Exact M2 migration strategy
9. Exact public contracts to freeze
10. Exact targeted and full verification commands
11. Conflicts and decisions
12. Updated file-by-file implementation map
```

M2-00 also creates short decision records for:

```text
ADR-M2-01 FastAPI/SSE version and adapter strategy
ADR-M2-02 Windows Job Object implementation
ADR-M2-03 event-type persistence strategy
ADR-M2-04 frontend workspace/version strategy
ADR-M2-05 API singleton mechanism
```

Exit criteria:

```text
No unresolved source conflict
M0 process-control evidence accepted
M1 schema inspected
dependency resolution tested
exact baseline recorded
reviewers approve repository-alignment document
```

---

## 5. Critical Invariants

### 5.1 One active job

Retain the M1 application and database invariant.

```text
Every nonterminal job occupies active_slot=1.
A second job returns ACTIVE_JOB_CONFLICT with the active job ID.
```

### 5.2 One active command per job

A database constraint must prevent more than one command in:

```text
QUEUED
STARTING
RUNNING
CANCELLING
```

for one job.

### 5.3 One Control Tower API/controller instance

Configuration alone is insufficient.

M2 must hold a process-lifetime singleton guard, preferably a Windows local named mutex keyed by the normalized database path.

```text
Second API/controller instance:
    fails startup or remains not-ready
    does not start dispatcher or ingestor
```

The mutex automatically releases when the owning process exits.

### 5.4 Persist before execution

No process executes before these facts are committed:

```text
job is QUEUED/STARTING
command row exists
worker_id and launch_attempt exist
immutable command manifest exists
worker process identity is recorded
worker is assigned to the Job Object
```

### 5.5 No arbitrary execution

The client cannot provide:

```text
executable
Python module
arguments
shell text
working directory
environment
timeout
output limits
spool path
log path
Job Object settings
```

The client may select only an approved backend operation/profile identifier.

### 5.6 Mutable files are not immutable artifacts

While active:

```text
stdout.log
stderr.log
event_spool.jsonl
```

are internal mutable files referenced by registered root ID and relative path.

They become immutable artifacts only after closure and validation.

### 5.7 Private and public events are separate

```text
worker_sequence:
    private delivery order from one worker

public_sequence:
    committed job-scoped sequence allocated by the Control Tower database
```

SSE uses only `public_sequence`.

### 5.8 Job version is not the event sequence

Increment `job.version` for state-changing mutation subjects only.

Do not increment it for:

```text
output byte growth
SSE keepalive
output-available notification
read-only queries
```

### 5.9 Diagnostic success is not migration proof

For the internal diagnostic profile:

```text
job may become COMPLETED
achieved_proof_level remains NULL
target_reached remains false
UI states "Foundation diagnostic completed"
UI never states "Migration completed"
```

---

## 6. Domain Contracts

### 6.1 Command states

```text
QUEUED
STARTING
RUNNING
CANCELLING
SUCCEEDED
FAILED
TIMED_OUT
CANCELLED
```

Allowed transitions:

| Current | Allowed next |
|---|---|
| `QUEUED` | `STARTING`, `CANCELLED`, `FAILED` |
| `STARTING` | `RUNNING`, `CANCELLING`, `CANCELLED`, `FAILED` |
| `RUNNING` | `CANCELLING`, `SUCCEEDED`, `FAILED`, `TIMED_OUT` |
| `CANCELLING` | `CANCELLED`, `FAILED` |
| Terminal | none |

`OUTPUT_LIMIT_EXCEEDED`, `LAUNCH_FAILED`, and similar outcomes are failure codes, not new command states.

### 6.2 Job states used by M2

```text
CREATED
QUEUED
STARTING
RUNNING
CANCELLING
RECOVERY_REQUIRED
COMPLETED
FAILED
CANCELLED
```

Transitions must use the existing M1 transition policy.

### 6.3 State authority

```text
Application/controller:
    QUEUED, STARTING, CANCELLING, RECOVERY_REQUIRED
    forced terminal cancellation/failure

Validated worker events:
    RUNNING
    cooperative terminal result

Process monitor:
    worker-exited-without-terminal-event failure
    forced timeout/cancellation result
```

### 6.4 Completion/cancellation race

```text
terminal completion committed first:
    cancellation returns the current terminal resource; no new state change

cancellation committed first:
    later success event is received but cannot complete the job
    receipt disposition = IGNORED_STALE
    state remains cancellation-controlled

worker killed:
    controller/process monitor creates the terminal result
```

Expected late events must not automatically force `RECOVERY_REQUIRED`.

---

## 7. Immutable Manifests

### 7.1 Run configuration

Materialize the exact M1 canonical run-configuration payload:

```text
control/run_configuration.json
```

Flow:

```text
load persisted M1 DTO
canonicalize using existing M1 checksum code
verify checksum equals database checksum
write temporary file
flush and fsync file
atomically publish final path
reopen and verify checksum
register immutable artifact
```

Do not add runtime-only fields to the canonical M1 payload.

### 7.2 Command manifest

Add:

```text
control/commands/{command_id}/command_manifest.json
```

The manifest contains:

```text
schema_version
job_id
command_id
worker_id
operation
run_configuration_artifact_id
run_configuration_checksum
working_directory root ID and relative path
stdout/stderr/result/spool relative paths
timeout
output limits
event schema version
created_at
manifest checksum
```

The worker command line contains only:

```text
approved Python executable
approved worker module
backend-resolved command-manifest path
```

The worker verifies the command-manifest checksum before doing work.

Benefits:

```text
smaller launch argument surface
auditable exact command contract
no browser-controlled executable details
stable reproduction evidence
```

---

## 8. Persistence Extension

The exact SQL depends on M2-00.

### 8.1 `command_executions`

Required semantics:

```text
command_id
job_id
operation
status
worker_id
launch_attempt
command_manifest_artifact_id
working_directory_root_id
working_directory_relative_path
timeout_seconds
deadline_at
max_stdout_bytes
max_stderr_bytes
worker_pid
worker_process_instance
process_control_id
stdout_relative_path
stderr_relative_path
result_relative_path
started_at
finished_at
exit_code
timed_out
cancelled
failure_code
stdout_artifact_id
stderr_artifact_id
result_artifact_id
spool_artifact_id
finalization_status
correlation_id
causation_id
created_at
updated_at
```

`process_control_id` is an application UUID, not a raw handle.

### 8.2 `worker_event_streams`

```text
job_id
command_id
worker_id
spool_root_id
spool_relative_path
last_ingested_sequence
last_ingested_byte_offset
status
terminal_event_sequence
ingestion_verified
created_at
updated_at
```

### 8.3 `worker_event_receipts`

```text
job_id
command_id
worker_id
worker_sequence
start_byte_offset
end_byte_offset
event_type
event_checksum
disposition
disposition_reason
public_sequence
created_at
```

Allowed dispositions:

```text
APPLIED
DUPLICATE
IGNORED_STALE
REJECTED_CONFLICT
```

Unique:

```text
(job_id, worker_id, worker_sequence)
```

### 8.4 `idempotency_records`

```text
operation
idempotency_key
request_checksum
resource_type
resource_id
original_status_code
created_at
```

Unique:

```text
(operation, idempotency_key)
```

M2 retains these records; automatic cleanup is deferred.

Rules:

```text
same key + same canonical request checksum:
    return original resource reference and current representation

same key + changed checksum:
    return IDEMPOTENCY_CONFLICT
```

### 8.5 Event-type persistence

Inspect the actual M1 schema.

Preferred outcome when M1 uses a closed `CHECK` list:

```text
event_types catalog table
run_events.event_type FK to event_types
one tested table rebuild in M2
future event additions insert catalog rows
```

Do not rebuild `run_events` when the current implementation is already safely extensible.

### 8.6 Required indexes

```text
one nonterminal command per job
queued command dispatch ordering
worker stream by status
worker receipt uniqueness
run event job/public sequence
idempotency operation/key
command job/created_at
```

### 8.7 Transaction boundaries

Never perform these inside a database transaction:

```text
filesystem write
fsync
hashing
process creation
process wait
pipe read
SSE wait
network call
```

Transactions cover only validation reads and durable state writes.

---

## 9. Safe Workspace Lifecycle

Logical layout:

```text
control/run_configuration.json
control/commands/{command_id}/command_manifest.json
control/event_spool.jsonl
commands/{command_id}/stdout.log
commands/{command_id}/stderr.log
commands/{command_id}/result.json
```

Workspace service requirements:

```text
resolve root through frozen runner profile
accept only validated relative paths
reject absolute, UNC, drive-qualified, traversal, and alternate-root input
inspect every existing parent component
reject unsafe symlink/junction/reparse behavior
create directories without unsafe alias following
create new files exclusively
refuse replacement of an already-prepared command workspace
never expose absolute paths
```

Crash cleanup:

```text
temporary manifest/config file:
    safe to delete or quarantine on next preparation attempt

existing final manifest with matching checksum:
    idempotent success

existing final manifest with different checksum:
    RECOVERY_REQUIRED / preparation conflict
```

---

## 10. Durable Start and Two-Phase Launch

### 10.1 Start command transaction

```text
validate Idempotency-Key
validate If-Match job version
require job CREATED
insert command QUEUED
transition job CREATED → QUEUED
append command_queued public event
append job_state_changed event as required by existing M1 convention
append audit
store idempotency record
commit
```

No process is launched in the request.

### 10.2 Dispatcher claim transaction

```text
select the oldest eligible QUEUED command
verify job is QUEUED
transition command QUEUED → STARTING
transition job QUEUED → STARTING
assign worker_id and launch_attempt
append event/audit
commit
```

### 10.3 Preparation

Outside the transaction:

```text
materialize run configuration
materialize command manifest
create Job Object
create worker suspended
assign worker to Job Object
```

### 10.4 Persist-before-resume transaction

Before the worker runs:

```text
verify command remains STARTING
record worker PID
record process-instance evidence
record process_control_id
record manifest artifact
record worker-prepared event/audit
commit
```

If this transaction fails:

```text
terminate suspended process
close handles
mark explicit launch failure or RECOVERY_REQUIRED
do not resume
```

### 10.5 Resume and monitor

```text
resume worker thread
register process handle with ProcessMonitor
wait asynchronously/in a dedicated thread for exit
```

If resume fails:

```text
terminate Job Object
command FAILED
job FAILED
audit exact OS error
```

---

## 11. API Singleton, Dispatcher, Ingestor, and Monitor

FastAPI lifespan owns:

```text
API singleton mutex
dispatcher service
worker-event ingestor
process monitor
committed-event notifier
```

### 11.1 Singleton

Recommended Windows mutex name:

```text
Local\AI-Migration-Control-Tower-<hash-of-normalized-db-path>
```

Second instance:

```text
does not start background services
fails startup or reports not-ready
```

### 11.2 Service execution

Synchronous SQLite and filesystem work must not block the event loop.

Use:

```text
dedicated service threads
or
async wrappers that offload blocking work
```

Every service uses its own database connection/unit of work according to the existing M1 safety pattern.

### 11.3 Process monitor

The monitor is mandatory because a worker can exit without a terminal spool event.

It records:

```text
exit code
exit time
whether a validated terminal event was ingested
whether cancellation/timeout was active
whether descendants are gone
```

Outcomes:

```text
terminal event ingested:
    verify and complete finalization

worker exits with no terminal event:
    controller-authored FAILED, CANCELLED, or TIMED_OUT result

process state uncertain:
    RECOVERY_REQUIRED
```

This is not M3 heartbeat/lease recovery.

---

## 12. Diagnostic Worker and Child Operation

Operation:

```text
FOUNDATION_DIAGNOSTIC
```

Production semantics:

```text
read-only
no source modification
no Maven
no OpenRewrite
no LangGraph
no proof advancement
bounded output
deterministic exit contract
```

The child is a real separate process.

Internal test-only modes may support:

```text
success
explicit failure
long-running cooperative cancellation
mixed stdout/stderr burst
descendant-process creation
output-limit breach
```

Test modes are selected by test fixtures or internal manifests, never by public browser input.

### 12.1 Environment

Build a fresh allowlist:

```text
required Windows system variables
approved PATH entries
TEMP/TMP
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
Control Tower correlation identifiers
```

Exclude:

```text
Azure credentials
API keys
Maven credentials
unrelated inherited secrets
arbitrary user environment
```

### 12.2 Time

```text
persist timestamps in UTC RFC3339
measure durations and deadlines with a monotonic clock
```

Controller owns the authoritative deadline.

---

## 13. Output Capture

Do not use `communicate()` for unbounded output.

Use two concurrent readers:

```text
stdout pipe → stdout.log
stderr pipe → stderr.log
```

Rules:

```text
read binary bytes
write append-only binary files
track byte offsets
flush on bounded intervals
emit throttled command_output_available events
never include log content in event payloads
enforce separate stdout and stderr limits
```

Output event payload:

```json
{
  "stream": "stdout",
  "start_offset": 0,
  "end_offset": 4096,
  "total_bytes": 4096
}
```

Throttle policy:

```text
at most one output notification per stream per configured interval
or when a configured byte threshold is crossed
always emit a final offset notification
```

Hard limit breach:

```text
failure_code = OUTPUT_LIMIT_EXCEEDED
request cooperative stop
force terminate after grace
controller finalizes failure
```

---

## 14. Worker Event Spool

### 14.1 Envelope

```json
{
  "event_schema_version": "1.0",
  "job_id": "uuid",
  "command_id": "uuid",
  "worker_id": "uuid",
  "worker_sequence": 1,
  "event_type": "command_started",
  "occurred_at": "RFC3339 UTC",
  "correlation_id": "uuid",
  "causation_id": "uuid",
  "payload": {},
  "event_checksum": "sha256"
}
```

`event_checksum` covers the canonical envelope excluding the checksum field itself.

It provides corruption and idempotency detection. It is not a cryptographic authentication boundary.

### 14.2 Writer

```text
canonical UTF-8 JSON
one record per newline
bounded record size
sequence begins at 1
monotonic sequence
flush and fsync before returning from append
single writer
```

### 14.3 Worker terminal order

```text
child exits
→ worker drains remaining pipe bytes
→ worker closes stdout/stderr writers
→ worker writes and closes result.json
→ worker appends and fsyncs terminal event
→ worker closes spool
→ worker exits
```

### 14.4 Reader

```text
read only the registered internal spool path
read from stored byte offset
require complete newline
do not ingest a partial final record
validate schema, checksum, IDs, and sequence
advance cursor only in the same transaction as receipt/event/projection
```

Duplicate behavior:

```text
existing receipt with same checksum:
    DUPLICATE
    advance cursor if required
    no second public event

same sequence with different checksum:
    REJECTED_CONFLICT
    RECOVERY_REQUIRED
```

---

## 15. Event Ingestion and Late-Event Rules

One transaction per private event:

```text
validate stream identity and expected sequence
insert receipt or recognize duplicate
validate event against current command/job state
apply allowed projection changes
allocate next public sequence if needed
insert public event
update stream cursor and terminal marker
append audit for state changes
commit
```

### 15.1 Canonical public events

Retain M1 events:

```text
job_created
job_state_changed
artifact_registered
```

Add only distinct M2 facts:

```text
command_queued
worker_prepared
worker_started
command_started
command_output_available
command_completed
command_timed_out
command_cancelled
worker_stopped
worker_event_rejected
```

Do not add `job_completed`, `job_failed`, or `artifact_created` when those duplicate existing M1 lifecycle events.

### 15.2 Late events

Examples:

```text
success after cancellation committed:
    receipt = IGNORED_STALE
    no transition to COMPLETED

duplicate terminal event:
    receipt = DUPLICATE
    no new public event

output event after terminal:
    receipt = IGNORED_STALE
    optionally record worker_event_rejected for diagnostics
```

Expected race outcomes do not automatically become recovery failures.

### 15.3 Recovery-required conditions

```text
sequence gap
checksum conflict
wrong worker identity
wrong command/job identity
manifest mismatch
impossible state contradiction
uncertain process launch
unsupported active state found at startup
```

---

## 16. Terminal Finalization and Forensic Artifacts

Terminal finalization starts only after:

```text
terminal result is authoritative
worker process exited
stdout/stderr writers closed
result file closed
spool closed or process death proves no further writes
```

Flow:

```text
validate paths and file identity
stream-hash stdout
stream-hash stderr
stream-hash result
stream-hash spool
prepare trusted metadata
commit artifact records and command links
append artifact events/audits
mark finalization complete
```

Spool policy:

```text
ingestion complete:
    register as WORKER_EVENT_SPOOL with ingestion_verified=true

ingestion incomplete/corrupt:
    still register the closed file as a FORENSIC_WORKER_EVENT_SPOOL
    ingestion_verified=false
    do not treat it as trusted execution evidence
```

This preserves recovery evidence.

Hashing occurs outside the database transaction. Metadata insertion and command linking are atomic and retry-safe.

---

## 17. Cancellation and Timeout

### 17.1 Cancellation request transaction

```text
validate If-Match
validate current state
transition job to CANCELLING
transition command to CANCELLING
append event/audit
commit
```

### 17.2 Cooperative path

M2 diagnostic child and worker use a backend-owned cancellation marker/protocol.

```text
controller publishes cancellation request
worker/child observes it
child exits cleanly
worker drains output
worker emits command_cancelled
```

This cooperative mechanism is specific to the M2 diagnostic. M3 generalizes command cancellation.

### 17.3 Forced path

After grace timeout:

```text
TerminateJobObject
wait for worker process handle
verify no active descendants
controller writes terminal command/job result
```

Do not wait for the killed worker to emit an event.

### 17.4 Timeout

Controller calculates deadline with a monotonic clock.

```text
deadline reached
→ cancellation path with timeout reason
→ forced termination after grace
→ command TIMED_OUT
→ job FAILED
```

A worker self-timeout may assist but is not authoritative.

---

## 18. Startup and Crash Semantics

Supported:

```text
browser reconnect
API restart after terminal job
API restart with untouched QUEUED command
```

Fail-closed:

```text
STARTING at startup
RUNNING at startup
CANCELLING at startup
uncertain launch result
```

Behavior:

```text
acquire singleton mutex
inspect nonterminal command/job state
QUEUED:
    eligible for dispatch

STARTING/RUNNING/CANCELLING:
    transition to RECOVERY_REQUIRED
    do not relaunch
    do not attach to PID
    preserve logs/spool for investigation
```

M2 does not promise active-process reattachment. M3 owns worker lease, heartbeat, orphan reconciliation, and supported resume.

---

## 19. HTTP API Contract

### 19.1 Configuration

```http
GET /v1/runner-profiles
GET /v1/pipelines
GET /v1/filesystem/roots
```

### 19.2 Jobs

```http
POST /v1/jobs
GET  /v1/jobs
GET  /v1/jobs/{job_id}
POST /v1/jobs/{job_id}/start
POST /v1/jobs/{job_id}/cancel
```

### 19.3 Commands and logs

```http
GET /v1/jobs/{job_id}/commands
GET /v1/jobs/{job_id}/commands/{command_id}
GET /v1/jobs/{job_id}/commands/{command_id}/logs/stdout
GET /v1/jobs/{job_id}/commands/{command_id}/logs/stderr
```

Log query:

```text
after_offset
max_bytes
```

Log response:

```json
{
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

### 19.4 Events

```http
GET /v1/jobs/{job_id}/events
GET /v1/jobs/{job_id}/events/stream
```

### 19.5 Artifacts

```http
GET /v1/jobs/{job_id}/artifacts
GET /v1/jobs/{job_id}/artifacts/{artifact_id}/metadata
```

### 19.6 Health

```http
GET /v1/health/live
GET /v1/health/ready
GET /v1/health/dependencies
```

Readiness fails when:

```text
singleton not owned
database unavailable
migration not current
required output root unavailable
dispatcher/ingestor/monitor fatal
Windows process-control capability unavailable
```

A domain job in `RECOVERY_REQUIRED` does not make the service unready.

---

## 20. Optimistic Concurrency and Idempotency

### 20.1 Job representation

`GET /v1/jobs/{job_id}` returns the mutation-relevant projection:

```text
job ID
job version
job state
active command state
configuration references
proof target/achieved summary
```

Recent events and event cursor are queried separately.

This allows a strong ETag based on the mutation projection:

```text
ETag: "job-<job_id>-v<version>"
```

### 20.2 Mutations

```text
start and cancel require If-Match
missing If-Match → 428 PRECONDITION_REQUIRED
stale If-Match → 412 PRECONDITION_FAILED
```

The adapter extracts `expected_version` and calls the M1/M2 application command.

### 20.3 Job creation and start idempotency

```text
Idempotency-Key required
canonical request checksum persisted
replay returns original resource reference
changed request under same key → 409 IDEMPOTENCY_CONFLICT
```

Cancellation is state-idempotent. An optional idempotency key may also be accepted.

---

## 21. Native SSE Contract

Use `EventSourceResponse` and `ServerSentEvent`.

Frame:

```text
id: <public_sequence>
event: <event_type>
data: <typed public event JSON>
retry: <milliseconds>
```

Rules:

```text
Last-Event-ID supported
after_sequence query supported
header/query conflict rejected
negative or malformed cursor rejected
cursor greater than current head rejected or handled by one documented rule
bounded replay batches
keepalive comments without event IDs
Cache-Control: no-cache
no raw worker event
no log text
no open database transaction while waiting
disconnect releases resources
database remains authoritative
```

Browser `EventSource` cannot provide the custom mutation header. The custom header requirement applies only to `fetch` mutation requests, not SSE.

Client startup:

```text
load recent public events and current head
open EventSource with after_sequence=<last applied>
browser reconnect then uses Last-Event-ID automatically
ignore any public sequence already applied
```

---

## 22. Local Security

Canonical local origins:

```text
Frontend: http://127.0.0.1:<configured-port>
API:      http://127.0.0.1:<configured-port>
```

Do not mix `localhost` and `127.0.0.1` in the supported runtime configuration.

Required controls:

```text
bind API to 127.0.0.1
bind frontend to 127.0.0.1
TrustedHost allowlist
exact CORS origin
no wildcard CORS
Origin validation on browser mutation endpoints
JSON-only mutation bodies
X-Control-Tower-Client header on browser mutation fetches
server-derived operating-system actor
no secrets in frontend bundle
no absolute paths in API payloads
no PIDs/process-control IDs in normal UI payloads
no arbitrary filesystem endpoint
no arbitrary command endpoint
```

Identity limitation:

```text
The actor is the operating-system account running the local API.
M2 does not authenticate individual local processes.
Remote binding remains prohibited.
```

---

## 23. Next.js Implementation

### 23.1 Pages

```text
/jobs/new
    registered profile
    registered pipeline
    source root + relative path
    output root + relative path
    diagnostic label
    create job

/jobs/[jobId]
    current job mutation projection
    active command
    recent public events
    SSE connection state
    bounded stdout/stderr windows
    start control
    cancellation confirmation
    terminal artifact metadata
```

### 23.2 Data behavior

Initial server fetch:

```text
cache: no-store
or equivalent dynamic rendering
```

Do not cache live job projections.

Client behavior:

```text
maintain last applied public sequence
apply events idempotently
refetch mutation projection after state-changing events
store latest ETag
on 412, refetch and show conflict message
load logs by byte offset
stop polling finalized logs after artifact link appears
```

### 23.3 Contract generation

Use:

```text
OpenAPI-generated TypeScript types
or
the current repository-approved shared-contract mechanism
```

Do not hand-maintain duplicate state enums.

### 23.4 UI language

Allowed:

```text
Foundation diagnostic completed
Command succeeded
Event replay connected
```

Forbidden:

```text
Migration completed
Build verified
Spring Boot upgraded
Proof achieved
```

---

## 24. Initial M2 Limits

These are proposed safe defaults for the small diagnostic slice. M2-00 may adjust them with evidence.

| Setting | Proposed default |
|---|---:|
| Worker event maximum | 64 KiB |
| Worker spool maximum | 32 MiB |
| Stdout maximum | 32 MiB |
| Stderr maximum | 32 MiB |
| Log-window maximum | 256 KiB |
| Public event replay batch | 500 events |
| Maximum SSE clients | 8 |
| Dispatcher fallback poll | 500 ms |
| Ingestor fallback poll | 250 ms |
| Output notification interval | 250 ms |
| Output notification byte threshold | 64 KiB |
| Diagnostic command timeout | 180 seconds |
| Graceful cancellation period | 5 seconds |
| SSE keepalive interval | 15 seconds |
| SSE reconnect delay | 1000 ms |

Rules:

```text
all limits backend-controlled
all limits tested at boundary and boundary+1
M4 defines different limits for real Maven/OpenRewrite logs
```

---

## 25. Standard Error Contract

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

M2 error codes:

```text
ACTIVE_JOB_CONFLICT
ACTIVE_COMMAND_CONFLICT
IDEMPOTENCY_CONFLICT
PRECONDITION_REQUIRED
JOB_VERSION_CONFLICT
INVALID_JOB_TRANSITION
COMMAND_NOT_FOUND
WORKER_PREPARATION_FAILED
WORKER_LAUNCH_FAILED
WORKER_EXITED_WITHOUT_TERMINAL_EVENT
WORKER_EVENT_INVALID
WORKER_EVENT_SEQUENCE_GAP
WORKER_EVENT_CONFLICT
OUTPUT_LIMIT_EXCEEDED
COMMAND_TIMED_OUT
CANCELLATION_FAILED
ARTIFACT_FINALIZATION_FAILED
SERVICE_INSTANCE_CONFLICT
SERVICE_NOT_READY
```

No OS paths, environment values, handles, or secret details appear in public errors.

---

## 26. Observability

Required structured fields:

```text
correlation_id
causation_id
job_id
command_id
worker_id
public_sequence
worker_sequence
launch_attempt
service_name
operation
duration_ms
failure_code
```

Required dependency diagnostics:

```text
FastAPI version
Python version
sqlite3 module version
SQLite runtime version
journal mode
foreign key status
busy timeout
frontend version/build ID
process-control capability
singleton ownership
dispatcher status
ingestor status
monitor status
```

Metrics/counters:

```text
queued command count
dispatch attempts
event-ingestion lag
duplicate receipts
rejected events
SSE client count
replay batch duration
stdout/stderr bytes
cancellation duration
artifact-finalization failures
SQLite busy events
```

No sensitive environment values are logged.

---

## 27. Jira Work Breakdown

### M2-00 — Align repository and freeze contracts

Deliver:

```text
repository alignment document
five ADRs
exact files/dependencies/tests
current baseline
approved M0 process-control evidence
```

### M2-01 — Add command, event, idempotency, and limit contracts

Deliver:

```text
CommandState
command transitions
private worker envelope
public event DTO
receipt dispositions
idempotency DTO
settings/limits
typed errors
```

### M2-02 — Add M2 persistence migration

Deliver:

```text
command_executions
worker_event_streams
worker_event_receipts
idempotency_records
event-type strategy
indexes
repositories/UoW extensions
migration tests
```

### M2-03 — Add secure workspace and immutable manifests

Deliver:

```text
safe command workspace
run_configuration.json
command_manifest.json
atomic publish
checksum verification
idempotent preparation
artifact registration
```

### M2-04 — Add durable private event spool

Deliver:

```text
canonical envelope checksum
JSONL writer
flush/fsync
reader
partial line handling
limits
cursor parsing
```

### M2-05 — Add diagnostic worker and child runtime

Deliver:

```text
worker entrypoint
manifest verification
fresh environment
fixed child operation
concurrent output capture
result contract
cooperative cancellation
```

### M2-06 — Add API singleton and durable dispatcher

Deliver:

```text
Windows named mutex
StartMigrationJob
durable QUEUED command
dispatcher claim
two-phase suspended launch
persist-before-resume
launch error handling
```

### M2-07 — Add event ingestion and projections

Deliver:

```text
receipt/cursor transaction
public event allocation
state projection
late-event dispositions
recovery-required handling
```

### M2-08 — Add process monitor, timeout, and cancellation

Deliver:

```text
Job Object ownership
process monitor
deadline handling
graceful stop
TerminateJobObject
controller-authored terminal outcomes
race tests
```

### M2-09 — Add terminal artifact finalization

Deliver:

```text
closed-file verification
stream hashing
log/result/spool registration
forensic spool handling
command artifact linking
retry-safe finalization
```

### M2-10 — Add FastAPI adapter and local security

Deliver:

```text
app factory/lifespan
configuration reads
jobs/start/cancel
commands/logs/events/artifacts
ETag/If-Match
idempotency
Host/Origin/CORS
actor provider
health
```

### M2-11 — Add native persisted SSE replay

Deliver:

```text
EventSourceResponse
ServerSentEvent
Last-Event-ID
after_sequence
bounded replay
keepalive
disconnect
notifier fallback
```

### M2-12 — Add minimal Next.js vertical slice

Deliver:

```text
new diagnostic job
current run
non-cached initial projection
SSE client
bounded log viewers
start/cancel
conflicts
terminal artifacts
accessibility
```

### M2-13 — Complete M2 acceptance and documentation

Deliver:

```text
all success/failure/timeout/cancel scenarios
crash-window suite
Windows process-tree suite
SSE reconnect suite
security/adversarial tests
dependency audits
full regression
evidence matrix
operational runbook
```

---

## 28. Test Strategy

### 28.1 Domain

```text
command values stable
every allowed transition
representative forbidden transitions
terminal states immutable
failure codes do not become states
late completion after cancellation
```

### 28.2 Database migration

```text
upgrade actual M1 database
preserve all M1 rows/checksums
preserve audit triggers
preserve event order
rollback injected failure
foreign_key_check
migration idempotency
migration checksum mutation rejection
one active command
idempotency uniqueness
```

### 28.3 Manifests/workspace

```text
canonical run config matches M1 checksum
command manifest checksum
manifest tampering rejected
atomic publish
crash leaves only safe temp file
matching existing manifest idempotent
different existing manifest conflicts
path traversal/UNC/drive/reparse rejection
absolute path not exposed
```

### 28.4 Singleton and dispatch

```text
second API instance rejected
no dispatcher before singleton ownership
queue commit before launch
HTTP request completion does not affect queued work
queued work dispatches after restart
two dispatchers cannot claim one command
process not resumed before PID/manifests persisted
persistence failure terminates suspended process
resume failure finalizes launch failure
```

### 28.5 Worker/process/output

```text
worker is separate process
child is separate process
Job Object handle not inherited
worker assigned before resume
child/grandchild remain in job
mixed stdout/stderr no deadlock
raw byte offsets correct
output notification throttled
stdout limit
stderr limit
worker exits before first event
legacy source unchanged
```

### 28.6 Spool/ingestion

```text
event fsync before append returns
complete newline required
partial final line retained
event checksum covers envelope
same checksum duplicate
conflicting duplicate
sequence gap
wrong worker/job/command
cursor rollback on DB failure
duplicate cursor catch-up
late success ignored after cancellation
public event and projection atomic
```

### 28.7 Process monitor/cancellation

```text
normal worker exit
exit without terminal event
graceful cancellation
forced cancellation
timeout
completion/cancel race
all descendants gone
nested parent-job scenario
controller finalizes after worker kill
```

### 28.8 Artifact finalization

```text
no artifact before file close
stable identity required
stream hashing
all final metadata links atomic
retry after DB failure
forensic spool registered when ingestion incomplete
absolute path hidden
```

### 28.9 FastAPI/security

```text
loopback-only runtime config
exact Host
exact Origin
CORS wildcard absent
mutation custom header required
SSE does not require custom header
server-derived actor
If-Match missing = 428
stale = 412
idempotency replay
changed idempotency body = 409
arbitrary execution fields rejected
public errors redacted
```

### 28.10 SSE

```text
replay from zero
replay from after_sequence
Last-Event-ID
header/query conflict
malformed cursor
future cursor behavior
ordered batches
lost notifier still replays
keepalive no ID
disconnect cleanup
max clients
only committed events
```

### 28.11 Next.js

```text
initial fetch is no-store
Server/Client boundary
generated contract use
EventSource after_sequence bootstrap
duplicate sequence ignored
state event triggers projection refresh
412 conflict refresh
byte-offset log pagination
keyboard controls
status not color-only
no false migration/proof wording
```

### 28.12 Crash windows

```text
crash before queue commit
crash after queue commit
crash after dispatcher claim
crash after suspended process creation
crash after Job Object assignment
crash after PID persistence before resume
crash while worker active
crash after terminal event before finalization
crash during artifact metadata commit
```

---

## 29. Acceptance Criteria

M2 is accepted only when:

1. M2-00 is approved against the actual `DEMO2` repository.
2. The exact post-M1 baseline is recorded and remains green.
3. The actual M1 database upgrades atomically with no lost data.
4. One active job and one active command are enforced in the database.
5. A second API/controller instance cannot start background services.
6. Job creation and start are durably idempotent.
7. Start commits a `QUEUED` command before launch.
8. No worker launch occurs inside an HTTP request or `BackgroundTasks`.
9. Run configuration and command manifest are immutable and checksum-verified.
10. The worker is created suspended and assigned before resume.
11. Worker process evidence is persisted before execution.
12. The Job Object handle is non-inheritable and held by the controller.
13. The child operation is backend-owned, read-only, and separate.
14. The client cannot choose executable details or absolute paths.
15. Stdout and stderr drain concurrently without unbounded memory buffering.
16. Output/event/spool limits are enforced.
17. Active logs and spool are not registered as immutable artifacts.
18. Closed logs/results/spool are hashed and registered.
19. Incomplete spool ingestion preserves a forensic artifact.
20. Private worker events are durable before acknowledgment.
21. Private event checksums cover the full canonical envelope.
22. Receipts are idempotent and separate from public events.
23. Receipt, projection, public sequence, event, cursor, and audit are atomic.
24. Expected late events are ignored safely, not misclassified as corruption.
25. Invalid identities, gaps, and conflicts fail closed.
26. Only committed public events are streamed.
27. SSE resumes from `Last-Event-ID` and explicit sequence.
28. Browser reconnect loses no persisted public event.
29. Typed cancellation stops the complete process tree.
30. Forced cancellation and timeout finalize without worker cooperation.
31. Worker exit without a terminal event is detected.
32. `QUEUED` work can dispatch after restart.
33. Unsupported active restart becomes `RECOVERY_REQUIRED`.
34. M2 does not claim active-worker reattachment.
35. Diagnostic completion leaves achieved migration proof unset.
36. Legacy source remains unchanged.
37. Local Host/Origin/CORS and actor controls pass.
38. Next.js contains no exclusive business, proof, authorization, or filesystem logic.
39. No M3+ migration, AI, governance, or repair behavior is introduced.
40. Backend, Windows, frontend, audit, security, and full regression checks pass.
41. Both reviewers approve the evidence matrix and operational runbook.

---

## 30. Definition of Done

```text
M2-00 repository alignment approved
five M2 ADRs approved
exact dependencies locked
Node uses supported LTS
FastAPI SSE strategy verified
single-instance mutex implemented
M1→M2 migration proven
run and command manifests proven
persist-before-resume launch proven
Job Object tests pass on Windows
private/public event separation proven
all crash-window tests pass
all replay tests pass
all local security tests pass
frontend build/type-check/tests pass
dependency audits pass or have approved exceptions
legacy engine behavior unchanged
full repository suite green
M2 evidence matrix complete
M2 local operations runbook complete
reviewers approve
```

---

## 31. Final Implementation Order

```text
M2-00 repository alignment and ADRs
M2-01 contracts
M2-02 persistence
M2-03 workspace and manifests
M2-04 private event spool
M2-05 worker and child runtime
M2-06 singleton and dispatcher
M2-07 ingestion and projections
M2-08 process monitor/cancellation/timeout
M2-09 terminal artifact finalization
M2-10 FastAPI and local security
M2-11 native SSE
M2-12 Next.js
M2-13 acceptance and documentation
```

Freeze before frontend implementation:

```text
job mutation projection
command projection
public event envelope
private worker envelope
error schema
ETag/If-Match rules
idempotency rules
SSE cursor rules
log-window response
```

---

# Final Engineering Rule

```text
Persist before launching.
Persist process identity before resuming.
Keep one controller instance.
Hold the Job Object handle in the controller.
Never inherit that handle into the worker.
Monitor process exit independently of worker events.
Stream only committed public events.
Treat mutable files as mutable until closure.
Preserve corrupt/incomplete spool as forensic evidence.
Fail closed on uncertainty.
Never call the M2 diagnostic a migration.
```
