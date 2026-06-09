"""Immutable DTOs returned by Control Tower application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CreatedMigrationJob:
    job_id: str
    version: int
    run_configuration_id: str
    stage_run_ids: tuple[str, ...]
    event_id: str
    audit_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
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
