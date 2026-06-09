"""SQLite repositories for Control Tower registration records."""

from __future__ import annotations

import json
import sqlite3

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
)


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
