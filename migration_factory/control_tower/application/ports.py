"""Ports for Control Tower application services."""

from __future__ import annotations

from typing import Protocol, Sequence
from typing_extensions import Self

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    ArtifactDto,
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
from migration_factory.control_tower.domain.states import JobState


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

    def get(self, job_id: str) -> MigrationJobDto | None: ...

    def get_active_job(self) -> MigrationJobRecord | None: ...

    def list(self) -> tuple[MigrationJobDto, ...]: ...

    def transition_state(
        self,
        job_id: str,
        expected_version: int,
        target_state: JobState,
        active_slot: int | None,
        updated_at: str,
    ) -> bool: ...

    def increment_event_sequence(self, job_id: str) -> int: ...


class RunConfigurationRepository(Protocol):
    def insert(self, run_configuration: RunConfigurationRecord) -> None: ...

    def get_for_job(self, job_id: str) -> RunConfigurationRecord | None: ...


class StageRunRepository(Protocol):
    def insert_many(self, stage_runs: Sequence[StageRunRecord]) -> None: ...

    def get(self, stage_run_id: str) -> StageRunRecord | None: ...

    def list_for_job(self, job_id: str) -> tuple[StageRunRecord, ...]: ...


class RunEventRepository(Protocol):
    def insert(self, event: RunEventRecord) -> None: ...

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
    ) -> None: ...

    def list_for_job(self, job_id: str) -> tuple[RunEventDto, ...]: ...

    def count_for_job(self, job_id: str) -> int: ...


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
    ) -> None: ...

    def list(self) -> tuple[AuditRecordDto, ...]: ...

    def count(self) -> int: ...

    def list_for_job(self, job_id: str) -> tuple[AuditRecordDto, ...]: ...

    def count_for_job(self, job_id: str) -> int: ...


class CommandExecutionRepository(Protocol):
    def insert_queued(self, command: CommandExecutionRecord) -> None: ...

    def get(self, command_id: str) -> CommandExecutionDto | None: ...

    def get_active_for_job(self, job_id: str) -> CommandExecutionDto | None: ...


class IdempotencyRepository(Protocol):
    def get(self, operation: str, idempotency_key: str) -> IdempotencyRecordDto | None: ...

    def insert(self, record: IdempotencyRecord) -> None: ...


class ControlTowerUnitOfWork(Protocol):
    runner_profiles: RunnerProfileRepository
    pipeline_definitions: PipelineDefinitionRepository
    migration_jobs: MigrationJobRepository
    run_configurations: RunConfigurationRepository
    stage_runs: StageRunRepository
    run_events: RunEventRepository
    artifacts: ArtifactRepository
    audit_records: AuditRecordRepository
    command_executions: CommandExecutionRepository
    idempotency_records: IdempotencyRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, tb) -> bool | None: ...


UnitOfWork = ControlTowerUnitOfWork
