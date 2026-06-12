"""Immutable record types for Control Tower persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.domain.commands import CommandState


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
class ArtifactRecord:
    artifact_id: str
    job_id: str
    stage_run_id: str | None
    artifact_type: str
    registered_root_id: str
    relative_path: str
    normalized_relative_path: str
    content_type: str | None
    size_bytes: int
    checksum_algorithm: str
    checksum: str
    created_at: str
    created_by: str


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


@dataclass(frozen=True, slots=True)
class CommandExecutionRecord:
    command_id: str
    job_id: str
    operation: str
    status: CommandState
    created_at: str
    updated_at: str
    correlation_id: str | None
    causation_id: str | None
    command_manifest_artifact_id: str | None = None
    working_directory_root_id: str | None = None
    working_directory_relative_path: str | None = None
    worker_id: str | None = None
    launch_attempt: int | None = None
    process_control_id: str | None = None
    worker_pid: int | None = None
    process_started_at: str | None = None


@dataclass(frozen=True, slots=True)
class CommandManifestRecord:
    command_id: str
    manifest_json: str
    manifest_checksum: str
    run_configuration_artifact_id: str
    run_configuration_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    operation: str
    idempotency_key: str
    request_checksum: str
    resource_type: str
    resource_id: str
    original_status_code: int
    created_at: str


@dataclass(frozen=True, slots=True)
class StageChainLedgerRecord:
    ledger_id: str
    job_id: str
    stage_index: int
    stage_run_id: str
    chain_status: str
    input_source_kind: str
    input_checksum: str | None
    output_artifact_id: str | None
    output_checksum: str | None
    output_registered_at: str | None
    checksum_guard: str
    created_at: str
    created_by: str


@dataclass(frozen=True, slots=True)
class StageOutputRegistryRecord:
    output_id: str
    job_id: str
    stage_index: int
    stage_run_id: str
    artifact_id: str
    artifact_type: str
    output_kind: str
    checksum_algorithm: str
    checksum: str
    registered_at: str
    registered_by: str


@dataclass(frozen=True, slots=True)
class StageChainEventRecord:
    event_id: str
    job_id: str
    stage_index: int | None
    event_type: str
    prior_status: str | None
    new_status: str | None
    ledger_id: str | None
    output_id: str | None
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str
