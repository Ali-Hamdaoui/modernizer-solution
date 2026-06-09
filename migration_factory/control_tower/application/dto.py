"""Immutable read DTOs returned by Control Tower application queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState


@dataclass(frozen=True)
class RunnerProfileDto:
    runner_profile_id: str
    runner_profile_version: str
    display_name: str
    schema_version: str
    payload: dict[str, Any]
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str


@dataclass(frozen=True)
class PipelineDefinitionDto:
    pipeline_id: str
    pipeline_version: str
    display_name: str
    schema_version: str
    graph_version: str
    graph_state_schema_version: str
    payload: dict[str, Any]
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str


@dataclass(frozen=True)
class MigrationJobDto:
    job_id: str
    version: int
    status: JobState
    active_slot: int | None
    last_event_sequence: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class RunEventDto:
    event_id: str
    job_id: str
    sequence: int
    event_type: str
    actor_type: str
    actor_id: str
    correlation_id: str | None
    causation_id: str | None
    payload: dict[str, Any]
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True)
class AuditRecordDto:
    audit_id: str
    job_id: str | None
    actor_type: str
    actor_id: str
    action: str
    prior_state: str | None
    new_state: str | None
    job_version: int | None
    correlation_id: str | None
    causation_id: str | None
    payload: dict[str, Any]
    payload_json: str
    created_at: str
