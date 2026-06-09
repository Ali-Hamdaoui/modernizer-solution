"""Application command DTOs for Control Tower."""

from __future__ import annotations

from dataclasses import dataclass

from migration_factory.control_tower.domain.states import TargetProofLevel
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
