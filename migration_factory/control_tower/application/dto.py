"""Application DTOs for Control Tower operations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreatedMigrationJob:
    job_id: str
    version: int
    run_configuration_id: str
    stage_run_ids: tuple[str, ...]
    event_id: str
    audit_id: str
    sequence: int
