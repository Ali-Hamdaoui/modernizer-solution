"""Application services for Control Tower operations."""

from __future__ import annotations

from typing import Callable
from uuid import uuid4

from migration_factory.control_tower.application.commands import CreateMigrationJobCommand
from migration_factory.control_tower.application.dto import CreatedMigrationJob
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
    NotFoundError,
    StorageIntegrityError,
)
from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.schemas.run_configuration import RunConfiguration


class CreateMigrationJobService:
    def __init__(self, unit_of_work_factory: Callable[[], ControlTowerUnitOfWork]) -> None:
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
            event_payload_json = canonical_json_text(event_payload)
            event_record = RunEventRecord(
                event_id=f"event-{job_id}-0001",
                job_id=job_id,
                sequence=1,
                event_type="job_created",
                actor_type="user",
                actor_id=command.actor,
                correlation_id=command.correlation_id,
                causation_id=None,
                payload_json=event_payload_json,
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
