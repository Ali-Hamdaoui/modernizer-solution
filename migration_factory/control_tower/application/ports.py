"""Ports for Control Tower application services."""

from __future__ import annotations

from typing import Protocol, Self, Sequence

from migration_factory.control_tower.domain.entities import (
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


class PipelineDefinitionRepository(Protocol):
    def get_exact(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionRecord | None: ...


class MigrationJobRepository(Protocol):
    def insert_created(self, job: MigrationJobRecord) -> None: ...

    def get_active_job(self) -> MigrationJobRecord | None: ...


class RunConfigurationRepository(Protocol):
    def insert(self, run_configuration: RunConfigurationRecord) -> None: ...


class StageRunRepository(Protocol):
    def insert_many(self, stage_runs: Sequence[StageRunRecord]) -> None: ...


class RunEventRepository(Protocol):
    def insert(self, event: RunEventRecord) -> None: ...


class AuditRecordRepository(Protocol):
    def insert(self, audit_record: AuditRecord) -> None: ...


class ControlTowerUnitOfWork(Protocol):
    runner_profiles: RunnerProfileRepository
    pipeline_definitions: PipelineDefinitionRepository
    migration_jobs: MigrationJobRepository
    run_configurations: RunConfigurationRepository
    stage_runs: StageRunRepository
    run_events: RunEventRepository
    audit_records: AuditRecordRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, exc_type, exc, tb) -> bool | None: ...
