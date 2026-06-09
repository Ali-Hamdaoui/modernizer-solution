"""Application services for immutable Control Tower configuration registration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.commands import (
    RegisterPipelineDefinitionCommand,
    RegisterRunnerProfileCommand,
    TransitionJobStateCommand,
)
from migration_factory.control_tower.application.dto import (
    MigrationJobDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
)
from migration_factory.control_tower.application.ports import UnitOfWork
from migration_factory.control_tower.domain.checksums import canonical_json, sha256_checksum, utc_now
from migration_factory.control_tower.domain.errors import (
    ExpectedVersionRequiredError,
    NotFoundError,
    RegistrationConflictError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.domain.transitions import (
    active_slot_for,
    validate_job_state_transition,
)
from migration_factory.control_tower.schemas import PipelineDefinition, RunnerProfile


UnitOfWorkFactory = Callable[[], UnitOfWork]


class ControlTowerRegistrationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def register_runner_profile(self, command: RegisterRunnerProfileCommand) -> RunnerProfileDto:
        profile = _validate_runner_profile(command.profile)
        payload = _schema_payload(profile)
        payload_json = canonical_json(payload)
        checksum = sha256_checksum(payload)

        with self._unit_of_work_factory() as uow:
            existing_checksum = uow.runner_profiles.find_checksum(
                profile.runner_profile_id,
                profile.runner_profile_version,
            )
            if existing_checksum is not None:
                if existing_checksum != checksum:
                    raise RegistrationConflictError(
                        "runner_profile",
                        profile.runner_profile_id,
                        profile.runner_profile_version,
                    )
                existing = uow.runner_profiles.get(
                    profile.runner_profile_id,
                    profile.runner_profile_version,
                )
                if existing is None:
                    raise NotFoundError("Runner profile checksum exists but row could not be loaded")
                return existing

            created_at = utc_now()
            dto = RunnerProfileDto(
                runner_profile_id=profile.runner_profile_id,
                runner_profile_version=profile.runner_profile_version,
                display_name=profile.display_name,
                schema_version=profile.schema_version,
                payload=payload,
                payload_json=payload_json,
                payload_checksum=checksum,
                created_at=created_at,
                created_by=command.actor_id,
            )
            uow.runner_profiles.insert(dto)
            uow.audit_records.append_global_audit(
                audit_id=str(uuid4()),
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                action="runner_profile_registered",
                payload_json=_registration_audit_payload_json(
                    action="runner_profile_registered",
                    registration_type="runner_profile",
                    entity_id=profile.runner_profile_id,
                    version=profile.runner_profile_version,
                    checksum=checksum,
                    schema_version=profile.schema_version,
                    display_name=profile.display_name,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.causation_id,
                ),
                created_at=created_at,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )
            return dto

    def register_pipeline_definition(
        self,
        command: RegisterPipelineDefinitionCommand,
    ) -> PipelineDefinitionDto:
        pipeline = _validate_pipeline_definition(command.pipeline)
        payload = _schema_payload(pipeline)
        payload_json = canonical_json(payload)
        checksum = sha256_checksum(payload)

        with self._unit_of_work_factory() as uow:
            existing_checksum = uow.pipeline_definitions.find_checksum(
                pipeline.pipeline_id,
                pipeline.pipeline_version,
            )
            if existing_checksum is not None:
                if existing_checksum != checksum:
                    raise RegistrationConflictError(
                        "pipeline_definition",
                        pipeline.pipeline_id,
                        pipeline.pipeline_version,
                    )
                existing = uow.pipeline_definitions.get(
                    pipeline.pipeline_id,
                    pipeline.pipeline_version,
                )
                if existing is None:
                    raise NotFoundError("Pipeline checksum exists but row could not be loaded")
                return existing

            created_at = utc_now()
            dto = PipelineDefinitionDto(
                pipeline_id=pipeline.pipeline_id,
                pipeline_version=pipeline.pipeline_version,
                display_name=pipeline.display_name,
                schema_version=pipeline.schema_version,
                graph_version=pipeline.graph_version,
                graph_state_schema_version=pipeline.graph_state_schema_version,
                payload=payload,
                payload_json=payload_json,
                payload_checksum=checksum,
                created_at=created_at,
                created_by=command.actor_id,
            )
            uow.pipeline_definitions.insert(dto)
            uow.audit_records.append_global_audit(
                audit_id=str(uuid4()),
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                action="pipeline_definition_registered",
                payload_json=_registration_audit_payload_json(
                    action="pipeline_definition_registered",
                    registration_type="pipeline_definition",
                    entity_id=pipeline.pipeline_id,
                    version=pipeline.pipeline_version,
                    checksum=checksum,
                    schema_version=pipeline.schema_version,
                    display_name=pipeline.display_name,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    causation_id=command.causation_id,
                ),
                created_at=created_at,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )
            return dto

    def get_runner_profile(
        self,
        runner_profile_id: str,
        runner_profile_version: str,
    ) -> RunnerProfileDto:
        with self._unit_of_work_factory() as uow:
            profile = uow.runner_profiles.get(runner_profile_id, runner_profile_version)
            if profile is None:
                raise NotFoundError(
                    f"Runner profile {runner_profile_id!r} version {runner_profile_version!r} not found"
                )
            return profile

    def list_runner_profiles(self) -> tuple[RunnerProfileDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.runner_profiles.list()

    def get_pipeline_definition(self, pipeline_id: str, pipeline_version: str) -> PipelineDefinitionDto:
        with self._unit_of_work_factory() as uow:
            pipeline = uow.pipeline_definitions.get(pipeline_id, pipeline_version)
            if pipeline is None:
                raise NotFoundError(
                    f"Pipeline definition {pipeline_id!r} version {pipeline_version!r} not found"
                )
            return pipeline

    def list_pipeline_definitions(self) -> tuple[PipelineDefinitionDto, ...]:
        with self._unit_of_work_factory() as uow:
            return uow.pipeline_definitions.list()

    def transition_job_state(self, command: TransitionJobStateCommand) -> MigrationJobDto:
        if command.expected_version is None:
            raise ExpectedVersionRequiredError()

        expected_version = command.expected_version
        target_state = _coerce_job_state(command.target_state)

        with self._unit_of_work_factory() as uow:
            job = uow.migration_jobs.get(command.job_id)
            if job is None:
                raise NotFoundError(f"Migration job {command.job_id!r} not found")
            if job.version != expected_version:
                raise StaleVersionError(command.job_id, expected_version, job.version)

            validate_job_state_transition(job.status, target_state)

            updated_at = utc_now()
            target_active_slot = active_slot_for(target_state)
            updated = uow.migration_jobs.transition_state(
                command.job_id,
                expected_version,
                target_state,
                target_active_slot,
                updated_at,
            )
            if not updated:
                current = uow.migration_jobs.get(command.job_id)
                if current is None:
                    raise NotFoundError(f"Migration job {command.job_id!r} not found")
                raise StaleVersionError(command.job_id, expected_version, current.version)

            new_version = expected_version + 1
            sequence = uow.migration_jobs.increment_event_sequence(command.job_id)
            event_payload = _job_state_changed_payload(
                job_id=command.job_id,
                prior_state=job.status,
                new_state=target_state,
                prior_version=expected_version,
                new_version=new_version,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                reason=command.reason,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )
            event_payload_json = canonical_json(event_payload)
            uow.run_events.append_job_state_changed_event(
                event_id=str(uuid4()),
                job_id=command.job_id,
                sequence=sequence,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                payload_json=event_payload_json,
                payload_checksum=sha256_checksum(event_payload),
                created_at=updated_at,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )

            audit_payload = dict(event_payload)
            audit_payload["event_sequence"] = sequence
            uow.audit_records.append_job_state_changed_audit(
                audit_id=str(uuid4()),
                job_id=command.job_id,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                prior_state=job.status,
                new_state=target_state,
                job_version=new_version,
                payload_json=canonical_json(audit_payload),
                created_at=updated_at,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )

            updated_job = uow.migration_jobs.get(command.job_id)
            if updated_job is None:
                raise NotFoundError(f"Migration job {command.job_id!r} not found after transition")
            return updated_job


def _validate_runner_profile(profile: RunnerProfile | dict[str, Any]) -> RunnerProfile:
    if isinstance(profile, RunnerProfile):
        return profile
    return RunnerProfile.model_validate(profile)


def _validate_pipeline_definition(
    pipeline: PipelineDefinition | dict[str, Any],
) -> PipelineDefinition:
    if isinstance(pipeline, PipelineDefinition):
        return pipeline
    return PipelineDefinition.model_validate(pipeline)


def _coerce_job_state(state: JobState | str) -> JobState:
    return state if isinstance(state, JobState) else JobState(state)


def _schema_payload(model: RunnerProfile | PipelineDefinition) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _job_state_changed_payload(
    *,
    job_id: str,
    prior_state: JobState,
    new_state: JobState,
    prior_version: int,
    new_version: int,
    actor_type: str,
    actor_id: str,
    reason: str,
    correlation_id: str | None,
    causation_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "actor_id": actor_id,
        "actor_type": actor_type,
        "job_id": job_id,
        "new_state": new_state.value,
        "new_version": new_version,
        "prior_state": prior_state.value,
        "prior_version": prior_version,
        "reason": reason,
    }
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    if causation_id is not None:
        payload["causation_id"] = causation_id
    return payload


def _registration_audit_payload_json(
    *,
    action: str,
    registration_type: str,
    entity_id: str,
    version: str,
    checksum: str,
    schema_version: str,
    display_name: str,
    actor_type: str,
    actor_id: str,
    correlation_id: str | None,
    causation_id: str | None,
) -> str:
    payload: dict[str, Any] = {
        "action": action,
        "actor_id": actor_id,
        "actor_type": actor_type,
        "checksum": checksum,
        "display_name": display_name,
        "id": entity_id,
        "registration_type": registration_type,
        "schema_version": schema_version,
        "version": version,
    }
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    if causation_id is not None:
        payload["causation_id"] = causation_id
    return canonical_json(payload)
