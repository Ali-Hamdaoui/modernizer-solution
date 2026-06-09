"""Application command DTOs for Control Tower."""

from __future__ import annotations

from dataclasses import dataclass

from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.schemas.pipeline_definition import PipelineDefinition
from migration_factory.control_tower.schemas.run_configuration import RunPolicy
from migration_factory.control_tower.schemas.runner_profile import RunnerProfile


@dataclass(frozen=True)
class RegisterRunnerProfileCommand:
    actor: str
    profile: RunnerProfile


@dataclass(frozen=True)
class RegisterPipelineDefinitionCommand:
    actor: str
    pipeline: PipelineDefinition


@dataclass(frozen=True)
class CreateMigrationJobCommand:
    actor: str
    legacy_source_ref: str
    output_root_ref: str
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: TargetProofLevel
    enabled_gates: tuple[str, ...]
    policy: RunPolicy
    correlation_id: str
