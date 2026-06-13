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
    RecordApprovalCommand,
    StartMigrationJobCommand,
    TimeoutCommand,
)
from migration_factory.control_tower.application.dto import (
    ArtifactDto,
    CommandExecutionDto,
    CommandOutputWindowDto,
    JobProjectionDto,
    RunEventDto,
    StageChainEntryDto,
)
from migration_factory.control_tower.application.ports import ControlTowerUnitOfWork, WorkerLauncher, WorkerTerminator
from migration_factory.control_tower.application.plan_amendments import (
    PlanAmendmentService,
    PlanChange,
)
from migration_factory.control_tower.application.proof import (
    DeterministicProofGateService,
    FinalReportService,
)
from migration_factory.control_tower.application.repairs import RepairService
from migration_factory.control_tower.application.patch_policy import PatchPolicyService
from migration_factory.control_tower.application.plan_reviews import PlanReviewService
from migration_factory.control_tower.application.plan_proposals import (
    FakeProviderPlanProposalService,
)
from migration_factory.control_tower.application.queries import (
    DEFAULT_PUBLIC_EVENT_REPLAY_BATCH_SIZE,
    ControlTowerQueryService,
    _decode_utf8_safe,
    parse_public_event_cursor,
)
from migration_factory.control_tower.application.services import (
    ApprovalService,
    CancelService,
    CommandFinalizationService,
    ControlTowerRegistrationService,
    DiagnosticJobService,
    ReconciliationService,
    StageContinuationPolicyService,
    TimeoutService,
    WorkerLaunchService,
)
from migration_factory.control_tower.application.runner_readiness import RunnerJdkReadinessService, ReadinessChecker
from migration_factory.control_tower.domain.errors import (
    ActiveCommandConflictError,
    ContinuationPolicyViolationError,
    ControlTowerError,
    ControllerOwnershipConflictError,
    ControllerOwnershipUnavailableError,
    EventCursorConflictError,
    ExpectedVersionRequiredError,
    IdempotencyConflictError,
    InvalidEventCursorError,
    InvalidJobStateTransitionError,
    NotFoundError,
    PatchContentEscapeError,
    PatchContentMismatchError,
    PatchContentOversizeError,
    PatchNotApprovedError,
    PatchPolicyValidationError,
    PatchRollbackError,
    PatchSnapshotNotFoundError,
    PlanAdvisoryValidationError,
    PlanAmendmentValidationError,
    RepairAttemptLimitExceededError,
    RepairClassificationError,
    RepairProposalValidationError,
    PlanReviewChecksumMismatchError,
    PlanReviewConflictError,
    PlanRevisionConflictError,
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


class PlanChangeRequest(StrictRequest):
    stage_index: int = Field(ge=1, le=3)
    change_type: str
    description: str
    rationale: str | None = None


class CreatePlanAmendmentRequest(StrictRequest):
    title: str
    summary: str
    source_kind: str = "manual"
    notes: tuple[str, ...] = ()
    changes: tuple[PlanChangeRequest, ...]


class CreatePlanRevisionRequest(StrictRequest):
    title: str
    summary: str
    source_kind: str = "manual"
    notes: tuple[str, ...] = ()
    changes: tuple[PlanChangeRequest, ...]
    revision_order: int | None = Field(default=None, ge=1)
    revision_state: str = "draft"


class CreateFakeProviderProposalRequest(StrictRequest):
    title: str
    summary: str
    notes: tuple[str, ...] = ()
    changes: tuple[PlanChangeRequest, ...]
    confidence_label: str | None = None
    confidence_score: float | None = Field(default=None, ge=0.0, le=1.0)
    model_invocation_id: str | None = None
    context_pack_manifest_id: str | None = None


class CreatePlanReviewDecisionRequest(StrictRequest):
    expected_checksum: str
    decision: str
    review_summary: str = ""


class CreateRepairClassificationRequest(StrictRequest):
    evidence_kind: str = "command_failure"
    failure_summary: str


class CreateFakeRepairProposalRequest(StrictRequest):
    proposal_summary: str | None = None


class CreateRepairAttemptRequest(StrictRequest):
    attempt_summary: str


class ValidatePatchRequest(StrictRequest):
    target_path: str
    patch_content: str
    patch_size_bytes: int = Field(ge=1, le=1_048_576)
    approval_id: str | None = None


class RecordSandboxSnapshotRequest(StrictRequest):
    stage_index: int = Field(ge=1, le=3)
    sandbox_artifact_id: str
    sandbox_checksum: str


class ApplyApprovedPatchRequest(StrictRequest):
    target_path: str
    patch_content: str
    patch_size_bytes: int = Field(ge=1, le=1_048_576)
    stage_index: int = Field(ge=1, le=3)
    approval_id: str | None = None


class RecordMavenValidationRequest(StrictRequest):
    maven_goal: str = Field(..., pattern="^(compile|test-compile)$")
    passed: bool
    result_summary: str = ""


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

    @app.get("/v1/runner-profiles/{runner_profile_id}/{runner_profile_version}/readiness")
    def get_runner_readiness(
        runner_profile_id: str,
        runner_profile_version: str,
    ) -> dict[str, Any]:
        """Check JDK 11/17/21 and Maven readiness for a runner profile.

        All JDK and Maven paths come from the registered runner profile,
        not from request bodies. This enforces the V1 invariant that
        browser payloads cannot choose raw executable paths or tool refs.
        """
        service = RunnerJdkReadinessService(unit_of_work_factory)
        try:
            result = service.check_runner_readiness(
                runner_profile_id,
                runner_profile_version,
                actor="api",
            )
        except ValueError as exc:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "RUNNER_PROFILE_NOT_FOUND",
                str(exc),
            ) from exc

        return {
            "runner_profile_id": result.runner_profile_id,
            "runner_profile_version": result.runner_profile_version,
            "checked_at": result.checked_at,
            "all_ready": result.all_ready,
            "checks": {
                "jdk_11": {
                    "ready": result.jdk_11.ready,
                    "path": result.jdk_11.jdk_path,
                    "message": result.jdk_11.message,
                },
                "jdk_17": {
                    "ready": result.jdk_17.ready,
                    "path": result.jdk_17.jdk_path,
                    "message": result.jdk_17.message,
                },
                "jdk_21": {
                    "ready": result.jdk_21.ready,
                    "path": result.jdk_21.jdk_path,
                    "message": result.jdk_21.message,
                },
                "maven": {
                    "ready": result.maven.ready,
                    "path": result.maven.executable_path,
                    "message": result.maven.message,
                },
            },
        }

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

    @app.get("/v1/model-profiles")
    def list_model_profiles() -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            profiles = [
                {
                    "profile_id": p.profile_id,
                    "display_name": p.display_name,
                    "provider_kind": p.provider_kind,
                    "is_active": p.is_active,
                    "created_at": p.created_at,
                }
                for p in uow.v1_model_profiles.list()
            ]
        return {"model_profiles": profiles}

    @app.get("/v1/model-profiles/{profile_id}")
    def get_model_profile(profile_id: str) -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            record = uow.v1_model_profiles.get(profile_id)
        if record is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "MODEL_PROFILE_NOT_FOUND",
                f"Model profile {profile_id!r} not found",
            )
        return {
            "profile_id": record.profile_id,
            "display_name": record.display_name,
            "provider_kind": record.provider_kind,
            "model_env_ref": record.model_env_ref,
            "endpoint_env_ref": record.endpoint_env_ref,
            "deployment_env_ref": record.deployment_env_ref,
            "is_active": record.is_active,
            "created_at": record.created_at,
            "created_by": record.created_by,
        }

    @app.post("/v1/model-profiles", status_code=status.HTTP_201_CREATED)
    async def register_model_profile(
        request: Request,
    ) -> dict[str, Any]:
        body: dict[str, Any] = await request.json()
        profile_id: str = body.get("profile_id", "")
        display_name: str = body.get("display_name", "")
        provider_kind: str = body.get("provider_kind", "fake")
        model_env_ref: str = body.get("model_env_ref", "")
        endpoint_env_ref: str = body.get("endpoint_env_ref", "")
        deployment_env_ref: str = body.get("deployment_env_ref", "")
        actor_id: str = body.get("actor_id", "api")
        correlation_id: str | None = body.get("correlation_id")

        if not profile_id or not display_name or not model_env_ref:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "INVALID_REQUEST",
                "profile_id, display_name, and model_env_ref are required",
            )

        if provider_kind not in ("fake", "azure_openai"):
            provider_kind = "fake"

        service = ControlTowerRegistrationService(unit_of_work_factory)
        record = service.register_model_profile(
            profile_id=profile_id,
            display_name=display_name,
            provider_kind=provider_kind,
            model_env_ref=model_env_ref,
            endpoint_env_ref=endpoint_env_ref,
            deployment_env_ref=deployment_env_ref,
            actor_type="api",
            actor_id=actor_id,
            correlation_id=correlation_id,
        )
        return {
            "profile_id": record.profile_id,
            "display_name": record.display_name,
            "provider_kind": record.provider_kind,
            "is_active": record.is_active,
            "created_at": record.created_at,
        }

    # ------------------------------------------------------------------
    # Model invocation audit endpoints (V1-10)
    # ------------------------------------------------------------------

    @app.get("/v1/model-invocations")
    def list_model_invocations() -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            invocations = [
                {
                    "invocation_id": inv.invocation_id,
                    "job_id": inv.job_id,
                    "profile_id": inv.profile_id,
                    "provider_kind": inv.provider_kind,
                    "model_name": inv.model_name,
                    "prompt_tokens": inv.prompt_tokens,
                    "completion_tokens": inv.completion_tokens,
                    "total_tokens": inv.total_tokens,
                    "redacted_summary": inv.redacted_summary,
                    "actor_type": inv.actor_type,
                    "actor_id": inv.actor_id,
                    "created_at": inv.created_at,
                }
                for inv in uow.v1_model_invocations.list()
            ]
        return {"model_invocations": invocations}

    @app.get("/v1/jobs/{job_id}/model-invocations")
    def list_job_model_invocations(job_id: str) -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            invocations = [
                {
                    "invocation_id": inv.invocation_id,
                    "profile_id": inv.profile_id,
                    "provider_kind": inv.provider_kind,
                    "model_name": inv.model_name,
                    "prompt_tokens": inv.prompt_tokens,
                    "completion_tokens": inv.completion_tokens,
                    "total_tokens": inv.total_tokens,
                    "redacted_summary": inv.redacted_summary,
                    "created_at": inv.created_at,
                }
                for inv in uow.v1_model_invocations.list_for_job(job_id)
            ]
        return {"model_invocations": invocations}

    # ------------------------------------------------------------------
    # Context pack manifest endpoints (V1-11A)
    # ------------------------------------------------------------------

    @app.get("/v1/context-pack-manifests")
    def list_context_pack_manifests() -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            manifests = [
                {
                    "manifest_id": m.manifest_id,
                    "pack_type": m.pack_type,
                    "pack_version": m.pack_version,
                    "title": m.title,
                    "description": m.description,
                    "checksum_algorithm": m.checksum_algorithm,
                    "checksum": m.checksum,
                    "model_profile_id": m.model_profile_id,
                    "model_name": m.model_name,
                    "token_count": m.token_count,
                    "created_at": m.created_at,
                    "created_by": m.created_by,
                }
                for m in uow.v1_context_pack_manifests.list()
            ]
        return {"context_pack_manifests": manifests}

    @app.get("/v1/jobs/{job_id}/context-pack-manifests")
    def list_job_context_pack_manifests(job_id: str) -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            manifests = [
                {
                    "manifest_id": m.manifest_id,
                    "pack_type": m.pack_type,
                    "pack_version": m.pack_version,
                    "title": m.title,
                    "description": m.description,
                    "checksum_algorithm": m.checksum_algorithm,
                    "checksum": m.checksum,
                    "model_profile_id": m.model_profile_id,
                    "model_name": m.model_name,
                    "token_count": m.token_count,
                    "created_at": m.created_at,
                    "created_by": m.created_by,
                }
                for m in uow.v1_context_pack_manifests.list_for_job(job_id)
            ]
        return {"context_pack_manifests": manifests}

    @app.get("/v1/context-pack-manifests/{manifest_id}")
    def get_context_pack_manifest(manifest_id: str) -> dict[str, Any]:
        with unit_of_work_factory() as uow:
            m = uow.v1_context_pack_manifests.get(manifest_id)
        if m is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "CONTEXT_PACK_MANIFEST_NOT_FOUND",
                f"Context pack manifest {manifest_id!r} not found",
            )
        return {
            "manifest_id": m.manifest_id,
            "pack_type": m.pack_type,
            "pack_version": m.pack_version,
            "title": m.title,
            "description": m.description,
            "evidence_refs_json": m.evidence_refs_json,
            "bounds_json": m.bounds_json,
            "redaction_policy": m.redaction_policy,
            "redacted_summary": m.redacted_summary,
            "checksum_algorithm": m.checksum_algorithm,
            "checksum": m.checksum,
            "model_profile_id": m.model_profile_id,
            "model_name": m.model_name,
            "token_count": m.token_count,
            "created_at": m.created_at,
            "created_by": m.created_by,
        }

    @app.post("/v1/jobs/{job_id}/plan-amendments", status_code=status.HTTP_201_CREATED)
    def create_plan_amendment(
        job_id: str,
        payload: CreatePlanAmendmentRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = PlanAmendmentService(unit_of_work_factory)
        try:
            record = service.create_amendment(
                job_id=job_id,
                source_kind=payload.source_kind,
                title=payload.title,
                summary=payload.summary,
                notes=payload.notes,
                changes=_plan_changes_from_request(payload.changes),
                created_by=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _plan_amendment_payload(service.to_amendment_dto(record))

    @app.post("/v1/plan-amendments/{amendment_id}/revisions", status_code=status.HTTP_201_CREATED)
    def create_plan_revision(
        amendment_id: str,
        payload: CreatePlanRevisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = PlanAmendmentService(unit_of_work_factory)
        try:
            record = service.create_revision(
                amendment_id=amendment_id,
                source_kind=payload.source_kind,
                title=payload.title,
                summary=payload.summary,
                notes=payload.notes,
                changes=_plan_changes_from_request(payload.changes),
                created_by=actor.actor_id,
                revision_order=payload.revision_order,
                revision_state=payload.revision_state,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _plan_revision_payload(service.to_revision_dto(record))

    @app.post("/v1/jobs/{job_id}/plan-amendments/preview")
    def preview_plan_amendment(
        job_id: str,
        payload: CreatePlanAmendmentRequest,
    ) -> dict[str, Any]:
        service = PlanAmendmentService(unit_of_work_factory)
        try:
            preview = service.preview_amendment(
                job_id=job_id,
                source_kind=payload.source_kind,
                title=payload.title,
                summary=payload.summary,
                notes=payload.notes,
                changes=_plan_changes_from_request(payload.changes),
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _plan_preview_payload(preview)

    @app.post("/v1/plan-amendments/{amendment_id}/fake-provider-proposals")
    def create_fake_provider_plan_proposal(
        amendment_id: str,
        payload: CreateFakeProviderProposalRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = FakeProviderPlanProposalService(unit_of_work_factory)
        raw_output = payload.model_dump(
            mode="json",
            exclude={"model_invocation_id", "context_pack_manifest_id"},
        )
        try:
            report = service.create_revision_from_fake_provider(
                amendment_id=amendment_id,
                raw_output=raw_output,
                created_by=actor.actor_id,
                model_invocation_id=payload.model_invocation_id,
                context_pack_manifest_id=payload.context_pack_manifest_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _advisory_validation_payload(report)

    @app.get("/v1/plan-revisions/{revision_id}/advisory-validation")
    def get_fake_provider_plan_validation(revision_id: str) -> dict[str, Any]:
        service = FakeProviderPlanProposalService(unit_of_work_factory)
        try:
            report = service.get_validation_report(revision_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _advisory_validation_payload(report)

    @app.post("/v1/plan-revisions/{revision_id}/review-decisions")
    def record_plan_review_decision(
        revision_id: str,
        payload: CreatePlanReviewDecisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = PlanReviewService(unit_of_work_factory)
        try:
            decision = service.record_review_decision(
                revision_id=revision_id,
                expected_checksum=payload.expected_checksum,
                decision=payload.decision,
                review_summary=payload.review_summary,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _plan_review_decision_payload(decision)

    @app.get("/v1/plan-revisions/{revision_id}/review-status")
    def get_plan_review_status(revision_id: str) -> dict[str, Any]:
        service = PlanReviewService(unit_of_work_factory)
        try:
            review_status = service.get_review_status(revision_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _plan_review_status_payload(review_status)

    @app.post("/v1/commands/{command_id}/repair-classifications")
    def classify_failed_command_for_repair(
        command_id: str,
        payload: CreateRepairClassificationRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = RepairService(unit_of_work_factory)
        try:
            classification = service.classify_failed_command(
                command_id=command_id,
                evidence_kind=payload.evidence_kind,
                failure_summary=payload.failure_summary,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _repair_classification_payload(classification)

    @app.post("/v1/commands/{command_id}/fake-repair-proposals")
    def record_fake_repair_proposal(
        command_id: str,
        payload: CreateFakeRepairProposalRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = RepairService(unit_of_work_factory)
        try:
            if payload.proposal_summary is None:
                proposal = service.generate_fake_repair_proposal(
                    command_id=command_id,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                    correlation_id=request.state.correlation_id,
                )
            else:
                proposal = service.record_fake_repair_proposal(
                    command_id=command_id,
                    proposal_summary=payload.proposal_summary,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                    correlation_id=request.state.correlation_id,
                )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _fake_repair_proposal_payload(proposal)

    @app.get("/v1/commands/{command_id}/fake-repair-proposals")
    def list_fake_repair_proposals(command_id: str) -> dict[str, Any]:
        service = RepairService(unit_of_work_factory)
        try:
            proposals = service.list_fake_repair_proposals(command_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return redact_public_data({
            "command_id": command_id,
            "proposals": [_fake_repair_proposal_payload(proposal) for proposal in proposals],
        })

    @app.post("/v1/commands/{command_id}/repair-attempts")
    def record_repair_attempt(
        command_id: str,
        payload: CreateRepairAttemptRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = RepairService(unit_of_work_factory)
        try:
            attempt = service.record_repair_attempt(
                command_id=command_id,
                attempt_summary=payload.attempt_summary,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _repair_attempt_payload(attempt)

    @app.get("/v1/commands/{command_id}/repair-status")
    def get_repair_status(command_id: str) -> dict[str, Any]:
        service = RepairService(unit_of_work_factory)
        try:
            repair_status = service.get_repair_status(command_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _repair_status_payload(repair_status)

    @app.get("/v1/commands/{command_id}/repair-attempts")
    def list_repair_attempts(command_id: str) -> dict[str, Any]:
        service = RepairService(unit_of_work_factory)
        try:
            attempts = service.list_repair_attempts(command_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return redact_public_data({
            "command_id": command_id,
            "attempts": [_repair_attempt_payload(attempt) for attempt in attempts],
        })

    # ------------------------------------------------------------------
    # Patch policy endpoints (V1-15A)
    # ------------------------------------------------------------------

    @app.post("/v1/commands/{command_id}/patch-policy-validations", status_code=status.HTTP_201_CREATED)
    def validate_patch_policy(
        command_id: str,
        payload: ValidatePatchRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        job_id = _resolve_job_id(command_id, unit_of_work_factory)
        service = PatchPolicyService(unit_of_work_factory)
        try:
            validation = service.validate_patch(
                command_id=command_id,
                job_id=job_id,
                target_path=payload.target_path,
                patch_content=payload.patch_content,
                patch_size_bytes=payload.patch_size_bytes,
                approval_id=payload.approval_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            # Rejections are recorded as validation records for audit
            rejection = service.validate_patch_and_reject(
                command_id=command_id,
                job_id=job_id,
                target_path=payload.target_path,
                patch_content=payload.patch_content,
                patch_size_bytes=payload.patch_size_bytes,
                rejection_reason=str(exc),
                approval_id=payload.approval_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "PATCH_POLICY_VIOLATION",
                str(exc),
            ) from exc
        return _patch_policy_validation_payload(validation)

    @app.get("/v1/commands/{command_id}/patch-policy-validations")
    def list_patch_policy_validations(command_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        try:
            validations = service.list_validations_for_command(command_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return {
            "command_id": command_id,
            "validations": [_patch_policy_validation_payload(v) for v in validations],
        }

    @app.get("/v1/patch-policy-validations/{validation_id}")
    def get_patch_policy_validation(validation_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        validation = service.get_validation(validation_id)
        if validation is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "VALIDATION_NOT_FOUND",
                f"Patch policy validation {validation_id!r} not found",
            )
        return _patch_policy_validation_payload(validation)

    @app.post("/v1/commands/{command_id}/sandbox-snapshots", status_code=status.HTTP_201_CREATED)
    def record_sandbox_snapshot(
        command_id: str,
        payload: RecordSandboxSnapshotRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        job_id = _resolve_job_id(command_id, unit_of_work_factory)
        service = PatchPolicyService(unit_of_work_factory)
        try:
            snapshot = service.record_sandbox_snapshot(
                command_id=command_id,
                job_id=job_id,
                stage_index=payload.stage_index,
                sandbox_artifact_id=payload.sandbox_artifact_id,
                sandbox_checksum=payload.sandbox_checksum,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _sandbox_snapshot_payload(snapshot)

    @app.get("/v1/commands/{command_id}/sandbox-snapshots")
    def get_sandbox_snapshot(command_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        snapshot = service.get_sandbox_snapshot_for_command(command_id)
        if snapshot is None:
            return {"command_id": command_id, "snapshot": None}
        return {
            "command_id": command_id,
            "snapshot": _sandbox_snapshot_payload(snapshot),
        }

    @app.post("/v1/commands/{command_id}/patch-applications", status_code=status.HTTP_201_CREATED)
    def apply_approved_patch(
        command_id: str,
        payload: ApplyApprovedPatchRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        job_id = _resolve_job_id(command_id, unit_of_work_factory)
        service = PatchPolicyService(unit_of_work_factory)
        try:
            application = service.apply_approved_patch(
                command_id=command_id,
                job_id=job_id,
                target_path=payload.target_path,
                patch_content=payload.patch_content,
                patch_size_bytes=payload.patch_size_bytes,
                stage_index=payload.stage_index,
                approval_id=payload.approval_id,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _patch_application_payload(application)

    @app.get("/v1/patch-applications/{application_id}")
    def get_patch_application(application_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        application = service.get_patch_application(application_id)
        if application is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "PATCH_APPLICATION_NOT_FOUND",
                f"Patch application {application_id!r} not found",
            )
        return _patch_application_payload(application)

    @app.get("/v1/commands/{command_id}/patch-applications")
    def get_patch_application_for_command(command_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        application = service.get_patch_application_for_command(command_id)
        if application is None:
            return {"command_id": command_id, "patch_application": None}
        return {
            "command_id": command_id,
            "patch_application": _patch_application_payload(application),
        }

    @app.post("/v1/commands/{command_id}/maven-validations", status_code=status.HTTP_201_CREATED)
    def record_maven_validation(
        command_id: str,
        payload: RecordMavenValidationRequest,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        job_id = _resolve_job_id(command_id, unit_of_work_factory)
        service = PatchPolicyService(unit_of_work_factory)
        try:
            validation = service.validate_patch_with_maven(
                command_id=command_id,
                job_id=job_id,
                maven_goal=payload.maven_goal,
                passed=payload.passed,
                result_summary=payload.result_summary,
                actor_type=actor.actor_type,
                actor_id=actor.actor_id,
                correlation_id=request.state.correlation_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return _maven_validation_payload(validation)

    @app.get("/v1/maven-validations/{maven_validation_id}")
    def get_maven_validation(maven_validation_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        validation = service.get_maven_validation(maven_validation_id)
        if validation is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "MAVEN_VALIDATION_NOT_FOUND",
                f"Maven validation {maven_validation_id!r} not found",
            )
        return _maven_validation_payload(validation)

    @app.get("/v1/commands/{command_id}/maven-validations")
    def get_maven_validation_for_command(command_id: str) -> dict[str, Any]:
        service = PatchPolicyService(unit_of_work_factory)
        application = service.get_patch_application_for_command(command_id)
        if application is None:
            return {"command_id": command_id, "maven_validation": None}
        validation = service.get_maven_validation_for_application(application.application_id)
        if validation is None:
            return {"command_id": command_id, "maven_validation": None}
        return {
            "command_id": command_id,
            "maven_validation": _maven_validation_payload(validation),
        }

    # ------------------------------------------------------------------
    # Approval endpoints (V1-07A)
    # ------------------------------------------------------------------

    class RecordApprovalRequest(BaseModel):
        model_config = ConfigDict(extra="forbid")
        interrupt_id: str
        request_checksum: str
        decision: str = Field(..., pattern="^(approved|rejected|replan_required)$")
        approved_by: str = Field(default="human", min_length=1)
        approval_comments: str = ""

    @app.post("/v1/approvals", status_code=status.HTTP_201_CREATED)
    async def record_approval(
        request: RecordApprovalRequest,
        http_request: Request,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-ID"),
    ) -> dict[str, Any]:
        actor = app.state.actor_provider.get_actor(http_request)
        service = ApprovalService(unit_of_work_factory)
        try:
            approval = service.record_approval(
                RecordApprovalCommand(
                    job_id="",
                    interrupt_id=request.interrupt_id,
                    request_checksum=request.request_checksum,
                    decision=request.decision,
                    approved_by=request.approved_by,
                    approval_comments=request.approval_comments,
                    actor_type=actor.actor_type,
                    actor_id=actor.actor_id,
                    correlation_id=correlation_id,
                )
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return {
            "approval_id": approval.approval_id,
            "interrupt_id": approval.interrupt_id,
            "decision": approval.decision,
            "approved_by": approval.approved_by,
            "created_at": approval.created_at,
        }

    @app.get("/v1/approvals/{approval_id}")
    def get_approval(approval_id: str) -> dict[str, Any]:
        service = ApprovalService(unit_of_work_factory)
        approval = service.get_approval(approval_id)
        if approval is None:
            raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"Approval {approval_id!r} not found.")
        return {
            "approval_id": approval.approval_id,
            "job_id": approval.job_id,
            "interrupt_id": approval.interrupt_id,
            "decision": approval.decision,
            "approved_by": approval.approved_by,
            "approval_comments": approval.approval_comments,
            "created_at": approval.created_at,
        }

    @app.get("/v1/jobs/{job_id}/approvals")
    def list_job_approvals(job_id: str) -> dict[str, Any]:
        service = ApprovalService(unit_of_work_factory)
        approvals = service.list_approvals_for_job(job_id)
        return {
            "job_id": job_id,
            "approvals": [
                {
                    "approval_id": a.approval_id,
                    "interrupt_id": a.interrupt_id,
                    "decision": a.decision,
                    "approved_by": a.approved_by,
                    "approval_comments": a.approval_comments,
                    "created_at": a.created_at,
                }
                for a in approvals
            ],
        }

    @app.get("/v1/jobs/{job_id}/proof-gates")
    def get_proof_gates(job_id: str) -> dict[str, Any]:
        service = DeterministicProofGateService(unit_of_work_factory)
        try:
            gates = service.compute_proof_gates(job_id)
            return {
                "job_id": job_id,
                "gates": {str(k): v for k, v in gates.items()},
                "gate_count": len(gates),
                "required_gates": 3,
                "algorithm": "sha256",
            }
        except ControlTowerError as exc:
            _raise_http_error(exc)
        except ValueError as exc:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "PROOF_GATES_INCOMPLETE",
                str(exc),
            )

    @app.post("/v1/jobs/{job_id}/proof-gates", status_code=status.HTTP_201_CREATED)
    def compute_proof_gates(
        job_id: str,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = DeterministicProofGateService(unit_of_work_factory)
        try:
            gates = service.compute_proof_gates(
                job_id,
                computed_by=actor.actor_id,
            )
            return {
                "job_id": job_id,
                "gates": {str(k): v for k, v in gates.items()},
                "gate_count": len(gates),
                "required_gates": 3,
                "algorithm": "sha256",
            }
        except ControlTowerError as exc:
            _raise_http_error(exc)
        except ValueError as exc:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "PROOF_GATES_INCOMPLETE",
                str(exc),
            )

    @app.get("/v1/jobs/{job_id}/proof-report")
    def get_proof_report(job_id: str) -> dict[str, Any]:
        service = FinalReportService(unit_of_work_factory)
        report = service.get_report(job_id)
        if report is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "PROOF_REPORT_NOT_FOUND",
                f"No proof report found for job {job_id!r}.",
            )
        return report

    @app.post("/v1/jobs/{job_id}/proof-report", status_code=status.HTTP_201_CREATED)
    def generate_proof_report(
        job_id: str,
        request: Request,
    ) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        service = FinalReportService(unit_of_work_factory)
        try:
            report = service.generate_final_report(
                job_id=job_id,
                generated_by=actor.actor_id,
            )
        except ControlTowerError as exc:
            _raise_http_error(exc)
        except ValueError as exc:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "PROOF_GATES_INCOMPLETE",
                str(exc),
            )
        return report

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

    @app.get("/v1/jobs/{job_id}/stages")
    def list_stage_chain(job_id: str) -> dict[str, Any]:
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            chain = query_service.get_stage_chain(job_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)
        return {
            "job_id": job_id,
            "stages": [_stage_chain_entry_payload(entry) for entry in chain],
        }

    @app.get("/v1/jobs/{job_id}/continuation-policy")
    def get_continuation_policy(job_id: str) -> dict[str, Any]:
        """Get the stage continuation policy status for a job.

        Returns the policy status for each stage, including whether
        the stage is blocked, queued, or ready to proceed.

        Browser payloads CANNOT choose raw paths, Maven goals, shell
        commands, working directories, or model deployments.
        """
        query_service = ControlTowerQueryService(unit_of_work_factory)
        try:
            chain = query_service.get_stage_chain(job_id)
        except ControlTowerError as exc:
            _raise_http_error(exc)

        policy_service = StageContinuationPolicyService(unit_of_work_factory)
        stages: list[dict[str, Any]] = []
        for entry in chain:
            allowed, reason = policy_service.check_stage_readiness(
                job_id, entry.stage_index
            )
            stages.append({
                "stage_index": entry.stage_index,
                "stage_run_id": entry.stage_run_id,
                "chain_status": entry.chain_status,
                "input_source_kind": entry.input_source_kind,
                "input_checksum": entry.input_checksum,
                "output_checksum": entry.output_checksum,
                "policy_allowed": allowed,
                "policy_reason": reason,
            })

        # Collect continuation events
        events = query_service.get_continuation_policy_events(job_id)
        return {
            "job_id": job_id,
            "pipeline_id": "springboot-216-to-356-java21-three-stage",
            "stages": stages,
            "continuation_events": [
                {
                    "event_id": e.event_id,
                    "stage_index": e.stage_index,
                    "event_type": e.event_type,
                    "new_status": e.new_status,
                    "created_at": e.created_at,
                }
                for e in events
            ],
        }

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


def _stage_chain_entry_payload(entry: StageChainEntryDto) -> dict[str, Any]:
    return redact_public_data({
        "ledger_id": entry.ledger_id,
        "job_id": entry.job_id,
        "stage_index": entry.stage_index,
        "stage_run_id": entry.stage_run_id,
        "chain_status": entry.chain_status,
        "input_source_kind": entry.input_source_kind,
        "input_checksum": entry.input_checksum,
        "output_artifact_id": entry.output_artifact_id,
        "output_checksum": entry.output_checksum,
        "output_registered_at": entry.output_registered_at,
        "created_at": entry.created_at,
    })


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


def _plan_changes_from_request(changes: tuple[PlanChangeRequest, ...]) -> tuple[PlanChange, ...]:
    return tuple(
        PlanChange(
            stage_index=change.stage_index,
            change_type=change.change_type,
            description=change.description,
            rationale=change.rationale,
        )
        for change in changes
    )


def _plan_amendment_payload(amendment: Any) -> dict[str, Any]:
    return redact_public_data({
        "amendment_id": amendment.amendment_id,
        "job_id": amendment.job_id,
        "source_kind": amendment.source_kind,
        "title": amendment.title,
        "summary": amendment.summary,
        "payload_checksum": amendment.payload_checksum,
        "redacted_summary": amendment.redacted_summary,
        "created_at": amendment.created_at,
        "created_by": amendment.created_by,
    })


def _plan_revision_payload(revision: Any) -> dict[str, Any]:
    return redact_public_data({
        "revision_id": revision.revision_id,
        "amendment_id": revision.amendment_id,
        "job_id": revision.job_id,
        "revision_order": revision.revision_order,
        "revision_state": revision.revision_state,
        "source_kind": revision.source_kind,
        "payload_checksum": revision.payload_checksum,
        "redacted_summary": revision.redacted_summary,
        "created_at": revision.created_at,
        "created_by": revision.created_by,
        "decided_at": revision.decided_at,
        "decided_by": revision.decided_by,
    })


def _plan_preview_payload(preview: Any) -> dict[str, Any]:
    return redact_public_data({
        "job_id": preview.job_id,
        "source_kind": preview.source_kind,
        "title": preview.title,
        "summary": preview.summary,
        "payload_checksum": preview.payload_checksum,
        "change_count": preview.change_count,
        "affected_stage_indexes": list(preview.affected_stage_indexes),
        "change_types": list(preview.change_types),
        "redacted_summary": preview.redacted_summary,
        "validation_status": preview.validation_status,
        "warning_codes": list(preview.warning_codes),
        "preview_persisted": preview.preview_persisted,
        "preview_applied": preview.preview_applied,
    })


def _advisory_validation_payload(report: Any) -> dict[str, Any]:
    return redact_public_data({
        "amendment_id": report.amendment_id,
        "job_id": report.job_id,
        "validation_status": report.validation_status,
        "source_kind": report.source_kind,
        "revision_persisted": report.revision_persisted,
        "non_authoritative": report.non_authoritative,
        "warning_codes": list(report.warning_codes),
        "rejection_codes": list(report.rejection_codes),
        "confidence_label": report.confidence_label,
        "confidence_score": report.confidence_score,
        "payload_checksum": report.payload_checksum,
        "model_invocation_id": report.model_invocation_id,
        "context_pack_manifest_id": report.context_pack_manifest_id,
        "revision_id": report.revision_id,
        "revision_order": report.revision_order,
        "revision_state": report.revision_state,
        "redacted_summary": report.redacted_summary,
    })


def _plan_review_decision_payload(decision: Any) -> dict[str, Any]:
    return redact_public_data({
        "review_decision_id": decision.review_decision_id,
        "revision_id": decision.revision_id,
        "amendment_id": decision.amendment_id,
        "job_id": decision.job_id,
        "decision": decision.decision,
        "reviewed_checksum": decision.reviewed_checksum,
        "review_summary": decision.review_summary,
        "actor_type": decision.actor_type,
        "actor_id": decision.actor_id,
        "created_at": decision.created_at,
    })


def _plan_review_status_payload(review_status: Any) -> dict[str, Any]:
    return redact_public_data({
        "revision_id": review_status.revision_id,
        "amendment_id": review_status.amendment_id,
        "job_id": review_status.job_id,
        "payload_checksum": review_status.payload_checksum,
        "review_required": review_status.review_required,
        "eligible_for_downstream": review_status.eligible_for_downstream,
        "status": review_status.status,
        "decision": review_status.decision,
        "review_summary": review_status.review_summary,
        "review_decision_id": review_status.review_decision_id,
        "reviewed_checksum": review_status.reviewed_checksum,
        "created_at": review_status.created_at,
    })


def _repair_classification_payload(classification: Any) -> dict[str, Any]:
    return redact_public_data({
        "classification_id": classification.classification_id,
        "command_id": classification.command_id,
        "job_id": classification.job_id,
        "command_status": classification.command_status,
        "evidence_kind": classification.evidence_kind,
        "evidence_summary": classification.evidence_summary,
        "evidence_checksum": classification.evidence_checksum,
        "classification_code": classification.classification_code,
        "reason_code": classification.reason_code,
        "repairable": classification.repairable,
        "attempt_limit": classification.attempt_limit,
        "actor_type": classification.actor_type,
        "actor_id": classification.actor_id,
        "created_at": classification.created_at,
    })


def _fake_repair_proposal_payload(proposal: Any) -> dict[str, Any]:
    return redact_public_data({
        "proposal_id": proposal.proposal_id,
        "classification_id": proposal.classification_id,
        "command_id": proposal.command_id,
        "job_id": proposal.job_id,
        "proposal_order": proposal.proposal_order,
        "proposal_kind": proposal.proposal_kind,
        "proposal_summary": proposal.proposal_summary,
        "proposal_checksum": proposal.proposal_checksum,
        "recommendation_type": proposal.recommendation_type,
        "confidence_label": proposal.confidence_label,
        "confidence_score": proposal.confidence_score,
        "warning_codes": list(proposal.warning_codes),
        "applicable": proposal.applicable,
        "context_checksum": proposal.context_checksum,
        "actor_type": proposal.actor_type,
        "actor_id": proposal.actor_id,
        "created_at": proposal.created_at,
    })


def _repair_attempt_payload(attempt: Any) -> dict[str, Any]:
    return redact_public_data({
        "attempt_id": attempt.attempt_id,
        "classification_id": attempt.classification_id,
        "command_id": attempt.command_id,
        "job_id": attempt.job_id,
        "attempt_order": attempt.attempt_order,
        "attempt_status": attempt.attempt_status,
        "attempt_summary": attempt.attempt_summary,
        "attempt_checksum": attempt.attempt_checksum,
        "actor_type": attempt.actor_type,
        "actor_id": attempt.actor_id,
        "created_at": attempt.created_at,
    })


def _repair_status_payload(repair_status: Any) -> dict[str, Any]:
    return redact_public_data({
        "command_id": repair_status.command_id,
        "job_id": repair_status.job_id,
        "command_status": repair_status.command_status,
        "classification": (
            _repair_classification_payload(repair_status.classification)
            if repair_status.classification is not None
            else None
        ),
        "attempts_used": repair_status.attempts_used,
        "proposal_count": repair_status.proposal_count,
        "attempt_limit": repair_status.attempt_limit,
        "remaining_attempts": repair_status.remaining_attempts,
        "eligible_for_fake_repair": repair_status.eligible_for_fake_repair,
        "attempts": [
            _repair_attempt_payload(attempt)
            for attempt in repair_status.attempts
        ],
        "proposals": [
            _fake_repair_proposal_payload(proposal)
            for proposal in repair_status.proposals
        ],
    })


def _patch_policy_validation_payload(validation: Any) -> dict[str, Any]:
    return redact_public_data({
        "validation_id": validation.validation_id,
        "command_id": validation.command_id,
        "job_id": validation.job_id,
        "approved": validation.approved,
        "validation_code": validation.validation_code,
        "reason_code": validation.reason_code,
        "target_path_hash": validation.target_path_hash,
        "patch_size_bytes": validation.patch_size_bytes,
        "metacharacter_hits": validation.metacharacter_hits,
        "policy_version": validation.policy_version,
        "actor_type": validation.actor_type,
        "actor_id": validation.actor_id,
        "created_at": validation.created_at,
    })


def _sandbox_snapshot_payload(snapshot: Any) -> dict[str, Any]:
    return redact_public_data({
        "snapshot_id": snapshot.snapshot_id,
        "command_id": snapshot.command_id,
        "job_id": snapshot.job_id,
        "stage_index": snapshot.stage_index,
        "sandbox_artifact_id": snapshot.sandbox_artifact_id,
        "sandbox_checksum": snapshot.sandbox_checksum,
        "actor_type": snapshot.actor_type,
        "actor_id": snapshot.actor_id,
        "created_at": snapshot.created_at,
    })


def _maven_validation_payload(validation: Any) -> dict[str, Any]:
    return redact_public_data({
        "maven_validation_id": validation.maven_validation_id,
        "application_id": validation.application_id,
        "command_id": validation.command_id,
        "job_id": validation.job_id,
        "maven_goal": validation.maven_goal,
        "passed": validation.passed,
        "result_summary": validation.result_summary,
        "actor_type": validation.actor_type,
        "actor_id": validation.actor_id,
        "created_at": validation.created_at,
    })


def _patch_application_payload(application: Any) -> dict[str, Any]:
    return redact_public_data({
        "application_id": application.application_id,
        "command_id": application.command_id,
        "job_id": application.job_id,
        "validation_id": application.validation_id,
        "snapshot_id": application.snapshot_id,
        "stage_index": application.stage_index,
        "target_path_hash": application.target_path_hash,
        "patch_size_bytes": application.patch_size_bytes,
        "applied_by": application.applied_by,
        "applied_at": application.applied_at,
        "status": application.status,
    })


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
    if isinstance(exc, PlanRevisionConflictError):
        raise _error(status.HTTP_409_CONFLICT, "PLAN_REVISION_CONFLICT", str(exc)) from exc
    if isinstance(exc, PlanAdvisoryValidationError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PLAN_ADVISORY_INVALID", str(exc)) from exc
    if isinstance(exc, PlanReviewChecksumMismatchError):
        raise _error(status.HTTP_409_CONFLICT, "PLAN_REVIEW_STALE_CHECKSUM", str(exc)) from exc
    if isinstance(exc, PlanReviewConflictError):
        raise _error(status.HTTP_409_CONFLICT, "PLAN_REVIEW_CONFLICT", str(exc)) from exc
    if isinstance(exc, PlanAmendmentValidationError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PLAN_AMENDMENT_INVALID", str(exc)) from exc
    if isinstance(exc, RepairProposalValidationError):
        raise _error(status.HTTP_400_BAD_REQUEST, "REPAIR_PROPOSAL_INVALID", str(exc)) from exc
    if isinstance(exc, RepairClassificationError):
        raise _error(status.HTTP_409_CONFLICT, "REPAIR_CLASSIFICATION_CONFLICT", str(exc)) from exc
    if isinstance(exc, RepairAttemptLimitExceededError):
        raise _error(status.HTTP_409_CONFLICT, "REPAIR_ATTEMPT_LIMIT_REACHED", str(exc)) from exc
    if isinstance(exc, PatchContentEscapeError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_ESCAPE_DETECTED", str(exc)) from exc
    if isinstance(exc, PatchContentMismatchError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_PATH_MISMATCH", str(exc)) from exc
    if isinstance(exc, PatchContentOversizeError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_OVERSIZE", str(exc)) from exc
    if isinstance(exc, PatchNotApprovedError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_NOT_APPROVED", str(exc)) from exc
    if isinstance(exc, PatchSnapshotNotFoundError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_SNAPSHOT_NOT_FOUND", str(exc)) from exc
    if isinstance(exc, PatchRollbackError):
        raise _error(status.HTTP_500_INTERNAL_SERVER_ERROR, "PATCH_ROLLBACK_FAILED", str(exc)) from exc
    if isinstance(exc, PatchPolicyValidationError):
        raise _error(status.HTTP_400_BAD_REQUEST, "PATCH_POLICY_VIOLATION", str(exc)) from exc
    if isinstance(exc, StaleVersionError):
        raise _error(status.HTTP_412_PRECONDITION_FAILED, "JOB_VERSION_CONFLICT", str(exc)) from exc
    if isinstance(exc, ExpectedVersionRequiredError):
        raise _error(status.HTTP_428_PRECONDITION_REQUIRED, "PRECONDITION_REQUIRED", str(exc)) from exc
    if isinstance(exc, NotFoundError):
        raise _error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", str(exc)) from exc
    if isinstance(exc, (InvalidJobStateTransitionError, ActiveCommandConflictError)):
        raise _error(status.HTTP_409_CONFLICT, "ACTIVE_COMMAND_CONFLICT", str(exc)) from exc
    raise _error(status.HTTP_400_BAD_REQUEST, "CONTROL_TOWER_ERROR", str(exc)) from exc


def _resolve_job_id(command_id: str, uow_factory: UnitOfWorkFactory) -> str:
    """Resolve job_id from command_id using the command_executions repository."""
    with uow_factory() as uow:
        command = uow.command_executions.get(command_id)
    if command is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "COMMAND_NOT_FOUND",
            f"Command {command_id!r} not found.",
        )
    if not command.job_id:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "COMMAND_HAS_NO_JOB",
            f"Command {command_id!r} has no associated job.",
        )
    return command.job_id


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
