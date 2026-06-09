"""SQLite repositories for Control Tower registration records."""

from __future__ import annotations

import json
import sqlite3

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    MigrationJobDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
    RunEventDto,
)
from migration_factory.control_tower.domain.errors import NotFoundError
from migration_factory.control_tower.domain.states import JobState


class SqliteRunnerProfileRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileDto | None:
        row = self._connection.execute(
            """
            SELECT runner_profile_id, runner_profile_version, display_name, schema_version,
                   payload_json, payload_checksum, created_at, created_by
            FROM runner_profiles
            WHERE runner_profile_id = ? AND runner_profile_version = ?
            """,
            (runner_profile_id, runner_profile_version),
        ).fetchone()
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


class SqlitePipelineDefinitionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionDto | None:
        row = self._connection.execute(
            """
            SELECT pipeline_id, pipeline_version, display_name, schema_version,
                   graph_version, graph_state_schema_version, payload_json,
                   payload_checksum, created_at, created_by
            FROM pipeline_definitions
            WHERE pipeline_id = ? AND pipeline_version = ?
            """,
            (pipeline_id, pipeline_version),
        ).fetchone()
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


class SqliteMigrationJobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

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
        return _migration_job_from_row(row) if row is not None else None

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
            raise NotFoundError(f"Migration job {job_id!r} not found")

        row = self._connection.execute(
            """
            SELECT last_event_sequence
            FROM migration_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"Migration job {job_id!r} not found")
        return int(row["last_event_sequence"])


class SqliteRunEventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

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

    def count_for_job(self, job_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return int(row["count"])


class SqliteAuditRecordRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

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
        self._connection.execute(
            """
            INSERT INTO audit_records (
                audit_id, job_id, actor_type, actor_id, action, prior_state, new_state,
                job_version, correlation_id, causation_id, payload_json, created_at
            ) VALUES (?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
            """,
            (
                audit_id,
                actor_type,
                actor_id,
                action,
                correlation_id,
                causation_id,
                payload_json,
                created_at,
            ),
        )

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
        self._connection.execute(
            """
            INSERT INTO audit_records (
                audit_id, job_id, actor_type, actor_id, action, prior_state, new_state,
                job_version, correlation_id, causation_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?, 'job_state_changed', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                audit_id,
                job_id,
                actor_type,
                actor_id,
                prior_state.value,
                new_state.value,
                job_version,
                correlation_id,
                causation_id,
                payload_json,
                created_at,
            ),
        )

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


def _migration_job_from_row(row: sqlite3.Row) -> MigrationJobDto:
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
