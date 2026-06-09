"""Command DTOs for Control Tower registration operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.schemas import PipelineDefinition, RunnerProfile


@dataclass(frozen=True)
class RegisterRunnerProfileCommand:
    profile: RunnerProfile | dict[str, Any]
    actor_type: str
    actor_id: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class RegisterPipelineDefinitionCommand:
    pipeline: PipelineDefinition | dict[str, Any]
    actor_type: str
    actor_id: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class TransitionJobStateCommand:
    job_id: str
    expected_version: int | None
    target_state: JobState
    actor_type: str
    actor_id: str
    reason: str
    correlation_id: str | None = None
    causation_id: str | None = None
