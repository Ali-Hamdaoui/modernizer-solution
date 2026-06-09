"""Application ports for Control Tower registration persistence."""

from __future__ import annotations

from typing import Protocol

from migration_factory.control_tower.application.dto import (
    AuditRecordDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
)


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

    def list(self) -> tuple[AuditRecordDto, ...]:
        ...

    def count(self) -> int:
        ...


class UnitOfWork(Protocol):
    runner_profiles: RunnerProfileRepository
    pipeline_definitions: PipelineDefinitionRepository
    audit_records: AuditRecordRepository

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        ...
