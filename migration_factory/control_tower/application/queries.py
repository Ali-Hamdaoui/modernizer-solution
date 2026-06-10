"""Read-only application queries for the Control Tower.

All queries return typed DTOs and never create events, audit records,
or mutate operational state.
"""

from __future__ import annotations

import json

from migration_factory.control_tower.application.dto import (
    ArtifactDto,
    AuditRecordDto,
    MigrationJobDto,
    PipelineDefinitionDto,
    RunConfigurationDto,
    RunEventDto,
    RunnerProfileDto,
    StageRunDto,
)
from migration_factory.control_tower.application.services import UnitOfWorkFactory
from migration_factory.control_tower.domain.errors import (
    EventCursorConflictError,
    InvalidEventCursorError,
    NotFoundError,
)


DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE = 500


class ControlTowerQueryService:
    """Read-only queries for Control Tower operational state."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    # ── MigrationJob ────────────────────────────────────────────

    def get_migration_job(self, job_id: str) -> MigrationJobDto:
        with self._unit_of_work_factory() as uow:
            job = uow.migration_jobs.get(job_id)
            if job is None:
                raise NotFoundError("migration job", job_id)
            return job

    def get_active_migration_job(self) -> MigrationJobDto | None:
        with self._unit_of_work_factory() as uow:
            record = uow.migration_jobs.get_active_job()
            if record is None:
                return None
            return MigrationJobDto(
                job_id=record.job_id,
                version=record.version,
                status=record.status,
                active_slot=record.active_slot,
                last_event_sequence=record.last_event_sequence,
                created_at=record.created_at,
                updated_at=record.updated_at,
                started_at=record.started_at,
                finished_at=record.finished_at,
            )

    def list_migration_jobs(self) -> tuple[MigrationJobDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.migration_jobs.list()

    # ── RunConfiguration ────────────────────────────────────────

    def get_run_configuration(self, job_id: str) -> RunConfigurationDto:
        with self._unit_of_work_factory() as uow:
            record = uow.run_configurations.get_for_job(job_id)
            if record is None:
                raise NotFoundError("run configuration", job_id)
            return RunConfigurationDto(
                run_configuration_id=record.run_configuration_id,
                job_id=record.job_id,
                schema_version=record.schema_version,
                runner_profile_id=record.runner_profile_id,
                runner_profile_version=record.runner_profile_version,
                pipeline_id=record.pipeline_id,
                pipeline_version=record.pipeline_version,
                target_proof_level=record.target_proof_level.value,
                enabled_gates=tuple(json.loads(record.enabled_gates_json)),
                policy=json.loads(record.policy_json),
                payload_json=record.payload_json,
                payload_checksum=record.payload_checksum,
                created_at=record.created_at,
            )

    # ── StageRun ─────────────────────────────────────────────────

    def list_stage_runs(self, job_id: str) -> tuple[StageRunDto, ...]:
        with self._unit_of_work_factory() as uow:
            records = uow.stage_runs.list_for_job(job_id)
            return tuple(
                StageRunDto(
                    stage_run_id=r.stage_run_id,
                    job_id=r.job_id,
                    stage_index=r.stage_index,
                    stage_id=r.stage_id,
                    status=r.status,
                    input_source=json.loads(r.input_source_json),
                    created_at=r.created_at,
                    started_at=r.started_at,
                    finished_at=r.finished_at,
                )
                for r in records
            )

    # ── RunEvent ─────────────────────────────────────────────────

    def list_run_events(self, job_id: str) -> tuple[RunEventDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.run_events.list_for_job(job_id)

    def replay_run_events(
        self,
        job_id: str,
        *,
        after_sequence: int,
        limit: int = DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE,
    ) -> tuple[RunEventDto, ...]:
        if after_sequence < 0:
            raise InvalidEventCursorError("after_sequence must be greater than or equal to 0")
        if limit < 1:
            raise InvalidEventCursorError("event replay limit must be greater than 0")
        with self._unit_of_work_factory() as uow:
            job = uow.migration_jobs.get(job_id)
            if job is None:
                raise NotFoundError("migration job", job_id)
            if after_sequence > job.last_event_sequence:
                raise InvalidEventCursorError(
                    "after_sequence cannot be greater than the latest committed event sequence"
                )
            return uow.run_events.list_for_job_after(job_id, after_sequence, limit)

    def latest_run_event_sequence(self, job_id: str) -> int:
        with self._unit_of_work_factory() as uow:
            job = uow.migration_jobs.get(job_id)
            if job is None:
                raise NotFoundError("migration job", job_id)
            return job.last_event_sequence

    # ── Artifact ─────────────────────────────────────────────────

    def list_artifacts(self, job_id: str) -> tuple[ArtifactDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.artifacts.list_for_job(job_id)

    # ── AuditRecord ──────────────────────────────────────────────

    def list_audit_records(self) -> tuple[AuditRecordDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.audit_records.list()

    def list_audit_records_for_job(self, job_id: str) -> tuple[AuditRecordDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.audit_records.list_for_job(job_id)

    # ── RunnerProfile ────────────────────────────────────────────

    def get_runner_profile(
        self,
        runner_profile_id: str,
        runner_profile_version: str,
    ) -> RunnerProfileDto:
        with self._unit_of_work_factory() as uow:
            profile = uow.runner_profiles.get(runner_profile_id, runner_profile_version)
            if profile is None:
                raise NotFoundError(
                    "runner profile",
                    f"{runner_profile_id}/{runner_profile_version}",
                )
            return profile

    def list_runner_profiles(self) -> tuple[RunnerProfileDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.runner_profiles.list()

    # ── PipelineDefinition ───────────────────────────────────────

    def get_pipeline_definition(
        self,
        pipeline_id: str,
        pipeline_version: str,
    ) -> PipelineDefinitionDto:
        with self._unit_of_work_factory() as uow:
            pipeline = uow.pipeline_definitions.get(pipeline_id, pipeline_version)
            if pipeline is None:
                raise NotFoundError(
                    "pipeline definition",
                    f"{pipeline_id}/{pipeline_version}",
                )
            return pipeline

    def list_pipeline_definitions(self) -> tuple[PipelineDefinitionDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.pipeline_definitions.list()


def parse_public_event_cursor(
    *,
    after_sequence: str | int | None,
    last_event_id: str | None,
    latest_sequence: int,
) -> int:
    query_sequence = _parse_optional_sequence(after_sequence, "after_sequence")
    header_sequence = _parse_optional_sequence(last_event_id, "Last-Event-ID")

    if query_sequence is not None and header_sequence is not None and query_sequence != header_sequence:
        raise EventCursorConflictError(header_sequence, query_sequence)

    sequence = query_sequence if query_sequence is not None else header_sequence
    if sequence is None:
        sequence = 0
    if sequence > latest_sequence:
        raise InvalidEventCursorError(
            "event cursor cannot be greater than the latest committed event sequence"
        )
    return sequence


def _parse_optional_sequence(value: str | int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        sequence = value
    else:
        text = value.strip()
        if not text:
            raise InvalidEventCursorError(f"{field_name} must be an integer")
        try:
            sequence = int(text, 10)
        except ValueError as exc:
            raise InvalidEventCursorError(f"{field_name} must be an integer") from exc
    if sequence < 0:
        raise InvalidEventCursorError(f"{field_name} must be greater than or equal to 0")
    return sequence
