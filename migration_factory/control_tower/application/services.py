"""Application services for Control Tower commands."""

from __future__ import annotations

from collections.abc import Callable

from migration_factory.control_tower.application.commands import (
    CreateMigrationJobCommand,
    RegisterPipelineDefinitionCommand,
    RegisterRunnerProfileCommand,
)
from migration_factory.control_tower.application.dto import MigrationJobDTO
from migration_factory.control_tower.application.errors import IncompatibleConfigurationError
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork


class ControlTowerCommandService:
    def __init__(self, unit_of_work_factory: Callable[[], ControlTowerUnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def register_runner_profile(self, command: RegisterRunnerProfileCommand) -> None:
        with self._unit_of_work_factory() as uow:
            uow.definitions.save_runner_profile(command.profile, actor=command.actor)

    def register_pipeline_definition(self, command: RegisterPipelineDefinitionCommand) -> None:
        with self._unit_of_work_factory() as uow:
            uow.definitions.save_pipeline_definition(command.pipeline, actor=command.actor)

    def create_migration_job(self, command: CreateMigrationJobCommand) -> MigrationJobDTO:
        with self._unit_of_work_factory() as uow:
            runner_profile = uow.definitions.get_runner_profile(
                command.runner_profile_id,
                command.runner_profile_version,
            )
            pipeline = uow.definitions.get_pipeline_definition(
                command.pipeline_id,
                command.pipeline_version,
            )
            _validate_jdk_compatibility(runner_profile, pipeline)
            return uow.jobs.create_job_with_configuration_stages_event_and_audit(
                actor=command.actor,
                legacy_source_ref=command.legacy_source_ref,
                output_root_ref=command.output_root_ref,
                runner_profile=runner_profile,
                pipeline=pipeline,
                target_proof_level=command.target_proof_level.value,
                enabled_gates=command.enabled_gates,
                policy_payload=command.policy.model_dump(mode="json"),
                correlation_id=command.correlation_id,
            )


def _validate_jdk_compatibility(runner_profile, pipeline) -> None:
    available_jdks = {jdk.jdk_id for jdk in runner_profile.jdk_inventory}
    missing = sorted(
        {stage.command_jdk for stage in pipeline.stages if stage.command_jdk not in available_jdks}
    )
    if missing:
        raise IncompatibleConfigurationError(
            "Pipeline requires JDK references absent from runner profile: "
            + ", ".join(missing)
        )
