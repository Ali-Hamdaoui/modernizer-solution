"""Application ports for Control Tower registration persistence."""

from __future__ import annotations

from typing import Protocol

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    MigrationJobDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
    RunEventDto,
)
from migration_factory.control_tower.domain.states import JobState


class RunnerProfileRepository(Protocol):
    def get(self, runner_profile_id: str, runner_profile_version: str) -> RunnerProfileDto | None:
        ...

    def list(self) -> tuple[RunnerProfileDto, ...]:
        ...

    def insert(self, profile: RunnerProfileDto) -> None:
        ...

    def find_checksum(self, runner_profile_id: str, runner_profile_version: str) -> str | None:
        ...


class PipelineDefinitionRepository(Protocol):
    def get(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionDto | None:
        ...

    def list(self) -> tuple[PipelineDefinitionDto, ...]:
        ...

    def insert(self, pipeline: PipelineDefinitionDto) -> None:
        ...

    def find_checksum(self, pipeline_id: str, pipeline_version: str) -> str | None:
        ...


class MigrationJobRepository(Protocol):
    def get(self, job_id: str) -> MigrationJobDto | None:
        ...

    def transition_state(
        self,
        job_id: str,
        expected_version: int,
        target_state: JobState,
        active_slot: int | None,
        updated_at: str,
    ) -> bool:
        ...

    def increment_event_sequence(self, job_id: str) -> int:
        ...


class RunEventRepository(Protocol):
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
        ...

    def list_for_job(self, job_id: str) -> tuple[RunEventDto, ...]:
        ...

    def count_for_job(self, job_id: str) -> int:
        ...


class AuditRecordRepository(Protocol):
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
        ...

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
        ...

    def list(self) -> tuple[AuditRecordDto, ...]:
        ...

    def count(self) -> int:
        ...

    def list_for_job(self, job_id: str) -> tuple[AuditRecordDto, ...]:
        ...

    def count_for_job(self, job_id: str) -> int:
        ...


class UnitOfWork(Protocol):
    runner_profiles: RunnerProfileRepository
    pipeline_definitions: PipelineDefinitionRepository
    migration_jobs: MigrationJobRepository
    run_events: RunEventRepository
    audit_records: AuditRecordRepository

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        ...
