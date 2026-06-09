"""Pipeline definition schemas for Control Tower configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator

from .common import NonEmptyString, StrictModel, require_non_empty_string


StageInputSourceKind = Literal["legacy_source", "previous_stage"]


class StageInputSource(StrictModel):
    kind: StageInputSourceKind
    previous_stage_index: int | None = None


class PipelineStageDefinition(StrictModel):
    stage_index: int
    stage_id: NonEmptyString
    display_name: NonEmptyString
    input_source: StageInputSource
    command_jdk: NonEmptyString
    continuation_policy: str | None = None

    @field_validator("stage_id", "display_name", "command_jdk", mode="after")
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @field_validator("continuation_policy", mode="after")
    @classmethod
    def _validate_optional_string(cls, value: str | None, info):
        if value is None:
            return value
        return require_non_empty_string(value, info.field_name)


class PipelineDefinition(StrictModel):
    schema_version: NonEmptyString
    pipeline_id: NonEmptyString
    pipeline_version: NonEmptyString
    display_name: NonEmptyString
    graph_version: NonEmptyString
    graph_state_schema_version: NonEmptyString
    stages: tuple[PipelineStageDefinition, ...]

    @field_validator(
        "schema_version",
        "pipeline_id",
        "pipeline_version",
        "display_name",
        "graph_version",
        "graph_state_schema_version",
        mode="after",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @model_validator(mode="after")
    def _validate_stages(self) -> "PipelineDefinition":
        if not self.stages:
            raise ValueError("stages must not be empty")

        expected_indexes = list(range(1, len(self.stages) + 1))
        stage_indexes = [stage.stage_index for stage in self.stages]
        if stage_indexes != expected_indexes:
            raise ValueError("stage indexes must be contiguous starting at 1")

        first_stage = self.stages[0]
        if first_stage.input_source.kind != "legacy_source":
            raise ValueError('stage 1 must use input_source.kind == "legacy_source"')
        if first_stage.input_source.previous_stage_index is not None:
            raise ValueError("legacy_source stages must not define previous_stage_index")

        for stage in self.stages[1:]:
            if stage.input_source.kind != "previous_stage":
                raise ValueError("stages after stage 1 must use previous_stage input sources")
            if (
                stage.input_source.previous_stage_index is not None
                and stage.input_source.previous_stage_index != stage.stage_index - 1
            ):
                raise ValueError("previous_stage_index must point to the immediately previous stage")

        return self
