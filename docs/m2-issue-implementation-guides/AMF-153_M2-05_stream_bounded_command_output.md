# AMF-153 - [Control Tower] M2-05 - Stream bounded command output to the browser

## 1. Issue source
- Jira key: AMF-153
- Jira title: [Control Tower] M2-05 - Stream bounded command output to the browser
- Jira status: In Progress
- Exact acceptance criteria:
  - Stdout/stderr drained concurrently as bytes without unbounded buffering.
  - Separate backend-controlled stdout/stderr limits enforced.
  - Output notifications throttled by configured time and byte thresholds; final offset notification emitted per stream.
  - Output events contain stream name and byte offsets, not log content.
  - Private event envelope includes job, command, worker, sequence, type, time, correlation, causation, payload, and full-envelope checksum.
  - Checksum covers canonical envelope excluding checksum; worker sequence starts at 1 and is monotonic.
  - JSONL records bounded and newline-terminated; append flushes/fsyncs before return; reader ignores incomplete final record.
  - Ingestor validates job, command, worker, schema, checksum, and exact sequence.
  - Duplicate matching event idempotent; sequence/checksum conflict or gap fails closed.
  - Receipt stores byte offsets/disposition.
  - Receipt, projection changes, public sequence, public event, cursor, and audit commit atomically; cursor does not advance on rollback.
  - Private events never returned by public endpoints.
  - Log API reads known command stream only; windows use byte offsets and max size.
  - UTF-8 boundary decoding safe and reports replacement use.
  - UI displays separate stdout/stderr viewers and resumes logs/events from last offsets/sequences.
  - Active log/spool files have no immutable artifact records.
  - Output-limit breach produces OUTPUT_LIMIT_EXCEEDED and approved termination path.
  - No log text in SSE; high-volume mixed output cannot deadlock; legacy source unchanged.
- Dependencies: AMF-152
- Non-goals:
  - Terminal log hashing
  - Terminal artifact links
  - Graceful/forced cancellation UI
  - Restart recovery
- Comments or attached notes: none returned in Jira search

## 2. Current repository context
- Relevant files:
  - `migration_factory/control_tower/application/services.py`
  - `migration_factory/control_tower/application/dto.py`
  - `migration_factory/control_tower/application/ports.py`
  - `migration_factory/control_tower/application/queries.py`
  - `migration_factory/control_tower/adapters/fastapi/app.py`
  - `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql`
  - `migration_factory/control_tower/infrastructure/worker_launcher.py`
  - `tests/control_tower/test_m2_event_replay.py`
  - `tests/control_tower/test_fastapi_diagnostic_queue.py`
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_sqlite_migrations.py`
- Relevant services/classes:
  - `DiagnosticJobService`
  - `CommandWorkspaceService`
  - `WorkerLaunchService`
  - `ControlTowerQueryService`
  - `SqliteCommandExecutionRepository`
  - `SqliteRunEventRepository`
  - `WindowsWorkerLauncher`
- Relevant repositories/migrations:
  - `SqliteCommandExecutionRepository`
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
  - No stdout/stderr window routes exist yet
- Relevant tests:
  - `tests/control_tower/test_m2_event_replay.py`
  - `tests/control_tower/test_fastapi_diagnostic_queue.py`
  - `tests/control_tower/test_m2_diagnostic_queue.py`
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_sqlite_migrations.py`
- Graphify queries used:
  - `Which services handle command execution lifecycle?`
  - `Which services update command execution state?`
  - `Which tests cover diagnostic worker launch and command execution?`
  - `Which repositories persist command executions and artifacts?`
  - `Which FastAPI routes expose Control Tower command execution?`
  - `WorkerLaunchService -> SqliteControlTowerUnitOfWork`
  - `WorkerLaunchService`
- What Graphify suggested:
  - The hot path lives in `DiagnosticJobService`, `CommandWorkspaceService`, `ControlTowerQueryService`, `SqliteCommandExecutionRepository`, `SqliteRunEventRepository`, and the FastAPI adapter.
  - The graph did not surface a `WorkerLaunchService` node cleanly, so source inspection was needed to confirm the actual class boundary.
  - The current query/replay surface is already event-centric; output streaming will need a new read path rather than a mutation of the existing public event replay.
- What source inspection confirmed:
  - `CommandManifest` already carries `stdout_relative_path`, `stderr_relative_path`, `timeout_seconds`, `max_stdout_bytes`, and `max_stderr_bytes`.
  - `SqliteCommandExecutionRepository` currently persists status, manifest link, working directory, worker identity, launch attempt, and process identity only.
  - `ControlTowerQueryService` replays committed public events but has no command-output API.
  - `app.py` currently exposes jobs, start, launch, and event replay only.
  - `worker_launcher.py` launches the worker on Windows, but does not stream stdout/stderr or expose bounded log windows.

## 3. Relationship to previous M2 work
This slice builds on:

- AMF-151 secure workspace/manifests: the manifest already names the stdout/stderr files and byte limits.
- AMF-152 controlled worker launch: the worker must be launched before there is anything to stream.
- existing command execution state: `QUEUED`, `STARTING`, `RUNNING`, `CANCELLING`, and terminal states already exist in `CommandState`.
- existing artifact registration: active logs/spool stay mutable and must not be registered as immutable artifacts.
- existing Unit of Work / SQLite repositories: output offsets and event receipts, if needed, must fit the current transactional model.

This issue is the first place where the worker's live bytes become user-visible. The browser may see log content in the bounded log-window endpoints, but SSE must remain offset-only.

## 4. Implementation strategy
1. Add a bounded-output read model in the application layer, likely a new DTO for `stdout` and `stderr` windows with `requested_offset`, `start_offset`, `next_offset`, `data`, `encoding`, `replacement_characters_used`, `truncated`, `terminal`, and `artifact_id`.
2. Extend the application port surface if the controller needs durable access to output offsets or terminal flags beyond what is already stored in `command_executions`.
3. Add a controller-side output reader that tails `stdout.log` and `stderr.log` as bytes, not text, and never uses one unbounded `communicate()` call.
4. Emit public `command_output_available` events with offsets only, so the browser can re-read bounded windows without receiving raw log text in SSE.
5. Add FastAPI routes for bounded stdout/stderr window reads under the current job/command route family.
6. Keep the worker-launch code focused on launch; put stream reading and truncation logic in a separate service/helper so it can be unit tested without Windows process creation.
7. Add tests for output ordering, truncation, UTF-8 split boundaries, byte-offset resumption, and no secret/path leakage.

Likely files:

- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/application/queries.py`
- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `migration_factory/control_tower/infrastructure/worker_launcher.py`
- `tests/control_tower/test_m2_event_replay.py`
- `tests/control_tower/test_fastapi_diagnostic_queue.py`
- `tests/control_tower/test_m2_worker_launch.py`
- `tests/control_tower/test_m2_diagnostic_queue.py`

## 5. Data model / persistence plan
- Expected schema changes:
  - likely a durable place for stdout/stderr byte cursors and terminal output state if the current `command_executions` row cannot reconstruct them
  - no raw log content in SQLite
- Migration naming:
  - if schema changes are required, put them in a new migration after `0002_m2_queued_diagnostic.sql`
  - name the migration for this slice, such as `0003_m2_command_output.sql`
- Immutability / retry / recovery rules:
  - log files remain mutable while the command is active
  - output events are append-only and offset-based
  - retry must not duplicate offsets or publish the same range twice
  - incomplete UTF-8 tails must not corrupt the next read
- Transaction boundaries:
  - file append and flush happen outside the database transaction
  - offset publication, receipt/projection updates, and audit rows stay atomic
  - rollback must not advance the browser cursor

## 6. API / event contract plan
- Endpoint/event changes:
  - add bounded stdout/stderr log-window endpoints
  - add public `command_output_available` events with byte offsets only
  - keep SSE committed-public-event only
- Public DTO fields:
  - `stream`
  - `requested_offset`
  - `start_offset`
  - `next_offset`
  - `data`
  - `encoding`
  - `replacement_characters_used`
  - `truncated`
  - `terminal`
  - `artifact_id`
- Must not expose:
  - secrets
  - absolute unsafe paths
  - raw handles
  - unbounded output
  - arbitrary process details

## 7. Linux behavior
- Linux should run portable bounded-output tests and API tests.
- Linux should confirm byte-offset replay, truncation, and UTF-8 split behavior.
- Linux should skip Windows Job Object integration tests with explicit reasons.
- Linux should fail closed on any case that would require unsupported process-control behavior.

## 8. Windows behavior
- Windows must run the same bounded-output tests plus the existing Job Object launch suite.
- Windows-specific verification should confirm the new output code does not break suspended launch/resume.
- No symlink privilege handling is specific to this slice unless a new temp-path helper introduces it.

## 9. Security and reliability rules
- Unbounded output: never buffer full stdout/stderr in memory.
- Shell injection: do not switch to `shell=True`.
- Environment leakage: do not echo inherited env or secrets in output events.
- Path leakage: do not expose absolute workspace paths in SSE or public DTOs.
- Process orphaning: bounded output must not depend on the child staying cooperative.
- Partial persistence: log append and cursor updates must tolerate crash/retry without duplication.
- Restart ambiguity: do not infer terminal state from a stale buffer alone.
- Cancellation race: output publication must not override the authoritative terminal path.
- Timeout race: limit breach must still publish the final safe offset before termination.
- Artifact integrity: active logs are not immutable artifacts.
- Duplicate finalization: avoid double-registering the same terminal log window.
- Replay/idempotency: offset-based reads must be safe to call repeatedly.

## 10. Test plan
- Focused unit tests:
  - byte-offset window slicing
  - UTF-8 boundary handling
  - truncation flag behavior
  - final offset emission
- Service tests:
  - concurrent stdout/stderr drain ordering
  - limit breach behavior
  - no memory blowup on large output
- Repository/migration tests:
  - only if schema changes are added
  - `PRAGMA foreign_key_check`
  - migration upgrade/rollback if needed
- FastAPI tests:
  - stdout/stderr window endpoints
  - SSE payloads remain offset-only
  - no absolute path leakage
- Linux tests:
  - portable output-window and SSE tests
  - skip Windows-only Job Object integration
- Windows tests:
  - launch suite stays green
  - no regression in process identity persistence
- Negative tests:
  - output limit breach
  - malformed cursor
  - truncated UTF-8 tail
  - secret-like content does not leak to SSE
- Restart/recovery tests:
  - not central here, but output windows should replay from stored offsets after reconnect
- Baseline comparison rule:
  - compare failures against a clean `origin/DEMO2` before calling them branch-caused
- Exact test commands:
  - `python -m pytest tests/control_tower/test_m2_event_replay.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_fastapi_diagnostic_queue.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_m2_diagnostic_queue.py tests/control_tower/test_m2_workspace.py tests/control_tower/test_sqlite_migrations.py -q -rs --tb=short`
  - `py -m pytest tests/control_tower/test_m2_worker_launch.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower -q -rs --tb=short`

## 11. Code snippets / patterns
Illustrative service shape:

```python
def read_command_output(job_id: str, command_id: str, stream: str, after_offset: int, max_bytes: int) -> CommandOutputWindowDto:
    ...
```

Bounded read loop:

```python
total = 0
while total < max_bytes:
    chunk = stream_handle.read(min(8192, max_bytes - total))
    if not chunk:
        break
    total += len(chunk)
```

Test shape:

```python
def test_large_stdout_is_truncated(tmp_path: Path) -> None:
    ...
```

Platform skip marker:

```python
@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-only Job Object integration; skipped on non-Windows.")
```

## 12. Definition of Done
- [ ] Stdout/stderr drained concurrently as bytes.
- [ ] Separate output limits enforced.
- [ ] Output notifications are throttled and final offsets are emitted.
- [ ] SSE contains offsets, not log text.
- [ ] Large-output tests pass without memory blowup.
- [ ] UTF-8 boundary tests pass.
- [ ] No secret/path leakage in public payloads.
- [ ] Focused and regression tests pass.
- [ ] `git diff --check` is clean.
- [ ] Required command output is captured in the implementation report.

## 13. Pi/Hermes `/goal` prompt
```text
Start from latest DEMO2 on a fresh branch. Use Graphify first, then use $test-discipline. Read AMF-153 and map every acceptance criterion before editing. Implement only AMF-153. Keep stdout/stderr streaming bounded, offset-based, and safe for reconnect. Do not change Jira status. Do not add unrelated runtime code. Run the Linux tests that cover event replay, diagnostic queue, workspace, and SQLite behavior, and run the Windows worker-launch tests if the platform applies. Commit locally with issue-owned files only. Do not push unless asked. Final report must include branch, base commit, files changed, test commands with exact results, acceptance-criteria status, final git status, and commit hash.
```
