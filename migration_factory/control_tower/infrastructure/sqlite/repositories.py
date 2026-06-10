"""SQLite repository implementations for Control Tower."""

from __future__ import annotations

import json
import sqlite3
from typing import Sequence

from migration_factory.control_tower.application.dto import (
    ArtifactDto,
    AuditRecordDto,
    CommandExecutionDto,
    IdempotencyRecordDto,
    MigrationJobDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
    RunEventDto,
)
from migration_factory.control_tower.domain.entities import (
    ArtifactRecord,
    AuditRecord,
    CommandExecutionRecord,
    IdempotencyRecord,
    MigrationJobRecord,
    PipelineDefinitionRecord,
    RunConfigurationRecord,
    RunEventRecord,
    RunnerProfileRecord,
    StageRunRecord,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.domain.commands import CommandState
from migration_factory.control_tower.domain.errors import NotFoundError, StorageIntegrityError, WorkspaceConflictError
from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.schemas.pipeline_definition import PipelineDefinition
from migration_factory.control_tower.schemas.runner_profile import RunnerProfile


class SqliteRunnerProfileRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_exact(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileRecord | None:
        row = self._select_one(runner_profile_id, runner_profile_version)
        if row is None:
            return None
        payload = RunnerProfile.model_validate_json(str(row["payload_json"]))
        return RunnerProfileRecord(
            runner_profile_id=str(row["runner_profile_id"]),
            runner_profile_version=str(row["runner_profile_version"]),
            display_name=str(row["display_name"]),
            schema_version=str(row["schema_version"]),
            payload_json=str(row["payload_json"]),
            payload_checksum=str(row["payload_checksum"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
            payload=payload,
        )

    def get(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileDto | None:
        row = self._select_one(runner_profile_id, runner_profile_version)
        return _runner_profile_from_row(row) if row is not None else None

    def list(self) -> tuple[RunnerProfileDto, ...]:
        rows = self._connection.execute(
            """
            SELECT runner_profile_id, runner_profile_version, display_name, schema_version,
                   payload_json, payload_checksum, created_at, created_by
            FROM runner_profiles
            ORDER BY runner_profile_id, runner_profile_version
            """
        ).fetchall()
        return tuple(_runner_profile_from_row(row) for row in rows)

    def insert(self, profile: RunnerProfileDto) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO runner_profiles (
                    runner_profile_id, runner_profile_version, display_name, schema_version,
                    payload_json, payload_checksum, created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.runner_profile_id,
                    profile.runner_profile_version,
                    profile.display_name,
                    profile.schema_version,
                    profile.payload_json,
                    profile.payload_checksum,
                    profile.created_at,
                    profile.created_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def find_checksum(self, runner_profile_id: str, runner_profile_version: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT payload_checksum
            FROM runner_profiles
            WHERE runner_profile_id = ? AND runner_profile_version = ?
            """,
            (runner_profile_id, runner_profile_version),
        ).fetchone()
        return str(row["payload_checksum"]) if row is not None else None

    def _select_one(self, runner_profile_id: str, runner_profile_version: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT runner_profile_id, runner_profile_version, display_name, schema_version,
                   payload_json, payload_checksum, created_at, created_by
            FROM runner_profiles
            WHERE runner_profile_id = ? AND runner_profile_version = ?
            """,
            (runner_profile_id, runner_profile_version),
        ).fetchone()


class SqlitePipelineDefinitionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_exact(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionRecord | None:
        row = self._select_one(pipeline_id, pipeline_version)
        if row is None:
            return None
        payload = PipelineDefinition.model_validate_json(str(row["payload_json"]))
        return PipelineDefinitionRecord(
            pipeline_id=str(row["pipeline_id"]),
            pipeline_version=str(row["pipeline_version"]),
            display_name=str(row["display_name"]),
            schema_version=str(row["schema_version"]),
            graph_version=str(row["graph_version"]),
            graph_state_schema_version=str(row["graph_state_schema_version"]),
            payload_json=str(row["payload_json"]),
            payload_checksum=str(row["payload_checksum"]),
            created_at=str(row["created_at"]),
            created_by=str(row["created_by"]),
            payload=payload,
        )

    def get(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionDto | None:
        row = self._select_one(pipeline_id, pipeline_version)
        return _pipeline_definition_from_row(row) if row is not None else None

    def list(self) -> tuple[PipelineDefinitionDto, ...]:
        rows = self._connection.execute(
            """
            SELECT pipeline_id, pipeline_version, display_name, schema_version,
                   graph_version, graph_state_schema_version, payload_json,
                   payload_checksum, created_at, created_by
            FROM pipeline_definitions
            ORDER BY pipeline_id, pipeline_version
            """
        ).fetchall()
        return tuple(_pipeline_definition_from_row(row) for row in rows)

    def insert(self, pipeline: PipelineDefinitionDto) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO pipeline_definitions (
                    pipeline_id, pipeline_version, display_name, schema_version,
                    graph_version, graph_state_schema_version, payload_json, payload_checksum,
                    created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pipeline.pipeline_id,
                    pipeline.pipeline_version,
                    pipeline.display_name,
                    pipeline.schema_version,
                    pipeline.graph_version,
                    pipeline.graph_state_schema_version,
                    pipeline.payload_json,
                    pipeline.payload_checksum,
                    pipeline.created_at,
                    pipeline.created_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def find_checksum(self, pipeline_id: str, pipeline_version: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT payload_checksum
            FROM pipeline_definitions
            WHERE pipeline_id = ? AND pipeline_version = ?
            """,
            (pipeline_id, pipeline_version),
        ).fetchone()
        return str(row["payload_checksum"]) if row is not None else None

    def _select_one(self, pipeline_id: str, pipeline_version: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT pipeline_id, pipeline_version, display_name, schema_version,
                   graph_version, graph_state_schema_version, payload_json,
                   payload_checksum, created_at, created_by
            FROM pipeline_definitions
            WHERE pipeline_id = ? AND pipeline_version = ?
            """,
            (pipeline_id, pipeline_version),
        ).fetchone()


class SqliteMigrationJobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_created(self, job: MigrationJobRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO migration_jobs (
                    job_id, version, status, active_slot, last_event_sequence,
                    runner_profile_id, runner_profile_version, pipeline_id, pipeline_version,
                    target_proof_level, achieved_proof_level, legacy_source_ref, output_root_ref,
                    created_at, updated_at, started_at, finished_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.version,
                    job.status.value,
                    job.active_slot,
                    job.last_event_sequence,
                    job.runner_profile_id,
                    job.runner_profile_version,
                    job.pipeline_id,
                    job.pipeline_version,
                    job.target_proof_level.value,
                    job.achieved_proof_level.value if job.achieved_proof_level else None,
                    job.legacy_source_ref,
                    job.output_root_ref,
                    job.created_at,
                    job.updated_at,
                    job.started_at,
                    job.finished_at,
                    job.created_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def get_active_job(self) -> MigrationJobRecord | None:
        row = self._connection.execute(
            """
            SELECT job_id, version, status, active_slot, last_event_sequence,
                   runner_profile_id, runner_profile_version, pipeline_id, pipeline_version,
                   target_proof_level, achieved_proof_level, legacy_source_ref, output_root_ref,
                   created_at, updated_at, started_at, finished_at, created_by
            FROM migration_jobs
            WHERE active_slot = 1
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
        return _migration_job_record_from_row(row) if row is not None else None

    def get(self, job_id: str) -> MigrationJobDto | None:
        row = self._connection.execute(
            """
            SELECT job_id, version, status, active_slot, last_event_sequence,
                   created_at, updated_at, started_at, finished_at
            FROM migration_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        return _migration_job_dto_from_row(row) if row is not None else None

    def transition_state(
        self,
        job_id: str,
        expected_version: int,
        target_state: JobState,
        active_slot: int | None,
        updated_at: str,
    ) -> bool:
        cursor = self._connection.execute(
            """
            UPDATE migration_jobs
            SET status = ?,
                version = version + 1,
                active_slot = ?,
                updated_at = ?
            WHERE job_id = ?
              AND version = ?
            """,
            (
                target_state.value,
                active_slot,
                updated_at,
                job_id,
                expected_version,
            ),
        )
        return cursor.rowcount == 1

    def list(self) -> tuple[MigrationJobDto, ...]:
        rows = self._connection.execute(
            """
            SELECT job_id, version, status, active_slot, last_event_sequence,
                   created_at, updated_at, started_at, finished_at
            FROM migration_jobs
            ORDER BY created_at, job_id
            """
        ).fetchall()
        return tuple(_migration_job_dto_from_row(row) for row in rows)

    def increment_event_sequence(self, job_id: str) -> int:
        cursor = self._connection.execute(
            """
            UPDATE migration_jobs
            SET last_event_sequence = last_event_sequence + 1
            WHERE job_id = ?
            """,
            (job_id,),
        )
        if cursor.rowcount != 1:
            raise NotFoundError("migration job", job_id)

        row = self._connection.execute(
            """
            SELECT last_event_sequence
            FROM migration_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("migration job", job_id)
        return int(row["last_event_sequence"])

class SqliteRunConfigurationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, run_configuration: RunConfigurationRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO run_configurations (
                    run_configuration_id, job_id, schema_version,
                    runner_profile_id, runner_profile_version, pipeline_id, pipeline_version,
                    target_proof_level, enabled_gates_json, policy_json,
                    payload_json, payload_checksum, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_configuration.run_configuration_id,
                    run_configuration.job_id,
                    run_configuration.schema_version,
                    run_configuration.runner_profile_id,
                    run_configuration.runner_profile_version,
                    run_configuration.pipeline_id,
                    run_configuration.pipeline_version,
                    run_configuration.target_proof_level.value,
                    run_configuration.enabled_gates_json,
                    run_configuration.policy_json,
                    run_configuration.payload_json,
                    run_configuration.payload_checksum,
                    run_configuration.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def get_for_job(self, job_id: str) -> RunConfigurationRecord | None:
        row = self._connection.execute(
            """
            SELECT run_configuration_id, job_id, schema_version, runner_profile_id,
                   runner_profile_version, pipeline_id, pipeline_version, target_proof_level,
                   enabled_gates_json, policy_json, payload_json, payload_checksum, created_at
            FROM run_configurations
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return RunConfigurationRecord(
            run_configuration_id=str(row["run_configuration_id"]),
            job_id=str(row["job_id"]),
            schema_version=str(row["schema_version"]),
            runner_profile_id=str(row["runner_profile_id"]),
            runner_profile_version=str(row["runner_profile_version"]),
            pipeline_id=str(row["pipeline_id"]),
            pipeline_version=str(row["pipeline_version"]),
            target_proof_level=TargetProofLevel(str(row["target_proof_level"])),
            enabled_gates_json=str(row["enabled_gates_json"]),
            policy_json=str(row["policy_json"]),
            payload_json=str(row["payload_json"]),
            payload_checksum=str(row["payload_checksum"]),
            created_at=str(row["created_at"]),
        )


class SqliteStageRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_many(self, stage_runs: Sequence[StageRunRecord]) -> None:
        try:
            self._connection.executemany(
                """
                INSERT INTO stage_runs (
                    stage_run_id, job_id, stage_index, stage_id, status,
                    input_source_json, created_at, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        stage.stage_run_id,
                        stage.job_id,
                        stage.stage_index,
                        stage.stage_id,
                        stage.status,
                        stage.input_source_json,
                        stage.created_at,
                        stage.started_at,
                        stage.finished_at,
                    )
                    for stage in stage_runs
                ],
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def get(self, stage_run_id: str) -> StageRunRecord | None:
        row = self._connection.execute(
            """
            SELECT stage_run_id, job_id, stage_index, stage_id, status, input_source_json,
                   created_at, started_at, finished_at
            FROM stage_runs
            WHERE stage_run_id = ?
            """,
            (stage_run_id,),
        ).fetchone()
        if row is None:
            return None
        return _stage_run_record_from_row(row)

    def list_for_job(self, job_id: str) -> tuple[StageRunRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT stage_run_id, job_id, stage_index, stage_id, status, input_source_json,
                   created_at, started_at, finished_at
            FROM stage_runs
            WHERE job_id = ?
            ORDER BY stage_index
            """,
            (job_id,),
        ).fetchall()
        return tuple(_stage_run_record_from_row(row) for row in rows)


class SqliteArtifactRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, artifact: ArtifactRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, job_id, stage_run_id, artifact_type,
                    registered_root_id, relative_path, normalized_relative_path,
                    content_type, size_bytes, checksum_algorithm, checksum,
                    created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.job_id,
                    artifact.stage_run_id,
                    artifact.artifact_type,
                    artifact.registered_root_id,
                    artifact.relative_path,
                    artifact.normalized_relative_path,
                    artifact.content_type,
                    artifact.size_bytes,
                    artifact.checksum_algorithm,
                    artifact.checksum,
                    artifact.created_at,
                    artifact.created_by,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def get_exact(
        self,
        job_id: str,
        registered_root_id: str,
        normalized_relative_path: str,
    ) -> ArtifactDto | None:
        row = self._connection.execute(
            """
            SELECT artifact_id, job_id, stage_run_id, artifact_type, registered_root_id,
                   relative_path, normalized_relative_path, content_type, size_bytes,
                   checksum_algorithm, checksum, created_at, created_by
            FROM artifacts
            WHERE job_id = ?
              AND registered_root_id = ?
              AND normalized_relative_path = ?
            """,
            (job_id, registered_root_id, normalized_relative_path),
        ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    def list_for_job(self, job_id: str) -> tuple[ArtifactDto, ...]:
        rows = self._connection.execute(
            """
            SELECT artifact_id, job_id, stage_run_id, artifact_type, registered_root_id,
                   relative_path, normalized_relative_path, content_type, size_bytes,
                   checksum_algorithm, checksum, created_at, created_by
            FROM artifacts
            WHERE job_id = ?
            ORDER BY created_at, artifact_id
            """,
            (job_id,),
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)


class SqliteRunEventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, event: RunEventRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO run_events (
                    event_id, job_id, sequence, event_type, actor_type, actor_id,
                    correlation_id, causation_id, payload_json, payload_checksum, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.job_id,
                    event.sequence,
                    event.event_type,
                    event.actor_type,
                    event.actor_id,
                    event.correlation_id,
                    event.causation_id,
                    event.payload_json,
                    event.payload_checksum,
                    event.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def append_job_state_changed_event(
        self,
        *,
        event_id: str,
        job_id: str,
        sequence: int,
        actor_type: str,
        actor_id: str,
        payload_json: str,
        payload_checksum: str,
        created_at: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO run_events (
                    event_id, job_id, sequence, event_type, actor_type, actor_id,
                    correlation_id, causation_id, payload_json, payload_checksum,
                    created_at
                ) VALUES (?, ?, ?, 'job_state_changed', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    job_id,
                    sequence,
                    actor_type,
                    actor_id,
                    correlation_id,
                    causation_id,
                    payload_json,
                    payload_checksum,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def list_for_job(self, job_id: str) -> tuple[RunEventDto, ...]:
        rows = self._connection.execute(
            """
            SELECT event_id, job_id, sequence, event_type, actor_type, actor_id,
                   correlation_id, causation_id, payload_json, payload_checksum,
                   created_at
            FROM run_events
            WHERE job_id = ?
            ORDER BY sequence
            """,
            (job_id,),
        ).fetchall()
        return tuple(_run_event_from_row(row) for row in rows)

    def list_for_job_after(
        self,
        job_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[RunEventDto, ...]:
        rows = self._connection.execute(
            """
            SELECT event_id, job_id, sequence, event_type, actor_type, actor_id,
                   correlation_id, causation_id, payload_json, payload_checksum,
                   created_at
            FROM run_events
            WHERE job_id = ?
              AND sequence > ?
            ORDER BY sequence
            LIMIT ?
            """,
            (job_id, after_sequence, limit),
        ).fetchall()
        return tuple(_run_event_from_row(row) for row in rows)

    def count_for_job(self, job_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["count"])


class SqliteAuditRecordRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, audit_record: AuditRecord) -> None:
        try:
            self._insert(
                audit_id=audit_record.audit_id,
                job_id=audit_record.job_id,
                actor_type=audit_record.actor_type,
                actor_id=audit_record.actor_id,
                action=audit_record.action,
                prior_state=audit_record.prior_state,
                new_state=audit_record.new_state,
                job_version=audit_record.job_version,
                correlation_id=audit_record.correlation_id,
                causation_id=audit_record.causation_id,
                payload_json=audit_record.payload_json,
                created_at=audit_record.created_at,
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def append_global_audit(
        self,
        *,
        audit_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        payload_json: str,
        created_at: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        try:
            self._insert(
                audit_id=audit_id,
                job_id=None,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                prior_state=None,
                new_state=None,
                job_version=None,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload_json=payload_json,
                created_at=created_at,
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def append_job_state_changed_audit(
        self,
        *,
        audit_id: str,
        job_id: str,
        actor_type: str,
        actor_id: str,
        prior_state: JobState,
        new_state: JobState,
        job_version: int,
        payload_json: str,
        created_at: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> None:
        try:
            self._insert(
                audit_id=audit_id,
                job_id=job_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="job_state_changed",
                prior_state=prior_state.value,
                new_state=new_state.value,
                job_version=job_version,
                correlation_id=correlation_id,
                causation_id=causation_id,
                payload_json=payload_json,
                created_at=created_at,
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def list(self) -> tuple[AuditRecordDto, ...]:
        rows = self._connection.execute(
            """
            SELECT audit_id, job_id, actor_type, actor_id, action, prior_state, new_state,
                   job_version, correlation_id, causation_id, payload_json, created_at
            FROM audit_records
            ORDER BY created_at, audit_id
            """
        ).fetchall()
        return tuple(_audit_record_from_row(row) for row in rows)

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM audit_records").fetchone()
        return int(row["count"])

    def list_for_job(self, job_id: str) -> tuple[AuditRecordDto, ...]:
        rows = self._connection.execute(
            """
            SELECT audit_id, job_id, actor_type, actor_id, action, prior_state, new_state,
                   job_version, correlation_id, causation_id, payload_json, created_at
            FROM audit_records
            WHERE job_id = ?
            ORDER BY created_at, audit_id
            """,
            (job_id,),
        ).fetchall()
        return tuple(_audit_record_from_row(row) for row in rows)

    def count_for_job(self, job_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM audit_records WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["count"])

    def _insert(
        self,
        *,
        audit_id: str,
        job_id: str | None,
        actor_type: str,
        actor_id: str,
        action: str,
        prior_state: str | None,
        new_state: str | None,
        job_version: int | None,
        correlation_id: str | None,
        causation_id: str | None,
        payload_json: str,
        created_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO audit_records (
                audit_id, job_id, actor_type, actor_id, action, prior_state, new_state,
                job_version, correlation_id, causation_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                job_id,
                actor_type,
                actor_id,
                action,
                prior_state,
                new_state,
                job_version,
                correlation_id,
                causation_id,
                payload_json,
                created_at,
            ),
        )


class SqliteCommandExecutionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_queued(self, command: CommandExecutionRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO command_executions (
                    command_id, job_id, operation, status, created_at, updated_at,
                    correlation_id, causation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.command_id,
                    command.job_id,
                    command.operation,
                    command.status.value,
                    command.created_at,
                    command.updated_at,
                    command.correlation_id,
                    command.causation_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc

    def get(self, command_id: str) -> CommandExecutionDto | None:
        row = self._connection.execute(
            """
            SELECT command_id, job_id, operation, status, created_at, updated_at,
                   correlation_id, causation_id,
                   command_manifest_artifact_id, working_directory_root_id,
                   working_directory_relative_path, worker_id, launch_attempt,
                   stdout_offset, stderr_offset
            FROM command_executions
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()
        return _command_execution_from_row(row) if row is not None else None

    def get_active_for_job(self, job_id: str) -> CommandExecutionDto | None:
        row = self._connection.execute(
            """
            SELECT command_id, job_id, operation, status, created_at, updated_at,
                   correlation_id, causation_id,
                   command_manifest_artifact_id, working_directory_root_id,
                   working_directory_relative_path, worker_id, launch_attempt,
                   stdout_offset, stderr_offset
            FROM command_executions
            WHERE job_id = ?
              AND status IN ('QUEUED', 'STARTING', 'RUNNING', 'CANCELLING')
            ORDER BY created_at, command_id
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        return _command_execution_from_row(row) if row is not None else None

    def update_status(self, command_id: str, status: CommandState) -> None:
        cursor = self._connection.execute(
            """UPDATE command_executions
            SET status = ?,
                updated_at = ?
            WHERE command_id = ?""",
            (
                status.value,
                utc_now_text(),
                command_id,
            ),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("command execution", command_id)

    def update_workspace_columns(
        self,
        command_id: str,
        *,
        command_manifest_artifact_id: str,
        working_directory_root_id: str,
        working_directory_relative_path: str,
        worker_id: str,
        launch_attempt: int,
    ) -> None:
        cursor = self._connection.execute(
            """UPDATE command_executions
            SET command_manifest_artifact_id = ?,
                working_directory_root_id = ?,
                working_directory_relative_path = ?,
                worker_id = ?,
                launch_attempt = ?,
                updated_at = ?
            WHERE command_id = ?
              AND command_manifest_artifact_id IS NULL""",
            (
                command_manifest_artifact_id,
                working_directory_root_id,
                working_directory_relative_path,
                worker_id,
                launch_attempt,
                utc_now_text(),
                command_id,
            ),
        )
        if cursor.rowcount == 0:
            raise WorkspaceConflictError(
                f"Workspace already prepared for command {command_id!r}"
            )

    def update_process_columns(
        self,
        command_id: str,
        *,
        status: CommandState,
        process_control_id: str,
        worker_pid: int,
        process_started_at: str,
    ) -> None:
        cursor = self._connection.execute(
            """UPDATE command_executions
            SET status = ?,
                process_control_id = ?,
                worker_pid = ?,
                process_started_at = ?,
                updated_at = ?
            WHERE command_id = ?
              AND command_manifest_artifact_id IS NOT NULL
              AND status IN ('QUEUED', 'STARTING')""",
            (
                status.value,
                process_control_id,
                worker_pid,
                process_started_at,
                utc_now_text(),
                command_id,
            ),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(
                "command execution",
                f"{command_id} not in QUEUED/STARTING or workspace not prepared",
            )

    def get_output_offsets(self, command_id: str) -> tuple[int, int]:
        row = self._connection.execute(
            """
            SELECT stdout_offset, stderr_offset
            FROM command_executions
            WHERE command_id = ?
            """,
            (command_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("command execution", command_id)
        return int(row["stdout_offset"]), int(row["stderr_offset"])

    def update_output_offsets(
        self,
        command_id: str,
        *,
        stdout_offset: int,
        stderr_offset: int,
    ) -> None:
        cursor = self._connection.execute(
            """UPDATE command_executions
            SET stdout_offset = ?,
                stderr_offset = ?,
                updated_at = ?
            WHERE command_id = ?""",
            (stdout_offset, stderr_offset, utc_now_text(), command_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("command execution", command_id)

    def set_output_limit_exceeded(self, command_id: str) -> None:
        cursor = self._connection.execute(
            """UPDATE command_executions
            SET output_limit_exceeded = 1,
                updated_at = ?
            WHERE command_id = ?""",
            (utc_now_text(), command_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError("command execution", command_id)


class SqliteIdempotencyRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, operation: str, idempotency_key: str) -> IdempotencyRecordDto | None:
        row = self._connection.execute(
            """
            SELECT operation, idempotency_key, request_checksum, resource_type,
                   resource_id, original_status_code, created_at
            FROM idempotency_records
            WHERE operation = ? AND idempotency_key = ?
            """,
            (operation, idempotency_key),
        ).fetchone()
        return _idempotency_record_from_row(row) if row is not None else None

    def insert(self, record: IdempotencyRecord) -> None:
        try:
            self._connection.execute(
                """
                INSERT INTO idempotency_records (
                    operation, idempotency_key, request_checksum, resource_type,
                    resource_id, original_status_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.operation,
                    record.idempotency_key,
                    record.request_checksum,
                    record.resource_type,
                    record.resource_id,
                    record.original_status_code,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise StorageIntegrityError(str(exc)) from exc


def _runner_profile_from_row(row: sqlite3.Row) -> RunnerProfileDto:
    payload_json = str(row["payload_json"])
    return RunnerProfileDto(
        runner_profile_id=str(row["runner_profile_id"]),
        runner_profile_version=str(row["runner_profile_version"]),
        display_name=str(row["display_name"]),
        schema_version=str(row["schema_version"]),
        payload=json.loads(payload_json),
        payload_json=payload_json,
        payload_checksum=str(row["payload_checksum"]),
        created_at=str(row["created_at"]),
        created_by=str(row["created_by"]),
    )


def _pipeline_definition_from_row(row: sqlite3.Row) -> PipelineDefinitionDto:
    payload_json = str(row["payload_json"])
    return PipelineDefinitionDto(
        pipeline_id=str(row["pipeline_id"]),
        pipeline_version=str(row["pipeline_version"]),
        display_name=str(row["display_name"]),
        schema_version=str(row["schema_version"]),
        graph_version=str(row["graph_version"]),
        graph_state_schema_version=str(row["graph_state_schema_version"]),
        payload=json.loads(payload_json),
        payload_json=payload_json,
        payload_checksum=str(row["payload_checksum"]),
        created_at=str(row["created_at"]),
        created_by=str(row["created_by"]),
    )


def _migration_job_dto_from_row(row: sqlite3.Row) -> MigrationJobDto:
    active_slot = row["active_slot"]
    return MigrationJobDto(
        job_id=str(row["job_id"]),
        version=int(row["version"]),
        status=JobState(str(row["status"])),
        active_slot=int(active_slot) if active_slot is not None else None,
        last_event_sequence=int(row["last_event_sequence"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=str(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] is not None else None,
    )


def _run_event_from_row(row: sqlite3.Row) -> RunEventDto:
    payload_json = str(row["payload_json"])
    return RunEventDto(
        event_id=str(row["event_id"]),
        job_id=str(row["job_id"]),
        sequence=int(row["sequence"]),
        event_type=str(row["event_type"]),
        actor_type=str(row["actor_type"]),
        actor_id=str(row["actor_id"]),
        correlation_id=str(row["correlation_id"]) if row["correlation_id"] is not None else None,
        causation_id=str(row["causation_id"]) if row["causation_id"] is not None else None,
        payload=json.loads(payload_json),
        payload_json=payload_json,
        payload_checksum=str(row["payload_checksum"]),
        created_at=str(row["created_at"]),
    )


def _audit_record_from_row(row: sqlite3.Row) -> AuditRecordDto:
    payload_json = str(row["payload_json"])
    job_version = row["job_version"]
    return AuditRecordDto(
        audit_id=str(row["audit_id"]),
        job_id=str(row["job_id"]) if row["job_id"] is not None else None,
        actor_type=str(row["actor_type"]),
        actor_id=str(row["actor_id"]),
        action=str(row["action"]),
        prior_state=str(row["prior_state"]) if row["prior_state"] is not None else None,
        new_state=str(row["new_state"]) if row["new_state"] is not None else None,
        job_version=int(job_version) if job_version is not None else None,
        correlation_id=str(row["correlation_id"]) if row["correlation_id"] is not None else None,
        causation_id=str(row["causation_id"]) if row["causation_id"] is not None else None,
        payload=json.loads(payload_json),
        payload_json=payload_json,
        created_at=str(row["created_at"]),
    )


def _artifact_from_row(row: sqlite3.Row) -> ArtifactDto:
    return ArtifactDto(
        artifact_id=str(row["artifact_id"]),
        job_id=str(row["job_id"]),
        stage_run_id=str(row["stage_run_id"]) if row["stage_run_id"] is not None else None,
        artifact_type=str(row["artifact_type"]),
        registered_root_id=str(row["registered_root_id"]),
        relative_path=str(row["relative_path"]),
        normalized_relative_path=str(row["normalized_relative_path"]),
        content_type=str(row["content_type"]) if row["content_type"] is not None else None,
        size_bytes=int(row["size_bytes"]),
        checksum_algorithm=str(row["checksum_algorithm"]),
        checksum=str(row["checksum"]),
        created_at=str(row["created_at"]),
        created_by=str(row["created_by"]),
    )


def _command_execution_from_row(row: sqlite3.Row) -> CommandExecutionDto:
    return CommandExecutionDto(
        command_id=str(row["command_id"]),
        job_id=str(row["job_id"]),
        operation=str(row["operation"]),
        status=CommandState(str(row["status"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        correlation_id=str(row["correlation_id"]) if row["correlation_id"] is not None else None,
        causation_id=str(row["causation_id"]) if row["causation_id"] is not None else None,
        command_manifest_artifact_id=(
            str(row["command_manifest_artifact_id"])
            if row["command_manifest_artifact_id"] is not None
            else None
        ),
        working_directory_root_id=(
            str(row["working_directory_root_id"])
            if row["working_directory_root_id"] is not None
            else None
        ),
        working_directory_relative_path=(
            str(row["working_directory_relative_path"])
            if row["working_directory_relative_path"] is not None
            else None
        ),
        worker_id=(
            str(row["worker_id"]) if row["worker_id"] is not None else None
        ),
        launch_attempt=(
            int(row["launch_attempt"]) if row["launch_attempt"] is not None else None
        ),
    )


def _idempotency_record_from_row(row: sqlite3.Row) -> IdempotencyRecordDto:
    return IdempotencyRecordDto(
        operation=str(row["operation"]),
        idempotency_key=str(row["idempotency_key"]),
        request_checksum=str(row["request_checksum"]),
        resource_type=str(row["resource_type"]),
        resource_id=str(row["resource_id"]),
        original_status_code=int(row["original_status_code"]),
        created_at=str(row["created_at"]),
    )


def _stage_run_record_from_row(row: sqlite3.Row) -> StageRunRecord:
    return StageRunRecord(
        stage_run_id=str(row["stage_run_id"]),
        job_id=str(row["job_id"]),
        stage_index=int(row["stage_index"]),
        stage_id=str(row["stage_id"]),
        status=str(row["status"]),
        input_source_json=str(row["input_source_json"]),
        created_at=str(row["created_at"]),
        started_at=None if row["started_at"] is None else str(row["started_at"]),
        finished_at=None if row["finished_at"] is None else str(row["finished_at"]),
    )


def _migration_job_record_from_row(row: sqlite3.Row) -> MigrationJobRecord:
    return MigrationJobRecord(
        job_id=str(row["job_id"]),
        version=int(row["version"]),
        status=JobState(str(row["status"])),
        active_slot=None if row["active_slot"] is None else int(row["active_slot"]),
        last_event_sequence=int(row["last_event_sequence"]),
        runner_profile_id=str(row["runner_profile_id"]),
        runner_profile_version=str(row["runner_profile_version"]),
        pipeline_id=str(row["pipeline_id"]),
        pipeline_version=str(row["pipeline_version"]),
        target_proof_level=TargetProofLevel(str(row["target_proof_level"])),
        achieved_proof_level=(
            None
            if row["achieved_proof_level"] is None
            else TargetProofLevel(str(row["achieved_proof_level"]))
        ),
        legacy_source_ref=str(row["legacy_source_ref"]),
        output_root_ref=str(row["output_root_ref"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=None if row["started_at"] is None else str(row["started_at"]),
        finished_at=None if row["finished_at"] is None else str(row["finished_at"]),
        created_by=str(row["created_by"]),
    )
