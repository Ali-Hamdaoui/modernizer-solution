# AMF-252 SQLite Database Lock Deep Audit and Fix

## Executive verdict

The reported HTTP 500 has a statically proven cause.  `GET /v1/v2/jobs/{job_id}/assistant/messages` used the default SQLite Unit of Work (UoW), whose entry path executes `BEGIN IMMEDIATE`.  That makes a read-only request contend for SQLite's sole writer reservation and explains the observed `sqlite3.OperationalError: database is locked` while a migration/repair writer is active.

This change routes that endpoint through the existing read-UoW adapter.  It therefore does not execute `BEGIN IMMEDIATE`; it uses the connection's autocommit read behavior for its single repository query.  Write UoWs remain `BEGIN IMMEDIATE`, preserving their serializing behavior.

This audit also found separate pre-existing long-lived write-UoW risks around model calls.  They are not changed here because they require a carefully tested read/compute/write refactor of repair/preflight behavior, rather than a mechanical transaction-mode replacement.  Consequently, the primary polling failure is fixed, but the recommendation for a broader controlled runtime involving model-triggering routes is **NO-GO until those scopes are separately addressed**.

## Exact runtime failure and lock acquisition trace

Reported runtime path:

```text
GET /v1/v2/jobs/0b9f9cef799045f3886cec2e568536dd/assistant/messages
  -> app.py:list_assistant_messages()
  -> unit_of_work_factory()
  -> SqliteControlTowerUnitOfWork.__enter__()
  -> connection.execute("BEGIN IMMEDIATE")
  -> SQLite attempts to acquire the single writer reservation
  -> active writer still owns it
  -> SQLITE_BUSY / sqlite3.OperationalError: database is locked
  -> HTTP 500
```

The exact owner connection cannot be identified statically: SQLite does not record connection identity in this traceback and the runtime capture contains no connection/process diagnostics.  The owner must be another connection to the same database with an open write transaction (or a process holding an incompatible SQLite lock).  The frontend GET is nevertheless proven to be a competing writer because of `BEGIN IMMEDIATE`.

## Current UoW transaction semantics

`SqliteControlTowerUnitOfWork` defaults to `transaction_mode="write"`.  On entry it issues `BEGIN IMMEDIATE`; on normal exit it commits only when `connection.in_transaction`, and on an exception it rolls back only when `connection.in_transaction`.  It closes the connection when constructed with `close_connection=True`.

The class already supports `transaction_mode="read"`.  In that mode `__enter__` intentionally does not issue an explicit `BEGIN`; with `sqlite3.connect(..., isolation_level=None)`, the repository `SELECT` executes in autocommit mode.  That is appropriate for `list_assistant_messages`, which performs one read query and does not require a multi-query repeatable snapshot.

The FastAPI `_read_unit_of_work()` adapter creates the usual UoW, switches supported UoWs to `transaction_mode="read"`, and then enters it.  It is already used by the high-frequency V2 polling endpoints for stages, approvals, events snapshot, pipeline, failure summary, gates, open gates, and current repair proposal.

## Read endpoint transaction semantics

Before this change, `list_assistant_messages()` directly used `with unit_of_work_factory() as uow`, selecting the write default and `BEGIN IMMEDIATE`.

After this change, it uses `with _read_unit_of_work(unit_of_work_factory) as uow`.  `V2AssistantService.get_messages()` only delegates to the assistant repository's read/list operation; it does not mutate state or invoke external I/O.  The route no longer asks SQLite for a write reservation.

## Write endpoint and worker transaction semantics

Normal command/mutation UoWs keep the default write mode and `BEGIN IMMEDIATE`.  This preserves existing serialization for event writes, idempotency records, gate decisions, proposal mutation, and other deterministic mutations.  SQLite migration application separately uses `BEGIN IMMEDIATE` in `infrastructure/sqlite/migrations/__init__.py`; that behavior is unchanged.

The V2 orchestrator opens short UoWs to load persisted manifests, record events, and create gates.  Its subprocess launch and `process.wait()` occur after the initial load scope exits; its event notifications also occur after the write scope exits.  No orchestrator write UoW was found spanning subprocess execution.

## WAL, timeout, and busy timeout

`connect_control_tower()` creates connections with `isolation_level=None` and `timeout=5.0`, then sets `PRAGMA busy_timeout = 5000`.  The UoW also sets `PRAGMA busy_timeout = 5000` and, for file-backed databases, attempts `PRAGMA journal_mode = WAL`.

Thus the intended runtime mode is WAL with a five-second busy timeout.  WAL permits a reader to run while a writer is active, but it still permits only one writer.  The fix does not change either timeout and does not use a longer timeout as a workaround.

## Long-lived transaction audit

Static inspection found these scopes:

* `V2OrchestratorRunner.start()` and `start_resume()` close their UoWs before starting a thread/subprocess. `_run_process()` calls `Popen` and `wait` outside a UoW. This is safe for the audited subprocess boundary.
* `GET /assistant/messages` performs only a repository read. It is now a read UoW.
* `POST /v1/migration-setups/preflight` currently calls `V2SetupService.run_preflight()` inside a write UoW. `run_preflight()` calls `_compute_readiness()`, which can call `model_client.smoke()`. This is a confirmed long-lived write transaction across network I/O.
* The legacy reviewer-critique route (`create_reviewer_critique`) calls the model inside a write UoW before persisting its critique. This is a confirmed long-lived write transaction across network I/O.
* The legacy revision-binding branch in the assistant action path calls the proposer model inside a write UoW before it writes the revised proposal. This is a confirmed long-lived write transaction across network I/O.
* The automatic repair-gate callback builds `V2LLMInvocationLedger` and invokes the repair diagnosis callback inside a write UoW. Its repair-chain path can invoke proposer/reviewer models; this is a confirmed long-lived write transaction across network I/O.

These remaining paths are not covered by the reported `assistant/messages` stack, but they can prolong writer ownership and therefore increase the chance of an unrelated writer receiving `SQLITE_BUSY`.  They need a dedicated, contract-preserving split into: short read/load transaction, external work with no UoW, and short serialized persist transaction.  This report deliberately does not claim they are fixed.

## Before and after transaction architecture

```text
Before
polling GET -> default UoW -> BEGIN IMMEDIATE -> writer contention -> 500

After
polling GET -> read UoW -> single autocommit SELECT -> WAL reader coexistence

Writes (unchanged)
mutation/worker event -> write UoW -> BEGIN IMMEDIATE -> commit/rollback -> close
```

## Exact files and symbols changed

* `migration_factory/control_tower/adapters/fastapi/app.py`
  * `list_assistant_messages()` now uses `_read_unit_of_work(unit_of_work_factory)`.
* `AMF252_SQLITE_DATABASE_LOCK_DEEP_AUDIT_AND_FIX.md`
  * This forensic audit and runtime-test recommendation.

No model transport, prompts, schemas, compiler extraction, Windows path handling, sandboxing, repair-chain semantics, frontend, timeout, or SQLite engine replacement was changed.

## Why this fix is safe

The changed route is read-only and its repository/service path has no writes.  The route is placed on the same existing read-UoW mechanism already used by the other listed high-frequency V2 polling routes.  Write UoWs retain `BEGIN IMMEDIATE`, so this does not weaken write-side serialization or idempotency guarantees.

Timeout-only remediation was rejected because a larger timeout would merely make a read request wait longer for an unnecessary writer reservation.  It would not prevent that request from competing with the active writer.

## Static checks performed

* Targeted source inspection of UoW construction, connection creation, WAL and timeout configuration, FastAPI polling routes, assistant repository path, worker lifecycle, and external-I/O call sites.
* `rg "BEGIN IMMEDIATE" migration_factory`.
* `rg "unit_of_work_factory\(\)" migration_factory/control_tower`.
* Python AST scan for direct external calls inside UoW scopes, followed by manual inspection of the identified model/subprocess paths.
* `py -m py_compile` for each touched Python file.
* `git diff --check`, `git diff --stat`, and `git status --short`.

No migration, model call, migration job, repair application, or Azure call was executed.

## Remaining concurrency risks

1. The four model-call write scopes identified above can hold SQLite's writer reservation for network latency and must be refactored before claiming global elimination of lock failures.
2. A complete audit of all older V1 GET/application query services remains advisable: many still construct the default write UoW for reads. They are outside the reported V2 polling failure but are architecturally susceptible to the same anti-pattern.
3. The runtime lock owner is not attributable from the supplied traceback. A controlled test should collect request/job correlation IDs, process IDs, SQLite transaction timing, and database path before attempting owner attribution.

## GO / NO-GO for one controlled runtime test

**NO-GO for a broad migration/repair test that triggers model calls**, because the audit proved additional long-lived write scopes across model I/O.  A narrow controlled test limited to an existing active writer plus concurrent polling of `/assistant/messages` is appropriate to verify this specific route-level correction, provided it does not trigger the identified model-backed paths.

Area	Before	After
Read-only GET UoW	Default write UoW	Read UoW / autocommit SELECT
Write UoW	BEGIN IMMEDIATE	BEGIN IMMEDIATE unchanged
BEGIN IMMEDIATE on reads	Yes for /assistant/messages	No for /assistant/messages
BEGIN IMMEDIATE on writes	Yes	Yes
WAL	UoW enables WAL for file-backed DB	Unchanged
busy_timeout	5000 ms	5000 ms unchanged
Long-lived DB transaction across model call	Present in audited preflight/repair paths	Still present; separate refactor required
Long-lived DB transaction across subprocess	Not found in audited V2 orchestrator path	Not found; unchanged
