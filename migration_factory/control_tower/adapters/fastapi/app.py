"""Minimal FastAPI adapter for the M2 diagnostic queue path."""

from __future__ import annotations

import getpass
import re
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from migration_factory.control_tower.application.commands import (
    CreateDiagnosticJobCommand,
    StartMigrationJobCommand,
)
from migration_factory.control_tower.application.dto import JobProjectionDto
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork
from migration_factory.control_tower.application.services import DiagnosticJobService
from migration_factory.control_tower.domain.errors import (
    ActiveCommandConflictError,
    ControlTowerError,
    ExpectedVersionRequiredError,
    IdempotencyConflictError,
    InvalidJobStateTransitionError,
    NotFoundError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.schemas.run_configuration import RunPolicy


UnitOfWorkFactory = Any
ETAG_RE = re.compile(r'^"job-(?P<job_id>.+)-v(?P<version>[1-9][0-9]*)"$')


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateJobRequest(StrictRequest):
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    legacy_source_root_id: str
    legacy_source_relative_path: str
    output_root_id: str
    output_relative_path: str
    target_proof_level: TargetProofLevel = TargetProofLevel.ANALYZED
    enabled_gates: tuple[str, ...] = ()
    policy: RunPolicy = Field(default_factory=RunPolicy)


class StartJobRequest(StrictRequest):
    pass


def create_app(unit_of_work_factory: UnitOfWorkFactory) -> FastAPI:
    app = FastAPI(title="AI Migration Control Tower", version="0.1.0")

    @app.get("/v1/runner-profiles")
    def list_runner_profiles() -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            profiles = [
                {
                    "runner_profile_id": profile.runner_profile_id,
                    "runner_profile_version": profile.runner_profile_version,
                    "display_name": profile.display_name,
                }
                for profile in uow.runner_profiles.list()
            ]
        return {"runner_profiles": profiles}

    @app.get("/v1/pipelines")
    def list_pipelines() -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            pipelines = [
                {
                    "pipeline_id": pipeline.pipeline_id,
                    "pipeline_version": pipeline.pipeline_version,
                    "display_name": pipeline.display_name,
                }
                for pipeline in uow.pipeline_definitions.list()
            ]
        return {"pipelines": pipelines}

    @app.get("/v1/filesystem/roots")
    def list_filesystem_roots() -> dict[str, Any]:
        roots: list[dict[str, str]] = []
        with unit_of_work_factory() as uow:
            for profile in uow.runner_profiles.list():
                for root in (profile.payload.get("filesystem", {}).get("roots", ()) or ()):
                    roots.append(
                        {
                            "runner_profile_id": profile.runner_profile_id,
                            "runner_profile_version": profile.runner_profile_version,
                            "root_id": str(root["root_id"]),
                            "kind": str(root["kind"]),
                            "display_name": str(root["root_id"]),
                        }
                    )
        return {"filesystem_roots": roots}

    @app.post("/v1/jobs", status_code=status.HTTP_201_CREATED)
    def create_job(
        request: CreateJobRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if not idempotency_key:
            raise _error(status.HTTP_400_BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
        service = DiagnosticJobService(unit_of_work_factory)
        try:
            projection = service.create_diagnostic_job(
                CreateDiagnosticJobCommand(
                    idempotency_key=idempotency_key,
                    runner_profile_id=request.runner_profile_id,
                    runner_profile_version=request.runner_profile_version,
                    pipeline_id=request.pipeline_id,
                    pipeline_version=request.pipeline_version,
                    legacy_source_root_id=request.legacy_source_root_id,
                    legacy_source_relative_path=request.legacy_source_relative_path,
                    output_root_id=request.output_root_id,
                    output_relative_path=request.output_relative_path,
                    target_proof_level=request.target_proof_level,
                    enabled_gates=request.enabled_gates,
                    policy=request.policy,
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        response.headers["ETag"] = projection.etag
        return _projection_payload(projection)

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, response: Response) -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            try:
                projection = _projection(uow, job_id)
            except ControlTowerError as exc:
                _raise_http_error(exc)
        response.headers["ETag"] = projection.etag
        return _projection_payload(projection)

    @app.post("/v1/jobs/{job_id}/start")
    def start_job(
        job_id: str,
        request: StartJobRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        del request
        if not idempotency_key:
            raise _error(status.HTTP_400_BAD_REQUEST, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key is required.")
        expected_version = _expected_version_from_if_match(job_id, if_match)
        service = DiagnosticJobService(unit_of_work_factory)
        try:
            projection = service.start_migration_job(
                StartMigrationJobCommand(
                    job_id=job_id,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                    actor_type="user",
                    actor_id=getpass.getuser(),
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        response.headers["ETag"] = projection.etag
        return _projection_payload(projection)

    return app


def _projection(uow: ControlTowerUnitOfWork, job_id: str) -> JobProjectionDto:
    job = uow.migration_jobs.get(job_id)
    if job is None:
        raise NotFoundError("migration job", job_id)
    return JobProjectionDto(
        job=job,
        active_command=uow.command_executions.get_active_for_job(job_id),
        etag=f'"job-{job.job_id}-v{job.version}"',
    )


def _projection_payload(projection: JobProjectionDto) -> dict[str, Any]:
    job = projection.job
    command = projection.active_command
    return {
        "job": {
            "job_id": job.job_id,
            "version": job.version,
            "state": job.status.value,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        },
        "active_command": None
        if command is None
        else {
            "command_id": command.command_id,
            "job_id": command.job_id,
            "operation": command.operation,
            "status": command.status.value,
            "created_at": command.created_at,
            "updated_at": command.updated_at,
        },
        "etag": projection.etag,
    }


def _expected_version_from_if_match(job_id: str, if_match: str | None) -> int:
    if if_match is None:
        raise _error(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "PRECONDITION_REQUIRED",
            "If-Match is required.",
        )
    match = ETAG_RE.fullmatch(if_match)
    if match is None or match.group("job_id") != job_id:
        raise _error(
            status.HTTP_412_PRECONDITION_FAILED,
            "JOB_VERSION_CONFLICT",
            "If-Match does not match the requested job.",
        )
    return int(match.group("version"))


def _raise_http_error(exc: ControlTowerError) -> None:
    if isinstance(exc, IdempotencyConflictError):
        raise _error(status.HTTP_409_CONFLICT, "IDEMPOTENCY_CONFLICT", str(exc)) from exc
    if isinstance(exc, StaleVersionError):
        raise _error(status.HTTP_412_PRECONDITION_FAILED, "JOB_VERSION_CONFLICT", str(exc)) from exc
    if isinstance(exc, ExpectedVersionRequiredError):
        raise _error(status.HTTP_428_PRECONDITION_REQUIRED, "PRECONDITION_REQUIRED", str(exc)) from exc
    if isinstance(exc, NotFoundError):
        raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc
    if isinstance(exc, (InvalidJobStateTransitionError, ActiveCommandConflictError)):
        raise _error(status.HTTP_409_CONFLICT, "ACTIVE_COMMAND_CONFLICT", str(exc)) from exc
    raise _error(status.HTTP_400_BAD_REQUEST, "CONTROL_TOWER_ERROR", str(exc)) from exc


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message, "details": {}}},
    )
