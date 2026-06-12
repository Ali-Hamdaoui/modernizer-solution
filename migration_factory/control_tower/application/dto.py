"""Immutable DTOs returned by Control Tower application services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.domain.commands import CommandState


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


@dataclass(frozen=True, slots=True)
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


@dataclass(frozen=True, slots=True)
class RunConfigurationDto:
    run_configuration_id: str
    job_id: str
    schema_version: str
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: str
    enabled_gates: tuple[str, ...]
    policy: dict[str, Any]
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StageRunDto:
    stage_run_id: str
    job_id: str
    stage_index: int
    stage_id: str
    status: str
    input_source: dict[str, Any]
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class ArtifactDto:
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
class CommandExecutionDto:
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
class WorkerLaunchResult:
    command_id: str
    job_id: str
    process_control_id: str
    worker_pid: int
    process_started_at: str
    worker_id: str
    launch_attempt: int


@dataclass(frozen=True, slots=True)
class CommandOutputWindowDto:
    """Bounded window of command output bytes."""

    command_id: str
    job_id: str
    stream: str
    requested_offset: int
    start_offset: int
    next_offset: int
    data: str
    encoding: str
    replacement_characters_used: int
    truncated: bool
    terminal: bool
    max_bytes: int


@dataclass(frozen=True, slots=True)
class IdempotencyRecordDto:
    operation: str
    idempotency_key: str
    request_checksum: str
    resource_type: str
    resource_id: str
    original_status_code: int
    created_at: str


@dataclass(frozen=True, slots=True)
class StageChainEntryDto:
    """Redacted, ordered stage chain projection from the V1 ledger."""

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
    created_at: str


@dataclass(frozen=True, slots=True)
class JobProjectionDto:
    job: MigrationJobDto
    active_command: CommandExecutionDto | None
    etag: str
