"""Read DTOs returned by Control Tower application services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationJobDTO:
    job_id: str
    version: int
    state: str
    last_event_sequence: int
    runner_profile_id: str
    pipeline_id: str
    target_proof_level: str


@dataclass(frozen=True)
class StageRunDTO:
    stage_run_id: str
    job_id: str
    stage_name: str
    state: str
    ordinal: int


@dataclass(frozen=True)
class RunEventDTO:
    event_id: str
    job_id: str
    sequence: int
    event_type: str
    payload_json: str


@dataclass(frozen=True)
class AuditRecordDTO:
    audit_record_id: str
    job_id: str | None
    action: str
    actor: str
    payload_json: str


@dataclass(frozen=True)
class RunConfigurationDTO:
    configuration_id: str
    job_id: str
    target_proof_level: str
    config_json: str
    config_checksum_sha256: str
