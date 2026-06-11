"""Minimal FastAPI adapter for the M2 diagnostic queue path."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field

from pathlib import Path

from migration_factory.control_tower.application.commands import (
    CancelCommand,
    CreateDiagnosticJobCommand,
    FinalizeCommandCommand,
    LaunchWorkerCommand,
    StartMigrationJobCommand,
    TimeoutCommand,
)
from migration_factory.control_tower.application.dto import (
    ArtifactDto,
    CommandExecutionDto,
    CommandOutputWindowDto,
    JobProjectionDto,
    RunEventDto,
)
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork, WorkerLauncher, WorkerTerminator
from migration_factory.control_tower.application.queries import (
    DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE,
    ControlTowerQueryService,
    _decode_utf8_safe,
    parse_public_event_cursor,
)
from migration_factory.control_tower.application.services import (
    CancelService,
    CommandFinalizationService,
    DiagnosticJobService,
    ReconciliationService,
    TimeoutService,
    WorkerLaunchService,
)
from migration_factory.control_tower.domain.errors import (
    ActiveCommandConflictError,
    ControlTowerError,
    ControllerOwnershipConflictError,
    ControllerOwnershipUnavailableError,
    EventCursorConflictError,
    ExpectedVersionRequiredError,
    IdempotencyConflictError,
    InvalidEventCursorError,
    InvalidJobStateTransitionError,
    NotFoundError,
    StaleVersionError,
    UnsupportedPlatformError,
)
from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.infrastructure.singleton import (
    ControllerOwnership,
    ControllerOwnershipStatus,
    controller_resource_path_from_unit_of_work_factory,
    create_controller_ownership,
)
from migration_factory.control_tower.schemas.run_configuration import RunPolicy
from migration_factory.control_tower.adapters.fastapi.security import (
    MUTATION_METHODS,
    ActorProvider,
    LocalApiSecuritySettings,
    OperatingSystemActorProvider,
    dependency_versions,
    normalize_correlation_id,
    path_accessible,
    public_error_payload,
    redact_public_data,
)


UnitOfWorkFactory = Any
ETAG_RE = re.compile(r'^"job-(?P<job_id>.+)-v(?P<version>[1-9][0-9]*)"$')


@dataclass(frozen=True, slots=True)
class EventReplayConfig:
    batch_size: int = DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE
    max_sse_clients: int = 8
    poll_interval_seconds: float = 0.25
    keepalive_interval_seconds: float = 15.0
    reconnect_delay_ms: int = 1000


class PublicEventNotifier:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    async def notify(self) -> None:
        async with self._condition:
            self._version += 1
            self._condition.notify_all()

    async def wait(self, seen_version: int, timeout_seconds: float) -> int:
        async with self._condition:
            if self._version != seen_version:
                return self._version
            try:
                await asyncio.wait_for(self._condition.wait(), timeout=timeout_seconds)
            except TimeoutError:
                pass
            return self._version


class SseClientLimiter:
    def __init__(self, maximum_clients: int) -> None:
        self._maximum_clients = maximum_clients
        self._active_clients = 0
        self._lock = asyncio.Lock()

    @property
    def active_clients(self) -> int:
        return self._active_clients

    async def acquire(self) -> bool:
        async with self._lock:
            if self._active_clients >= self._maximum_clients:
                return False
            self._active_clients += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._active_clients > 0:
                self._active_clients -= 1


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


class LaunchWorkerRequest(StrictRequest):
    command_id: str


class FinalizeCommandRequest(StrictRequest):
    command_id: str
    outcome: str


class TimeoutRequest(StrictRequest):
    command_id: str = ""
    timeout_seconds: int = 3600
    deadline: float = 0.0


@asynccontextmanager
async def _control_tower_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run startup reconciliation on service start."""
    try:
        _ensure_controller_ownership(app)
        yield
    finally:
        ownership: ControllerOwnership = app.state.controller_ownership
        try:
            ownership.release()
        except ControlTowerError:
            pass


def _LOG_RECONCILIATION(results: list[dict[str, Any]]) -> None:
    """Log reconciliation results for observability."""
    import logging as _logging

    logger = _logging.getLogger(__name__)
    for result in results:
        logger.info(
            "Startup reconciliation: job_id=%s action=%s",
            result.get("job_id", "?"),
            result.get("action", "?"),
        )


def create_app(
    unit_of_work_factory: UnitOfWorkFactory,
    *,
    worker_launcher: WorkerLauncher | None = None,
    worker_terminator: WorkerTerminator | None = None,
    event_replay_config: EventReplayConfig | None = None,
    security_settings: LocalApiSecuritySettings | None = None,
    actor_provider: ActorProvider | None = None,
    controller_ownership: ControllerOwnership | None = None,
) -> FastAPI:
    config = event_replay_config or EventReplayConfig()
    local_security = security_settings or LocalApiSecuritySettings()
    resolved_actor_provider = actor_provider or OperatingSystemActorProvider()
    resolved_controller_ownership = controller_ownership or create_controller_ownership(
        controller_resource_path_from_unit_of_work_factory(unit_of_work_factory)
    )
    app = FastAPI(title="AI Migration Control Tower", version="0.1.0", lifespan=_control_tower_lifespan)
    app.state.event_replay_config = config
    app.state.public_event_notifier = PublicEventNotifier()
    app.state.sse_client_limiter = SseClientLimiter(config.max_sse_clients)
    app.state.unit_of_work_factory = unit_of_work_factory
    app.state.security_settings = local_security
    app.state.actor_provider = resolved_actor_provider
    app.state.worker_launcher = worker_launcher
    app.state.worker_terminator = worker_terminator
    app.state.controller_ownership = resolved_controller_ownership
    app.state.controller_services_started = False
    app.state.reconciliation_results = []

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[local_security.frontend_origin],
        allow_credentials=False,
        allow_methods=list(local_security.cors_allowed_methods),
        allow_headers=list(local_security.cors_allowed_headers),
    )

    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next):
        correlation_id = normalize_correlation_id(request.headers.get("X-Correlation-ID"))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.middleware("http")
    async def enforce_local_security(request: Request, call_next):
        host = request.headers.get("host")
        if not host:
            return _json_error(
                request,
                status.HTTP_400_BAD_REQUEST,
                "MISSING_HOST",
                "Host header is required.",
            )
        if host != local_security.trusted_api_host:
            return _json_error(
                request,
                status.HTTP_403_FORBIDDEN,
                "UNTRUSTED_HOST",
                "Host is not allowed.",
            )

        if request.method in MUTATION_METHODS:
            origin = request.headers.get("origin")
            if origin != local_security.frontend_origin:
                return _json_error(
                    request,
                    status.HTTP_403_FORBIDDEN,
                    "INVALID_ORIGIN",
                    "Origin is not allowed for mutation requests.",
                )
            client_id = request.headers.get("X-Control-Tower-Client")
            if client_id != local_security.frontend_client_id:
                return _json_error(
                    request,
                    status.HTTP_400_BAD_REQUEST,
                    "INVALID_CLIENT_HEADER",
                    "X-Control-Tower-Client is required for mutation requests.",
                )
            content_type = request.headers.get("content-type", "")
            if not content_type.lower().startswith("application/json"):
                return _json_error(
                    request,
                    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    "UNSUPPORTED_MEDIA_TYPE",
                    "Mutation requests must use Content-Type application/json.",
                )

        if request.url.path not in {
            "/v1/health/live",
            "/v1/health/ready",
            "/v1/health/dependencies",
        }:
            ownership = _ensure_controller_ownership(app)
            if not ownership.ready:
                error_code = "SERVICE_INSTANCE_CONFLICT" if ownership.status == "conflict" else "SERVICE_NOT_READY"
                return _json_error(
                    request,
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    error_code,
                    "Local Control Tower controller ownership is unavailable.",
                )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code", "HTTP_ERROR"))
        message = str(detail.get("message", "Request failed."))
        return _json_error(request, exc.status_code, code, message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        return _json_error(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "Request body did not match the expected contract.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        del exc
        return _json_error(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_SERVER_ERROR",
            "Internal server error.",
        )

    @app.get("/v1/health/live")
    def health_live(request: Request) -> dict[str, Any]:
        return {
            "status": "live",
            "service": "control-tower-api",
            "correlation_id": request.state.correlation_id,
        }

    @app.get("/v1/health/ready")
    def health_ready(request: Request) -> dict[str, Any]:
        payload = _ready_payload(
            request=request,
            app=app,
            unit_of_work_factory=unit_of_work_factory,
        )
        return redact_public_data(payload)

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
        return {"runner_profiles": redact_public_data(profiles)}

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
        return {"pipelines": redact_public_data(pipelines)}

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
        return {"filesystem_roots": redact_public_data(roots)}

    @app.post("/v1/jobs", status_code=status.HTTP_201_CREATED)
    async def create_job(
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
        await app.state.public_event_notifier.notify()
        return _projection_payload(projection)

    @app.get("/v1/jobs")
    def list_jobs() -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        return {
            "jobs": [
                {
                    "job_id": job.job_id,
                    "version": job.version,
                    "state": job.status.value,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                }
                for job in query_service.list_migration_jobs()
            ]
        }

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
    async def start_job(
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
        actor = resolved_actor_provider.current_actor()
        service = DiagnosticJobService(unit_of_work_factory)
        try:
            projection = service.start_migration_job(
                StartMigrationJobCommand(
                    job_id=job_id,
                    expected_version=expected_version,
                    idempotency_key=idempotency_key,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        response.headers["ETag"] = projection.etag
        await app.state.public_event_notifier.notify()
        return _projection_payload(projection)

    @app.post("/v1/jobs/{job_id}/launch")
    async def launch_worker(
        job_id: str,
        request: LaunchWorkerRequest,
    ) -> dict[str, Any]:
        if worker_launcher is None:
            raise _error(
                status.HTTP_501_NOT_IMPLEMENTED,
                "WORKER_LAUNCH_NOT_CONFIGURED",
                "Worker launcher is not configured.",
            )
        service = WorkerLaunchService(unit_of_work_factory, worker_launcher)
        try:
            result = service.execute(
                LaunchWorkerCommand(
                    command_id=request.command_id,
                    job_id=job_id,
                    actor_type="system",
                    actor_id="controller",
                )
            )
        except (ControlTowerError, FileNotFoundError) as exc:
            if isinstance(exc, UnsupportedPlatformError):
                raise _error(
                    status.HTTP_501_NOT_IMPLEMENTED,
                    "UNSUPPORTED_PLATFORM",
                    str(exc),
                ) from exc
            if isinstance(exc, ControlTowerError):
                _raise_http_error(exc)
            raise _error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "WORKER_LAUNCH_FAILED",
                str(exc),
            ) from exc
        await app.state.public_event_notifier.notify()
        return {
            "command_id": result.command_id,
            "job_id": result.job_id,
            "status": "RUNNING",
        }

    @app.post("/v1/jobs/{job_id}/finalize")
    async def finalize_command(
        job_id: str,
        request: FinalizeCommandRequest,
    ) -> dict[str, Any]:
        service = CommandFinalizationService(unit_of_work_factory)
        try:
            service.execute(
                FinalizeCommandCommand(
                    command_id=request.command_id,
                    job_id=job_id,
                    outcome=request.outcome,
                    actor_type="system",
                    actor_id="controller",
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        await app.state.public_event_notifier.notify()
        return {
            "command_id": request.command_id,
            "job_id": job_id,
            "status": "FINALIZED",
        }

    @app.get("/v1/jobs/{job_id}/events")
    def replay_events(
        job_id: str,
        after_sequence: str | None = Query(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            latest_sequence = query_service.latest_run_event_sequence(job_id)
            cursor = parse_public_event_cursor(
                after_sequence=after_sequence,
                last_event_id=last_event_id,
                latest_sequence=latest_sequence,
            )
            events = query_service.replay_run_events(
                job_id,
                after_sequence=cursor,
                limit=config.batch_size,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        next_after_sequence = events[-1].sequence if events else cursor
        return {
            "job_id": job_id,
            "after_sequence": cursor,
            "next_after_sequence": next_after_sequence,
            "latest_sequence": latest_sequence,
            "events": [_event_payload(event) for event in events],
        }

    @app.get("/v1/jobs/{job_id}/events/stream")
    async def stream_events(
        job_id: str,
        request: Request,
        after_sequence: str | None = Query(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> EventSourceResponse:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            latest_sequence = query_service.latest_run_event_sequence(job_id)
            cursor = parse_public_event_cursor(
                after_sequence=after_sequence,
                last_event_id=last_event_id,
                latest_sequence=latest_sequence,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)

        limiter: SseClientLimiter = app.state.sse_client_limiter
        if not await limiter.acquire():
            raise _error(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "SSE_CLIENT_LIMIT_REACHED",
                "Too many active event replay clients.",
            )

        return EventSourceResponse(
            _event_stream(
                job_id=job_id,
                initial_after_sequence=cursor,
                request=request,
                query_service=query_service,
                notifier=app.state.public_event_notifier,
                limiter=limiter,
                config=config,
            )
        )

    @app.get("/v1/jobs/{job_id}/commands")
    def list_commands(job_id: str) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            commands = query_service.list_command_executions(job_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return {"job_id": job_id, "commands": [_command_payload(command) for command in commands]}

    @app.get("/v1/jobs/{job_id}/commands/{command_id}/stdout")
    def read_stdout(
        job_id: str,
        command_id: str,
        after_offset: int = Query(default=0),
        max_bytes: int = Query(default=8192, le=1048576),
    ) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            window = query_service.get_command_output_window(
                job_id,
                command_id,
                stream="stdout",
                after_offset=after_offset,
                max_bytes=max_bytes,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _output_window_payload(window)

    @app.get("/v1/jobs/{job_id}/commands/{command_id}/logs/stdout")
    def read_stdout_log(
        job_id: str,
        command_id: str,
        after_offset: int = Query(default=0),
        max_bytes: int = Query(default=8192, le=1048576),
    ) -> dict[str, Any]:
        return read_stdout(job_id, command_id, after_offset=after_offset, max_bytes=max_bytes)

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel_job(
        job_id: str,
        request: StrictRequest,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        if if_match is None:
            raise _error(
                status.HTTP_428_PRECONDITION_REQUIRED,
                "PRECONDITION_REQUIRED",
                "If-Match is required for cancel.",
            )
        expected_version = _expected_version_from_if_match(job_id, if_match)
        actor = resolved_actor_provider.current_actor()

        service = CancelService(unit_of_work_factory, worker_terminator)
        try:
            projection = service.cancel(
                CancelCommand(
                    job_id=job_id,
                    expected_version=expected_version,
                    grace_period_seconds=5.0,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        await app.state.public_event_notifier.notify()
        return _projection_payload(projection)

    @app.post("/v1/jobs/{job_id}/timeout")
    async def handle_timeout(
        job_id: str,
        request: TimeoutRequest,
    ) -> dict[str, Any]:
        import time as _time

        # If no deadline provided, compute from monotonic clock
        deadline = request.deadline
        if deadline <= 0.0:
            deadline = _time.monotonic()

        service = TimeoutService(unit_of_work_factory, worker_terminator)
        try:
            projection = service.handle_timeout(
                TimeoutCommand(
                    job_id=job_id,
                    command_id=request.command_id,
                    timeout_seconds=int(request.timeout_seconds),
                    deadline=float(deadline),
                    actor_type="system",
                    actor_id="system",
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        await app.state.public_event_notifier.notify()
        return _projection_payload(projection)

    @app.get("/v1/jobs/{job_id}/commands/{command_id}/stderr")
    def read_stderr(
        job_id: str,
        command_id: str,
        after_offset: int = Query(default=0),
        max_bytes: int = Query(default=8192, le=1048576),
    ) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            window = query_service.get_command_output_window(
                job_id,
                command_id,
                stream="stderr",
                after_offset=after_offset,
                max_bytes=max_bytes,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _output_window_payload(window)

    @app.get("/v1/jobs/{job_id}/commands/{command_id}/logs/stderr")
    def read_stderr_log(
        job_id: str,
        command_id: str,
        after_offset: int = Query(default=0),
        max_bytes: int = Query(default=8192, le=1048576),
    ) -> dict[str, Any]:
        return read_stderr(job_id, command_id, after_offset=after_offset, max_bytes=max_bytes)

    @app.get("/v1/jobs/{job_id}/artifacts")
    def list_artifacts(job_id: str) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            query_service.get_migration_job(job_id)
            artifacts = query_service.list_artifacts(job_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return {"job_id": job_id, "artifacts": [_artifact_payload(artifact) for artifact in artifacts]}

    @app.get("/v1/health/live")
    def health_live(request: Request) -> dict[str, Any]:
        return {
            "status": "live",
            "service": "control-tower-api",
            "correlation_id": request.state.correlation_id,
        }

    @app.get("/v1/health/ready")
    def health_ready(request: Request) -> dict[str, Any]:
        payload = _ready_payload(
            request=request,
            app=app,
            unit_of_work_factory=unit_of_work_factory,
        )
        return redact_public_data(payload)

    @app.get("/v1/health/dependencies")
    def health_dependencies(request: Request) -> dict[str, Any]:
        payload = _dependencies_payload(
            request=request,
            app=app,
            unit_of_work_factory=unit_of_work_factory,
        )
        return redact_public_data(payload)

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
    recovery_reason = None
    if job.status == JobState.RECOVERY_REQUIRED:
        recovery_reason = "uncertain active execution after restart"
    return redact_public_data({
        "job": {
            "job_id": job.job_id,
            "version": job.version,
            "state": job.status.value,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "recovery_reason": recovery_reason,
        },
        "active_command": None
        if command is None
        else _command_payload(command),
        "etag": projection.etag,
    })


def _command_payload(command: CommandExecutionDto) -> dict[str, Any]:
    return {
        "command_id": command.command_id,
        "job_id": command.job_id,
        "operation": command.operation,
        "status": command.status.value,
        "created_at": command.created_at,
        "updated_at": command.updated_at,
        "command_manifest_artifact_id": command.command_manifest_artifact_id,
        "working_directory_root_id": command.working_directory_root_id,
        "working_directory_relative_path": command.working_directory_relative_path,
        "worker_id": command.worker_id,
        "launch_attempt": command.launch_attempt,
    }


def _artifact_payload(artifact: ArtifactDto) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "job_id": artifact.job_id,
        "stage_run_id": artifact.stage_run_id,
        "artifact_type": artifact.artifact_type,
        "registered_root_id": artifact.registered_root_id,
        "relative_path": artifact.relative_path,
        "normalized_relative_path": artifact.normalized_relative_path,
        "content_type": artifact.content_type,
        "size_bytes": artifact.size_bytes,
        "checksum_algorithm": artifact.checksum_algorithm,
        "checksum": artifact.checksum,
        "created_at": artifact.created_at,
        "created_by": artifact.created_by,
    }


def _output_window_payload(window: CommandOutputWindowDto) -> dict[str, Any]:
    return {
        "command_id": window.command_id,
        "job_id": window.job_id,
        "stream": window.stream,
        "requested_offset": window.requested_offset,
        "start_offset": window.start_offset,
        "next_offset": window.next_offset,
        "data": window.data,
        "encoding": window.encoding,
        "replacement_characters_used": window.replacement_characters_used,
        "truncated": window.truncated,
        "terminal": window.terminal,
        "max_bytes": window.max_bytes,
    }


async def _event_stream(
    *,
    job_id: str,
    initial_after_sequence: int,
    request: Request,
    query_service: ControlTowerQueryService,
    notifier: PublicEventNotifier,
    limiter: SseClientLimiter,
    config: EventReplayConfig,
) -> AsyncIterator[str | ServerSentEvent]:
    last_sent_sequence = initial_after_sequence
    last_keepalive = time.monotonic()
    notifier_version = notifier.version
    try:
        while True:
            if await request.is_disconnected():
                break

            events = query_service.replay_run_events(
                job_id,
                after_sequence=last_sent_sequence,
                limit=config.batch_size,
            )
            if events:
                for event in events:
                    last_sent_sequence = event.sequence
                    yield _sse_frame(
                        id=str(event.sequence),
                        event=event.event_type,
                        data=_event_payload(event),
                        retry=config.reconnect_delay_ms,
                    )
                last_keepalive = time.monotonic()
                continue

            now = time.monotonic()
            if now - last_keepalive >= config.keepalive_interval_seconds:
                last_keepalive = now
                yield ": keepalive\n\n"

            notifier_version = await notifier.wait(
                notifier_version,
                config.poll_interval_seconds,
            )
    finally:
        await limiter.release()


def _event_payload(event: RunEventDto) -> dict[str, Any]:
    return redact_public_data({
        "event_id": event.event_id,
        "job_id": event.job_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "payload": event.payload,
        "payload_checksum": event.payload_checksum,
        "created_at": event.created_at,
    })


def _sse_frame(
    *,
    id: str,
    event: str,
    data: dict[str, Any],
    retry: int | None,
) -> str:
    lines = [f"id: {id}", f"event: {event}"]
    if retry is not None:
        lines.append(f"retry: {retry}")
    lines.append(f"data: {json.dumps(data, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


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
    if isinstance(exc, UnsupportedPlatformError):
        raise _error(status.HTTP_501_NOT_IMPLEMENTED, "UNSUPPORTED_PLATFORM", "Worker launch is not supported on this platform.") from exc
    if isinstance(exc, EventCursorConflictError):
        raise _error(status.HTTP_400_BAD_REQUEST, "EVENT_CURSOR_CONFLICT", str(exc)) from exc
    if isinstance(exc, InvalidEventCursorError):
        raise _error(status.HTTP_400_BAD_REQUEST, "INVALID_EVENT_CURSOR", str(exc)) from exc
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
        detail={"code": code, "message": message},
    )


def _json_error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", normalize_correlation_id(None))
    return JSONResponse(
        status_code=status_code,
        content=public_error_payload(code, message, correlation_id),
        headers={"X-Correlation-ID": correlation_id},
    )


def _ready_payload(
    *,
    request: Request,
    app: FastAPI,
    unit_of_work_factory: UnitOfWorkFactory,
) -> dict[str, Any]:
    migration = _migration_status(unit_of_work_factory)
    roots = _registered_root_status(unit_of_work_factory)
    process_control = _process_control_status(app)
    singleton = _singleton_status(app)
    service_loop = _service_loop_status(app)
    ready = all(
        (
            migration["ready"],
            roots["ready"],
            process_control["ready"],
            singleton["ready"],
            service_loop["ready"],
        )
    )
    return {
        "status": "ready" if ready else "not_ready",
        "correlation_id": request.state.correlation_id,
        "checks": {
            "singleton_ownership": singleton,
            "db_migrations": migration,
            "required_root_access": roots,
            "service_loop": service_loop,
            "process_control": process_control,
        },
    }


def _dependencies_payload(
    *,
    request: Request,
    app: FastAPI,
    unit_of_work_factory: UnitOfWorkFactory,
) -> dict[str, Any]:
    settings: LocalApiSecuritySettings = app.state.security_settings
    return {
        "status": "ok",
        "correlation_id": request.state.correlation_id,
        "runtime": dependency_versions(),
        "origins": {
            "api": settings.api_origin,
            "frontend": settings.frontend_origin,
        },
        "db_migrations": _migration_status(unit_of_work_factory),
        "process_control": _process_control_status(app),
        "service_loop": _service_loop_status(app),
    }


def _singleton_status(app: FastAPI) -> dict[str, Any]:
    status = _ensure_controller_ownership(app)
    return {
        "ready": status.ready,
        "status": status.status,
    }


def _ensure_controller_ownership(app: FastAPI) -> ControllerOwnershipStatus:
    ownership: ControllerOwnership = app.state.controller_ownership
    if not ownership.is_owned:
        try:
            ownership.acquire()
        except (ControllerOwnershipConflictError, ControllerOwnershipUnavailableError):
            return ownership.snapshot()
        if not app.state.controller_services_started:
            _run_startup_reconciliation(app)
            app.state.controller_services_started = True
    elif not app.state.controller_services_started:
        _run_startup_reconciliation(app)
        app.state.controller_services_started = True
    return ownership.snapshot()


def _run_startup_reconciliation(app: FastAPI) -> None:
    unit_of_work_factory: UnitOfWorkFactory = app.state.unit_of_work_factory
    try:
        service = ReconciliationService(unit_of_work_factory)
        results = service.reconcile_all()
        app.state.reconciliation_results = results
        if results:
            _LOG_RECONCILIATION(results)
    except Exception:
        pass


def _service_loop_status(app: FastAPI) -> dict[str, Any]:
    notifier_ready = hasattr(app.state, "public_event_notifier")
    limiter_ready = hasattr(app.state, "sse_client_limiter")
    config_ready = hasattr(app.state, "event_replay_config")
    return {
        "ready": notifier_ready and limiter_ready and config_ready,
        "status": "ok" if notifier_ready and limiter_ready and config_ready else "missing",
        "sse_active_clients": getattr(app.state.sse_client_limiter, "active_clients", 0),
    }


import sys as _sys


def _process_control_status(app: FastAPI) -> dict[str, Any]:
    launcher = getattr(app.state, "worker_launcher", None)
    terminator = getattr(app.state, "worker_terminator", None)
    ready = launcher is not None and terminator is not None
    # On Linux/macOS, Windows process-control is genuinely unavailable;
    # the service is still ready for everything else.
    if not _sys.platform.startswith("win"):
        ready = True
    return {
        "ready": ready,
        "status": "configured" if launcher is not None and terminator is not None else "not_configured",
    }


def _migration_status(unit_of_work_factory: UnitOfWorkFactory) -> dict[str, Any]:
    from migration_factory.control_tower.infrastructure.sqlite.migrations import discover_migrations

    expected_versions = [migration.version for migration in discover_migrations()]
    try:
        uow = unit_of_work_factory()
        connection = getattr(uow, "connection", None)
        if connection is None:
            return {"ready": False, "status": "unknown", "applied_versions": 0}
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if table_exists is None:
            return {"ready": False, "status": "missing", "applied_versions": 0}
        rows = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        applied_versions = [int(row["version"]) for row in rows]
        return {
            "ready": applied_versions == expected_versions,
            "status": "current" if applied_versions == expected_versions else "outdated",
            "applied_versions": len(applied_versions),
            "expected_versions": len(expected_versions),
        }
    except Exception:
        return {"ready": False, "status": "error", "applied_versions": 0}


def _registered_root_status(unit_of_work_factory: UnitOfWorkFactory) -> dict[str, Any]:
    try:
        with unit_of_work_factory() as uow:
            roots: list[Path] = []
            for profile in uow.runner_profiles.list():
                for root in (profile.payload.get("filesystem", {}).get("roots", ()) or ()):
                    root_path = root.get("path")
                    if isinstance(root_path, str):
                        roots.append(Path(root_path))
        accessible_count = sum(1 for root in roots if path_accessible(root))
        ready = accessible_count == len(roots)
        if not roots:
            return {"ready": True, "status": "not_configured", "checked_root_count": 0}
        return {
            "ready": ready,
            "status": "ok" if ready else "inaccessible",
            "checked_root_count": len(roots),
            "accessible_root_count": accessible_count,
        }
    except Exception:
        return {"ready": False, "status": "error", "checked_root_count": 0}
