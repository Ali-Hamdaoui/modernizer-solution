"""Application command DTOs for Control Tower."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.artifacts import ArtifactHashResult
from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.schemas import PipelineDefinition, RunnerProfile
from migration_factory.control_tower.schemas.run_configuration import RunPolicy


@dataclass(frozen=True, slots=True)
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
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RegisterRunnerProfileCommand:
    profile: RunnerProfile | dict[str, Any]
    actor_type: str
    actor_id: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RegisterPipelineDefinitionCommand:
    pipeline: PipelineDefinition | dict[str, Any]
    actor_type: str
    actor_id: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class RegisterArtifactCommand:
    job_id: str
    artifact: ArtifactHashResult
    artifact_type: str
    actor_type: str
    actor_id: str
    stage_run_id: str | None = None
    content_type: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class TransitionJobStateCommand:
    job_id: str
    expected_version: int | None
    target_state: JobState
    actor_type: str
    actor_id: str
    reason: str
    correlation_id: str | None = None
    causation_id: str | None = None
