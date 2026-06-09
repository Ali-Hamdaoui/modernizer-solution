"""Run configuration schemas for Control Tower."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator

from .common import NonEmptyString, StrictModel, require_non_empty_string


TargetProofLevel = Literal[
    "ANALYZED",
    "PLANNED",
    "TRANSFORMED",
    "BUILD_TEST_VERIFIED",
    "RUNTIME_VERIFIED",
    "ENDPOINT_VERIFIED",
]


class RunPolicy(StrictModel):
    continue_after_warning: bool
    enable_runtime_gate: bool
    enable_endpoint_gate: bool
    allow_ai_assistance: bool
    allow_ai_repair: bool


class RunConfiguration(StrictModel):
    schema_version: NonEmptyString
    run_configuration_id: NonEmptyString
    job_id: NonEmptyString
    runner_profile_id: NonEmptyString
    runner_profile_version: NonEmptyString
    pipeline_id: NonEmptyString
    pipeline_version: NonEmptyString
    target_proof_level: TargetProofLevel
    enabled_gates: tuple[str, ...]
    policy: RunPolicy

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
