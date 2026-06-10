"""Minimal FastAPI adapter for the M2 diagnostic queue path."""

from __future__ import annotations

import asyncio
import getpass
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.sse import EventSourceResponse
from pydantic import BaseModel, ConfigDict, Field

from migration_factory.control_tower.application.commands import (
    CreateDiagnosticJobCommand,
    StartMigrationJobCommand,
)
from migration_factory.control_tower.application.dto import JobProjectionDto, RunEventDto
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork
from migration_factory.control_tower.application.queries import (
    DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE,
    ControlTowerQueryService,
    parse_public_event_cursor,
)
from migration_factory.control_tower.application.services import DiagnosticJobService
from migration_factory.control_tower.domain.errors import (
    ActiveCommandConflictError,
    ControlTowerError,
    EventCursorConflictError,
    ExpectedVersionRequiredError,
    IdempotencyConflictError,
    InvalidEventCursorError,
    InvalidJobStateTransitionError,
    NotFoundError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.schemas.run_configuration import RunPolicy


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


def create_app(
    unit_of_work_factory: UnitOfWorkFactory,
    *,
    event_replay_config: EventReplayConfig | None = None,
) -> FastAPI:
    config = event_replay_config or EventReplayConfig()
    app = FastAPI(title="AI Migration Control Tower", version="0.1.0")
    app.state.event_replay_config = config
    app.state.public_event_notifier = PublicEventNotifier()
    app.state.sse_client_limiter = SseClientLimiter(config.max_sse_clients)

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
        await app.state.public_event_notifier.notify()
        return _projection_payload(projection)

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


async def _event_stream(
    *,
    job_id: str,
    initial_after_sequence: int,
    request: Request,
    query_service: ControlTowerQueryService,
    notifier: PublicEventNotifier,
    limiter: SseClientLimiter,
    config: EventReplayConfig,
) -> AsyncIterator[str]:
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
    return {
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
    }


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
        detail={"error": {"code": code, "message": message, "details": {}}},
    )
