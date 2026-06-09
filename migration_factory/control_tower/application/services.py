"""Application services for Control Tower operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.commands import (
    CreateMigrationJobCommand,
    RegisterPipelineDefinitionCommand,
    RegisterRunnerProfileCommand,
    TransitionJobStateCommand,
)
from migration_factory.control_tower.application.dto import (
    CreatedMigrationJob,
    MigrationJobDto,
    PipelineDefinitionDto,
    RunnerProfileDto,
)
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork
from migration_factory.control_tower.domain.checksums import canonical_json_text, sha256_canonical_json, utc_now_text
from migration_factory.control_tower.domain.entities import (
    AuditRecord,
    MigrationJobRecord,
    RunConfigurationRecord,
    RunEventRecord,
    StageRunRecord,
)
from migration_factory.control_tower.domain.errors import (
    CompatibilityError,
    ConcurrencyConflictError,
    ExpectedVersionRequiredError,
    NotFoundError,
    RegistrationConflictError,
    StaleVersionError,
    StorageIntegrityError,
)
from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.domain.transitions import active_slot_for, validate_job_state_transition
from migration_factory.control_tower.schemas import PipelineDefinition, RunnerProfile
from migration_factory.control_tower.schemas.run_configuration import RunConfiguration


UnitOfWorkFactory = Callable[[], ControlTowerUnitOfWork]


class CreateMigrationJobService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, command: CreateMigrationJobCommand) -> CreatedMigrationJob:
        with self._unit_of_work_factory() as uow:
            runner = uow.runner_profiles.get_exact(
                command.runner_profile_id,
                command.runner_profile_version,
            )
            if runner is None:
                raise NotFoundError(
                    "runner profile",
                    f"{command.runner_profile_id}/{command.runner_profile_version}",
                )

            pipeline = uow.pipeline_definitions.get_exact(
                command.pipeline_id,
                command.pipeline_version,
            )
            if pipeline is None:
                raise NotFoundError(
                    "pipeline definition",
                    f"{command.pipeline_id}/{command.pipeline_version}",
                )

            self._validate_runner_pipeline_compatibility(runner.payload, pipeline.payload)

            job_id = f"job-{uuid4().hex}"
            now = utc_now_text()
            run_configuration_id = f"run-config-{job_id}"
            stage_run_ids: list[str] = []

            run_configuration_payload = RunConfiguration(
                schema_version="1.0.0",
                run_configuration_id=run_configuration_id,
                job_id=job_id,
                runner_profile_id=runner.runner_profile_id,
                runner_profile_version=runner.runner_profile_version,
                pipeline_id=pipeline.pipeline_id,
                pipeline_version=pipeline.pipeline_version,
                target_proof_level=command.target_proof_level,
                enabled_gates=command.enabled_gates,
                policy=command.policy,
            )
            run_configuration_payload_json = canonical_json_text(run_configuration_payload)
            run_configuration_checksum = sha256_canonical_json(run_configuration_payload)

            job_record = MigrationJobRecord(
                job_id=job_id,
                version=1,
                status=JobState.CREATED,
                active_slot=1,
                last_event_sequence=1,
                runner_profile_id=runner.runner_profile_id,
                runner_profile_version=runner.runner_profile_version,
                pipeline_id=pipeline.pipeline_id,
                pipeline_version=pipeline.pipeline_version,
                target_proof_level=command.target_proof_level,
                achieved_proof_level=None,
                legacy_source_ref=command.legacy_source_ref,
                output_root_ref=command.output_root_ref,
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
                created_by=command.actor,
            )

            run_configuration_record = RunConfigurationRecord(
                run_configuration_id=run_configuration_id,
                job_id=job_id,
                schema_version=run_configuration_payload.schema_version,
                runner_profile_id=run_configuration_payload.runner_profile_id,
                runner_profile_version=run_configuration_payload.runner_profile_version,
                pipeline_id=run_configuration_payload.pipeline_id,
                pipeline_version=run_configuration_payload.pipeline_version,
                target_proof_level=run_configuration_payload.target_proof_level,
                enabled_gates_json=canonical_json_text(run_configuration_payload.enabled_gates),
                policy_json=canonical_json_text(run_configuration_payload.policy),
                payload_json=run_configuration_payload_json,
                payload_checksum=run_configuration_checksum,
                created_at=now,
            )

            try:
                uow.migration_jobs.insert_created(job_record)
            except StorageIntegrityError as exc:
                active_job = uow.migration_jobs.get_active_job()
                if active_job is not None:
                    raise ConcurrencyConflictError(
                        "Another active migration job already occupies the single active slot."
                    ) from exc
                raise

            uow.run_configurations.insert(run_configuration_record)

            stage_runs = []
            for stage in pipeline.payload.stages:
                stage_run_id = f"stage-{job_id}-{stage.stage_index:04d}"
                stage_run_ids.append(stage_run_id)
                stage_runs.append(
                    StageRunRecord(
                        stage_run_id=stage_run_id,
                        job_id=job_id,
                        stage_index=stage.stage_index,
                        stage_id=stage.stage_id,
                        status="PENDING",
                        input_source_json=canonical_json_text(stage.input_source),
                        created_at=now,
                        started_at=None,
                        finished_at=None,
                    )
                )

            if stage_runs:
                uow.stage_runs.insert_many(stage_runs)

            event_payload = {
                "job_id": job_id,
                "runner_profile_id": runner.runner_profile_id,
                "runner_profile_version": runner.runner_profile_version,
                "pipeline_id": pipeline.pipeline_id,
                "pipeline_version": pipeline.pipeline_version,
                "legacy_source_ref": command.legacy_source_ref,
                "output_root_ref": command.output_root_ref,
                "target_proof_level": command.target_proof_level,
                "enabled_gates": command.enabled_gates,
                "policy": command.policy,
            }
            event_record = RunEventRecord(
                event_id=f"event-{job_id}-0001",
                job_id=job_id,
                sequence=1,
                event_type="job_created",
                actor_type="user",
                actor_id=command.actor,
                correlation_id=command.correlation_id,
                causation_id=None,
                payload_json=canonical_json_text(event_payload),
                payload_checksum=sha256_canonical_json(event_payload),
                created_at=now,
            )
            uow.run_events.insert(event_record)

            audit_payload = {
                "job_id": job_id,
                "run_configuration_id": run_configuration_id,
                "stage_run_ids": stage_run_ids,
                "event_id": event_record.event_id,
            }
            audit_record = AuditRecord(
                audit_id=f"audit-{job_id}-0001",
                job_id=job_id,
                actor_type="user",
                actor_id=command.actor,
                action="job_created",
                prior_state=None,
                new_state=JobState.CREATED.value,
                job_version=1,
                correlation_id=command.correlation_id,
                causation_id=event_record.event_id,
                payload_json=canonical_json_text(audit_payload),
                created_at=now,
            )
            uow.audit_records.insert(audit_record)

            return CreatedMigrationJob(
                job_id=job_id,
                version=1,
                run_configuration_id=run_configuration_id,
                stage_run_ids=tuple(stage_run_ids),
                event_id=event_record.event_id,
                audit_id=audit_record.audit_id,
                sequence=1,
            )

    def _validate_runner_pipeline_compatibility(self, runner_payload, pipeline_payload) -> None:
        runner_jdk_ids = {jdk.jdk_id for jdk in runner_payload.jdks}
        missing_jdks = [
            stage.command_jdk
            for stage in pipeline_payload.stages
            if stage.command_jdk not in runner_jdk_ids
        ]
        if missing_jdks:
            unique_missing = ", ".join(sorted(set(missing_jdks)))
            raise CompatibilityError(
                "Pipeline references JDKs not available in the selected runner profile: "
                f"{unique_missing}"
            )


class ControlTowerRegistrationService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def register_runner_profile(self, command: RegisterRunnerProfileCommand) -> RunnerProfileDto:
        profile = _validate_runner_profile(command.profile)
        payload = _schema_payload(profile)
        payload_json = canonical_json_text(payload)
        checksum = sha256_canonical_json(payload)

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

            created_at = utc_now_text()
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
        payload_json = canonical_json_text(payload)
        checksum = sha256_canonical_json(payload)

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

            created_at = utc_now_text()
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
                raise NotFoundError("migration job", command.job_id)
            if job.version != expected_version:
                raise StaleVersionError(command.job_id, expected_version, job.version)

            validate_job_state_transition(job.status, target_state)

            updated_at = utc_now_text()
            updated = uow.migration_jobs.transition_state(
                command.job_id,
                expected_version,
                target_state,
                active_slot_for(target_state),
                updated_at,
            )
            if not updated:
                current = uow.migration_jobs.get(command.job_id)
                if current is None:
                    raise NotFoundError("migration job", command.job_id)
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
            event_payload_json = canonical_json_text(event_payload)
            event_id = str(uuid4())
            uow.run_events.append_job_state_changed_event(
                event_id=event_id,
                job_id=command.job_id,
                sequence=sequence,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                payload_json=event_payload_json,
                payload_checksum=sha256_canonical_json(event_payload),
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
                payload_json=canonical_json_text(audit_payload),
                created_at=updated_at,
                correlation_id=command.correlation_id,
                causation_id=command.causation_id,
            )

            updated_job = uow.migration_jobs.get(command.job_id)
            if updated_job is None:
                raise NotFoundError("migration job", command.job_id)
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
    return canonical_json_text(payload)
