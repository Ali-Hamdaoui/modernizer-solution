"""Run configuration schemas for Control Tower."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from migration_factory.control_tower.domain.states import TargetProofLevel

from .common import NonEmptyString, StrictModel, require_non_empty_string


class StageContinuationPolicy(str, Enum):
    AUTO_ON_GREEN = "auto_on_green"
    MANUAL = "manual"
    MANUAL_ON_WARNING_OR_FAILURE = "manual_on_warning_or_failure"


class RunPolicy(StrictModel):
    continue_after_warning: bool = False
    enable_runtime_gate: bool = False
    enable_endpoint_gate: bool = False
    enable_build_repair: bool = True
    enable_llm_repair_proposal: bool = True
    max_repair_attempts: int = 3
    repair_scope: str = "build_only"
    stage_continuation_policy: StageContinuationPolicy = StageContinuationPolicy.AUTO_ON_GREEN

    @field_validator("stage_continuation_policy", mode="before")
    @classmethod
    def _coerce_stage_continuation_policy(cls, value):
        if isinstance(value, StageContinuationPolicy):
            return value
        return StageContinuationPolicy(value)

    @field_validator("repair_scope", mode="after")
    @classmethod
    def _validate_repair_scope(cls, value: str) -> str:
        return require_non_empty_string(value, "repair_scope")

    @classmethod
    def f15_manual(cls) -> "RunPolicy":
        """Return the default policy for new F15 governed-stage jobs."""
        return cls(stage_continuation_policy=StageContinuationPolicy.MANUAL)


class RunConfiguration(StrictModel):
    schema_version: NonEmptyString
    run_configuration_id: NonEmptyString
    job_id: NonEmptyString
    runner_profile_id: NonEmptyString
    runner_profile_version: NonEmptyString
    pipeline_id: NonEmptyString
    pipeline_version: NonEmptyString
    target_proof_level: TargetProofLevel
    enabled_gates: tuple[str, ...] = Field(default_factory=tuple)
    policy: RunPolicy

    @field_validator(
        "target_proof_level",
        mode="before",
    )
    @classmethod
    def _coerce_target_proof_level(cls, value):
        if isinstance(value, TargetProofLevel):
            return value
        return TargetProofLevel(value)

    @field_validator(
        "schema_version",
        "run_configuration_id",
        "job_id",
        "runner_profile_id",
        "runner_profile_version",
        "pipeline_id",
        "pipeline_version",
        mode="after",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @field_validator("enabled_gates", mode="after")
    @classmethod
    def _validate_enabled_gates(cls, value: tuple[str, ...], info):
        return tuple(require_non_empty_string(item, info.field_name) for item in value)
