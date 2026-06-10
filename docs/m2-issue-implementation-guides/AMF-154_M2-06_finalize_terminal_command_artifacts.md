# AMF-154 - [Control Tower] M2-06 - Finalize terminal command artifacts and forensic evidence

## 1. Issue source
- Jira key: AMF-154
- Jira title: [Control Tower] M2-06 - Finalize terminal command artifacts and forensic evidence
- Jira status: In Progress
- Exact acceptance criteria:
  - Diagnostic success and explicit-failure paths emit one authoritative terminal result.
  - Command/job terminal transitions follow approved state authority.
  - Finalization does not begin while worker or writers may modify files.
  - Paths revalidated through registered-root path service.
  - File identity, size, mtime, and resolved path stable during hashing; hashing streamed.
  - Stdout, stderr, result, and spool receive immutable metadata only after closure.
  - Artifact metadata insertion and command-artifact linking are atomic and retry-safe.
  - DB failure after hashing leaves no partial linkage; retry succeeds idempotently.
  - Complete spool ingestion produces verified worker-event-spool artifact.
  - Incomplete/conflicting/corrupt spool produces forensic spool artifact, not presented as verified execution evidence.
  - Public artifact APIs expose registered IDs and safe metadata only.
  - UI replaces active log polling with terminal artifact references and distinguishes verified from forensic evidence.
  - Diagnostic completion leaves achieved migration proof unset.
  - Terminal UI language says Foundation diagnostic completed or approved failure wording; no migration/build/proof claims.
  - Existing artifact-security and append-only audit tests remain green.
- Dependencies: AMF-153
- Non-goals:
  - Repair snapshots
  - Rollback artifacts
  - Maven/OpenRewrite evidence
  - Migration proof calculation
  - Report generation
- Comments or attached notes: none returned in Jira search

## 2. Current repository context
- Relevant files:
  - `migration_factory/control_tower/application/services.py`
  - `migration_factory/control_tower/application/dto.py`
  - `migration_factory/control_tower/application/ports.py`
  - `migration_factory/control_tower/application/queries.py`
  - `migration_factory/control_tower/adapters/fastapi/app.py`
  - `migration_factory/control_tower/infrastructure/workspace.py`
  - `migration_factory/control_tower/infrastructure/sqlite/artifact_paths.py`
  - `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
  - `migration_factory/control_tower/infrastructure/sqlite/migrations/0002_m2_queued_diagnostic.sql`
  - `tests/control_tower/test_artifact_registry.py`
  - `tests/control_tower/test_audit_records.py`
  - `tests/control_tower/test_m2_workspace.py`
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_m2_event_replay.py`
- Relevant services/classes:
  - `ArtifactRegistryService`
  - `CommandWorkspaceService`
  - `DiagnosticJobService`
  - `ControlTowerQueryService`
  - `SqliteArtifactRepository`
  - `SqliteCommandExecutionRepository`
- Relevant repositories/migrations:
  - `SqliteArtifactRepository`
  - `SqliteCommandExecutionRepository`
  - `SqliteRunEventRepository`
  - `0002_m2_queued_diagnostic.sql`
- Relevant FastAPI routes:
  - `POST /v1/jobs`
  - `GET /v1/jobs/{job_id}`
  - `POST /v1/jobs/{job_id}/start`
  - `POST /v1/jobs/{job_id}/launch`
  - `GET /v1/jobs/{job_id}/events`
  - `GET /v1/jobs/{job_id}/events/stream`
  - no terminal artifact routes exist yet
- Relevant tests:
  - `tests/control_tower/test_artifact_registry.py`
  - `tests/control_tower/test_audit_records.py`
  - `tests/control_tower/test_m2_workspace.py`
  - `tests/control_tower/test_m2_worker_launch.py`
  - `tests/control_tower/test_m2_event_replay.py`
  - `tests/control_tower/test_m1_acceptance.py`
- Graphify queries used:
  - `Which services handle command execution lifecycle?`
  - `Which services update command execution state?`
  - `Which tests cover diagnostic worker launch and command execution?`
  - `Which repositories persist command executions and artifacts?`
  - `Which FastAPI routes expose Control Tower command execution?`
  - `CommandWorkspaceService`
  - `WorkerLaunchService -> SqliteControlTowerUnitOfWork`
- What Graphify suggested:
  - `ArtifactRegistryService`, `CommandWorkspaceService`, `SqliteArtifactRepository`, and `SqliteCommandExecutionRepository` are the main persistence and linking surfaces.
  - The current graph already distinguishes mutable workspace files from immutable registered artifacts.
  - Finalization will likely need to bridge the workspace helper layer and the artifact registry layer, not replace either one.
- What source inspection confirmed:
  - `CommandWorkspaceService` currently registers `run_configuration` and `command_manifest` artifacts only.
  - `workspace.py` already has `stream_sha256`, `materialize_command_manifest`, and atomic publish helpers.
  - `artifact_paths.py` already validates registered roots and hashes trusted artifacts.
  - `SqliteArtifactRepository` already stores stable artifact metadata and deduplicates by job/root/path.
  - `command_executions` already carries `stdout_relative_path`, `stderr_relative_path`, `result_relative_path`, `process_control_id`, `stdout_artifact_id`, `stderr_artifact_id`, `result_artifact_id`, `spool_artifact_id`, and `finalization_status` in the M2 plan, but the current repository code does not yet expose a terminal-finalization service.

## 3. Relationship to previous M2 work
This slice builds on:

- AMF-151 secure workspace/manifests: terminal artifacts must be revalidated against the registered roots.
- AMF-152 controlled worker launch: finalization starts only after the worker and writers are no longer mutable.
- existing command execution state: terminal states must be authoritative before artifact closure.
- existing artifact registration: the finalization path should reuse the artifact registry instead of inventing a separate artifact store.
- existing Unit of Work / SQLite repositories: artifact linking and audit rows must remain atomic.

This is the slice where mutable execution evidence becomes immutable operational evidence.

## 4. Implementation strategy
1. Add a terminal-finalization service that takes the authoritative terminal outcome, job/command identity, and the closed file paths.
2. Revalidate every path through the registered-root path service before hashing or registering anything.
3. Stream-hash `stdout`, `stderr`, `result.json`, and `spool` after the worker has exited and the writers are closed.
4. Distinguish verified spool ingestion from forensic spool preservation.
5. Register terminal artifacts through `ArtifactRegistryService` or a small wrapper around it so artifact IDs stay consistent with the rest of M2.
6. Link terminal artifact IDs back to the command execution row atomically.
7. Append a public event and audit trail entry only after artifact metadata and command links are durable.
8. Make the whole finalization path idempotent so a crash after hashing but before commit can safely retry.

Likely files:

- `migration_factory/control_tower/application/services.py`
- `migration_factory/control_tower/application/commands.py`
- `migration_factory/control_tower/application/dto.py`
- `migration_factory/control_tower/application/ports.py`
- `migration_factory/control_tower/infrastructure/workspace.py`
- `migration_factory/control_tower/infrastructure/sqlite/artifact_paths.py`
- `migration_factory/control_tower/infrastructure/sqlite/repositories.py`
- `migration_factory/control_tower/adapters/fastapi/app.py`
- `tests/control_tower/test_artifact_registry.py`
- `tests/control_tower/test_audit_records.py`
- `tests/control_tower/test_m2_worker_launch.py`
- `tests/control_tower/test_m2_workspace.py`
- `tests/control_tower/test_m2_event_replay.py`

## 5. Data model / persistence plan
- Expected schema changes:
  - use the command execution row to store terminal artifact IDs and finalization status if the existing table can be widened safely
  - if not, add a narrow terminal-artifact link table keyed by `command_id`
  - keep log content out of SQLite rows
- Migration naming:
  - if schema changes are required, add a new migration after `0002_m2_queued_diagnostic.sql`
  - name it for the slice, such as `0004_m2_terminal_artifacts.sql`
- Immutability / retry / recovery rules:
  - only closed files become immutable artifacts
  - hashing is streamed and must not read the whole file into memory
  - retry after failure must not create duplicate artifacts or duplicate links
  - complete and forensic spool artifacts must be distinguishable at the DTO level and in the database
- Transaction boundaries:
  - hashing occurs outside the DB transaction
  - artifact inserts, command links, events, and audits commit together
  - partial link state must not survive a rollback

## 6. API / event contract plan
- Endpoint/event changes:
  - add terminal artifact listing and metadata access if not already present
  - expose verified vs forensic spool metadata separately
  - keep public artifact APIs restricted to IDs and safe metadata
- Public DTO fields:
  - `artifact_id`
  - `artifact_type`
  - `registered_root_id`
  - `relative_path`
  - `normalized_relative_path`
  - `content_type`
  - `size_bytes`
  - `checksum_algorithm`
  - `checksum`
  - `created_at`
  - `created_by`
  - `verification_status` or equivalent if the artifact is forensic
- Must not expose:
  - secrets
  - absolute unsafe paths
  - raw handles
  - unbounded output
  - arbitrary process details

## 7. Linux behavior
- Linux should run the artifact registry, audit, and workspace tests.
- Linux should prove file hashing is streamed and that no absolute path leaks into artifact metadata.
- Linux should verify forensic spool behavior with local temp files and registered roots.
- Linux should skip Windows-only process-control tests with explicit reasons.

## 8. Windows behavior
- Windows must keep the Job Object launch suite green while terminal finalization runs.
- Windows should verify the same terminal-artifact behavior against Windows path semantics.
- Windows-specific verification should ensure no raw handle or PID leaks appear in artifact payloads or UI-facing DTOs.

## 9. Security and reliability rules
- Unbounded output: finalization must only hash closed files, not active streams.
- Shell injection: not relevant to hashing, but keep any helper commands shell-free.
- Environment leakage: never persist env values in artifact payloads.
- Path leakage: never expose absolute workspace paths to the browser.
- Process orphaning: do not finalize while the process could still write.
- Partial persistence: artifacts and command links must commit atomically.
- Restart ambiguity: closed spool may become forensic evidence, but uncertain state must never masquerade as verified evidence.
- Cancellation race: if cancellation lands first, finalization must obey the resulting authoritative state.
- Timeout race: a timeout-generated terminal result must still follow the same artifact rules.
- Artifact integrity: use streamed SHA-256 and stable path validation.
- Duplicate finalization: idempotent retry must not create second artifact records.
- Replay/idempotency: terminal artifact references should be safe to reread after reconnect.

## 10. Test plan
- Focused unit tests:
  - streamed hashing of closed files
  - stable identity checks
  - forensic vs verified spool classification
  - idempotent retry after injected failure
- Service tests:
  - terminal finalization success path
  - failure path before commit
  - replay after retry
- Repository/migration tests:
  - new terminal-artifact columns or link table, if added
  - `PRAGMA foreign_key_check`
  - no duplicate artifact rows after retry
- FastAPI tests:
  - terminal artifact metadata endpoint(s)
  - no raw path or handle exposure
  - terminal UI payload uses artifact references instead of live log polling
- Linux tests:
  - workspace, artifact, and audit suites
  - safe path validation on POSIX
- Windows tests:
  - launch suite and terminal artifact path handling
  - no Windows-specific metadata leaks
- Negative tests:
  - DB failure after hashing
  - corrupt spool
  - incomplete spool
  - conflict on same normalized path with different checksum
- Restart/recovery tests:
  - terminal artifacts remain queryable after reopen
- Baseline comparison rule:
  - compare failures against clean `origin/DEMO2`
- Exact test commands:
  - `python -m pytest tests/control_tower/test_artifact_registry.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_audit_records.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_m2_workspace.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower/test_m2_worker_launch.py -q -rs --tb=short`
  - `python -m pytest tests/control_tower -q -rs --tb=short`

## 11. Code snippets / patterns
Finalizer shape:

```python
def finalize_terminal_artifacts(command_id: str, job_id: str) -> None:
    ...
```

Retry-safe linking:

```python
if existing is not None:
    return existing
insert_artifact()
update_command_links()
```

Forensic spool branch:

```python
spool_type = "WORKER_EVENT_SPOOL" if verified else "FORENSIC_WORKER_EVENT_SPOOL"
```

Test shape:

```python
def test_retry_after_hashing_failure_succeeds(tmp_path: Path) -> None:
    ...
```

## 12. Definition of Done
- [ ] Diagnostic success and explicit-failure paths produce one authoritative terminal result.
- [ ] Finalization waits for closure and worker exit.
- [ ] Hashing is streamed and path-validated.
- [ ] Verified and forensic spool artifacts are distinguishable.
- [ ] Artifact metadata and command links are atomic and retry-safe.
- [ ] No partial linkage survives rollback.
- [ ] Artifact API redacts unsafe details.
- [ ] Regression tests pass.
- [ ] `git diff --check` is clean.
- [ ] Required command output is recorded in the implementation report.

## 13. Pi/Hermes `/goal` prompt
```text
Start from latest DEMO2 on a fresh branch. Use Graphify first, then use $test-discipline. Read AMF-154 and map every acceptance criterion before editing. Implement only AMF-154. Finalize closed stdout/stderr/result/spool files into immutable artifacts with retry-safe linking and forensic spool handling. Do not change Jira status. Do not add unrelated runtime code. Run the artifact, audit, workspace, and worker-launch tests that prove the finalization path. Commit locally with issue-owned files only. Do not push unless asked. Final report must include branch, base commit, files changed, test commands with exact results, acceptance-criteria status, final git status, and commit hash.
```
