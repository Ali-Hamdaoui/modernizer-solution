"""Immutable record types for Control Tower persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState, TargetProofLevel


@dataclass(frozen=True, slots=True)
class RunnerProfileRecord:
    runner_profile_id: str
    runner_profile_version: str
    display_name: str
    schema_version: str
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str
    payload: Any


@dataclass(frozen=True, slots=True)
class PipelineDefinitionRecord:
    pipeline_id: str
    pipeline_version: str
    display_name: str
    schema_version: str
    graph_version: str
    graph_state_schema_version: str
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str
    payload: Any


@dataclass(frozen=True, slots=True)
class MigrationJobRecord:
    job_id: str
    version: int
    status: JobState
    active_slot: int | None
    last_event_sequence: int
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: TargetProofLevel
    achieved_proof_level: TargetProofLevel | None
    legacy_source_ref: str
    output_root_ref: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    created_by: str


@dataclass(frozen=True, slots=True)
class RunConfigurationRecord:
    run_configuration_id: str
    job_id: str
    schema_version: str
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: TargetProofLevel
    enabled_gates_json: str
    policy_json: str
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StageRunRecord:
    stage_run_id: str
    job_id: str
    stage_index: int
    stage_id: str
    status: str
    input_source_json: str
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    event_id: str
    job_id: str
    sequence: int
    event_type: str
    actor_type: str
    actor_id: str
    correlation_id: str | None
    causation_id: str | None
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditRecord:
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
    payload_json: str
    created_at: str
