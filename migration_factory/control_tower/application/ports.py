"""Ports for Control Tower application services."""

from __future__ import annotations

from typing import Protocol, Self, Sequence

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    ArtifactDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
)
from migration_factory.control_tower.domain.entities import (
    ArtifactRecord,
    AuditRecord,
    MigrationJobRecord,
    PipelineDefinitionRecord,
    RunConfigurationRecord,
    RunEventRecord,
    RunnerProfileRecord,
    StageRunRecord,
)


class RunnerProfileRepository(Protocol):
    def get_exact(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileRecord | None: ...

    def get(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileDto | None: ...

    def list(self) -> tuple[RunnerProfileDto, ...]: ...

    def insert(self, profile: RunnerProfileDto) -> None: ...

    def find_checksum(self, runner_profile_id: str, runner_profile_version: str) -> str | None: ...


class PipelineDefinitionRepository(Protocol):
    def get_exact(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionRecord | None: ...

    def get(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionDto | None: ...

    def list(self) -> tuple[PipelineDefinitionDto, ...]: ...

    def insert(self, pipeline: PipelineDefinitionDto) -> None: ...

    def find_checksum(self, pipeline_id: str, pipeline_version: str) -> str | None: ...


class MigrationJobRepository(Protocol):
    def insert_created(self, job: MigrationJobRecord) -> None: ...

    def get(self, job_id: str) -> MigrationJobRecord | None: ...

    def get_active_job(self) -> MigrationJobRecord | None: ...

    def increment_last_event_sequence(self, job_id: str) -> int | None: ...


class RunConfigurationRepository(Protocol):
    def insert(self, run_configuration: RunConfigurationRecord) -> None: ...

    def get_for_job(self, job_id: str) -> RunConfigurationRecord | None: ...


class StageRunRepository(Protocol):
    def insert_many(self, stage_runs: Sequence[StageRunRecord]) -> None: ...

    def get(self, stage_run_id: str) -> StageRunRecord | None: ...


class RunEventRepository(Protocol):
    def insert(self, event: RunEventRecord) -> None: ...


class ArtifactRepository(Protocol):
    def insert(self, artifact: ArtifactRecord) -> None: ...

    def get_exact(
        self,
        job_id: str,
        registered_root_id: str,
        normalized_relative_path: str,
    ) -> ArtifactDto | None: ...

    def list_for_job(self, job_id: str) -> tuple[ArtifactDto, ...]: ...


class AuditRecordRepository(Protocol):
    def insert(self, audit_record: AuditRecord) -> None: ...

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
    ) -> None: ...

    def list(self) -> tuple[AuditRecordDto, ...]: ...

    def count(self) -> int: ...


class ControlTowerUnitOfWork(Protocol):
    runner_profiles: RunnerProfileRepository
    pipeline_definitions: PipelineDefinitionRepository
    migration_jobs: MigrationJobRepository
    run_configurations: RunConfigurationRepository
    stage_runs: StageRunRepository
    run_events: RunEventRepository
    artifacts: ArtifactRepository
    audit_records: AuditRecordRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, tb) -> bool | None: ...


UnitOfWork = ControlTowerUnitOfWork
