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

from pathlib import Path, PureWindowsPath

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
from migration_factory.control_tower.application.env_parser import (
    EnvParseResult,
    parse_env_block,
    parse_result_to_dict,
)
from migration_factory.control_tower.application.v2_azure_health_service import (
    V2AzureHealthService,
)
from migration_factory.control_tower.application.v2_job_service import (
    V2MigrationJobService,
)
from migration_factory.control_tower.application.v2_worker_stage import (
    V2WorkerStageService,
)
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    is_ai_smoke_required,
    V2SetupService,
)
from migration_factory.control_tower.application.v2_settings import (
    ControlTowerSettings,
    build_settings_projection,
    settings_projection_to_dict,
)
from migration_factory.control_tower.application.v2_approval_mapping import (
    V2ApprovalMappingService,
)
from migration_factory.control_tower.application.v2_stage_progression import (
    V2StageProgressionService,
)
from migration_factory.control_tower.application.v2_assistant_service import (
    V2AssistantService,
)
from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
)
from migration_factory.control_tower.application.v2_model_schemas import (
    validate_against_schema,
    SchemaValidationError,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.control_tower.application.v2_orchestrator_runner import (
    V2OrchestratorRunner,
    _bounded,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    create_orchestrator_diagnosis_callback,
)
from migration_factory.control_tower.application.redaction import redact_public_value
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
from migration_factory.control_tower.application.redaction import redact_model_summary


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


class RecordApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interrupt_id: str
    request_checksum: str
    decision: str = Field(..., pattern="^(approved|rejected|replan_required)$")
    approved_by: str = Field(default="human", min_length=1)
    approval_comments: str = ""


class ParseEnvRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    env_block: str


class CreateSetupRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_name: str
    legacy_app_path: str
    output_parent_path: str
    ai_hub_path: str
    java11_home: str
    java17_home: str
    java21_home: str
    maven_cmd: str
    proof_level: str = "build_test_verified"
    skip_endpoint_smoke: bool = False
    migration_flags: dict[str, Any] = {}
    correlation_id: str | None = None


class PreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_id: str


class CreateV2JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_id: str


class StartV2JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    setup_id: str


class ApproveCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_checksum: str


# F07 reviewer request — context only, no decision from client

class CreateReviewerCritiqueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    proposal_type: str = "repair"  # repair, pom_patch
    proposal_checksum: str
    context_pack_checksum: str
    # Internal: model_invocation_id for audit (set by orchestrator, not client)
    model_invocation_id: str | None = None
    # F07: decision, reasoning, missing_evidence, unsafe_assumptions are
    # NEVER accepted from client body — the model generates them.


class StageProgressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    setup_id: str
    current_stage: int
    sandbox_path: str


class AssistantMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    role: str
    content: str
    correlation_id: str | None = None


class AssistantAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    correlation_id: str | None = None


class DraftActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    action_type: str
    reason: str
    stage_index: int = 1
    # F05: optional revision steering fields
    source_proposal_id: str | None = None
    failed_command_id: str | None = None
    revision_instruction: str | None = None
    context_pack_checksum: str | None = None
    revision_of: str | None = None
    revision_number: int | None = Field(default=None, ge=1)
    allowed_scope: str | None = None


class CreateRepairProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: str
    failure_summary: str
    hypothesis: str
    patch_summary: str
    affected_paths: list[str]


class ApproveRepairProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_checksum: str
    # F07: both checksums required — reviewer gate is mandatory, no bypass
    proposal_checksum: str
    context_pack_checksum: str


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
    v2_orchestrator_runner: Any | None = None,
    v2_assistant_model_client: Any | None = None,
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
    app.state.v2_settings = ControlTowerSettings()
    app.state.v2_assistant_model_client = v2_assistant_model_client or V2AssistantModelClient()
    app.state.worker_launcher = worker_launcher
    app.state.worker_terminator = worker_terminator
    # ── F02: Wire automatic failure diagnosis into the orchestrator ──
    def _diagnosis_event_sink(
        job_id: str,
        stage: int | None,
        event_type: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        with unit_of_work_factory() as uow:
            redacted_payload = redact_public_value(payload or {})
            uow.v2_events.save(
                job_id=job_id,
                stage=stage,
                event_type=event_type,
                status=status,
                message=_bounded(str(redact_public_value(message))),
                payload=redacted_payload if isinstance(redacted_payload, dict) else {},
            )
        if app.state.public_event_notifier is not None:
            asyncio.run(app.state.public_event_notifier.notify())

    _repair_flow = V2RepairFlowService()
    _diagnosis_callback = create_orchestrator_diagnosis_callback(
        repair_flow=_repair_flow,
        event_sink=_diagnosis_event_sink,
    )

    app.state.v2_orchestrator_runner = v2_orchestrator_runner or V2OrchestratorRunner(
        unit_of_work_factory=unit_of_work_factory,
        notifier=app.state.public_event_notifier,
        diagnosis_callback=_diagnosis_callback,
    )
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

    @app.get("/v1/settings/ai")
    def get_ai_settings() -> dict[str, Any]:
        """Return redacted Azure Foundry settings with env refs only.

        Never returns endpoint URLs, API keys, deployment IDs, or any
        secret values. The UI receives env ref names and booleans only.
        """
        settings: ControlTowerSettings = app.state.v2_settings
        projection = build_settings_projection(settings)
        return settings_projection_to_dict(projection)

    # ------------------------------------------------------------------
    # V2 Azure health check endpoint (A4)
    # ------------------------------------------------------------------

    @app.post("/v1/model-profiles/{profile_id}/health-check")
    def run_model_health_check(
        profile_id: str,
    ) -> dict[str, Any]:
        """Run a redacted Azure model health check.

        Health checks are non-blocking: Azure BLOCKED/DEGRADED does
        not prevent deterministic migration start. It only affects AI
        assistant features.
        """
        settings: ControlTowerSettings = app.state.v2_settings
        with unit_of_work_factory() as uow:
            service = V2AzureHealthService(uow.v2_azure_health, settings)
            result = service.run_health_check(profile_id=profile_id)
        return service.health_to_dict(result)

    @app.get("/v1/model-profiles/{profile_id}/health")
    def get_model_health(profile_id: str) -> dict[str, Any]:
        """Get the latest health check for a model profile."""
        settings: ControlTowerSettings = app.state.v2_settings
        with unit_of_work_factory() as uow:
            service = V2AzureHealthService(uow.v2_azure_health, settings)
            result = service.get_latest_health(profile_id)
        return service.health_to_dict(result)

    # ------------------------------------------------------------------
    # V2 Setup parser endpoint (A2)
    # ------------------------------------------------------------------

    @app.post("/v1/migration-setups/parse-env")
    async def parse_env(
        payload: ParseEnvRequest,
    ) -> dict[str, Any]:
        """Parse a pasted PowerShell env block into typed local setup fields.

        The parser is pure: no execution, no I/O, no persistence. It
        extracts only allowlisted keys, returns ignored/blocked key sets,
        and maps known flags to typed options.
        """
        result = parse_env_block(payload.env_block)
        return parse_result_to_dict(result)

    # ------------------------------------------------------------------
    # V2 Setup persistence and preflight endpoints (A3)
    # ------------------------------------------------------------------

    @app.post("/v1/migration-setups", status_code=status.HTTP_201_CREATED)
    def create_setup(
        payload: CreateSetupRequestSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Create a new V2 migration setup draft."""
        with unit_of_work_factory() as uow:
            service = V2SetupService(uow.v2_setups)
            req = CreateSetupRequest(
                run_name=payload.run_name,
                legacy_app_path=payload.legacy_app_path,
                output_parent_path=payload.output_parent_path,
                ai_hub_path=payload.ai_hub_path,
                java11_home=payload.java11_home,
                java17_home=payload.java17_home,
                java21_home=payload.java21_home,
                maven_cmd=payload.maven_cmd,
                proof_level=payload.proof_level,
                skip_endpoint_smoke=payload.skip_endpoint_smoke,
                migration_flags=payload.migration_flags,
                created_by="operator",
                correlation_id=payload.correlation_id or request.state.correlation_id,
            )
            dto = service.create_setup(req)
        return service.setup_to_dict(dto)

    @app.get("/v1/migration-setups")
    def list_setups() -> dict[str, Any]:
        """List all V2 migration setup drafts."""
        with unit_of_work_factory() as uow:
            service = V2SetupService(uow.v2_setups)
            dtos = service.list_setups()
        return {
            "setups": [service.setup_to_dict(dto) for dto in dtos],
        }

    @app.get("/v1/migration-setups/{setup_id}")
    def get_setup(setup_id: str) -> dict[str, Any]:
        """Get a V2 migration setup draft by ID."""
        with unit_of_work_factory() as uow:
            service = V2SetupService(uow.v2_setups)
            dto = service.get_setup(setup_id)
        if dto is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "SETUP_NOT_FOUND",
                f"Setup {setup_id!r} not found",
            )
        return service.setup_to_dict(dto)

    @app.post("/v1/migration-setups/preflight", status_code=status.HTTP_201_CREATED)
    def run_preflight(
        payload: PreflightRequest,
        request: Request,
    ) -> dict[str, Any]:
        """Run preflight readiness checks for a setup."""
        with unit_of_work_factory() as uow:
            service = V2SetupService(
                uow.v2_setups,
                model_client=app.state.v2_assistant_model_client,
            )
            try:
                dto = service.run_preflight(
                    setup_id=payload.setup_id,
                    checked_by="operator",
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "SETUP_NOT_FOUND",
                    str(exc),
                ) from exc
        return service.preflight_to_dict(dto)

    @app.get("/v1/migration-setups/{setup_id}/readiness")
    def get_readiness(setup_id: str) -> dict[str, Any]:
        """Get the latest preflight readiness for a setup."""
        with unit_of_work_factory() as uow:
            service = V2SetupService(uow.v2_setups)
            readiness = service.get_readiness(setup_id)
        return service.readiness_to_dict(readiness)

    # ------------------------------------------------------------------
    # V2 Azure model smoke check
    # ------------------------------------------------------------------

    @app.post("/v1/v2/azure/check-smoke")
    def check_azure_smoke() -> dict[str, Any]:
        """Check Azure OpenAI model readiness with a real smoke call.

        Sends a tiny prompt to the configured deployment and returns
        a sanitised result.  Never exposes API keys or secrets.
        """
        client = app.state.v2_assistant_model_client
        result = client.smoke()
        return {
            "success": result.success,
            "provider": result.provider,
            "failure_reason": result.failure_reason,
            "redacted_summary": redact_model_summary(result.redacted_summary),
            "response_snippet": redact_model_summary(result.response_snippet),
            "latency_ms": result.latency_ms,
            "checked_at": result.checked_at,
        }

    # ------------------------------------------------------------------
    # V2 Migration job creation endpoint (A6)
    # ------------------------------------------------------------------

    @app.post("/v1/v2/migration-jobs", status_code=status.HTTP_201_CREATED)
    def create_v2_job(
        payload: CreateV2JobRequest,
    ) -> dict[str, Any]:
        """Create a V2 parent migration job from a ready setup.

        Requires a setup with a current READY preflight. Azure-only
        failures do not block job creation.
        """
        with unit_of_work_factory() as uow:
            service = V2MigrationJobService(
                setup_repo=uow.v2_setups,
                job_repo=uow.v2_jobs,
            )
            try:
                result = service.create_job(payload.setup_id)
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "JOB_CREATION_FAILED",
                    str(exc),
                ) from exc
            _append_v2_event(
                uow,
                job_id=result.job_id,
                stage=None,
                event_type="job_created",
                status="created",
                message="V2 migration job created.",
                payload={"setup_id": result.setup_id, "pipeline_id": result.pipeline_id},
            )
        return service.result_to_dict(result)

    @app.get("/v1/v2/migration-jobs/{job_id}")
    def get_v2_job(job_id: str) -> dict[str, Any]:
        """Return persisted V2 parent job projection."""
        with unit_of_work_factory() as uow:
            service = V2MigrationJobService(
                setup_repo=uow.v2_setups,
                job_repo=uow.v2_jobs,
            )
            result = service.get_job(job_id)
        if result is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "JOB_NOT_FOUND",
                f"V2 migration job {job_id!r} not found.",
            )
        return service.result_to_dict(result)

    @app.get(
        "/v1/v2/jobs/{job_id}/stages",
        include_in_schema=False,
        operation_id="get_v2_job_stages_alias",
    )
    @app.get("/v1/v2/migration-jobs/{job_id}/stages")
    def get_v2_job_stages(job_id: str) -> dict[str, Any]:
        """Return three fixed V2 stages with state derived from commands/events."""
        with unit_of_work_factory() as uow:
            job = _require_v2_job(uow, job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            events = uow.v2_events.list_by_job(job_id)
        return {
            "job_id": job_id,
            "stages": _v2_stages_from_job(job, commands, events),
        }

    @app.get("/v1/v2/jobs/{job_id}/approvals")
    def list_v2_job_approvals(job_id: str) -> dict[str, Any]:
        """Return V2 approval cards, or [] for valid jobs with no cards."""
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            cards = uow.v2_approvals.list_cards_by_job(job_id)
            service = V2ApprovalMappingService(approval_repo=uow.v2_approvals)
        return {
            "job_id": job_id,
            "approvals": [service.card_to_dict(card) for card in cards],
        }

    # ------------------------------------------------------------------
    # V2 Worker Stage 1 execution endpoint (A7)
    # ------------------------------------------------------------------

    @app.post("/v1/v2/migration-jobs/start-stage1")
    def start_v2_stage1(
        payload: StartV2JobRequest,
    ) -> dict[str, Any]:
        """Start Stage 1 for a V2 migration job.

        Builds a backend-owned command manifest from the V2 setup.
        Browser cannot supply argv or env values.
        Blocks start when AI is required and the model smoke failed.
        """
        with unit_of_work_factory() as uow:
            job = _require_v2_job(uow, payload.job_id)
            if job.setup_id != payload.setup_id:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "JOB_SETUP_MISMATCH",
                    "Stage start setup_id must match the persisted job.",
                )
            # Check AI readiness from the latest persisted preflight
            setup = uow.v2_setups.get(job.setup_id)
            if setup is not None and is_ai_smoke_required(setup.skip_endpoint_smoke):
                preflight_svc = V2SetupService(uow.v2_setups)
                readiness = preflight_svc.get_readiness(job.setup_id)
                if readiness is None:
                    raise _error(
                        status.HTTP_400_BAD_REQUEST,
                        "AI_MODEL_SMOKE_REQUIRED",
                        "Run preflight before starting when AI smoke is required.",
                    )
                azure_ready = readiness.gates.get("azure_model_ready", True)
                if not azure_ready:
                    raise _error(
                        status.HTTP_400_BAD_REQUEST,
                        "AI_MODEL_NOT_READY",
                        "Azure model smoke failed. "
                        "Migration cannot start when AI is required and the model is unavailable. "
                        "Run preflight to see the failure reason.",
                    )
            service = V2WorkerStageService(
                setup_repo=uow.v2_setups,
                command_repo=uow.v2_commands,
            )
            try:
                result = service.build_stage1_manifest(
                    job_id=payload.job_id,
                    setup_id=payload.setup_id,
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "STAGE1_START_FAILED",
                    str(exc),
                ) from exc
            _append_v2_event(
                uow,
                job_id=payload.job_id,
                stage=1,
                event_type="stage_queued",
                status="queued",
                message="Stage 1 command manifest queued for real orchestrator execution.",
                payload={"command_id": result.command_id},
            )
        app.state.v2_orchestrator_runner.start(job_id=payload.job_id, command_id=result.command_id)
        asyncio.run(app.state.public_event_notifier.notify())
        return service.result_to_dict(result)

    @app.get(
        "/v1/v2/jobs/{job_id}/events/snapshot",
        include_in_schema=False,
        operation_id="get_v2_job_event_snapshot_alias",
    )
    @app.get("/v1/v2/migration-jobs/{job_id}/events/snapshot")
    def get_v2_job_event_snapshot(
        job_id: str,
        after: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        """Return ordered V2 cockpit events for tests/fallback clients."""
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            events = uow.v2_events.list_after_sequence(job_id, after)
        return {
            "job_id": job_id,
            "after": after,
            "events": [_v2_event_payload(event) for event in events],
            "latest_sequence": events[-1].sequence if events else after,
        }

    @app.get(
        "/v1/v2/jobs/{job_id}/pipeline",
        include_in_schema=False,
        operation_id="get_v2_job_pipeline_alias",
    )
    @app.get("/v1/v2/migration-jobs/{job_id}/pipeline")
    def get_v2_job_pipeline(job_id: str) -> dict[str, Any]:
        """Return operator-facing pipeline state derived from V2 events."""
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
        return redact_public_data(_v2_pipeline_projection(job_id, events))

    @app.get(
        "/v1/v2/jobs/{job_id}/failure-summary",
        include_in_schema=False,
        operation_id="get_v2_job_failure_summary_alias",
    )
    @app.get("/v1/v2/migration-jobs/{job_id}/failure-summary")
    def get_v2_job_failure_summary(job_id: str) -> dict[str, Any]:
        """Return redacted failure/repair summary for the cockpit.

        Never returns absolute paths, secrets, or raw token data.
        """
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
        return redact_public_data(_v2_failure_summary(job_id, events))

    @app.get("/v1/v2/jobs/{job_id}/artifacts/{artifact_kind}")
    def get_v2_job_artifact_preview(
        job_id: str,
        artifact_kind: str,
    ) -> dict[str, Any]:
        """Return a bounded, redacted preview of a named artifact.

        Only allows artifact kinds from persisted artifact_refs.
        Never accepts arbitrary paths.
        Bounds output to 32 KB.
        Redacts secrets and full local paths.
        """
        safe_kinds = {
            "phase2_log", "post_transform_test_log", "failure_classification",
            "repair_plan", "deterministic_repair_plan", "copilot_repair_response",
            "dependency_policy_report", "dependency_policy_summary",
            "dependency_repair_plan", "orchestration_summary",
            "target_dependency_plan", "rewrite_dry_run.patch",
            "rewrite_impact_summary.json", "repair_ledger", "migration_ledger",
        }
        if artifact_kind not in safe_kinds:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "UNKNOWN_ARTIFACT_KIND",
                f"Unknown artifact kind.",
            )
        with unit_of_work_factory() as uow:
            job = _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            # Look up setup to determine the trusted artifact workspace root
            setup = uow.v2_setups.get(job.setup_id) if job.setup_id else None

        if setup is None or not setup.output_parent_path:
            return {
                "job_id": job_id,
                "artifact_kind": artifact_kind,
                "exists": False,
                "preview": "",
                "truncated": False,
                "content_type": "text/plain",
            }

        # Find the artifact ref from artifact_written events belonging to this job
        artifact_path = None
        for event in events:
            if event.type == "artifact_written":
                try:
                    payload = json.loads(event.payload_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    continue
                kind = str(payload.get("artifact_kind", ""))
                if kind == artifact_kind:
                    path_val = payload.get("relative_path") or payload.get("path")
                    if path_val:
                        artifact_path = str(path_val)
                        break

        if not artifact_path:
            return {
                "job_id": job_id,
                "artifact_kind": artifact_kind,
                "exists": False,
                "preview": "",
                "truncated": False,
                "content_type": "text/plain",
            }

        # Resolve from stored artifact ref (not from request)
        try:
            from migration_factory.control_tower.application.redaction import redact_model_summary

            candidate = _resolve_v2_artifact_preview_path(
                artifact_ref=artifact_path,
                setup=setup,
                commands=commands,
            )
            if candidate is None:
                return {
                    "job_id": job_id,
                    "artifact_kind": artifact_kind,
                    "exists": False,
                    "preview": "",
                    "truncated": False,
                    "content_type": "text/plain",
                }

            # Read bounded preview
            max_bytes = 32768
            raw = candidate.read_bytes()[:max_bytes]
            truncated = len(raw) == max_bytes
            if raw[:3] == b"\xef\xbb\xbf":
                raw = raw[3:]
            try:
                text = raw.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, LookupError):
                text = raw.decode("latin-1", errors="replace")
            preview = redact_model_summary(text)
        except Exception:
            return {
                "job_id": job_id,
                "artifact_kind": artifact_kind,
                "exists": False,
                "preview": "",
                "truncated": False,
                "content_type": "text/plain",
            }

        return {
            "job_id": job_id,
            "artifact_kind": artifact_kind,
            "exists": True,
            "preview": preview,
            "truncated": truncated,
            "content_type": "text/plain",
        }

    @app.get("/v1/v2/migration-jobs/{job_id}/events")
    async def stream_v2_job_events(
        job_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
        once: bool = Query(default=False),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        """Stream V2 cockpit events as EventSource-compatible SSE."""
        try:
            cursor = int(last_event_id) if last_event_id else after
        except ValueError as exc:
            raise _error(status.HTTP_400_BAD_REQUEST, "INVALID_EVENT_CURSOR", "Last-Event-ID must be an integer.") from exc
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
        return EventSourceResponse(
            _v2_event_stream(
                job_id=job_id,
                initial_after_sequence=cursor,
                request=request,
                unit_of_work_factory=unit_of_work_factory,
                notifier=app.state.public_event_notifier,
                config=app.state.event_replay_config,
                once=once,
            )
        )

    # ------------------------------------------------------------------
    # V2 Approval mapping endpoints (A9/P0-005)
    # ------------------------------------------------------------------

    @app.post("/v1/v2/jobs/{job_id}/approvals/{card_id}/approve")
    def approve_decision_card(
        job_id: str,
        card_id: str,
        payload: ApproveCardRequest,
    ) -> dict[str, Any]:
        """Approve a decision card with checksum validation.

        Validates the expected checksum against the stored card.
        On success, queues a resume command. LLM cannot approve.
        """
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            card = uow.v2_approvals.get_card(card_id)
            if card is None:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "CARD_NOT_FOUND",
                    f"Decision card {card_id!r} not found",
                )
            commands = uow.v2_commands.list_by_job(job_id)
            run_dir = _v2_resume_run_dir_from_commands(commands, card.stage_index, card.interrupt_id)
            service = V2ApprovalMappingService(
                approval_repo=uow.v2_approvals,
            )
            try:
                card_before = service.get_card(card_id)
                resume = service.approve(
                    card_id=card_id,
                    expected_checksum=payload.expected_checksum,
                    job_id=job_id,
                    run_dir=run_dir,
                )
                is_new_approve = card_before is None or card_before.status != "approved"
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "APPROVAL_FAILED",
                    str(exc),
                ) from exc
            if is_new_approve and resume.resume_id:
                _append_v2_event(
                    uow,
                    job_id=job_id,
                    stage=resume.stage_index,
                    event_type="approval_resume_queued",
                    status="queued",
                    message="Approval accepted; backend-owned resume command queued.",
                    payload={"card_id": card_id, "resume_id": resume.resume_id},
                )
        if is_new_approve and resume.resume_id:
            app.state.v2_orchestrator_runner.start_resume(job_id=job_id, resume_id=resume.resume_id)
        asyncio.run(app.state.public_event_notifier.notify())
        return service.resume_to_dict(resume)

    @app.post("/v1/v2/jobs/{job_id}/approvals/{card_id}/reject")
    def reject_decision_card(
        job_id: str,
        card_id: str,
    ) -> dict[str, Any]:
        """Reject a decision card, pausing the stage."""
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            service = V2ApprovalMappingService(
                approval_repo=uow.v2_approvals,
            )
            try:
                card = service.reject(
                    card_id=card_id,
                    job_id=job_id,
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "REJECTION_FAILED",
                    str(exc),
                ) from exc
        return service.card_to_dict(card)

    @app.get("/v1/v2/jobs/{job_id}/approvals/{card_id}")
    def get_decision_card(
        job_id: str,
        card_id: str,
    ) -> dict[str, Any]:
        """Get a decision card by ID."""
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            service = V2ApprovalMappingService(
                approval_repo=uow.v2_approvals,
            )
            card = service.get_card(card_id)
        if card is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "CARD_NOT_FOUND",
                f"Decision card {card_id!r} not found",
            )
        return service.card_to_dict(card)

    # ------------------------------------------------------------------
    # V2 Stage progression endpoint (A8/P0-005)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # V2 Assistant endpoints (A10/P0-006)
    # ------------------------------------------------------------------

    @app.post("/v1/v2/jobs/{job_id}/assistant/messages")
    def add_assistant_message(
        job_id: str,
        payload: AssistantMessageRequest,
    ) -> dict[str, Any]:
        """Add an assistant message. Does not execute anything."""
        with unit_of_work_factory() as uow:
            service = V2AssistantService(
                assistant_repo=uow.v2_assistant,
            )
            try:
                msg = service.add_message(
                    job_id=payload.job_id,
                    role=payload.role,
                    content=payload.content,
                    correlation_id=payload.correlation_id,
                )
            except SchemaValidationError as exc:
                raise _error(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "SCHEMA_VALIDATION_FAILED",
                    str(exc),
                ) from exc
        return service.message_to_dict(msg)

    @app.get("/v1/v2/jobs/{job_id}/assistant/messages")
    def list_assistant_messages(
        job_id: str,
    ) -> dict[str, Any]:
        """List assistant messages for a job."""
        with unit_of_work_factory() as uow:
            service = V2AssistantService(
                assistant_repo=uow.v2_assistant,
            )
            messages = service.get_messages(job_id)
        return {
            "job_id": job_id,
            "messages": [service.message_to_dict(m) for m in messages],
        }

    @app.post("/v1/v2/jobs/{job_id}/assistant/ask")
    def ask_v2_assistant(
        job_id: str,
        payload: AssistantAskRequest,
    ) -> dict[str, Any]:
        """Ask the V2 assistant for read-only status guidance."""
        with unit_of_work_factory() as uow:
            job = _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
            approvals = uow.v2_approvals.list_cards_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            pipeline = _v2_pipeline_projection(job_id, events)
            service = V2AssistantService(assistant_repo=uow.v2_assistant)
            user_msg = service.add_message(
                job_id=job_id,
                role="user",
                content=payload.question,
                correlation_id=payload.correlation_id,
            )
            # Emit model_invocation_started event before model call
            uow.v2_events.save(
                job_id=job_id,
                stage=None,
                event_type="model_invocation_started",
                status="running",
                message="Assistant model invocation started.",
                payload={"provider": "azure_openai", "role": "assistant"},
            )
            fallback_answer = _build_v2_assistant_answer(
                question=payload.question,
                events=events,
                approvals=approvals,
                commands=commands,
            )
            model_result = app.state.v2_assistant_model_client.answer(
                prompt=_build_v2_assistant_prompt(
                    question=payload.question,
                    job=job,
                    pipeline=pipeline,
                    events=events,
                    approvals=approvals,
                ),
                fallback=fallback_answer,
            )
            assistant_msg = service.add_message(
                job_id=job_id,
                role="assistant",
                content=model_result.content,
                correlation_id=user_msg.message_id,
            )
        with unit_of_work_factory() as uow:
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=None,
                event_type="model_invocation_completed" if model_result.success else "model_invocation_failed",
                status="completed" if model_result.success else "failed",
                message=model_result.redacted_summary,
                payload={
                    "provider": model_result.provider,
                    "role": model_result.role,
                    "source": model_result.source,
                    "success": model_result.success,
                },
            )
        return {
            "job_id": job_id,
            "user_message": service.message_to_dict(user_msg),
            "assistant_message": service.message_to_dict(assistant_msg),
            "model": {
                "status": model_result.model_status,
                "source": model_result.source,
                "provider": model_result.provider,
                "role": model_result.role,
                "failure_reason": model_result.failure_reason,
            },
            "guardrails": {
                "read_only": True,
                "cannot_execute": True,
                "cannot_approve": True,
                "cannot_write_files": True,
                "cannot_change_route_or_stage": True,
                "cannot_override_proof": True,
            },
        }

    @app.post("/v1/v2/jobs/{job_id}/assistant/actions/draft")
    def draft_assistant_action(
        job_id: str,
        payload: DraftActionRequest,
    ) -> dict[str, Any]:
        """Draft a pending action (does NOT execute).

        The assistant CANNOT execute, approve, write files,
        change route, or override proof.

        F05: Actions are validated against ACTION_REQUEST_SCHEMA which
        restricts action_type to F05_ALLOWED_ACTION_TYPES. Revision
        steering fields are passed through for revise_repair_proposal.
        """
        action_type = (
            "request_reviewer_critique"
            if payload.action_type.strip().lower() == "review"
            else payload.action_type
        )
        # Validate against ActionRequest schema at the model-output boundary
        # This now rejects blocked action types like execute_command_directly
        action_data: dict[str, Any] = {
            "action_type": action_type,
            "reason": payload.reason,
            "stage_index": payload.stage_index,
            "payload_checksum": f"draft-{payload.job_id[:8]}",
        }
        # Pass revision fields if present (F05)
        if payload.source_proposal_id is not None:
            action_data["source_proposal_id"] = payload.source_proposal_id
        if payload.failed_command_id is not None:
            action_data["failed_command_id"] = payload.failed_command_id
        if payload.revision_instruction is not None:
            action_data["revision_instruction"] = payload.revision_instruction
        if payload.context_pack_checksum is not None:
            action_data["context_pack_checksum"] = payload.context_pack_checksum
        if payload.revision_of is not None:
            action_data["revision_of"] = payload.revision_of
        if payload.revision_number is not None:
            action_data["revision_number"] = payload.revision_number
        if payload.allowed_scope is not None:
            action_data["allowed_scope"] = payload.allowed_scope

        try:
            validate_against_schema("ActionRequest", action_data)
        except SchemaValidationError as exc:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "SCHEMA_VALIDATION_FAILED",
                str(exc),
            ) from exc

        # F05: If action_type is revise_repair_proposal, resolve revision binding
        revision_binding = None
        if action_type == "revise_repair_proposal" and payload.source_proposal_id:
            from migration_factory.control_tower.application.v2_action_resolver import (
                V2AssistantActionResolver,
                ActionBindingRequest,
                ActionResolverProtocol,
            )
            with unit_of_work_factory() as uow:
                resolver_proto = ActionResolverProtocol(
                    get_job=uow.v2_jobs.get,
                    list_commands=uow.v2_commands.list_by_job,
                    get_proposal=uow.v2_repairs.get_proposal,
                )
                action_resolver = V2AssistantActionResolver(resolver=resolver_proto)
                binding_request = ActionBindingRequest(
                    job_id=job_id,
                    action_type=action_type,
                    source_proposal_id=payload.source_proposal_id,
                    failed_command_id=payload.failed_command_id,
                    revision_instruction=payload.revision_instruction,
                    context_pack_checksum=payload.context_pack_checksum,
                    allowed_scope=payload.allowed_scope or "any",
                )
                try:
                    revision_binding = action_resolver.resolve_revision(binding_request)
                except ValueError as exc:
                    raise _error(
                        status.HTTP_400_BAD_REQUEST,
                        "REVISION_RESOLUTION_FAILED",
                        str(exc),
                    ) from exc

        with unit_of_work_factory() as uow:
            service = V2AssistantService(
                assistant_repo=uow.v2_assistant,
            )
            try:
                draft = service.draft_action(
                    job_id=payload.job_id,
                    action_type=action_type,
                    reason=payload.reason,
                    stage_index=payload.stage_index,
                    source_proposal_id=payload.source_proposal_id,
                    failed_command_id=payload.failed_command_id,
                    revision_instruction=payload.revision_instruction,
                    context_pack_checksum=payload.context_pack_checksum,
                    revision_of=payload.revision_of,
                    revision_number=payload.revision_number,
                    allowed_scope=payload.allowed_scope,
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "DRAFT_ACTION_BLOCKED",
                    str(exc),
                ) from exc
        result = service.draft_to_dict(draft)

        # F05: If revision binding resolved, create a revised proposal draft
        # via model-backed revision (not source copy)
        revised_proposal = None
        if revision_binding is not None:
            with unit_of_work_factory() as uow:
                repair_service = V2RepairFlowService(
                    repair_repo=uow.v2_repairs,
                )
                # Load source proposal for context
                source_record = uow.v2_repairs.get_proposal(payload.source_proposal_id)
                source_failure = source_record.failure_summary if source_record else "Unknown failure"
                source_hypothesis = source_record.hypothesis if source_record else ""
                source_patch = source_record.patch_summary if source_record else ""
                source_paths = (
                    tuple(json.loads(source_record.affected_paths_json))
                    if source_record and source_record.affected_paths_json
                    else ()
                )

                # F05: Build revision prompt and call model (not source copy)
                from migration_factory.control_tower.application.v2_prompt_router import (
                    EventPromptRouter,
                    PROMPT_TEMPLATES,
                )

                revision_template = PROMPT_TEMPLATES["revise_repair"]
                revision_payload = {
                    "event_type": "repair_proposal_revised",
                    "stage_index": str(revision_binding.failed_command.stage_index),
                    "source_proposal_id": payload.source_proposal_id,
                    "failed_command_id": payload.failed_command_id or "",
                    "failure_summary": source_failure,
                    "hypothesis": source_hypothesis,
                    "patch_summary": source_patch,
                    "affected_paths": list(source_paths),
                    "evidence_refs": "none",
                    "pom_summary_ref": "none",
                    "sandbox_binding_ref": revision_binding.binding.binding_checksum,
                    "context_pack_checksum": payload.context_pack_checksum or "",
                    "allowed_scope": payload.allowed_scope or "any",
                    "revision_instruction": payload.revision_instruction or "No specific instruction.",
                    "safety_policy": "No legacy source mutation. Only sandbox changes.",
                }

                # Format the revision prompt
                from migration_factory.control_tower.application.v2_model_schemas import (
                    ContextPackBuilder,
                )
                dummy_pack = ContextPackBuilder.build_context_pack(
                    pack_type="repair_proposal",
                    title="Revision",
                    description=source_failure,
                    evidence_refs=(),
                )
                revision_prompt = EventPromptRouter._format_prompt(
                    template=revision_template.template,
                    pack=dummy_pack,
                    payload=revision_payload,
                )

                # Call the model — keep fallback for answer() but check success
                model_result = app.state.v2_assistant_model_client.answer(
                    prompt=revision_prompt,
                    fallback=json.dumps({
                        "failure_hypothesis": source_hypothesis,
                        "patch_summary": source_patch,
                        "affected_paths": list(source_paths),
                        "validation_plan": "Re-validate after revision",
                    }),
                )

                # F05: Fail closed — no model output = no revised proposal
                if not model_result.success:
                    raise _error(
                        status.HTTP_502_BAD_GATEWAY,
                        "REVISION_MODEL_FAILED",
                        f"Revision model unavailable: {model_result.redacted_summary}",
                    )

                # F05: Parse and validate model output — NO fallback
                # Invalid/non-JSON/schema-failing model output raises ValueError
                try:
                    revised_output = _parse_and_validate_model_output(
                        model_content=model_result.content,
                        schema_name="RepairProposal",
                    )
                except ValueError as exc:
                    raise _error(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        "INVALID_REPAIR_PROPOSAL_OUTPUT",
                        str(exc),
                    ) from exc

                # Enforce pom_only on the REVISED model output's affected_paths
                revised_paths = revised_output.get("affected_paths", [])
                if isinstance(revised_paths, str):
                    try:
                        revised_paths = json.loads(revised_paths)
                    except (json.JSONDecodeError, TypeError):
                        revised_paths = []
                if (payload.allowed_scope or "any") == "pom_only":
                    non_pom = [
                        p for p in revised_paths
                        if not p.endswith("pom.xml") and "/pom.xml" not in p
                    ]
                    if non_pom:
                        raise _error(
                            status.HTTP_400_BAD_REQUEST,
                            "POM_ONLY_VIOLATION",
                            f"Revised model output contains non-POM paths: {non_pom}",
                        )

                # Persist using VALIDATED model output, not source copy
                revised_proposal = repair_service.create_revision_proposal(
                    command_id=revision_binding.failed_command.command_id,
                    source_proposal_id=payload.source_proposal_id,
                    failure_summary=revised_output.get("failure_hypothesis", source_failure),
                    hypothesis=revised_output.get("failure_hypothesis", source_hypothesis),
                    patch_summary=revised_output.get("patch_summary", source_patch),
                    affected_paths=tuple(revised_paths),
                    revision_instruction=payload.revision_instruction or "",
                    context_pack_checksum=payload.context_pack_checksum or "",
                    allowed_scope=payload.allowed_scope or "any",
                    revision_number=(payload.revision_number or 0) + 1,
                )

                # Emit repair_proposal_revised event (only after successful persistence)
                _append_v2_event(
                    uow,
                    job_id=job_id,
                    stage=revision_binding.failed_command.stage_index,
                    event_type="repair_proposal_revised",
                    status="completed",
                    message=f"Revised proposal {revised_proposal.proposal_id} created from {payload.source_proposal_id}",
                    payload={
                        "revised_proposal_id": revised_proposal.proposal_id,
                        "source_proposal_id": payload.source_proposal_id,
                        "revision_number": revised_proposal.revision_number,
                        "allowed_scope": revised_proposal.allowed_scope,
                        "command_id": revision_binding.failed_command.command_id,
                    },
                )

            result["revision_binding"] = action_resolver.result_to_dict(revision_binding)
            result["revised_proposal"] = repair_service.proposal_to_dict(revised_proposal)

        return result

    # ------------------------------------------------------------------
    # V2 Repair flow endpoints (A12/P0-007)
    # ------------------------------------------------------------------

    @app.post("/v1/v2/commands/{command_id}/repair/flow-proposal")
    def create_repair_proposal(
        command_id: str,
        payload: CreateRepairProposalRequest,
    ) -> dict[str, Any]:
        """Create a repair proposal from failed command evidence."""
        # Validate against RepairProposal schema at the model-output boundary
        repair_data = {
            "failure_hypothesis": payload.hypothesis,
            "patch_summary": payload.patch_summary,
            "affected_paths": payload.affected_paths,
            "validation_plan": f"Verify repair for {payload.command_id}",
        }
        try:
            validate_against_schema("RepairProposal", repair_data)
        except SchemaValidationError as exc:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "SCHEMA_VALIDATION_FAILED",
                str(exc),
            ) from exc

        with unit_of_work_factory() as uow:
            service = V2RepairFlowService(
                repair_repo=uow.v2_repairs,
            )
            proposal = service.create_proposal(
                command_id=payload.command_id,
                failure_summary=payload.failure_summary,
                hypothesis=payload.hypothesis,
                patch_summary=payload.patch_summary,
                affected_paths=tuple(payload.affected_paths),
            )
        return service.proposal_to_dict(proposal)

    @app.post("/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/approve")
    def approve_repair_proposal(
        command_id: str,
        proposal_id: str,
        payload: ApproveRepairProposalRequest,
    ) -> dict[str, Any]:
        """Approve a repair proposal with checksum.

        F07: Requires proposal_checksum and context_pack_checksum.
        Fails closed unless a latest accepted reviewer critique matches
        both current checksums.
        """
        with unit_of_work_factory() as uow:
            reviewer_service = V2ReviewerService(
                reviewer_repo=uow.v2_reviewer,
            )
            service = V2RepairFlowService(
                repair_repo=uow.v2_repairs,
                reviewer_service=reviewer_service,
            )
            try:
                proposal = service.approve_proposal(
                    proposal_id=proposal_id,
                    approval_checksum=payload.approval_checksum,
                    proposal_checksum=payload.proposal_checksum,
                    context_pack_checksum=payload.context_pack_checksum,
                )
                # Look up the reviewer critique_id for the response
                accepted = reviewer_service.check_reviewer_gate(
                    proposal_id=proposal_id,
                    proposal_checksum=payload.proposal_checksum,
                    context_pack_checksum=payload.context_pack_checksum,
                )
                reviewer_critique_id = accepted.critique_id if accepted else None
                reviewer_decision = accepted.decision if accepted else None
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "REPAIR_APPROVAL_FAILED",
                    str(exc),
                ) from exc
        return service.proposal_to_dict(
            proposal,
            reviewer_critique_id=reviewer_critique_id,
            reviewer_decision=reviewer_decision,
        )

    # ------------------------------------------------------------------
    # F07: Reviewer critique endpoints
    # ------------------------------------------------------------------

    @app.post("/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/reviewer-critique")
    def create_reviewer_critique(
        command_id: str,
        proposal_id: str,
        payload: CreateReviewerCritiqueRequest,
    ) -> dict[str, Any]:
        """Request a reviewer critique via model — NEVER accepts decision from client.

        The backend builds the reviewer prompt from the proposal context,
        calls the reviewer model, validates the output against
        REVIEWER_CRITIQUE_SCHEMA, and persists the critique.

        Clients CANNOT fabricate a decision=accept — only the model output
        determines the verdict.
        """
        with unit_of_work_factory() as uow:
            # Load proposal context for the reviewer prompt
            proposal_record = uow.v2_repairs.get_proposal(proposal_id)
            if proposal_record is None:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "PROPOSAL_NOT_FOUND",
                    f"Proposal {proposal_id!r} not found",
                )

            # Build the reviewer prompt using the existing template
            from migration_factory.control_tower.application.v2_prompt_router import (
                EventPromptRouter,
                PROMPT_TEMPLATES,
            )
            from migration_factory.control_tower.application.v2_model_schemas import (
                ContextPackBuilder,
            )

            reviewer_template = PROMPT_TEMPLATES["reviewer"]
            reviewer_payload = {
                "event_type": "review_requested",
                "stage_index": "1",
                "failure_summary": proposal_record.failure_summary,
                "evidence_refs": "none",
                "sandbox_binding_ref": "none",
                "pom_summary_ref": "none",
                "safety_policy": "No legacy source mutation. Only sandbox changes. Human approval required.",
                "proposal_checksum": payload.proposal_checksum,
                "context_pack_checksum": payload.context_pack_checksum,
            }

            dummy_pack = ContextPackBuilder.build_context_pack(
                pack_type="reviewer_critique",
                title="Review",
                description=proposal_record.failure_summary,
                evidence_refs=(),
            )
            reviewer_prompt = EventPromptRouter._format_prompt(
                template=reviewer_template.template,
                pack=dummy_pack,
                payload=reviewer_payload,
            )

            # Call the reviewer model
            fallback_json = json.dumps({
                "decision": "revise",
                "reasoning": "Model unavailable — defaulting to revise for safety.",
                "missing_evidence": ["Model output unavailable"],
                "unsafe_assumptions": ["Reviewer model did not respond"],
            })
            model_result = app.state.v2_assistant_model_client.answer(
                prompt=reviewer_prompt,
                fallback=fallback_json,
            )

            # Parse and validate model output
            reviewer_output = _parse_and_validate_model_output(
                model_content=model_result.content,
                schema_name="ReviewerCritique",
                fallback={
                    "decision": "revise",
                    "reasoning": "Model unavailable — defaulting to revise for safety.",
                    "missing_evidence": ["Model output unavailable"],
                    "unsafe_assumptions": ["Reviewer model did not respond"],
                },
            )

            # Persist the VALIDATED reviewer critique
            service = V2ReviewerService(
                reviewer_repo=uow.v2_reviewer,
            )
            try:
                critique = service.record_critique(
                    proposal_id=proposal_id,
                    proposal_type=payload.proposal_type,
                    proposal_checksum=payload.proposal_checksum,
                    context_pack_checksum=payload.context_pack_checksum,
                    decision=reviewer_output["decision"],
                    reasoning=reviewer_output["reasoning"],
                    missing_evidence=tuple(reviewer_output.get("missing_evidence", [])),
                    unsafe_assumptions=tuple(reviewer_output.get("unsafe_assumptions", [])),
                    model_invocation_id=payload.model_invocation_id,
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "CRITIQUE_FAILED",
                    str(exc),
                ) from exc
        return service.critique_to_dict(critique)

    @app.get("/v1/v2/commands/{command_id}/repair/proposal/{proposal_id}/reviewer-critiques")
    def list_reviewer_critiques(
        command_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        """List all reviewer critiques for a proposal."""
        with unit_of_work_factory() as uow:
            service = V2ReviewerService(
                reviewer_repo=uow.v2_reviewer,
            )
            critiques = service.list_critiques(proposal_id)
        return {
            "command_id": command_id,
            "proposal_id": proposal_id,
            "critiques": [service.critique_to_dict(c) for c in critiques],
        }

    @app.get("/v1/v2/reviewer-critiques/{critique_id}")
    def get_reviewer_critique(
        critique_id: str,
    ) -> dict[str, Any]:
        """Get a reviewer critique by ID."""
        with unit_of_work_factory() as uow:
            service = V2ReviewerService(
                reviewer_repo=uow.v2_reviewer,
            )
            critique = service.get_critique(critique_id)
        if critique is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "CRITIQUE_NOT_FOUND",
                f"Reviewer critique {critique_id!r} not found",
            )
        return service.critique_to_dict(critique)

    @app.post("/v1/v2/jobs/{job_id}/stages/progress")
    def progress_to_next_stage(
        job_id: str,
        payload: StageProgressRequest,
    ) -> dict[str, Any]:
        """Auto-queue the next stage from the current stage sandbox.

        Stage 2 input = Stage 1 sandbox.
        Stage 3 input = Stage 2 sandbox.
        No Boot 4 path. No user-selected stage inputs.
        """
        with unit_of_work_factory() as uow:
            service = V2StageProgressionService(
                setup_repo=uow.v2_setups,
                command_repo=uow.v2_commands,
            )
            try:
                result = service.queue_next_stage(
                    job_id=job_id,
                    setup_id=payload.setup_id,
                    current_stage=payload.current_stage,
                    sandbox_path=payload.sandbox_path,
                )
            except ValueError as exc:
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "STAGE_PROGRESSION_FAILED",
                    str(exc),
                ) from exc
        return service.continuation_to_dict(result)

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


def _require_v2_job(uow: Any, job_id: str) -> Any:
    job = uow.v2_jobs.get(job_id)
    if job is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            f"V2 migration job {job_id!r} not found.",
        )
    return job


def _append_v2_event(
    uow: Any,
    *,
    job_id: str,
    stage: int | None,
    event_type: str,
    status: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    redacted_payload = redact_public_data(payload or {})
    return uow.v2_events.save(
        job_id=job_id,
        stage=stage,
        event_type=event_type,
        status=status,
        message=_bounded_event_text(str(redact_public_data(message))),
        payload=redacted_payload if isinstance(redacted_payload, dict) else {},
    )


def _emit_v2_stage1_uat_events(uow: Any, *, job_id: str, command_id: str) -> None:
    """Emit deterministic UAT adapter events for manifest-only Stage 1 starts."""
    events = (
        (1, "stage_queued", "queued", "Stage 1 command manifest queued.", {"command_id": command_id}),
        (1, "stage_started", "running", "Stage 1 deterministic UAT adapter started.", {"adapter": "deterministic_uat"}),
        (1, "command_started", "running", "Backend-owned Stage 1 manifest accepted.", {"command_id": command_id}),
        (1, "stdout", "running", "UAT adapter verifying backend-owned manifest and evidence stream.", {"command_id": command_id}),
        (1, "artifact_written", "completed", "UAT evidence artifact registered.", {"artifact_kind": "uat-stage1-evidence"}),
        (1, "proof_updated", "completed", "Stage 1 deterministic proof evidence updated.", {"proof_source": "uat-adapter"}),
        (1, "stage_completed", "completed", "Stage 1 deterministic UAT adapter completed.", {"command_id": command_id}),
    )
    for stage, event_type, event_status, message, payload in events:
        _append_v2_event(
            uow,
            job_id=job_id,
            stage=stage,
            event_type=event_type,
            status=event_status,
            message=message,
            payload=payload,
        )


def _build_v2_assistant_answer(
    *,
    question: str,
    events: tuple[Any, ...],
    approvals: tuple[Any, ...],
    commands: tuple[Any, ...],
) -> str:
    latest = events[-1] if events else None
    failures = [event for event in events if event.status == "failed" or event.type in {"stage_failed", "transform_failed", "build_failed"}]
    pending_approvals = [card for card in approvals if card.status == "pending"]
    approved_cards = [card for card in approvals if card.status == "approved"]
    running = [event for event in events if event.status == "running"]
    completed = [event for event in events if event.type == "stage_completed"]
    repair_events = [event for event in events if event.type in {"repair_started", "repair_fallback_generated"}]

    # Build a rich stage status summary
    stage_lines: list[str] = []
    stage_status_events = {}
    for event in events:
        if event.type == "stage_completed" and event.stage:
            stage_status_events[event.stage] = "completed"
        elif event.type == "stage_failed" and event.stage:
            stage_status_events[event.stage] = "failed"
        elif event.status == "running" and event.stage:
            stage_status_events.setdefault(event.stage, "running")
        elif event.type in {"stage_queued", "next_stage_queued"} and event.stage:
            stage_status_events.setdefault(event.stage, "queued")

    for stage_idx in sorted(stage_status_events):
        stage_lines.append(f"  Stage {stage_idx}: {stage_status_events[stage_idx]}")
    stage_summary = "\n".join(stage_lines) if stage_lines else "  No stage events recorded yet."

    # Extract artifact kinds
    artifact_kinds: list[str] = []
    for event in events:
        if event.type == "artifact_written":
            try:
                payload = json.loads(event.payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            kind = str(payload.get("artifact_kind", ""))
            if kind and kind not in artifact_kinds:
                artifact_kinds.append(kind)

    # Extract diagnostic info from failures
    diagnostic_lines: list[str] = []
    for failure in failures[-3:]:
        diag_parts: list[str] = []
        try:
            payload = json.loads(failure.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        result_kind = str(payload.get("result_kind", ""))
        if result_kind:
            diag_parts.append(result_kind.replace("_", " "))
        matched = str(payload.get("matched_line", ""))
        if matched:
            diag_parts.append(f"matched: {_bounded_event_text(matched, limit=120)}")
        build_tool = str(payload.get("build_tool", ""))
        if build_tool:
            diag_parts.append(build_tool)
        module = str(payload.get("module", ""))
        if module:
            diag_parts.append(f"module: {module}")
        if diag_parts:
            diagnostic_lines.append(f"  {failure.type}: {'; '.join(diag_parts)}")
    diagnostics = "\n".join(diagnostic_lines) if diagnostic_lines else ""

    # Determine action
    if failures:
        failure_msgs = [f"{event.type}: {event.message}" for event in failures[-3:]]
        if diagnostics:
            failure_msgs.append(f"Diagnostics:\n{diagnostics}")
        action = f"Failed: {'; '.join(failure_msgs)}. Review failure evidence and decide whether to create a bounded repair proposal."
    elif pending_approvals:
        card = pending_approvals[-1]
        action = f"Approval required at Stage {card.stage_index}. Review the approval card checksum ({card.request_checksum[:12]}...) in the decisions panel. Only a human can approve it."
    elif approved_cards:
        action = "Approval accepted. Backend-owned orchestrator should resume. Wait for transform/build events."
    elif latest is None:
        action = "Start migration or wait for the backend to emit Stage 1 events."
    elif completed:
        action = "All stages completed. Wait for backend-owned proof report generation."
    elif running:
        action = "Wait for the running backend-owned orchestrator command to finish or request more evidence."
    else:
        action = "Inspect the evidence stream for the next operator action."

    latest_text = "No evidence events have been recorded yet."
    if latest is not None:
        latest_text = f"Latest event: stage {latest.stage or '-'} {latest.type} ({latest.status}) - {latest.message}"
    command_text = f"{len(commands)} backend-owned command manifest(s) are persisted."
    approval_state = (
        f"{len(pending_approvals)} approval pending, {len(approved_cards)} approved."
        if pending_approvals or approved_cards
        else "No approval cards."
    )
    repair_state = (
        f"Repair loop active ({len(repair_events)} repair events)." if repair_events
        else "No repair loop active."
    )
    artifact_text = f"Artifacts generated: {', '.join(artifact_kinds[-10:])}." if artifact_kinds else "No artifacts generated yet."

    proof_note = ""
    completed_stage_indices = sorted({event.stage for event in events if event.type == "stage_completed" and event.stage})
    if completed_stage_indices:
        latest_completed_stage = completed_stage_indices[-1]
        stage_build_completed = any(event.stage == latest_completed_stage and event.type == "build_completed" for event in events)
        stage_test_completed = any(event.stage == latest_completed_stage and event.type == "test_completed" for event in events)
        if stage_build_completed and stage_test_completed:
            proof_note = f"Proof: Stage {latest_completed_stage} passed with build and test evidence."

    # Model availability note
    model_note = ""
    if not _model_client_available():
        model_note = (
            "\nNote: Azure OpenAI model is not configured (missing endpoint, key, or deployment). "
            "This is a deterministic fallback response. AI-backed coaching is unavailable until model readiness is restored."
        )

    answer = (
        f"Question: {_bounded_event_text(question)}\n\n"
        f"Stage Status:\n{stage_summary}\n\n"
        f"{latest_text}\n"
        f"{command_text} {approval_state} {repair_state}\n"
        f"{artifact_text}\n"
        f"{proof_note}\n"
        f"Next operator action: {action}{model_note}\n\n"
        "Guardrails: I can explain status and summarize evidence only. I cannot execute, approve, write files, "
        "change route/stage, choose Maven goals, choose deployments, or override proof. "
        "All migration execution is backend-owned."
    )
    return str(redact_public_data(answer))


def _build_v2_assistant_prompt(
    *,
    question: str,
    job: Any,
    pipeline: dict[str, Any],
    events: tuple[Any, ...],
    approvals: tuple[Any, ...],
    max_chars: int = 8000,
) -> str:
    latest_events = [_v2_event_payload(event) for event in events[-12:] if event.type not in _RAW_EVENT_TYPES]
    pending_approvals = [
        {
            "card_id": card.card_id,
            "stage_index": card.stage_index,
            "status": card.status,
            "summary": card.summary,
            "request_checksum": card.request_checksum,
        }
        for card in approvals
        if card.status == "pending"
    ]
    approved_cards = [
        {"card_id": card.card_id, "stage_index": card.stage_index, "status": card.status}
        for card in approvals
        if card.status == "approved"
    ]
    # Build grouped failure summary (one card per root cause, with collapsed repair events)
    grouped_failure_summary = _v2_failure_summary(job_id="", events=events)
    grouped_failures = grouped_failure_summary.get("failures", [])
    # Build stage status summary
    stage_statuses: dict[str, str] = {}
    for event in events:
        if event.stage is None:
            continue
        stage_key = f"stage_{event.stage}"
        if event.type == "stage_completed":
            stage_statuses[stage_key] = "completed"
        elif event.type == "stage_failed":
            stage_statuses[stage_key] = "failed"
        elif event.status == "running" and stage_key not in stage_statuses:
            stage_statuses.setdefault(stage_key, "running")
    # Derive artifact kinds from events
    artifact_kinds: list[str] = []
    for event in events:
        if event.type == "artifact_written":
            try:
                payload = json.loads(event.payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            kind = str(payload.get("artifact_kind", ""))
            if kind and kind not in artifact_kinds:
                artifact_kinds.append(kind)
    # Build model/fallback status
    model_status = "available" if _model_client_available() else "fallback"
    model_source = "azure_openai" if _model_client_available() else "deterministic"
    prompt = {
        "question": question,
        "job": {
            "job_id": getattr(job, "job_id", ""),
            "setup_id": getattr(job, "setup_id", ""),
            "pipeline_id": getattr(job, "pipeline_id", ""),
        },
        "pipeline_rows": pipeline.get("rows", []),
        "stage_statuses": stage_statuses,
        "latest_events": latest_events,
        "pending_approvals": pending_approvals,
        "approved_approvals": approved_cards,
        "failure_summary": {
            "failures": [_f for f in grouped_failures for _f in [{"type": f["type"], "stage": f["stage"], "title": f["title"], "message": f["message"], "build_status": f["build_status"], "final_status": f["final_status"], "result_kind": f["result_kind"], "repair_loop_status": f["repair_loop_status"], "copilot_status": f["copilot_status"], "event_types": f["event_types"], "repair_events": f["repair_events"]}]],
            "count": len(grouped_failures),
        },
        "artifact_kinds": artifact_kinds[-20:],
        "model": {
            "status": model_status,
            "source": model_source,
        },
        "guardrails": {
            "read_only": True,
            "cannot_execute": True,
            "cannot_approve": True,
            "cannot_write_files": True,
            "cannot_change_route_or_stage": True,
            "cannot_override_proof": True,
            "llm_cannot_approve_exact_checksum_required": True,
        },
    }
    result = json.dumps(redact_public_data(prompt), separators=(",", ":"), sort_keys=True)
    # Bound context length to prevent token overflow
    if len(result) > max_chars:
        # Shrink the largest fields: latest_events and failure_summary
        prompt["latest_events"] = latest_events[-3:]
        prompt["failure_summary"]["failures"] = prompt["failure_summary"]["failures"][-2:]
        prompt["failure_summary"]["count"] = len(prompt["failure_summary"]["failures"])
        result = json.dumps(redact_public_data(prompt), separators=(",", ":"), sort_keys=True)
        if len(result) > max_chars:
            # Ultimate truncation: keep only critical fields
            prompt["latest_events"] = []
            prompt["failure_summary"]["failures"] = []
            prompt["failure_summary"]["count"] = 0
            prompt["pipeline_rows"] = [
                {"key": r["key"], "status": r["status"]}
                for r in prompt["pipeline_rows"]
            ]
            result = json.dumps(redact_public_data(prompt), separators=(",", ":"), sort_keys=True)
    return result[:max_chars]


def _model_client_available() -> bool:
    """Check if the Azure OpenAI model client is configured and reachable."""
    import os as _os
    endpoint = _os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = _os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    deployment = _os.environ.get("AZURE_OPENAI_ASSISTANT_DEPLOYMENT", "").strip()
    return bool(endpoint and api_key and deployment)


def _v2_resume_run_dir_from_commands(commands: tuple[Any, ...], stage_index: int, run_id: str) -> str:
    for command in commands:
        if int(getattr(command, "stage_index", 0)) != int(stage_index):
            continue
        try:
            argv = json.loads(command.argv_json)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(argv, list):
            continue
        modernized = _argv_value(argv, "--modernized")
        if modernized:
            return str(Path(str(modernized)) / ".migration" / "runs" / run_id)
    raise _error(
        status.HTTP_400_BAD_REQUEST,
        "RESUME_RUN_DIR_UNAVAILABLE",
        "Backend could not derive approval resume run directory from persisted command manifest.",
    )


def _argv_value(argv: list[Any], option: str) -> str:
    for index, value in enumerate(argv[:-1]):
        if value == option:
            return str(argv[index + 1])
    return ""


_PIPELINE_PHASES = (
    ("preflight", "Preflight", {"job_created", "stage_queued"}),
    ("analysis", "Analysis Agent", {"analysis_started", "analysis_completed", "analysis_failed"}),
    ("planning", "Planning Agent", {"planning_started", "planning_completed", "planning_failed"}),
    ("assessment", "Assessment Agent", {"assessment_started", "assessment_completed", "assessment_failed"}),
    ("human_approval", "Human Approval", {
        "approval_required", "approval_blocked", "stage_blocked_for_approval",
        "approval_started", "approval_completed", "approval_resume_queued", "resume_started",
    }),
    ("sandbox_transform", "Transform Agent", {
        "sandbox_transform_started", "sandbox_transform_completed", "sandbox_transform_failed",
        "transform_started", "transform_failed",
    }),
    ("build_validation", "Build Agent", {"build_started", "build_completed", "build_failed"}),
    ("test_validation", "Test Validation", {"test_started", "test_completed", "test_failed"}),
    ("failure_repair", "Repair/Failure", {
        "repair_started", "repair_fallback_generated", "repair_completed",
        "copilot_repair_invalid_response", "copilot_availability_checked",
    }),
    ("result_contract", "Result Contract", {"result_contract_failed"}),
    ("final_report", "Final Report", {
        "final_report_started", "final_report_completed", "final_report_failed",
    }),
    ("stage_report", "Stage Report", {
        "stage_report_started", "stage_report_completed", "stage_report_failed",
    }),
)
_RAW_EVENT_TYPES = {"stdout", "stderr"}
_IMPORTANT_EVENT_TYPES = {
    "approval_required",
    "approval_started",
    "approval_completed",
    "stage_blocked_for_approval",
    "approval_resume_queued",
    "artifact_written",
    "proof_updated",
    "stage_failed",
    "stage_completed",
    "model_invocation_started",
    "model_invocation_completed",
    "model_invocation_failed",
    "copilot_status_checked",
    "sandbox_transform_started",
    "sandbox_transform_completed",
    "sandbox_transform_failed",
    "transform_failed",
    "build_failed",
    "repair_started",
    "repair_fallback_generated",
    "copilot_repair_invalid_response",
    "next_stage_queued",
    "final_report_started",
    "final_report_completed",
    "final_report_failed",
    "stage_report_started",
    "stage_report_completed",
    "stage_report_failed",
    "result_contract_failed",
}


def _active_stage_index(events: tuple[Any, ...]) -> int:
    """Determine the current/active stage from events."""
    failed_stages = {e.stage for e in events if e.stage and e.type == "stage_failed"}
    completed_stages = {e.stage for e in events if e.stage and e.type == "stage_completed"}

    # Find latest running/blocked/started stage
    candidates = [
        e for e in events
        if e.stage and e.type in {
            "stage_failed", "stage_started", "resume_started",
            "sandbox_transform_started", "build_started", "test_started",
            "approval_required", "stage_blocked_for_approval",
            "final_report_started", "final_report_completed", "final_report_failed",
            "stage_report_started", "stage_report_completed", "stage_report_failed",
        }
    ]
    if candidates:
        latest = max(candidates, key=lambda e: e.sequence)
        return latest.stage

    # Check next_stage_queued for latest to_stage
    for event in reversed(events):
        if event.type == "next_stage_queued":
            payload = _event_payload_dict(event)
            to_stage = int(payload.get("to_stage") or event.stage or 0)
            if to_stage:
                return to_stage

    if completed_stages:
        return max(completed_stages)
    return 1


def _v2_pipeline_projection(job_id: str, events: tuple[Any, ...]) -> dict[str, Any]:
    active_stage = _active_stage_index(events)

    # Scope events to active stage; global events (no stage) are included
    def _is_allowed_for_stage(event: Any) -> bool:
        if event.stage is None:
            return True
        if event.stage == active_stage:
            return True
        # Allow next_stage_queued even if its to_stage differs
        if event.type == "next_stage_queued":
            return True
        return False

    stage_events = [e for e in events if _is_allowed_for_stage(e)]

    rows: list[dict[str, Any]] = []
    for key, label, event_types in _PIPELINE_PHASES:
        # For final_report, only Stage 3 events count (defense-in-depth)
        matching = [
            event for event in stage_events
            if event.type in event_types
            and (key != "final_report" or event.stage == 3)
        ]
        latest = matching[-1] if matching else None
        row_status = _pipeline_row_status(key, matching)
        latest_message = latest.message if latest is not None else "Waiting for backend-owned evidence."
        if key == "test_validation" and not matching:
            active_build_failed = any(
                event.stage == active_stage
                and event.type == "build_failed"
                and (event.status == "failed" or event.type.endswith("_failed"))
                for event in stage_events
            )
            if active_build_failed:
                row_status = "skipped"
                latest_message = "Not run because sandbox build failed."
        # Deduplicate artifact counts by relative_path per phase
        seen_paths: set[str] = set()
        for event in events:
            if event.type == "artifact_written" and _event_phase_key(event) == key:
                try:
                    payload = json.loads(event.payload_json or "{}")
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                path = str(payload.get("relative_path", ""))
                if path and path not in seen_paths:
                    seen_paths.add(path)
        rows.append(
            {
                "key": key,
                "label": label,
                "status": row_status,
                "latest_message": latest_message,
                "artifact_count": len(seen_paths),
                "last_updated": latest.created_at if latest is not None else "",
            }
        )
    important = [
        _v2_event_payload(event)
        for event in events
        if event.type in _IMPORTANT_EVENT_TYPES
        or event.status in {"blocked", "failed"}
        or (event.type not in _RAW_EVENT_TYPES and event.type.endswith(("_started", "_completed", "_failed")))
    ]
    raw = [_v2_event_payload(event) for event in events if event.type in _RAW_EVENT_TYPES]
    return {
        "job_id": job_id,
        "rows": rows,
        "evidence": important[-100:],
        "raw_logs": raw[-200:],
        "active_stage_index": active_stage,
    }


def _pipeline_row_status(key: str, events: list[Any]) -> str:
    if not events:
        return "pending"
    # Failure supersedes everything
    if any(event.status == "failed" or event.type.endswith("_failed") for event in events):
        return "failed"
    # Approval-specific: once accepted/completed or transform started, it's pass
    if key == "human_approval":
        approval_passed_types = {
            "approval_completed", "approval_resume_queued", "resume_started",
            "sandbox_transform_started", "sandbox_transform_completed",
        }
        if any(event.type in approval_passed_types for event in events):
            return "pass"
        if any(event.type == "approval_started" for event in events):
            return "running"
        if any(event.status == "blocked" or event.type in {"approval_required", "stage_blocked_for_approval"} for event in events):
            return "blocked"
        return "pending"
    latest = events[-1]
    if latest.status == "blocked":
        return "blocked"
    if latest.status == "running" or latest.type.endswith("_started"):
        return "running"
    if any(event.status == "completed" or event.type.endswith("_completed") for event in events):
        return "pass"
    return "pending"


def _resolve_v2_artifact_preview_path(
    *,
    artifact_ref: str,
    setup: Any,
    commands: tuple[Any, ...],
) -> Path | None:
    ref = str(artifact_ref or "").strip()
    if not ref or _is_unsafe_artifact_ref(ref):
        return None

    relative_ref = Path(ref)
    base_roots = _v2_artifact_base_roots(setup=setup, commands=commands)
    for base_root in base_roots:
        candidate = _contained_existing_file(base_root, relative_ref)
        if candidate is not None:
            return candidate

    if ref.replace("\\", "/").startswith(".migration/"):
        rest = Path(*Path(ref).parts[1:])
        for base_root in base_roots:
            try:
                migration_dirs = base_root.rglob(".migration") if base_root.is_dir() else ()
                for migration_dir in migration_dirs:
                    candidate = _contained_existing_file(migration_dir.parent, Path(".migration") / rest)
                    if candidate is not None:
                        return candidate
            except (OSError, ValueError):
                continue

    return None


def _is_unsafe_artifact_ref(ref: str) -> bool:
    if ref.startswith(("\\\\", "//")):
        return True
    path = Path(ref)
    win_path = PureWindowsPath(ref)
    if path.is_absolute() or win_path.is_absolute() or win_path.drive:
        return True
    return any(part == ".." for part in path.parts)


def _v2_artifact_base_roots(*, setup: Any, commands: tuple[Any, ...]) -> tuple[Path, ...]:
    roots: list[Path] = []

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if not text:
            return
        path = Path(text)
        win_path = PureWindowsPath(text)
        if not (path.is_absolute() or win_path.is_absolute() or win_path.drive):
            return
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return
        if resolved not in roots:
            roots.append(resolved)

    add(getattr(setup, "output_parent_path", ""))
    for command in commands:
        try:
            argv = json.loads(getattr(command, "argv_json", "") or "[]")
        except (json.JSONDecodeError, TypeError):
            argv = []
        if not isinstance(argv, list):
            continue
        for index, item in enumerate(argv):
            if str(item) == "--modernized" and index + 1 < len(argv):
                add(argv[index + 1])
            if str(item) in {"--legacy", "--sandbox"} and index + 1 < len(argv):
                add(argv[index + 1])
    return tuple(roots)


def _contained_existing_file(base_root: Path, relative_ref: Path) -> Path | None:
    try:
        resolved_base = base_root.resolve(strict=False)
        candidate = (resolved_base / relative_ref).resolve(strict=True)
        candidate.relative_to(resolved_base)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_file():
        return None
    return candidate


def _failure_primary_key(event: Any, payload: dict[str, Any]) -> str:
    """Derive a primary key for grouping related failure events.

    Same-stage terminal transform/build failures are one root failure even
    when individual events carry different payload keys.
    """
    if event.type == "result_contract_failed":
        return "result_contract_failed"
    if event.type in {"sandbox_transform_failed", "build_failed", "transform_failed", "stage_failed"}:
        values = [
            payload.get("build_status"),
            payload.get("final_status"),
            payload.get("transform_status"),
            payload.get("result_kind"),
            event.type,
        ]
        normalized = " ".join(str(value or "").upper() for value in values)
        if (
            "BUILD_FAILED_IN_SANDBOX" in normalized
            or "FALLBACK_REPAIR_PLAN" in normalized
            or "DEPENDENCY_ERROR" in normalized
            or event.type in {"sandbox_transform_failed", "build_failed", "transform_failed"}
        ):
            return "terminal_transform_build_failure"
    build_status = str(payload.get("build_status", "") or "")
    if build_status:
        return f"build_status:{build_status}"
    final_status = str(payload.get("final_status", "") or "")
    if final_status:
        return f"final_status:{final_status}"
    result_kind = str(payload.get("result_kind", "") or "")
    if result_kind:
        return f"result_kind:{result_kind}"
    return f"type:{event.type}"


_PRIMARY_EVENT_PRIORITY = {
    "build_failed": 0,
    "sandbox_transform_failed": 1,
    "transform_failed": 2,
    "test_failed": 3,
    "stage_failed": 4,
    "result_contract_failed": 5,
    "copilot_repair_invalid_response": 6,
    "repair_started": 7,
}


_REPAIR_EVENT_TYPES = {"repair_started", "repair_fallback_generated", "copilot_repair_invalid_response"}


def _v2_failure_summary(job_id: str, events: tuple[Any, ...]) -> dict[str, Any]:
    """Build a redacted failure/repair summary from V2 events,
    grouped by root cause.

    Returns one card per root failure with collapsed repair events.
    """
    from collections import defaultdict

    # Collect failed events (excluding repair events which are attached to root failures)
    failed_events = [
        event for event in events
        if (event.status == "failed" or event.type.endswith("_failed") or event.type == "result_contract_failed")
        and event.type not in _REPAIR_EVENT_TYPES
    ]
    repair_events_typed = [
        event for event in events
        if event.type in _REPAIR_EVENT_TYPES
    ]

    # Group by (stage_index, primary_key)
    groups: dict[tuple[int | None, str], list[Any]] = defaultdict(list)
    group_payloads: dict[tuple[int | None, str], dict[str, Any]] = {}

    for event in failed_events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        primary_key = _failure_primary_key(event, payload)
        key = (event.stage, primary_key)
        groups[key].append(event)
        if key not in group_payloads:
            group_payloads[key] = payload

    failures: list[dict[str, Any]] = []
    for (stage_key, _primary_key), fevents in groups.items():
        # Pick the primary event (highest priority type)
        fevents_sorted = sorted(fevents, key=lambda e: _PRIMARY_EVENT_PRIORITY.get(e.type, 99))
        primary = fevents_sorted[0]
        payload = _merged_event_payloads(fevents_sorted)
        stage_repair_payload = _merged_event_payloads(
            [event for event in repair_events_typed if event.stage == primary.stage]
        )
        for key, value in stage_repair_payload.items():
            if key not in payload or payload.get(key) in ("", None, False):
                payload[key] = value
        result_kind = str(payload.get("result_kind", ""))

        if primary.type == "result_contract_failed":
            next_action = (
                "Inspect orchestrator stdout/stderr and orchestration_summary.json. "
                "The subprocess exited but Control Tower could not parse its final result contract."
            )
            title = "Control Tower Contract Failure"
        elif _primary_key == "terminal_transform_build_failure":
            if result_kind == "dependency_error":
                title = f"Stage {primary.stage or '?'} Dependency/Build Failure"
            else:
                title = f"Stage {primary.stage or '?'} Build/Transform Failure"
        elif result_kind:
            title = f"Stage {primary.stage or '?'} {result_kind.replace('_', ' ').title()}"
        else:
            title = f"Stage {primary.stage or '?'} failure"

        # Build related event types list
        related_event_types = list(dict.fromkeys(e.type for e in fevents_sorted))

        # Find repair events belonging to this stage
        stage_repair_events = [
            {"type": e.type, "message": _bounded_event_text(e.message)}
            for e in repair_events_typed if e.stage == primary.stage
        ]

        failures.append({
            "type": primary.type,
            "stage": primary.stage,
            "title": title,
            "message": _bounded_event_text(primary.message),
            "build_status": str(payload.get("build_status", "")),
            "test_status": str(payload.get("test_status", "")),
            "final_status": str(payload.get("final_status", "")),
            "final_proof_level": str(payload.get("final_proof_level", "")),
            "repair_loop_status": str(payload.get("repair_loop_status", "")),
            "copilot_status": str(payload.get("copilot_invocation_status", "")),
            "repair_fallback": str(payload.get("repair_fallback_generated", "")),
            # SA4 diagnostic fields
            "matched_line": _safe_failure_str(payload.get("matched_line")),
            "command": _safe_failure_list(payload.get("command") or payload.get("resolved_command")),
            "requested_command": _safe_failure_list(payload.get("requested_command")),
            "build_tool": _safe_failure_str(payload.get("build_tool")),
            "module": _safe_failure_str(payload.get("module")),
            "main_class": _safe_failure_str(payload.get("main_class")),
            "unit_id": _safe_failure_str(payload.get("unit_id")),
            "result_kind": result_kind,
            "java_home": _safe_failure_str(payload.get("java_home")),
            "detected_version": _safe_failure_str(payload.get("detected_version")),
            "required_minimum": _safe_failure_str(payload.get("required_minimum")),
            # Result contract diagnostic fields
            "exit_code": payload.get("exit_code"),
            "final_json_found": payload.get("final_json_found"),
            "parse_strategy": str(payload.get("parse_strategy", "")),
            "stdout_tail": _safe_failure_str(payload.get("stdout_tail")),
            "stderr_tail": _safe_failure_str(payload.get("stderr_tail")),
            # Grouping fields
            "event_types": related_event_types,
            "repair_events": stage_repair_events,
            "next_operator_action": _next_operator_action(result_kind),
        })

    # Collect repair events not already attached to a failure group
    ungrouped_repair = [
        {"type": e.type, "message": _bounded_event_text(e.message)}
        for e in repair_events_typed
        if not any(e.stage == f["stage"] for f in failures)
    ]

    artifact_kinds: list[str] = []
    for event in events:
        if event.type == "artifact_written":
            try:
                payload = json.loads(event.payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            kind = str(payload.get("artifact_kind", ""))
            if kind and kind not in artifact_kinds:
                artifact_kinds.append(kind)
    return {
        "job_id": job_id,
        "has_failures": len(failures) > 0,
        "failures": failures,
        "repair_loop_active": len(repair_events_typed) > 0,
        "repair_events": ungrouped_repair,
        "artifact_kinds": artifact_kinds,
    }


def _merged_event_payloads(events: list[Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for event in events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        for key, value in payload.items():
            if value in ("", None, [], {}):
                continue
            if key not in merged or merged.get(key) in ("", None, False):
                merged[key] = value
    return merged


def _safe_failure_str(value: Any) -> str:
    """Return sanitized string or empty string for failure diagnostic fields.

    Values exceeding 256 chars are truncated. Sensitive content is redacted.
    Paths, secrets, and env assignments are scrubbed as defense-in-depth
    even though the orchestrator also redacts before persisting events.
    """
    if value is None:
        return ""
    from migration_factory.control_tower.application.redaction import redact_model_summary
    text = redact_model_summary(str(value))
    if len(text) > 256:
        text = text[:256] + "...[truncated]"
    return text


def _safe_failure_list(value: Any) -> list[str]:
    """Return sanitized string list for command fields."""
    if value is None:
        return []
    result: list[str] = []
    for item in value if isinstance(value, (list, tuple)) else []:
        txt = _safe_failure_str(item)
        if txt:
            result.append(txt)
    return result[:6]  # cap at 6 entries


def _next_operator_action(result_kind: str) -> str:
    """Suggest next operator action from build error result kind."""
    kind = result_kind.lower()
    action_map: dict[str, str] = {
        "dependency_error": "Check dependency coordinates and repository access. "
                             "Review matched_line for missing artifact and verify network/proxy settings.",
        "compilation_error": "Review the matched_line for Java compilation errors. "
                              "Fix source code, check Java version compatibility, or adjust compiler flags.",
        "jdk_version_mismatch": "The detected Java version does not meet the minimum required for this stage. "
                                 "Update JAVA_HOME or re-run preflight with the correct JDK path.",
        "missing_jdk": "No JDK was found for this stage. "
                        "Verify JAVA_HOME, JAVA11_HOME, JAVA17_HOME, or JAVA21_HOME are set in the setup.",
        "maven_not_found": "Maven command was not found. Verify MAVEN_CMD path or Maven installation.",
        "maven_version_too_old": "The installed Maven version is too old for this Spring Boot target. "
                                  "Upgrade Maven or switch profile.",
        "project_detection_error": "Could not detect a Java project at the sandbox path. "
                                    "Verify that the previous stage produced valid output.",
        "build_timeout": "Build exceeded the timeout. Consider increasing AI_MIGRATION_COPILOT_TIMEOUT_SECONDS "
                          "or investigating performance issues.",
        "startup_validation_failed": "Application started but validation checks failed. "
                                      "Review logs for startup errors or health check failures.",
        "command_error": "Build command failed. Review the matched_line and stderr for details.",
    }
    return action_map.get(kind, "Review build failure details and logs. If the issue persists, check preflight configuration.")


def _event_phase_key(event: Any) -> str:
    """Map an artifact_written event to its pipeline phase.

    Looks at the event's artifact_kind/relative_path in payload first,
    then falls back to event type matching.
    """
    event_type = str(event.type)
    # Phase events are directly mapped
    for key, _label, event_types in _PIPELINE_PHASES:
        if event_type in event_types:
            return key
    # For artifact_written, derive phase from payload
    if event_type == "artifact_written":
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        kind = str(payload.get("artifact_kind", "")).lower()
        path = str(payload.get("relative_path", "")).lower()
        # Map by artifact_kind
        if any(k in kind for k in ("analysis", "analyze")) or "analysis" in path:
            return "analysis"
        if any(k in kind for k in ("plan", "planning")) or "planning" in path:
            return "planning"
        if any(k in kind for k in ("assessment", "assess")) or "assessment" in path:
            return "assessment"
        if any(k in kind for k in ("approval", "decision")):
            return "human_approval"
        if any(k in kind for k in ("transform", "openrewrite", "migration_ledger", "phase2")):
            return "sandbox_transform"
        if any(k in kind for k in ("build", "compile")) or "build" in path:
            return "build_validation"
        if any(k in kind for k in ("test", "validation")) or "test" in path:
            return "test_validation"
        if any(k in kind for k in ("final", "proof", "orchestration", "report")):
            return "final_report"
        if any(k in kind for k in ("repair", "copilot", "fallback")):
            return "failure_repair"
    return ""


def _event_payload_dict(event: Any) -> dict[str, Any]:
    """Extract a dict payload from an event, handling both dict and JSON string forms."""
    payload_json = getattr(event, "payload_json", None)
    if payload_json:
        if isinstance(payload_json, str):
            try:
                return json.loads(payload_json)
            except (json.JSONDecodeError, TypeError):
                return {}
        if isinstance(payload_json, dict):
            return payload_json
    payload = getattr(event, "payload", None)
    if payload is not None:
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                return {}
        if isinstance(payload, dict):
            return payload
    return {}


def _v2_stages_from_job(job: Any, commands: tuple[Any, ...], events: tuple[Any, ...]) -> list[dict[str, Any]]:
    try:
        stages = json.loads(job.stage_chain_json)
    except (json.JSONDecodeError, TypeError):
        stages = []
    if not stages:
        stages = [
            {
                "stage_index": 1,
                "stage_run_id": "",
                "pipeline_stage": "Stage 1",
                "input_source_kind": "legacy_source",
                "chain_status": "pending",
            },
            {
                "stage_index": 2,
                "stage_run_id": "",
                "pipeline_stage": "Stage 2",
                "input_source_kind": "stage_1_sandbox",
                "chain_status": "pending",
            },
            {
                "stage_index": 3,
                "stage_run_id": "",
                "pipeline_stage": "Stage 3",
                "input_source_kind": "stage_2_sandbox",
                "chain_status": "pending",
            },
        ]

    command_stages = {command.stage_index for command in commands}
    # Chronological lifecycle reducer — processes events in sequence order.
    # Each event transitions the state; later running/terminal events override
    # earlier blocked/pending.  This is *not* a max-precedence scan.
    from collections import defaultdict
    stage_events: dict[int, list[Any]] = defaultdict(list)
    for event in events:
        if event.stage is None and event.type != "next_stage_queued":
            continue
        if event.type == "next_stage_queued":
            payload = _event_payload_dict(event)
            from_stage = int(payload.get("from_stage") or 0)
            to_stage = int(payload.get("to_stage") or event.stage or 0)
            if from_stage:
                stage_events[from_stage].append(event)
            if to_stage:
                stage_events[to_stage].append(event)
            continue
        if event.stage:
            stage_events[event.stage].append(event)

    status_by_stage: dict[int, str] = {
        idx: _reduce_stage_status_with_next_stage(evts, idx) for idx, evts in stage_events.items()
    }
    for stage_index in command_stages:
        status_by_stage.setdefault(stage_index, "queued")

    normalized = []
    for stage in sorted(stages, key=lambda item: int(item["stage_index"])):
        stage_index = int(stage["stage_index"])
        normalized.append({
            "stage_index": stage_index,
            "stage_run_id": stage.get("stage_run_id", ""),
            "pipeline_stage": stage.get("pipeline_stage", f"Stage {stage_index}"),
            "input_source_kind": stage.get("input_source_kind", ""),
            "chain_status": status_by_stage.get(stage_index, stage.get("chain_status", "pending")),
        })
    return normalized


def _reduce_stage_status_with_next_stage(events: list[Any], stage_index: int) -> str:
    """Reduce chronologically-ordered events, handling next_stage_queued.

    next_stage_queued with from_stage marks that stage as completed.
    next_stage_queued with to_stage marks that stage as queued.
    """
    current = "pending"
    for event in events:
        if event.type == "next_stage_queued":
            payload = _event_payload_dict(event)
            from_stage = int(payload.get("from_stage") or 0)
            to_stage = int(payload.get("to_stage") or event.stage or 0)
            if from_stage == stage_index:
                current = _transition_stage_status(current, "completed")
            elif to_stage == stage_index:
                current = _transition_stage_status(current, "queued")
            continue
        mapped = _stage_status_from_event(event.type, event.status)
        current = _transition_stage_status(current, mapped)
    return current


def _stage_status_from_event(event_type: str, event_status: str) -> str:
    """Map a single (event_type, event_status) to a stage status label.

    This is an *input* to the chronological reducer; the label alone does
    NOT determine the final stage status (see ``_reduce_stage_status``).
    """
    if event_type == "stage_failed" or event_status == "failed":
        return "failed"
    if event_type == "stage_completed":
        return "completed"
    if event_type in {
        "stage_started", "command_started",
        "sandbox_transform_started", "sandbox_transform_completed",
        "resume_started", "approval_resume_queued", "approval_completed",
        "build_started", "test_started",
    } or event_status == "running":
        return "running"
    if event_type in {"approval_required", "stage_blocked_for_approval"} or event_status == "blocked":
        return "blocked"
    if event_type in {"stage_queued", "next_stage_queued"} or event_status == "queued":
        return "queued"
    return "pending"


def _reduce_stage_status(events: list[Any]) -> str:
    """Reduce chronologically-ordered events to a single stage status.

    Applies a state transition for each event so that later active/terminal
    events override earlier blocked/pending states.  This replaces the old
    max-precedence scan that could never un-block a stage after approval.
    """
    current = "pending"
    for event in events:
        mapped = _stage_status_from_event(event.type, event.status)
        current = _transition_stage_status(current, mapped)
    return current


def _transition_stage_status(current: str, mapped: str) -> str:
    """State-transition helper: given current status and mapped label,
    return the new status respecting lifecycle rules.

    * failed         → terminal (highest priority)
    * completed      → terminal unless a later failure arrives
    * running        → overrides blocked/pending/queued
    * blocked        → applies only if not already running/completed/failed
    * queued         → applies only if not already past it
    * pending        → no change
    """
    if mapped == "failed":
        return "failed"
    if mapped == "completed":
        return "completed"
    if mapped == "running":
        return "running"
    if mapped == "blocked":
        if current in ("running", "completed", "failed"):
            return current
        return "blocked"
    if mapped == "queued":
        if current in ("running", "completed", "failed", "blocked"):
            return current
        return "queued"
    return current


def _v2_event_payload(event: Any) -> dict[str, Any]:
    try:
        payload = json.loads(event.payload_json)
    except (json.JSONDecodeError, TypeError):
        payload = {}
    return redact_public_data({
        "event_id": event.event_id,
        "job_id": event.job_id,
        "stage": event.stage,
        "type": event.type,
        "status": event.status,
        "message": _bounded_event_text(event.message),
        "payload": payload,
        "created_at": event.created_at,
        "sequence": event.sequence,
    })


def _bounded_event_text(value: str, *, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...[truncated]"


async def _v2_event_stream(
    *,
    job_id: str,
    initial_after_sequence: int,
    request: Request,
    unit_of_work_factory: UnitOfWorkFactory,
    notifier: PublicEventNotifier,
    config: EventReplayConfig,
    once: bool = False,
) -> AsyncIterator[str]:
    last_sent_sequence = initial_after_sequence
    last_keepalive = time.monotonic()
    notifier_version = notifier.version
    while True:
        if await request.is_disconnected():
            break
        with unit_of_work_factory() as uow:
            events = uow.v2_events.list_after_sequence(job_id, last_sent_sequence)
        if events:
            for event in events:
                last_sent_sequence = event.sequence
                yield _sse_frame(
                    id=str(event.sequence),
                    event=event.type,
                    data=_v2_event_payload(event),
                    retry=config.reconnect_delay_ms,
                )
            last_keepalive = time.monotonic()
            if once:
                break
            continue
        now = time.monotonic()
        if now - last_keepalive >= config.keepalive_interval_seconds:
            last_keepalive = now
            yield ": keepalive\n\n"
        notifier_version = await notifier.wait(notifier_version, config.poll_interval_seconds)


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


def _parse_and_validate_model_output(
    *,
    model_content: str,
    schema_name: str,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse JSON from model output and validate against the named schema.

    If the model returns plain text that is not valid JSON, or the JSON
    fails schema validation, and a fallback is provided, the fallback is
    returned with a logged warning. If no fallback is provided, a
    ValueError is raised.

    This is the boundary between raw model text and typed backend objects.
    """
    from migration_factory.control_tower.application.v2_model_schemas import (
        validate_against_schema,
        SchemaValidationError,
    )

    parsed: dict[str, Any] | None = None
    try:
        # Try direct JSON parse
        parsed = json.loads(model_content) if isinstance(model_content, str) else model_content
        if not isinstance(parsed, dict):
            parsed = None
    except (json.JSONDecodeError, TypeError):
        # Try to extract JSON from markdown code blocks
        import re as _re
        m = _re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', str(model_content))
        if m:
            try:
                parsed = json.loads(m.group(1))
                if not isinstance(parsed, dict):
                    parsed = None
            except (json.JSONDecodeError, TypeError):
                pass

    if parsed is not None:
        try:
            validate_against_schema(schema_name, parsed)
            return parsed
        except SchemaValidationError:
            pass

    if fallback is not None:
        return fallback
    raise ValueError(
        f"Model output could not be parsed as valid {schema_name}"
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
