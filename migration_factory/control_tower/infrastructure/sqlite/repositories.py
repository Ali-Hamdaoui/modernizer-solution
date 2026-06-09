"""SQLite repository implementations for Control Tower."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
import uuid

from migration_factory.control_tower.application.dto import (
    AuditRecordDTO,
    MigrationJobDTO,
    RunConfigurationDTO,
    RunEventDTO,
    StageRunDTO,
)
from migration_factory.control_tower.application.errors import (
    ActiveMigrationJobConflictError,
    DefinitionNotFoundError,
    RepositoryIntegrityError,
)
from migration_factory.control_tower.domain.checksums import (
    canonical_json_text,
    sha256_canonical_json,
)
from migration_factory.control_tower.domain.states import JobState, StageState
from migration_factory.control_tower.schemas.pipeline_definition import PipelineDefinition
from migration_factory.control_tower.schemas.run_configuration import RunConfiguration
from migration_factory.control_tower.schemas.runner_profile import RunnerProfile


class SqliteDefinitionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def save_runner_profile(self, profile: RunnerProfile, *, actor: str) -> None:
        now = _utc_now()
        payload = profile.model_dump(mode="json")
        self.connection.execute(
            """
            INSERT INTO runner_profiles (profile_id, display_name, config_json, created_utc, updated_utc)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                display_name = excluded.display_name,
                config_json = excluded.config_json,
                updated_utc = excluded.updated_utc
            """,
            (
                profile.runner_profile_id,
                profile.display_name,
                canonical_json_text(payload),
                now,
                now,
            ),
        )
        _insert_audit(
            self.connection,
            job_id=None,
            entity_type="runner_profile",
            entity_id=profile.runner_profile_id,
            action="runner_profile_registered",
            actor=actor,
            payload={"runner_profile_version": profile.runner_profile_version},
        )

    def save_pipeline_definition(self, pipeline: PipelineDefinition, *, actor: str) -> None:
        now = _utc_now()
        payload = pipeline.model_dump(mode="json")
        self.connection.execute(
            """
            INSERT INTO pipeline_definitions (
                pipeline_id, pipeline_name, pipeline_version, description,
                definition_json, created_utc, updated_utc
            )
            VALUES (?, ?, ?, '', ?, ?, ?)
            ON CONFLICT(pipeline_id) DO UPDATE SET
                pipeline_name = excluded.pipeline_name,
                pipeline_version = excluded.pipeline_version,
                definition_json = excluded.definition_json,
                updated_utc = excluded.updated_utc
            """,
            (
                pipeline.pipeline_id,
                pipeline.pipeline_id,
                pipeline.pipeline_version,
                canonical_json_text(payload),
                now,
                now,
            ),
        )
        _insert_audit(
            self.connection,
            job_id=None,
            entity_type="pipeline_definition",
            entity_id=pipeline.pipeline_id,
            action="pipeline_definition_registered",
            actor=actor,
            payload={"pipeline_version": pipeline.pipeline_version},
        )

    def get_runner_profile(self, profile_id: str, version: str) -> RunnerProfile:
        row = self.connection.execute(
            "SELECT config_json FROM runner_profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            raise DefinitionNotFoundError(
                f"Runner profile not found: {profile_id}@{version}"
            )
        profile = RunnerProfile.model_validate(_tuplify(json.loads(row["config_json"])))
        if profile.runner_profile_version != version:
            raise DefinitionNotFoundError(
                f"Runner profile not found: {profile_id}@{version}"
            )
        return profile

    def get_pipeline_definition(self, pipeline_id: str, version: str) -> PipelineDefinition:
        row = self.connection.execute(
            """
            SELECT definition_json, pipeline_version
            FROM pipeline_definitions
            WHERE pipeline_id = ?
            """,
            (pipeline_id,),
        ).fetchone()
        if row is None or row["pipeline_version"] != version:
            raise DefinitionNotFoundError(
                f"Pipeline definition not found: {pipeline_id}@{version}"
            )
        pipeline = PipelineDefinition.model_validate(
            _tuplify(json.loads(row["definition_json"]))
        )
        if pipeline.pipeline_version != version:
            raise DefinitionNotFoundError(
                f"Pipeline definition not found: {pipeline_id}@{version}"
            )
        return pipeline


class SqliteMigrationJobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_job_with_configuration_stages_event_and_audit(
        self,
        *,
        actor: str,
        legacy_source_ref: str,
        output_root_ref: str,
        runner_profile: RunnerProfile,
        pipeline: PipelineDefinition,
        target_proof_level: str,
        enabled_gates: tuple[str, ...],
        policy_payload: dict,
        correlation_id: str,
    ) -> MigrationJobDTO:
        job_id = f"job-{uuid.uuid4().hex}"
        configuration_id = f"run-config-{uuid.uuid4().hex}"
        now = _utc_now()

        try:
            self.connection.execute(
                """
                INSERT INTO migration_jobs (
                    job_id, version, pipeline_id, runner_profile_id, requested_by,
                    state, active_slot, last_event_sequence, target_proof_level,
                    legacy_source_ref, output_root_ref, created_utc, updated_utc
                )
                VALUES (?, 1, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    pipeline.pipeline_id,
                    runner_profile.runner_profile_id,
                    actor,
                    JobState.CREATED.value,
                    target_proof_level,
                    legacy_source_ref,
                    output_root_ref,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _raise_integrity_error(exc)

        configuration = RunConfiguration.model_validate(
            {
                "schema_version": "1.0.0",
                "run_configuration_id": configuration_id,
                "job_id": job_id,
                "runner_profile_id": runner_profile.runner_profile_id,
                "runner_profile_version": runner_profile.runner_profile_version,
                "pipeline_id": pipeline.pipeline_id,
                "pipeline_version": pipeline.pipeline_version,
                "target_proof_level": target_proof_level,
                "enabled_gates": enabled_gates,
                "policy": policy_payload,
            }
        )
        config_payload = configuration.model_dump(mode="json")
        config_json = canonical_json_text(config_payload)
        config_checksum = sha256_canonical_json(config_payload)
        self.connection.execute(
            """
            INSERT INTO run_configurations (
                configuration_id, job_id, target_proof_level, config_json,
                config_checksum_sha256, created_utc
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (configuration_id, job_id, target_proof_level, config_json, config_checksum, now),
        )

        for stage in pipeline.stages:
            self.connection.execute(
                """
                INSERT INTO stage_runs (
                    stage_run_id, job_id, stage_name, state, ordinal, details_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"stage-{uuid.uuid4().hex}",
                    job_id,
                    stage.stage_id,
                    StageState.PENDING.value,
                    stage.stage_index,
                    canonical_json_text(stage.model_dump(mode="json")),
                ),
            )

        event_payload = {
            "job_id": job_id,
            "correlation_id": correlation_id,
            "runner_profile_id": runner_profile.runner_profile_id,
            "runner_profile_version": runner_profile.runner_profile_version,
            "pipeline_id": pipeline.pipeline_id,
            "pipeline_version": pipeline.pipeline_version,
        }
        self.connection.execute(
            """
            INSERT INTO run_events (
                event_id, job_id, sequence, event_type, event_utc,
                payload_json, payload_checksum_sha256
            )
            VALUES (?, ?, 1, 'job_created', ?, ?, ?)
            """,
            (
                f"event-{uuid.uuid4().hex}",
                job_id,
                now,
                canonical_json_text(event_payload),
                sha256_canonical_json(event_payload),
            ),
        )
        _insert_audit(
            self.connection,
            job_id=job_id,
            entity_type="migration_job",
            entity_id=job_id,
            action="job_created",
            actor=actor,
            payload=event_payload,
        )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> MigrationJobDTO:
        row = self.connection.execute(
            """
            SELECT job_id, version, state, last_event_sequence, runner_profile_id,
                   pipeline_id, target_proof_level
            FROM migration_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise DefinitionNotFoundError(f"Migration job not found: {job_id}")
        return MigrationJobDTO(
            job_id=row["job_id"],
            version=int(row["version"]),
            state=row["state"],
            last_event_sequence=int(row["last_event_sequence"]),
            runner_profile_id=row["runner_profile_id"],
            pipeline_id=row["pipeline_id"],
            target_proof_level=row["target_proof_level"],
        )

    def get_run_configuration(self, job_id: str) -> RunConfigurationDTO:
        row = self.connection.execute(
            """
            SELECT configuration_id, job_id, target_proof_level, config_json,
                   config_checksum_sha256
            FROM run_configurations
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise DefinitionNotFoundError(f"Run configuration not found for job: {job_id}")
        return RunConfigurationDTO(
            configuration_id=row["configuration_id"],
            job_id=row["job_id"],
            target_proof_level=row["target_proof_level"],
            config_json=row["config_json"],
            config_checksum_sha256=row["config_checksum_sha256"],
        )

    def list_stages(self, job_id: str) -> list[StageRunDTO]:
        rows = self.connection.execute(
            """
            SELECT stage_run_id, job_id, stage_name, state, ordinal
            FROM stage_runs
            WHERE job_id = ?
            ORDER BY ordinal ASC
            """,
            (job_id,),
        ).fetchall()
        return [
            StageRunDTO(
                stage_run_id=row["stage_run_id"],
                job_id=row["job_id"],
                stage_name=row["stage_name"],
                state=row["state"],
                ordinal=int(row["ordinal"]),
            )
            for row in rows
        ]

    def list_events(self, job_id: str) -> list[RunEventDTO]:
        rows = self.connection.execute(
            """
            SELECT event_id, job_id, sequence, event_type, payload_json
            FROM run_events
            WHERE job_id = ?
            ORDER BY sequence ASC
            """,
            (job_id,),
        ).fetchall()
        return [
            RunEventDTO(
                event_id=row["event_id"],
                job_id=row["job_id"],
                sequence=int(row["sequence"]),
                event_type=row["event_type"],
                payload_json=row["payload_json"],
            )
            for row in rows
        ]

    def list_audit_records(self, job_id: str) -> list[AuditRecordDTO]:
        rows = self.connection.execute(
            """
            SELECT audit_record_id, job_id, action, actor, payload_json
            FROM audit_records
            WHERE job_id = ?
            ORDER BY recorded_utc ASC
            """,
            (job_id,),
        ).fetchall()
        return [
            AuditRecordDTO(
                audit_record_id=row["audit_record_id"],
                job_id=row["job_id"],
                action=row["action"],
                actor=row["actor"],
                payload_json=row["payload_json"],
            )
            for row in rows
        ]


def _insert_audit(
    connection: sqlite3.Connection,
    *,
    job_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str,
    payload: dict,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_records (
            audit_record_id, job_id, stage_run_id, entity_type, entity_id,
            action, payload_json, recorded_utc, actor
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"audit-{uuid.uuid4().hex}",
            job_id,
            entity_type,
            entity_id,
            action,
            canonical_json_text(payload),
            _utc_now(),
            actor,
        ),
    )


def _raise_integrity_error(exc: sqlite3.IntegrityError) -> None:
    message = str(exc)
    if (
        "ux_migration_jobs_one_active_slot" in message
        or "UNIQUE constraint failed: migration_jobs.active_slot" in message
    ):
        raise ActiveMigrationJobConflictError(
            "A nonterminal migration job already exists."
        ) from exc
    raise RepositoryIntegrityError(message) from exc


def _tuplify(value):
    if isinstance(value, list):
        return tuple(_tuplify(item) for item in value)
    if isinstance(value, dict):
        return {key: _tuplify(item) for key, item in value.items()}
    return value


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
