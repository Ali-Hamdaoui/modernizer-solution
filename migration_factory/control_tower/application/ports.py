"""Application ports implemented by infrastructure adapters."""

from __future__ import annotations

from typing import Protocol

from migration_factory.control_tower.application.dto import (
    AuditRecordDTO,
    MigrationJobDTO,
    RunConfigurationDTO,
    RunEventDTO,
    StageRunDTO,
)
from migration_factory.control_tower.schemas.pipeline_definition import PipelineDefinition
from migration_factory.control_tower.schemas.runner_profile import RunnerProfile


class ControlTowerUnitOfWork(Protocol):
    definitions: "DefinitionRepository"
    jobs: "MigrationJobRepository"

    def __enter__(self) -> "ControlTowerUnitOfWork": ...
    def __exit__(self, exc_type, exc, traceback) -> None: ...


class DefinitionRepository(Protocol):
    def save_runner_profile(self, profile: RunnerProfile, *, actor: str) -> None: ...
    def save_pipeline_definition(self, pipeline: PipelineDefinition, *, actor: str) -> None: ...
    def get_runner_profile(self, profile_id: str, version: str) -> RunnerProfile: ...
    def get_pipeline_definition(self, pipeline_id: str, version: str) -> PipelineDefinition: ...


class MigrationJobRepository(Protocol):
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
    ) -> MigrationJobDTO: ...

    def get_job(self, job_id: str) -> MigrationJobDTO: ...
    def get_run_configuration(self, job_id: str) -> RunConfigurationDTO: ...
    def list_stages(self, job_id: str) -> list[StageRunDTO]: ...
    def list_events(self, job_id: str) -> list[RunEventDTO]: ...
    def list_audit_records(self, job_id: str) -> list[AuditRecordDTO]: ...
