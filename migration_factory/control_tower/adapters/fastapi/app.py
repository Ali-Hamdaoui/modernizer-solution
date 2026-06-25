"""Minimal FastAPI adapter for the M2 diagnostic queue path."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
import hashlib
from typing import Any, Callable

from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
from migration_factory.control_tower.application.v2_final_report_service import (
    V2FinalReportService,
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
    V2AssistantModelResult,
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
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_repair_gate_service import (
    V2RepairGateService,
    create_repair_gate_diagnosis_callback,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_gate_action_service import (
    V2GateActionService,
)
from migration_factory.control_tower.application.v2_gate_artifact_resolver import (
    V2GateArtifactResolver,
)
from migration_factory.control_tower.application.v2_evidence_pack_builder import (
    EvidencePackBuilder,
    evidence_pack_to_dict,
)
from migration_factory.control_tower.application.v2_gate_assistant import (
    ActionPreview,
    ClassifiedIntent,
    ConfirmationStore,
    GateActionExecutor,
    GateActionPreviewBuilder,
    GateContext,
    GateContextLoader,
    GateIntentClassifier,
)
from migration_factory.control_tower.application.v2_assistant_response_composer import (
    AssistantResponseCard,
    AssistantResponseSection,
    V2AssistantResponseComposer,
)
from migration_factory.control_tower.application.v2_phase_gate_service import (
    AvailableAction,
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_orchestrator_runner import (
    V2OrchestratorRunner,
    V2OrchestratorStart,
    _bounded,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    create_orchestrator_diagnosis_callback,
)
from migration_factory.control_tower.application.redaction import (
    redact_absolute_paths,
    redact_public_value,
)
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
from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.domain.gate_checksum import gate_checksum
from migration_factory.control_tower.schemas.phase_gate import (
    GateActorType,
    GateDecision,
    GatePhase,
)
from migration_factory.control_tower.application.v2_gate_errors import (
    http_status_for_gate_status,
)
from uuid import uuid4

# F14 â€” Stage 3 POM dependency editor imports
from migration_factory.control_tower.application.pom_dependency_editor import (
    PomDependencyEditor,
)
from migration_factory.control_tower.application.pom_change_models import (
    PomProposeRequest,
    PomApplyRequest,
    PomRepairApplyRequest,
    PomRollbackRequest,
)


UnitOfWorkFactory = Any
ETAG_RE = re.compile(r'^"job-(?P<job_id>.+)-v(?P<version>[1-9][0-9]*)"$')
_POM_DEPENDENCY_EDITOR_FACTORY: Callable[[], PomDependencyEditor] | None = None
_ASSISTANT_RESPONSE_COMPOSER = V2AssistantResponseComposer()


def _configure_pom_dependency_editor_factory(
    factory: Callable[[], PomDependencyEditor],
) -> None:
    global _POM_DEPENDENCY_EDITOR_FACTORY
    _POM_DEPENDENCY_EDITOR_FACTORY = factory


def _build_pom_dependency_editor() -> PomDependencyEditor:
    """Build the configured F14 POM editor used by API and assistant paths."""
    if _POM_DEPENDENCY_EDITOR_FACTORY is None:
        raise RuntimeError("PomDependencyEditor factory is not configured")
    return _POM_DEPENDENCY_EDITOR_FACTORY()


@contextmanager
def _read_unit_of_work(unit_of_work_factory: UnitOfWorkFactory):
    uow = unit_of_work_factory()
    if hasattr(uow, "transaction_mode"):
        uow.transaction_mode = "read"
    with uow as entered:
        yield entered


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
    policy: RunPolicy | None = None


class StartV2JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    setup_id: str


class ApproveCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_checksum: str

class GateActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: GateDecision
    expected_gate_checksum: str
    idempotency_key: str | None = None
    decided_by: str
    actor_type: GateActorType
    reason: str = ""
    proposal_id: str | None = None
    proposal_checksum: str | None = None
    context_pack_checksum: str | None = None
    user_feedback: str = ""

# F07 reviewer request â€” context only, no decision from client

class CreateReviewerCritiqueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    proposal_type: str = "repair"  # repair, pom_patch
    proposal_checksum: str
    context_pack_checksum: str
    # Internal: model_invocation_id for audit (set by orchestrator, not client)
    model_invocation_id: str | None = None
    # F07: decision, reasoning, missing_evidence, unsafe_assumptions are
    # NEVER accepted from client body â€” the model generates them.


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
    # F07: both checksums required â€” reviewer gate is mandatory, no bypass
    proposal_checksum: str
    context_pack_checksum: str


# â”€â”€ F14 POM dependency editor request schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class PomProposeRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_request: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = None


class PomApplyRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str | None = None
    user_request: str | None = None
    idempotency_key: str | None = None
    plan_preview: dict[str, Any] | None = None  # Advisory only, never trusted


class PomRepairApplyRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repair_plan_id: str
    idempotency_key: str | None = None


class PomRollbackRequestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    change_id: str
    idempotency_key: str | None = None


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
    # â”€â”€ F02: Wire automatic failure diagnosis into the orchestrator â”€â”€
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
    _diagnosis_service = V2FailureDiagnosisService(
        repair_flow=_repair_flow,
        event_sink=_diagnosis_event_sink,
    )
    _orchestrator_diagnosis_callback = create_orchestrator_diagnosis_callback(
        service=_diagnosis_service,
    )

    def _repair_gate_enabled_for_job(job_id: str) -> bool:
        with unit_of_work_factory() as uow:
            run_config = uow.run_configurations.get_for_job(job_id)
        if run_config is None or not run_config.policy_json:
            return False
        try:
            policy = RunPolicy(**json.loads(run_config.policy_json))
        except Exception:
            return False
        return policy.enable_build_repair

    def _maybe_create_repair_gate(
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if not V2FailureDiagnosisService.is_diagnosable_event(event_type):
            return
        if not _repair_gate_enabled_for_job(job_id):
            return

        with unit_of_work_factory() as uow:
            gate_service = V2PhaseGateService(uow.phase_gates)
            decision_service = V2GateActionService(
                uow.phase_gates,
                uow.gate_decisions,
                gate_service,
                revision_repo=uow.artifact_revisions,
                repair_service=_repair_flow,
            )
            repair_gate_service = V2RepairGateService(
                gate_service=gate_service,
                gate_action_service=decision_service,
                repair_flow=_repair_flow,
                diagnosis_service=_diagnosis_service,
            )
            create_repair_gate_diagnosis_callback(
                repair_gate_service,
                _diagnosis_service,
            )(job_id, stage_index, command_id, event_type, payload)

    def _diagnosis_callback(
        job_id: str,
        stage: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        _orchestrator_diagnosis_callback(job_id, stage, command_id, event_type, payload)
        _maybe_create_repair_gate(job_id, stage, command_id, event_type, payload)
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
                run_config_repo=uow.run_configurations,
                runner_profile_repo=uow.runner_profiles,
                pipeline_repo=uow.pipeline_definitions,
            )
            try:
                result = service.create_job(payload.setup_id, policy=payload.policy)
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
            service = V2MigrationJobService(
                setup_repo=uow.v2_setups,
                job_repo=uow.v2_jobs,
                run_config_repo=uow.run_configurations,
                runner_profile_repo=uow.runner_profiles,
                pipeline_repo=uow.pipeline_definitions,
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
            job = _require_v2_job(uow, job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            events = uow.v2_events.list_by_job(job_id)
        return {
            "job_id": job_id,
            "stages": _v2_stages_from_job(job, commands, events),
        }

    @app.get("/v1/v2/jobs/{job_id}/report")
    def get_v2_final_report(job_id: str) -> dict[str, Any]:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            service = V2FinalReportService(
                job_repo=uow.v2_jobs,
                command_repo=uow.v2_commands,
            )
            report = service.get_report(job_id)
        if report is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "V2_REPORT_NOT_FOUND",
                f"No generated V2 report found for job {job_id!r}.",
            )
        return service.snapshot_to_dict(report)

    @app.post("/v1/v2/jobs/{job_id}/report", status_code=status.HTTP_201_CREATED)
    def generate_v2_final_report(job_id: str) -> dict[str, Any]:
        actor = resolved_actor_provider.current_actor()
        with unit_of_work_factory() as uow:
            _require_v2_job(uow, job_id)
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="final_report_requested",
                status="queued",
                message="Final report generation requested by operator.",
                payload={"actor_id": actor.actor_id},
            )
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="final_report_started",
                status="running",
                message="Final report generation started.",
                payload={"actor_id": actor.actor_id},
            )
            service = V2FinalReportService(
                job_repo=uow.v2_jobs,
                command_repo=uow.v2_commands,
            )
            try:
                report = service.generate_report(job_id)
            except ValueError as exc:
                _append_v2_event(
                    uow,
                    job_id=job_id,
                    stage=3,
                    event_type="final_report_failed",
                    status="failed",
                    message=str(exc),
                    payload={"actor_id": actor.actor_id},
                )
                raise _error(
                    status.HTTP_400_BAD_REQUEST,
                    "V2_REPORT_GENERATION_FAILED",
                    str(exc),
                ) from exc
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="artifact_written",
                status="completed",
                message="Artifact written: final_migration_report_docs",
                payload={
                    "artifact_kind": "final_migration_report_docs",
                    "relative_path": report.docs_report_json,
                },
            )
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="artifact_written",
                status="completed",
                message="Artifact written: final_migration_summary_docs",
                payload={
                    "artifact_kind": "final_migration_summary_docs",
                    "relative_path": report.docs_report_markdown,
                },
            )
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="artifact_written",
                status="completed",
                message="Artifact written: final_migration_pdf_docs",
                payload={
                    "artifact_kind": "final_migration_pdf_docs",
                    "relative_path": report.docs_report_pdf,
                },
            )
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=3,
                event_type="final_report_completed",
                status="completed",
                message="Final report generated and stored in docs.",
                payload={
                    "actor_id": actor.actor_id,
                    "docs_report_json": report.docs_report_json,
                    "docs_report_markdown": report.docs_report_markdown,
                    "docs_report_pdf": report.docs_report_pdf,
                    "total_duration_seconds": report.total_duration_seconds,
                },
            )
        return service.snapshot_to_dict(report)

    @app.get("/v1/v2/jobs/{job_id}/report.pdf")
    def download_v2_final_report_pdf(job_id: str) -> FileResponse:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            service = V2FinalReportService(
                job_repo=uow.v2_jobs,
                command_repo=uow.v2_commands,
            )
            report = service.get_report(job_id)
        if report is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "V2_REPORT_NOT_FOUND",
                f"No generated V2 report found for job {job_id!r}.",
            )
        pdf_path = Path(report.run_report_pdf)
        if not pdf_path.is_file():
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "V2_REPORT_PDF_NOT_FOUND",
                f"No generated V2 report PDF found for job {job_id!r}.",
            )
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"{job_id}-full-migration-report.pdf",
            headers={"Content-Disposition": f'attachment; filename="{job_id}-full-migration-report.pdf"'},
        )

    @app.get("/v1/v2/jobs/{job_id}/approvals")
    def list_v2_job_approvals(job_id: str) -> dict[str, Any]:
        """Return V2 approval cards, or [] for valid jobs with no cards."""
        with _read_unit_of_work(unit_of_work_factory) as uow:
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
        return redact_public_data(_v2_failure_summary(job_id, events))

    def _v2_gate_to_dict(
        gate: Any,
        *,
        available_actions: list[AvailableAction] | None = None,
    ) -> dict[str, Any]:
        try:
            refs_raw = json.loads(gate.source_artifact_refs_json or "[]")
        except (json.JSONDecodeError, TypeError):
            refs_raw = []
        if isinstance(refs_raw, dict):
            refs = [str(value) for value in refs_raw.values() if value]
        elif isinstance(refs_raw, list):
            refs = [str(value) for value in refs_raw if value]
        else:
            refs = []
        checksum = gate_checksum(
            gate_id=gate.gate_id,
            job_id=gate.job_id,
            gate_phase=gate.gate_phase,
            stage_index=gate.stage_index,
            source_artifact_checksum=gate.source_artifact_checksum,
            source_artifact_refs=tuple(refs),
        )
        return {
            "gate_id": gate.gate_id,
            "job_id": gate.job_id,
            "gate_phase": gate.gate_phase,
            "stage_index": gate.stage_index,
            "gate_status": gate.gate_status,
            "gate_decision": gate.gate_decision,
            "source_artifact_checksum": gate.source_artifact_checksum,
            "source_artifact_refs": refs,
            "created_at": gate.created_at,
            "resolved_at": gate.resolved_at,
            "resolved_by": gate.resolved_by,
            "checksum": checksum,
            "available_actions": [
                {
                    "action": action.action,
                    "label": action.label,
                    "description": action.description,
                    "blocked": action.blocked,
                    "block_reason": action.block_reason,
                }
                for action in (available_actions or [])
            ],
        }

    def _v2_gate_detail_payload(
        uow: Any,
        gate: Any,
    ) -> dict[str, Any]:
        gate_service = V2PhaseGateService(uow.phase_gates)
        available_actions = gate_service.get_available_actions(gate.gate_id)
        gate_dict = _v2_gate_to_dict(gate, available_actions=available_actions)

        evidence: dict[str, Any] | None = None
        setup = None
        job = uow.v2_jobs.get(gate.job_id)
        if job is not None and getattr(job, "setup_id", None):
            setup = uow.v2_setups.get(job.setup_id)
        storage_root = getattr(setup, "output_parent_path", None) if setup is not None else None
        resolver = V2GateArtifactResolver(uow.phase_gates, storage_root=storage_root)
        pack_builder = EvidencePackBuilder(resolver)
        try:
            gate_phase = GatePhase(gate.gate_phase)
        except ValueError:
            gate_phase = None
        if gate_phase == GatePhase.ANALYSIS_REVIEW:
            evidence = evidence_pack_to_dict(pack_builder.build_analysis_pack(gate.gate_id))
        elif gate_phase == GatePhase.PLANNING_REVIEW:
            evidence = evidence_pack_to_dict(pack_builder.build_planning_pack(gate.gate_id))
        elif gate_phase == GatePhase.APPROVAL_REVIEW:
            evidence = evidence_pack_to_dict(pack_builder.build_approval_pack(gate.gate_id))
        elif gate_phase in {GatePhase.REPAIR_REVIEW, GatePhase.STAGE_COMPLETION_REVIEW}:
            evidence = evidence_pack_to_dict(pack_builder.build_failure_pack(gate.gate_id))

        return {
            "gate": gate_dict,
            "evidence": evidence,
            "checksum": gate_dict["checksum"],
        }

    def _v2_gate_action_response(
        uow: Any,
        *,
        job_id: str,
        gate_id: str,
        payload: GateActionRequest,
    ) -> dict[str, Any]:
        gate_service = V2PhaseGateService(uow.phase_gates)
        repair_flow = V2RepairFlowService(repair_repo=uow.v2_repairs)
        action_service = V2GateActionService(
            uow.phase_gates,
            uow.gate_decisions,
            gate_service,
            revision_repo=uow.artifact_revisions,
            repair_service=repair_flow,
        )
        repair_gate_service = V2RepairGateService(
            gate_service=gate_service,
            gate_action_service=action_service,
            repair_flow=repair_flow,
        )

        gate = uow.phase_gates.get(gate_id)
        if gate is None:
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "GATE_NOT_FOUND",
                f"Gate {gate_id!r} not found.",
            )
        if gate.job_id != job_id:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "GATE_JOB_MISMATCH",
                "Gate job does not match the requested job.",
            )

        try:
            gate_refs = json.loads(gate.source_artifact_refs_json or "[]")
        except (json.JSONDecodeError, TypeError):
            gate_refs = []
        gate_checksum_value = gate_checksum(
            gate_id=gate.gate_id,
            job_id=gate.job_id,
            gate_phase=gate.gate_phase,
            stage_index=gate.stage_index,
            source_artifact_checksum=gate.source_artifact_checksum,
            source_artifact_refs=tuple(gate_refs),
        )

        actor_type = payload.actor_type.value if hasattr(payload.actor_type, "value") else str(payload.actor_type)
        action_value = payload.action.value if hasattr(payload.action, "value") else str(payload.action)
        if action_value == GateDecision.CONTINUE.value:
            result = action_service.continue_from_gate(
                gate_id=gate_id,
                job_id=job_id,
                decided_by=payload.decided_by,
                idempotency_key=payload.idempotency_key,
                expected_gate_checksum=payload.expected_gate_checksum,
                actor_type=actor_type,
            )
        elif action_value == GateDecision.REANALYZE.value:
            result = action_service.request_reanalysis(
                gate_id=gate_id,
                job_id=job_id,
                decided_by=payload.decided_by,
                user_feedback=payload.user_feedback,
                idempotency_key=payload.idempotency_key,
                expected_gate_checksum=payload.expected_gate_checksum,
            )
        elif action_value == GateDecision.REVISE.value:
            if gate.gate_phase == GatePhase.REPAIR_REVIEW.value:
                result = repair_gate_service.request_repair_revision(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    proposal_id=payload.proposal_id or "",
                    user_feedback=payload.user_feedback,
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                )
            else:
                result = action_service.request_plan_revision(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    user_feedback=payload.user_feedback,
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                )
        elif action_value == GateDecision.APPROVE.value:
            if gate.gate_phase == GatePhase.REPAIR_REVIEW.value:
                result = repair_gate_service.approve_repair(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    proposal_id=payload.proposal_id or "",
                    proposal_checksum=payload.proposal_checksum or "",
                    context_pack_checksum=payload.context_pack_checksum or "",
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                    actor_type=actor_type,
                )
            else:
                revision_requested_active = False
                if gate.gate_phase == GatePhase.APPROVAL_REVIEW.value:
                    revision_requested_active = (
                        _approval_review_blocked_revision_card(
                            uow,
                            job_id=job_id,
                            stage_index=gate.stage_index,
                            gate_checksum=gate_checksum_value,
                        )
                        is not None
                    )
                result = action_service.approve_transformation(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                    actor_type=actor_type,
                    revision_requested_active=revision_requested_active,
                )
        elif action_value == GateDecision.REJECT.value:
            if gate.gate_phase == GatePhase.REPAIR_REVIEW.value:
                result = repair_gate_service.reject_repair(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    reason=payload.reason,
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                    actor_type=actor_type,
                )
            else:
                result = action_service.reject_gate(
                    gate_id=gate_id,
                    job_id=job_id,
                    decided_by=payload.decided_by,
                    reason=payload.reason,
                    idempotency_key=payload.idempotency_key,
                    expected_gate_checksum=payload.expected_gate_checksum,
                    actor_type=actor_type,
                )
        else:
            raise _error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "UNSUPPORTED_GATE_ACTION",
                f"Unsupported gate action {action_value!r}.",
            )

        if result.status == "idempotency_conflict":
            raise _error(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_CONFLICT",
                result.reason or "Idempotency key was reused for a different request.",
            )
        if result.status == "stale_checksum":
            raise _error(
                status.HTTP_409_CONFLICT,
                "STALE_GATE_CHECKSUM",
                result.reason or "Gate checksum is stale.",
            )
        if result.status in {"actor_not_authoritative", "invalid_decision", "gate_not_open", "gate_not_found", "command_conflict", "approval_failed", "no_repair_service", "no_action_service"}:
            raise _error(
                http_status_for_gate_status(result.status),
                result.status.upper(),
                result.reason or result.status,
            )

        return {
            "result": {
                "decision_id": result.decision_id,
                "gate_id": result.gate_id,
                "job_id": job_id,
                "action": result.action,
                "status": result.status,
                "result_gate_id": result.result_gate_id,
                "result_command_id": result.result_command_id,
                "result_revision_id": result.result_revision_id,
                "reason": result.reason,
            }
        }

    @app.get("/v1/v2/jobs/{job_id}/gates")
    def list_v2_job_gates(job_id: str) -> dict[str, Any]:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            gates = sorted(
                uow.phase_gates.list_by_job(job_id),
                key=lambda gate: (gate.created_at, gate.stage_index, gate.gate_id),
            )
            gate_service = V2PhaseGateService(uow.phase_gates)
            return {
                "gates": [
                    _v2_gate_to_dict(
                        gate,
                        available_actions=gate_service.get_available_actions(gate.gate_id),
                    )
                    for gate in gates
                ]
            }

    @app.get("/v1/v2/jobs/{job_id}/gates/open")
    def get_v2_job_open_gate(job_id: str) -> dict[str, Any]:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            open_gates = uow.phase_gates.list_open(job_id)
            gate = open_gates[0] if open_gates else None
            gate_service = V2PhaseGateService(uow.phase_gates)
            return {
                "gate": None if gate is None else _v2_gate_to_dict(
                    gate,
                    available_actions=gate_service.get_available_actions(gate.gate_id),
                )
            }

    @app.get("/v1/v2/jobs/{job_id}/gates/{gate_id}")
    def get_v2_job_gate(job_id: str, gate_id: str) -> dict[str, Any]:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            gate = uow.phase_gates.get(gate_id)
            if gate is None or gate.job_id != job_id:
                raise _error(
                    status.HTTP_404_NOT_FOUND,
                    "GATE_NOT_FOUND",
                    f"Gate {gate_id!r} not found.",
                )
            return _v2_gate_detail_payload(uow, gate)

    @app.post("/v1/v2/jobs/{job_id}/gates/{gate_id}/actions")
    def post_v2_job_gate_action(
        job_id: str,
        gate_id: str,
        payload: GateActionRequest,
    ) -> dict[str, Any]:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            return _v2_gate_action_response(uow, job_id=job_id, gate_id=gate_id, payload=payload)


    @app.get("/v1/v2/jobs/{job_id}/artifacts/{artifact_kind}")
    def get_v2_job_artifact_preview(
        job_id: str,
        artifact_kind: str,
        stage: int | None = Query(default=None, ge=1, le=3),
    ) -> dict[str, Any]:
        """Return a bounded, redacted preview of a named artifact.

        Only allows artifact kinds from persisted artifact_refs.
        Never accepts arbitrary paths.
        Bounds output to 32 KB.
        Redacts secrets and full local paths.
        Supports optional stage filter for stage-scoped artifacts.
        """
        safe_kinds = {
            "phase2_log", "post_transform_test_log", "failure_classification",
            "repair_plan", "deterministic_repair_plan", "copilot_repair_response",
            "dependency_policy_report", "dependency_policy_summary",
            "dependency_repair_plan", "orchestration_summary",
            "target_dependency_plan", "rewrite_dry_run.patch",
            "rewrite_impact_summary.json", "repair_ledger", "migration_ledger",
            "openrewrite_plugin_xml", "approved_plan_lock",
        }
        if artifact_kind not in safe_kinds:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "UNKNOWN_ARTIFACT_KIND",
                f"Unknown artifact kind.",
            )
        with _read_unit_of_work(unit_of_work_factory) as uow:
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

        # Find the artifact ref from artifact_written events belonging to this job.
        # If stage filter is provided, only match events for that stage.
        # When multiple matches exist, prefer the latest (highest sequence) match.
        artifact_path = None
        best_sequence = -1
        for event in events:
            if event.type != "artifact_written":
                continue
            if stage is not None and event.stage != stage:
                continue
            try:
                payload = json.loads(event.payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            kind = str(payload.get("artifact_kind", ""))
            if kind == artifact_kind:
                path_val = payload.get("relative_path") or payload.get("path")
                if path_val and getattr(event, "sequence", 0) > best_sequence:
                    artifact_path = str(path_val)
                    best_sequence = getattr(event, "sequence", 0)

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

    @app.get("/v1/v2/jobs/{job_id}/files/root-pom")
    def get_v2_job_root_pom_file(
        request: Request,
        job_id: str,
        stage: int = Query(default=1, ge=1, le=4),
        mode: str = Query(default="preview", pattern="^(preview|download)$"),
    ) -> Any:
        """Return the backend-resolved root pom.xml for a completed stage.

        The only supported file alias is root_pom. The request never accepts
        a path; the file is resolved from persisted command/event sandbox state.
        """
        if "path" in request.query_params or "file" in request.query_params:
            raise _error(
                status.HTTP_400_BAD_REQUEST,
                "PATH_NOT_ACCEPTED",
                "File paths are not accepted for this endpoint.",
            )
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)

        preview = _resolve_root_pom_file_alias_preview(
            job_id=job_id,
            stage_index=stage,
            events=events,
            commands=commands,
            max_bytes=32768,
        )
        if mode == "preview" or not preview.get("exists"):
            preview.pop("_path", None)
            return preview

        # Download mode: read full file, redact, return as text response
        # Uses same redaction policy as preview (never returns raw file)
        candidate_path = preview.get("_path")
        if not isinstance(candidate_path, Path) or not candidate_path.is_file():
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "ROOT_POM_NOT_AVAILABLE",
                "Root pom.xml is not available for that stage.",
            )
        from migration_factory.control_tower.application.redaction import redact_model_summary
        try:
            raw_bytes = candidate_path.read_bytes()
            if raw_bytes[:3] == b"\xef\xbb\xbf":
                raw_bytes = raw_bytes[3:]
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
            except (UnicodeDecodeError, LookupError):
                text = raw_bytes.decode("latin-1", errors="replace")
            redacted = redact_model_summary(text)
        except (OSError, RuntimeError, ValueError):
            raise _error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "ROOT_POM_READ_ERROR",
                "Root pom.xml could not be read for download.",
            )
        return Response(
            content=redacted,
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="stage-{stage}-pom.xml"'},
        )

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
        with _read_unit_of_work(unit_of_work_factory) as uow:
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
        launch_status: str | None = None
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
            if resume.resume_id:
                launch_status = _resume_launch_state_from_events(
                    uow,
                    job_id=job_id,
                    resume_id=resume.resume_id,
                )
            if is_new_approve and resume.resume_id:
                _append_v2_event(
                    uow,
                    job_id=job_id,
                    stage=resume.stage_index,
                    event_type="approval_resume_queued",
                    status="queued",
                    message="Approval accepted; backend-owned resume command queued.",
                    payload={"card_id": card_id, "resume_id": resume.resume_id, "resume_status": "queued"},
                )
                launch_status = "queued"
        if is_new_approve and resume.resume_id:
            resume_launch = _start_resume_command(
                app,
                job_id=job_id,
                resume_id=resume.resume_id,
                stage_index=resume.stage_index,
            )
            launch_status = resume_launch.status
            if resume_launch.status == "retrying":
                with unit_of_work_factory() as event_uow:
                    _append_v2_event(
                        event_uow,
                        job_id=job_id,
                        stage=resume.stage_index,
                        event_type="approval_resume_queued",
                        status="retrying",
                        message="Approval accepted; backend-owned resume command is retrying.",
                        payload={
                            "card_id": card_id,
                            "resume_id": resume.resume_id,
                            "resume_status": "retrying",
                        },
                    )
        asyncio.run(app.state.public_event_notifier.notify())
        response = service.resume_to_dict(resume)
        response["launch_status"] = launch_status or ("queued" if resume.resume_id else "")
        return response


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

    _confirmation_store = ConfirmationStore()

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
        """Ask the V2 assistant for read-only status guidance.

        F15: If the job has an open PhaseGate, the assistant becomes
        gate-aware — it loads gate context, classifies intent, and
        either explains gate-bound evidence or returns an action
        preview for state-changing intents. Confirmation toggles
        execution through V2GateActionService.
        """
        # -- Phase 1: Check for open gate --------------------------
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            open_gates = uow.phase_gates.list_open(job_id)

        question_lower = payload.question.strip().lower()
        assistant_intent = _classify_v2_assistant_intent(question_lower)

        if open_gates:
            open_gate = open_gates[0]
            if (
                _assistant_question_requires_write(question_lower=question_lower, assistant_intent=assistant_intent)
                or _question_looks_like_approval_review_revision_request(payload.question)
            ):
                try:
                    return _handle_gate_aware_ask(
                        app=app,
                        job_id=job_id,
                        open_gate=open_gate,
                        question=payload.question,
                        correlation_id=payload.correlation_id,
                        confirmation_store=_confirmation_store,
                        unit_of_work_factory=unit_of_work_factory,
                    )
                except sqlite3.OperationalError as exc:
                    if _is_sqlite_locked_error(exc):
                        return {
                            "job_id": job_id,
                            "gate_aware": True,
                            "executed": False,
                            "busy": True,
                            "assistant_message": {
                                "message_id": None,
                                "job_id": job_id,
                                "role": "assistant",
                                "content": "The orchestrator is busy right now. Retry shortly.",
                                "correlation_id": payload.correlation_id,
                                "created_at": utc_now_text(),
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
                    raise
            return _handle_gate_aware_read_only_ask(
                app=app,
                job_id=job_id,
                open_gate=open_gate,
                question=payload.question,
                correlation_id=payload.correlation_id,
                unit_of_work_factory=unit_of_work_factory,
            )

        resolved_gate_response = _handle_resolved_gate_checksum_confirm(
            job_id=job_id,
            question=payload.question,
            correlation_id=payload.correlation_id,
            unit_of_work_factory=unit_of_work_factory,
        )
        if resolved_gate_response is not None:
            return resolved_gate_response

        # -- Phase 2: No open gate — fall back to existing assistant --
        with unit_of_work_factory() as uow:
            job = _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
            approvals = uow.v2_approvals.list_cards_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            pipeline = _v2_pipeline_projection(job_id, events)
            service = V2AssistantService(assistant_repo=uow.v2_assistant)
            if not _assistant_question_requires_write(
                question_lower=question_lower,
                assistant_intent=assistant_intent,
            ):
                return _handle_v2_assistant_read_only_ask(
                    app=app,
                    job_id=job_id,
                    question=payload.question,
                    correlation_id=payload.correlation_id,
                    unit_of_work_factory=unit_of_work_factory,
                )
            # Read prior persisted messages for conversation history
            prior_messages = service.get_messages(job_id)
            user_msg = service.add_message(
                job_id=job_id,
                role="user",
                content=payload.question,
                correlation_id=payload.correlation_id,
            )
            # Build bounded conversation history from prior messages (excludes current user message)
            conversation_history = _build_bounded_conversation_history(
                messages=prior_messages,
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
            # Resolve artifact previews for artifact-content questions
            setup = uow.v2_setups.get(job.setup_id) if job.setup_id else None
            artifact_previews_list = _resolve_assistant_artifact_previews(
                question=payload.question,
                events=events,
                commands=commands,
                setup=setup,
                assistant_intent=assistant_intent,
            )
            artifact_previews = tuple(artifact_previews_list)
            if assistant_intent in {"apply_dependency_change", "rollback_pom_change"} and uow.connection.in_transaction:
                uow.connection.execute("COMMIT")
            fallback_answer = _build_v2_assistant_answer(
                question=payload.question,
                events=events,
                approvals=approvals,
                commands=commands,
                artifact_previews=artifact_previews if artifact_previews else None,
                assistant_intent=assistant_intent,
            )
            if assistant_intent in {"apply_dependency_change", "rollback_pom_change"}:
                model_result = V2AssistantModelResult(
                    content=fallback_answer,
                    source="backend_controlled",
                    model_status="not_used",
                    provider="backend",
                    role="assistant",
                    success=True,
                    redacted_summary="Backend-controlled assistant action completed.",
                    failure_reason="",
                )
            else:
                assistant_prompt = _build_v2_assistant_prompt(
                    question=payload.question,
                    job=job,
                    pipeline=pipeline,
                    events=events,
                    approvals=approvals,
                    artifact_previews=artifact_previews if artifact_previews else None,
                    assistant_intent=assistant_intent,
                    conversation_history=conversation_history,
                )
                assistant_client = app.state.v2_assistant_model_client
                if hasattr(assistant_client, "answer_with_role"):
                    model_result = assistant_client.answer_with_role(
                        role=V2ModelRole.ASSISTANT,
                        prompt=assistant_prompt,
                        fallback=fallback_answer,
                        conversation_history=conversation_history,
                    )
                else:
                    model_result = assistant_client.answer(
                        prompt=assistant_prompt,
                        fallback=fallback_answer,
                        conversation_history=conversation_history,
                    )
            assistant_msg = service.add_message(
                job_id=job_id,
                role="assistant",
                content=model_result.content,
                correlation_id=user_msg.message_id,
            )
        with unit_of_work_factory() as uow:
            is_fallback = (
                not model_result.success
                and model_result.source == "deterministic"
            )
            _append_v2_event(
                uow,
                job_id=job_id,
                stage=None,
                event_type="model_invocation_completed" if model_result.success else "model_invocation_failed",
                status="completed" if model_result.success else ("fallback" if is_fallback else "failed"),
                message=model_result.redacted_summary,
                payload={
                    "provider": model_result.provider,
                    "role": model_result.role,
                    "source": model_result.source,
                    "success": model_result.success,
                    "is_fallback": is_fallback,
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

                # Call the model â€” keep fallback for answer() but check success
                model_result = app.state.v2_assistant_model_client.answer(
                    prompt=revision_prompt,
                    fallback=json.dumps({
                        "failure_hypothesis": source_hypothesis,
                        "patch_summary": source_patch,
                        "affected_paths": list(source_paths),
                        "validation_plan": "Re-validate after revision",
                    }),
                )

                # F05: Fail closed â€” no model output = no revised proposal
                if not model_result.success:
                    raise _error(
                        status.HTTP_502_BAD_GATEWAY,
                        "REVISION_MODEL_FAILED",
                        f"Revision model unavailable: {model_result.redacted_summary}",
                    )

                # F05: Parse and validate model output â€” NO fallback
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
        """Request a reviewer critique via model â€” NEVER accepts decision from client.

        The backend builds the reviewer prompt from the proposal context,
        calls the reviewer model, validates the output against
        REVIEWER_CRITIQUE_SCHEMA, and persists the critique.

        Clients CANNOT fabricate a decision=accept â€” only the model output
        determines the verdict.
        """
        event_emitted = False
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
                "reasoning": "Model unavailable â€” defaulting to revise for safety.",
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
                    "reasoning": "Model unavailable â€” defaulting to revise for safety.",
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
            command = uow.v2_commands.get(command_id)
            if command is not None:
                _append_v2_event(
                    uow,
                    job_id=command.job_id,
                    stage=command.stage_index,
                    event_type="reviewer_critique_created",
                    status="completed",
                    message=f"Reviewer critique {critique.critique_id} recorded for proposal {proposal_id}",
                    payload=service.critique_to_dict(critique),
                )
                event_emitted = True
        if event_emitted:
            asyncio.run(app.state.public_event_notifier.notify())
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

    # ------------------------------------------------------------------
    # F14 â€” Stage 3 POM Dependency Review + Apply + Validate + Rollback
    # ------------------------------------------------------------------

    @app.get("/v1/v2/jobs/{job_id}/stage/3/pom")
    def get_stage3_pom(job_id: str) -> dict[str, Any]:
        """Get redacted Stage 3 POM content."""
        pom_content = _read_stage3_pom_content(job_id)
        pom_path = _resolve_sandbox_path_string(job_id, 3)
        target_dep_plan = _load_target_dependency_plan(job_id)

        editor = PomDependencyEditor()
        view = editor.get_stage3_pom(
            job_id,
            pom_content=pom_content,
            pom_path=pom_path,
            target_dependency_plan=target_dep_plan,
        )
        return view.to_public_dict()

    @app.get("/v1/v2/jobs/{job_id}/stage/3/dependency-review")
    def get_stage3_dependency_review(job_id: str) -> dict[str, Any]:
        """Get classified Stage 3 dependency review."""
        pom_content = _read_stage3_pom_content(job_id)
        pom_path = _resolve_sandbox_path_string(job_id, 3)
        target_dep_plan = _load_target_dependency_plan(job_id)
        policy_report = _load_dependency_policy_report(job_id)

        editor = PomDependencyEditor()
        review = editor.review_stage3_dependencies(
            job_id,
            pom_content=pom_content,
            pom_path=pom_path,
            target_dependency_plan=target_dep_plan,
            dependency_policy_report=policy_report,
        )
        return review.to_public_dict()

    @app.post("/v1/v2/jobs/{job_id}/stage/3/pom/propose-change")
    def propose_pom_change(
        job_id: str,
        payload: PomProposeRequestSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Propose a POM change (read-only, no write)."""
        pom_content = _read_stage3_pom_content(job_id)

        editor = _build_pom_dependency_editor()
        proposal = editor.propose_change(
            job_id,
            payload.user_request,
            payload.idempotency_key,
            pom_content=pom_content,
        )
        return proposal.to_public_dict()

    @app.post("/v1/v2/jobs/{job_id}/stage/3/pom/apply-change")
    def apply_pom_change(
        job_id: str,
        payload: PomApplyRequestSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Apply a POM change (backend validates then writes to Stage 3 sandbox)."""
        pom_content = _read_stage3_pom_content(job_id)
        sandbox_path = _resolve_sandbox_path_string(job_id, 3)
        build_cmd = _detect_build_command(job_id)

        if not sandbox_path:
            raise _error(status.HTTP_400_BAD_REQUEST, "NO_SANDBOX", "Stage 3 sandbox not available")

        editor = _build_pom_dependency_editor()

        if payload.proposal_id:
            result = editor.apply_change_from_proposal(
                job_id,
                payload.proposal_id,
                payload.idempotency_key or uuid4().hex,
                pom_content=pom_content,
                sandbox_path=sandbox_path,
                build_command=build_cmd,
            )
        elif payload.user_request:
            result = editor.apply_change_from_user_request(
                job_id,
                payload.user_request,
                payload.idempotency_key or uuid4().hex,
                pom_content=pom_content,
                sandbox_path=sandbox_path,
                build_command=build_cmd,
            )
        else:
            raise _error(status.HTTP_400_BAD_REQUEST, "INVALID_REQUEST", "proposal_id or user_request is required")

        return result.to_public_dict()

    @app.get("/v1/v2/jobs/{job_id}/stage/3/pom/changes")
    def list_pom_changes(job_id: str) -> dict[str, Any]:
        """List all POM changes for the job."""
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            editor = PomDependencyEditor(change_repo=uow.v2_pom_changes)
            changes = editor.list_changes(job_id)
        return {"job_id": job_id, "changes": [c.to_public_dict() for c in changes]}

    @app.get("/v1/v2/jobs/{job_id}/stage/3/pom/changes/{change_id}")
    def get_pom_change(job_id: str, change_id: str) -> dict[str, Any]:
        """Get a specific POM change record."""
        # Delegate to list and filter (in production, add direct lookup)
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            editor = PomDependencyEditor(change_repo=uow.v2_pom_changes)
            changes = editor.list_changes(job_id)
        for c in changes:
            if c.change_id == change_id:
                return c.to_public_dict()
        raise _error(status.HTTP_404_NOT_FOUND, "CHANGE_NOT_FOUND", f"Change {change_id} not found")

    @app.get("/v1/v2/jobs/{job_id}/stage/3/pom/validation/{validation_id}")
    def get_validation_result(job_id: str, validation_id: str) -> dict[str, Any]:
        """Get validation run result."""
        with _read_unit_of_work(unit_of_work_factory) as uow:
            _require_v2_job(uow, job_id)
            editor = PomDependencyEditor(
                validation_repo=uow.v2_pom_validations,
                repair_plan_repo=uow.v2_pom_repair_plans,
            )
            result = editor.get_validation_result(job_id, validation_id)
        if result is None:
            raise _error(status.HTTP_404_NOT_FOUND, "VALIDATION_NOT_FOUND", f"Validation {validation_id} not found")
        return result.to_public_dict()

    @app.post("/v1/v2/jobs/{job_id}/stage/3/pom/repair")
    def apply_repair_plan(
        job_id: str,
        payload: PomRepairApplyRequestSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Apply a repair plan."""
        editor = _build_pom_dependency_editor()
        result = editor.apply_repair_plan(
            job_id,
            payload.repair_plan_id,
            payload.idempotency_key or uuid4().hex,
        )
        return result.to_public_dict()

    @app.post("/v1/v2/jobs/{job_id}/stage/3/pom/rollback")
    def rollback_pom_change(
        job_id: str,
        payload: PomRollbackRequestSchema,
        request: Request,
    ) -> dict[str, Any]:
        """Rollback a POM change."""
        editor = _build_pom_dependency_editor()
        result = editor.rollback_change(
            job_id,
            payload.change_id,
            payload.idempotency_key or uuid4().hex,
        )
        return result.to_public_dict()

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

    # â”€â”€ F14 helper functions â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _make_pom_dependency_editor() -> PomDependencyEditor:
        """Build a PomDependencyEditor backed by the current UoW repos."""
        uow = unit_of_work_factory()
        return PomDependencyEditor(
            event_sink=uow.v2_events,
            change_repo=uow.v2_pom_changes,
            proposal_repo=uow.v2_pom_proposals,
            validation_repo=uow.v2_pom_validations,
            repair_plan_repo=uow.v2_pom_repair_plans,
            resolve_sandbox_root=lambda job_id, stage: _resolve_stage3_sandbox_path(job_id),
            resolve_pom_content=lambda job_id: _read_stage3_pom_content(job_id),
        )

    _configure_pom_dependency_editor_factory(_make_pom_dependency_editor)

    def _read_stage3_pom_content(job_id: str) -> str:
        """Read the Stage 3 sandbox root POM content."""
        path = _resolve_stage3_sandbox_path(job_id)
        if path is None:
            return ""
        pom_file = path / "pom.xml"
        if pom_file.exists():
            return pom_file.read_text(encoding="utf-8")
        return ""

    def _resolve_stage3_sandbox_path(job_id: str) -> Path | None:
        """Resolve Stage 3 sandbox root path for a job."""
        try:
            with _read_unit_of_work(unit_of_work_factory) as uow:
                job = uow.v2_jobs.get(job_id)
                if job is None:
                    return None
                events = tuple(uow.v2_events.list_by_job(job_id))
                commands = tuple(uow.v2_commands.list_by_job(job_id))
        except Exception:
            return None
        resolved = _resolve_stage_sandbox_root(
            stage_index=3,
            events=events,
            commands=commands,
        )
        if resolved:
            return resolved[0]
        return None

    def _resolve_sandbox_path_string(job_id: str, stage: int) -> str:
        """Resolve sandbox path as string."""
        if stage == 3:
            path = _resolve_stage3_sandbox_path(job_id)
            return str(path) if path else ""
        try:
            with _read_unit_of_work(unit_of_work_factory) as uow:
                _require_v2_job(uow, job_id)
                events = tuple(uow.v2_events.list_by_job(job_id))
                commands = tuple(uow.v2_commands.list_by_job(job_id))
        except Exception:
            return ""
        resolved = _resolve_stage_sandbox_root(
            stage_index=stage,
            events=events,
            commands=commands,
        )
        return str(resolved[0]) if resolved else ""

    def _load_target_dependency_plan(job_id: str) -> dict[str, Any] | None:
        """Load target dependency plan artifact for a job."""
        try:
            with _read_unit_of_work(unit_of_work_factory) as uow:
                artifacts = uow.artifacts.list_by_job(job_id)
                for a in artifacts:
                    if a.artifact_kind in ("target_dependency_plan", "dependency_plan"):
                        try:
                            return json.loads(a.content or "{}")
                        except (json.JSONDecodeError, TypeError):
                            pass
        except Exception:
            pass
        return None

    def _load_dependency_policy_report(job_id: str) -> dict[str, Any] | None:
        """Load dependency policy report artifact for a job."""
        try:
            with _read_unit_of_work(unit_of_work_factory) as uow:
                artifacts = uow.artifacts.list_by_job(job_id)
                for a in artifacts:
                    if a.artifact_kind in ("dependency_policy_report", "policy_report"):
                        try:
                            return json.loads(a.content or "{}")
                        except (json.JSONDecodeError, TypeError):
                            pass
        except Exception:
            pass
        return None

    def _detect_build_command(job_id: str) -> str:
        """Detect the appropriate Maven build command."""
        try:
            from migration_factory.agents.build_agent.detection import full_validation_command
            path = _resolve_stage3_sandbox_path(job_id)
            if path:
                cmd = full_validation_command(str(path))
                if cmd:
                    return cmd
        except Exception:
            pass
        return "mvn clean compile test"

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


# â”€â”€ Artifact-content assistant helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_ARTIFACT_CONTENT_KEYWORDS = {
    "pom", "xml", "artifact", "openrewrite", "plugin", "plan lock",
    "approved_plan", "pending_plan", "full pom", "rewrite", "dry run",
    "patch", "ledger", "log", "report", "summary",
    "dependency", "dependencies", "proposal",
}

_ARTIFACT_CONTENT_QUESTION_PATTERNS = (
    "show", "give", "display", "print", "preview", "download",
    "what is in", "what's in", "content", "contents", "open",
    "read", "get", "fetch", "see", "view", "look at",
    "explain", "describe", "tell me about", "analyze", "compare",
    "summarize", "inspect", "break down", "breakdown",
    # Proposal / change patterns (needed for artifact resolution)
    "draft", "propose", "change", "upgrade", "modify",
    "migrate", "repair", "create", "update",
)


_ROOT_POM_ALIAS_TERMS = (
    "pom.xml", "pom xml", "full pom", "full pom.xml", "full pom xml",
    "root pom", "root_pom",
    "pom", "pom file", "pom content", "maven pom", "build file",
    "project xml", "dependencies", "dependency", "plugins",
)


def _classify_v2_assistant_intent(question: str) -> str:
    lowered = str(question or "").lower()

    if (
        "validation" in lowered
        and any(term in lowered for term in ("result", "status", "latest", "show"))
        and any(term in lowered for term in ("stage 3", "stage3", "pom", "change"))
    ):
        return "pom_validation_result"

    # 1. Model status first (model/Azure/provider questions)
    #    BUT skip if user is also asking about POM/dependency changes — model status is secondary
    pom_or_dep_terms = (
        "pom", "pom.xml", "dependency", "property", "modelmapper",
        "jackson", "spring boot", "version", "apply change", "propose change",
    )
    has_pom_or_dep = any(t in lowered for t in pom_or_dep_terms)
    looks_like_status_question = any(t in lowered for t in (
        "what happened", "what is happening", "happening now", "stage status", "what stage", "which stage",
        "done?", "completed?", "progress",
    )) or re.search(r'\bis stage\b', lowered) or re.search(r'\bstatus\b', lowered) is not None
    if any(term in lowered for term in ("model", "azure", "openai", "connected", "provider", "fallback", "deterministic")):
        # Only route to model_status if user is NOT asking about POM/deps at the same time
        if not has_pom_or_dep or looks_like_status_question:
            return "model_status"

    # 2. Check if the user explicitly says NOT to apply/execute —
    #    this negates capability_boundary and shifts toward proposal
    user_says_dont_apply = any(phrase in lowered for phrase in (
        "do not apply", "don't apply", "do not execute",
        "don't execute", "do not write", "don't write",
        "do not change", "just tell me", "only tell me",
        "just propose", "only propose",
    ))

    advisory_mode = user_says_dont_apply or any(phrase in lowered for phrase in (
        "propose", "suggest", "review", "analyze",
        "can i", "should i", "what do you think",
    ))
    if advisory_mode and any(term in lowered for term in (
        "pom", "pom.xml", "dependency", "property", "version", ":",
    )):
        if any(term in lowered for term in (
            "update", "updating", "change", "changing", "set", "setting", "upgrade", "upgrading",
        )):
            return "pom_change_proposal"

    # 3. Capability / action boundary — takes priority
    #    BUT skip if user explicitly said DO NOT apply
    if not user_says_dont_apply:
        capability_boundary_terms = (
            "you can change", "can you change", "you can do", "why can't",
            "do it", "make the change", "apply it", "apply the pom",
            "apply the change", "write the pom", "execute the change",
            "can you apply", "can you execute", "can you write",
            "change it yourself", "do it yourself",
        )
        if any(term in lowered for term in capability_boundary_terms):
            return "capability_boundary"

    # 3.25 Rollback must route before generic POM proposal/review handling.
    if any(t in lowered for t in ("rollback", "roll back")) and any(
        t in lowered for t in ("pom", "stage 3", "stage3", "change")
    ):
        return "rollback_pom_change"

    # 3.5 Explicit "apply this ... change" pattern (catch BEFORE explicit dep change)
    if not user_says_dont_apply and any(t in lowered for t in ("apply this", "apply the", "apply it", "execute this",
                                                               "do it", "make the change", "write the change",
                                                               "go ahead and apply", "proceed with apply",
                                                               "please apply", "apply now")):
        if not any(t in lowered for t in ("review", "what dependency", "what should", "which dependency")):
            return "apply_dependency_change"

    # 4. Explicit single dependency/property change request (e.g. "update library-name to 1.2.3")
    #    Expanded to catch "update property X to Y" and "update X to Y.Z" patterns
    explicit_dep_change_patterns = (
        r"(?:update|upgrade|change|set|bump|replace)\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+)",
        r"(?:update|upgrade|change)\s+(?:dependency|version of)\s+([\w.\-:]+)",
        r"(?:update|change)\s+property\s+([\w.\-]+)",
        r"(?:update|change)\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+)",
        r"(?:set|bump)\s+([\w.\-:]+)\s+(?:to)\s+([\d.]+)",
        r"(?:update|upgrade|change|set)\s+([\w.\-]+)\.(?:version)\s+(?:to|version)\s+([\d.]+)",
    )
    for pattern in explicit_dep_change_patterns:
        if re.search(pattern, lowered):
            if advisory_mode:
                return "pom_change_proposal"
            # If user explicitly says apply/execute/do it, route to apply
            if not user_says_dont_apply and any(t in lowered for t in ("apply this", "apply the", "apply it", "execute this",
                                                                       "do it", "make the change", "write the change",
                                                                       "go ahead and apply", "proceed with apply",
                                                                       "please apply", "apply now")):
                if not any(t in lowered for t in ("review", "what dependency", "what should", "which dependency")):
                    return "apply_dependency_change"
            if not any(t in lowered for t in ("review", "what dependency", "what should", "which dependency")):
                return "apply_dependency_change"

    # 5. POM change proposal intent — draft/upgrade/propose/modify with POM terms
    #    Check BEFORE stage3 review so proposals take priority over reviews
    proposal_actions = (
        "propose", "draft", "upgrade", "modify", "change",
        "migrate", "repair", "create proposal", "safe pom",
        "pom change", "what should we change",
    )
    proposal_artifact_terms = (
        "pom", "pom.xml", "pom xml", "dependency", "dependencies",
        "plugin", "spring boot", "spring-boot", "boot",
        "version", "java.version", "proposal",
    )
    if any(action in lowered for action in proposal_actions) and any(
        term in lowered for term in proposal_artifact_terms
    ):
        return "pom_change_proposal"

    # 6. Stage 3 dependency review intent — broad dependency modernization at final stage
    stage3_review_terms = (
        "dependency modernization", "dependency review", "dependency report",
        "what dependencies should", "which dependencies should",
        "what dependencies need", "which dependencies need",
        "analyze final pom", "analyze stage 3 pom",
        "review stage 3 pom", "review final pom",
        "dependency modernization report",
        "check the final pom", "check stage 3 pom",
        "propose app-specific dependency",
        "not handled by openrewrite", "needs operator decision",
        "what app dependencies",
    )
    # Must include both a review/modernization term AND a stage 3 / final stage reference
    looks_like_stage3_review = any(term in lowered for term in stage3_review_terms) or bool(
        re.search(r'\breview\b.*\b(?:pom|dependency|dependencies)\b', lowered)
        or re.search(r'\b(?:analyze|check|inspect|examine)\b.*\b(?:pom|dependency|dependencies)\b', lowered)
    )
    looks_like_stage3_context = any(term in lowered for term in (
        "stage 3", "phase 3", "final stage", "target stage", "final pom", "final target",
        "after openrewrite", "java 21", "spring boot 3", "spring boot 3.5",
        "now that we are on", "now that we have", "at stage 3",
    ))
    # Also detect any stage reference (1/2/3) for review context
    looks_like_any_stage_context = looks_like_stage3_context or bool(
        re.search(r'\bstage\s*[123]\b', lowered) or re.search(r'\bphase\s*[123]\b', lowered)
    )
    # Skip if it looks like a pure status question
    looks_like_status = any(term in lowered for term in (
        "what happened", "is stage", "stage status", "what stage", "which stage",
        "done?", "completed?", "status", "progress",
    )) or re.search(r'\bis stage\b', lowered) or re.search(r'\bstatus\b', lowered) is not None
    # Allow review if: has review terms AND (has any stage context OR has strong standalone review terms)
    has_standalone_review_terms = any(t in lowered for t in (
        "needs operator decision", "dependency modernization report",
        "dependency modernization", "dependency report",
        "what dependencies need", "which dependencies need",
    ))
    if looks_like_stage3_review and (looks_like_any_stage_context or has_standalone_review_terms) and not looks_like_status:
        return "stage3_dependency_review"

    # 7. POM / dependency explanation (includes raw XML requests)
    artifact_terms = (
        "pom", "pom.xml", "pom xml", "dependency", "dependencies",
        "plugin", "xml", "artifact", "rewrite", "patch",
        "plan", "report", "summary", "openrewrite",
    )
    artifact_actions = (
        "explain", "describe", "show", "give", "display", "print",
        "preview", "download", "open", "read", "get", "fetch",
        "see", "view", "look at", "analyze", "compare",
        "summarize", "inspect", "break down", "breakdown",
        "what is in", "what's in", "content", "contents",
        "what", "which", "list", "raw",
    )

    if any(term in lowered for term in artifact_terms) and (
        any(action in lowered for action in artifact_actions)
        or any(term in lowered for term in ("dependency", "dependencies", "pom", "pom.xml", "pom xml"))
    ):
        if any(term in lowered for term in ("pom", "pom.xml", "pom xml", "dependency", "dependencies")):
            return "pom_or_dependency_explanation"
        return "artifact_content"

    # 8. Status questions
    if any(term in lowered for term in ("what happened", "what is happening", "happening now", "status", "progress", "running", "failed", "failure", "next", "approve", "approval", "stage", "done", "completed", "ready", "pass", "fail", "proof", "pipeline", "is stage", "stage status", "what stage", "which stage")):
        return "status"

    return "general_question"


def _build_bounded_conversation_history(
    messages: tuple[Any, ...],
    max_messages: int = 8,
) -> list[dict[str, str]]:
    """Build a bounded, redacted conversation history from prior messages.

    Returns up to max_messages recent role/content pairs.
    Redacts content, excludes raw paths, secrets, and approval tokens.
    """
    from migration_factory.control_tower.application.redaction import redact_model_summary

    if not messages:
        return []
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    history: list[dict[str, str]] = []
    for msg in recent:
        role = str(getattr(msg, "role", "user") or "user")
        content = str(getattr(msg, "content", "") or "")
        if not content.strip():
            continue
        safe = redact_model_summary(str(content))
        safe = safe[:512]  # Bound each message
        safe = re.sub(r'/[^\s"]+/[^\s"]*', "[path-redacted]", safe)
        safe = re.sub(r'\b[0-9a-f]{32,}\b', "[token-redacted]", safe)
        history.append({"role": role, "content": safe})
    return history


def _question_looks_like_artifact_content(question: str) -> bool:
    """Detect if a user question is asking for artifact content."""
    lowered = str(question or "").lower()
    # Quick guard: must be asking for something
    if not any(pattern in lowered for pattern in _ARTIFACT_CONTENT_QUESTION_PATTERNS):
        return False
    # Must mention artifact-related terms
    return any(keyword in lowered for keyword in _ARTIFACT_CONTENT_KEYWORDS)


def _question_requests_root_pom_alias(question: str) -> bool:
    """Detect requests for the fixed root_pom alias, not arbitrary paths."""
    lowered = str(question or "").lower()
    if not any(pattern in lowered for pattern in _ARTIFACT_CONTENT_QUESTION_PATTERNS):
        return False
    return any(term in lowered for term in _ROOT_POM_ALIAS_TERMS)


def _stage_index_from_question(question: str) -> int | None:
    lowered = str(question or "").lower()
    match = re.search(r"\b(?:stage|phase)\s*([1-3])\b", lowered)
    if match:
        return int(match.group(1))
    if any(term in lowered for term in ("final stage", "target stage", "final pom", "target pom", "final target")):
        return 3
    return None


def _get_requested_stage(question: str, intent: str = "") -> int | None:
    """Extract requested stage from question, with intent-aware defaults.

    - 'stage 3', 'phase 3', 'final stage', 'target stage', 'final pom' -> stage=3
    - 'stage 1' -> stage=1
    - 'stage 2' -> stage=2
    - If no stage given and intent is stage3_dependency_review, default to stage=3
    - If no stage given and intent is pom_dependency_change_request, prefer stage 3 if evidence available
    - Otherwise returns None (keep existing behavior)
    """
    lowered = str(question or "").lower()
    match = re.search(r"\b(?:stage|phase)\s*([1-3])\b", lowered)
    if match:
        return int(match.group(1))
    # Named stage references
    if any(term in lowered for term in ("stage 3", "phase 3", "final stage", "target stage", "final pom", "final target")):
        return 3
    if "stage 2" in lowered or "phase 2" in lowered:
        return 2
    if "stage 1" in lowered or "phase 1" in lowered:
        return 1
    # Intent-based defaults
    if intent in ("stage3_dependency_review",):
        return 3
    # If user asks for full/root/current/final POM without explicit stage,
    # prefer Stage 3 if it is complete (checked via events)
    if any(term in lowered for term in ("full pom", "root pom", "current pom", "final pom", "the pom")):
        return None  # Let caller resolve via _default_stage_from_events
    return None


def _is_final_dependency_review_allowed(
    stage_index: int,
    root_pom_preview: dict[str, Any] | None,
    events: tuple[Any, ...],
) -> tuple[bool, str]:
    """Check if a final dependency review is allowed at the given stage.

    Returns (allowed: bool, reason: str).
    Reasons: ok, stage_not_3, root_pom_unavailable, stage_running,
    stage_not_completed, proof_missing, build_or_tests_missing.
    """
    if stage_index != 3:
        return False, "stage_not_3"
    if not root_pom_preview or not root_pom_preview.get("exists"):
        return False, "root_pom_unavailable"
    # Check stage 3 events for stability
    stage_events = sorted(
        [event for event in events if getattr(event, "stage", None) == 3],
        key=lambda event: getattr(event, "sequence", 0),
    )
    if not stage_events:
        return False, "stage_not_completed"
    latest_stage_event = stage_events[-1]
    if getattr(latest_stage_event, "status", "") == "running" or str(
        getattr(latest_stage_event, "type", "")
    ).endswith("_started"):
        return False, "stage_running"
    if not any(
        getattr(event, "type", "") in {"sandbox_transform_completed", "stage_completed"}
        or (
            getattr(event, "status", "") == "completed"
            and str(getattr(event, "type", ""))
            in {"transform_completed", "build_completed", "test_completed"}
        )
        for event in stage_events
    ):
        return False, "stage_not_completed"
    has_build = any(
        getattr(e, "type", "") in {"build_completed", "test_completed"} for e in stage_events
    )
    if not has_build:
        return True, "ok"  # Not blocking on missing build/test â€” just warn
    return True, "ok"


def _default_stage_when_stage3_complete(events: tuple[Any, ...]) -> int | None:
    """If Stage 3 is complete (has completion events), default to stage=3.

    Used when user asks for "full POM" or "root POM" without explicit stage number.
    Returns 3 if Stage 3 is complete, None otherwise.
    """
    stage_events = sorted(
        [event for event in events if getattr(event, "stage", None) == 3],
        key=lambda event: getattr(event, "sequence", 0),
    )
    if not stage_events:
        return None
    latest_stage_event = stage_events[-1]
    if getattr(latest_stage_event, "status", "") == "running" or str(
        getattr(latest_stage_event, "type", "")
    ).endswith("_started"):
        return None
    if any(
        getattr(event, "type", "") in {"sandbox_transform_completed", "stage_completed"}
        or (
            getattr(event, "status", "") == "completed"
            and str(getattr(event, "type", ""))
            in {"transform_completed", "build_completed", "test_completed"}
        )
        for event in stage_events
    ):
        return 3
    return None


def _handle_gate_aware_ask(
    app: Any,
    job_id: str,
    open_gate: Any,
    question: str,
    correlation_id: str | None,
    confirmation_store: ConfirmationStore,
    unit_of_work_factory: Any,
) -> dict[str, Any]:
    """Handle an /ask request when an open PhaseGate exists.

    Loads gate context, classifies intent, and either explains
    gate-bound evidence, returns an action preview (state-changing
    intents), or executes a confirmed action.
    """
    from migration_factory.control_tower.application.v2_assistant_service import (
        V2AssistantService,
    )
    from migration_factory.control_tower.application.v2_gate_action_service import (
        V2GateActionService,
    )
    from migration_factory.control_tower.domain.checksums import (
        sha256_canonical_json,
        utc_now_text,
    )

    with unit_of_work_factory() as uow:
        gate_repo = uow.phase_gates
        gate_service = V2PhaseGateService(gate_repo)
        job = uow.v2_jobs.get(job_id)
        setup = None
        if job is not None and getattr(job, "setup_id", None):
            setup = uow.v2_setups.get(job.setup_id)
        storage_root = getattr(setup, "output_parent_path", None) if setup is not None else None
        resolver = V2GateArtifactResolver(gate_repo, storage_root=storage_root)
        loader = GateContextLoader(
            gate_service=gate_service,
            resolver=resolver,
        )
        context, evidence_pack = loader.load_gate_with_evidence(open_gate.gate_id)
        if context is None:
            # Gate not found — fall through to existing assistant
            return _fallback_to_existing_assistant(
                app=app,
                job_id=job_id,
                question=question,
                correlation_id=correlation_id,
                unit_of_work_factory=unit_of_work_factory,
            )

        service = V2AssistantService(assistant_repo=uow.v2_assistant)

        # Persist user message
        user_msg = service.add_message(
            job_id=job_id,
            role="user",
            content=question,
            correlation_id=correlation_id,
        )

        # -- Detect confirmation intent before classification ----
        question_lower = question.strip().lower()
        _CONFIRM_PATTERNS = (
            "confirm", "yes", "yes,", "yeah", "sure",
            "go ahead", "do it", "apply", "proceed",
            "okay", "ok,", "ok ", "approved",
        )
        is_confirm = any(
            question_lower == p or question_lower.startswith(p + " ")
            or question_lower.startswith(p + ",") or question_lower.startswith(p + ".")
            for p in _CONFIRM_PATTERNS
        )

        # Classify intent
        classifier = GateIntentClassifier()
        intent: ClassifiedIntent = classifier.classify(
            user_input=question,
            available_actions=context.available_actions,
            gate_phase=context.gate_phase,
        )

        if open_gate.gate_phase == "approval_review":
            blocked_revision_card = _approval_review_blocked_revision_card(
                uow,
                job_id=job_id,
                stage_index=open_gate.stage_index,
                gate_checksum=context.checksum,
            )
            exact_checksum = _extract_confirm_checksum(question)
            if exact_checksum:
                if blocked_revision_card is not None:
                    assistant_msg = service.add_message(
                        job_id=job_id,
                        role="assistant",
                        content=_approval_review_revision_blocked_message(),
                        correlation_id=user_msg.message_id,
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "approve_from_gate",
                        "executed": False,
                        "available_actions": _approval_review_available_actions(blocked_revision=True),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }
                if exact_checksum != context.checksum:
                    assistant_msg = service.add_message(
                        job_id=job_id,
                        role="assistant",
                        content="Checksum mismatch. Confirm the latest gate checksum from the review surface.",
                        correlation_id=user_msg.message_id,
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "confirm_checksum",
                        "executed": False,
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }

                approval_service = V2ApprovalMappingService(uow.v2_approvals)
                pending_cards = [
                    card
                    for card in uow.v2_approvals.list_cards_by_job(job_id)
                    if card.stage_index == open_gate.stage_index and card.status == "pending"
                ]
                pending_card = next(
                    (card for card in pending_cards if card.request_checksum == context.checksum),
                    pending_cards[0] if pending_cards else None,
                )
                if pending_card is None:
                    assistant_msg = service.add_message(
                        job_id=job_id,
                        role="assistant",
                        content="No pending approval card exists for this gate.",
                        correlation_id=user_msg.message_id,
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "confirm_checksum",
                        "executed": False,
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }

                commands = uow.v2_commands.list_by_job(job_id)
                run_dir = _v2_resume_run_dir_from_commands(
                    commands,
                    open_gate.stage_index,
                    pending_card.interrupt_id,
                )
                card_before = approval_service.get_card(pending_card.card_id)
                is_new_approve = card_before is None or card_before.status != "approved"
                resume = approval_service.approve(
                    card_id=pending_card.card_id,
                    expected_checksum=context.checksum,
                    job_id=job_id,
                    run_dir=run_dir,
                )

                action_service = V2GateActionService(
                    uow.phase_gates,
                    uow.gate_decisions,
                    V2PhaseGateService(uow.phase_gates),
                    revision_repo=uow.artifact_revisions,
                    command_repo=uow.v2_commands,
                )
                gate_result = action_service.approve_from_gate(
                    gate_id=open_gate.gate_id,
                    job_id=job_id,
                    decided_by="human",
                    expected_gate_checksum=context.checksum,
                )

                existing_resume_status = (
                    _resume_launch_state_from_events(
                        uow,
                        job_id=job_id,
                        resume_id=resume.resume_id,
                    )
                    if resume.resume_id
                    else None
                )
                if hasattr(uow, "connection"):
                    uow.connection.commit()

                resume_launch: V2OrchestratorStart | None = None
                if is_new_approve and resume.resume_id:
                    resume_launch = _start_resume_command(
                        app,
                        job_id=job_id,
                        resume_id=resume.resume_id,
                        stage_index=resume.stage_index,
                    )
                    with unit_of_work_factory() as event_uow:
                        _append_v2_event(
                            event_uow,
                            job_id=job_id,
                            stage=resume.stage_index,
                            event_type="approval_resume_queued",
                            status=resume_launch.status if resume_launch.status in {"retrying", "started"} else "queued",
                            message=(
                                "Approval accepted; backend-owned resume command is retrying."
                                if resume_launch.status == "retrying"
                                else "Approval accepted; backend-owned resume command queued."
                            ),
                            payload={
                                "card_id": pending_card.card_id,
                                "resume_id": resume.resume_id,
                                "resume_status": resume_launch.status,
                            },
                        )

                resume_status = resume_launch.status if resume_launch is not None else existing_resume_status
                if resume_status is None and resume.resume_id:
                    resume_status = "queued"

                assistant_content = "Checksum confirmed. Approval review resolved and resume queued."
                if resume_status == "retrying":
                    assistant_content = (
                        "Checksum confirmed. Approval review resolved, but the resume launch is retrying."
                    )
                elif existing_resume_status in {"queued", "started"} and not is_new_approve:
                    assistant_content = (
                        "Checksum confirmed. Approval review is already resolved and the resume is already queued or running."
                    )

                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=assistant_content,
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "confirm_checksum",
                    "executed": gate_result.status == "executed" or bool(resume.resume_id),
                    "execution_result": {
                        "success": gate_result.status == "executed" or bool(resume.resume_id),
                        "status": gate_result.status,
                        "decision_id": gate_result.decision_id,
                        "reason": gate_result.reason,
                        "resume_id": resume.resume_id,
                        "resume_status": resume_status,
                        "resume_launch_message": resume_launch.message if resume_launch is not None else "",
                    },
                    "guardrails": {
                        "read_only": False,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            if blocked_revision_card is not None and (
                intent.action_type == "approve_from_gate"
                or question_lower == "approve"
            ):
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=_approval_review_revision_blocked_message(),
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "approve_from_gate",
                    "executed": False,
                    "available_actions": _approval_review_available_actions(blocked_revision=True),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            if intent.action_type == "approve_from_gate" or question_lower == "approve":
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=_format_approval_review_preview(context),
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "approve_from_gate",
                    "executed": False,
                    "action_preview": {
                        "action_type": "approve_from_gate",
                        "reason": "Preview only; exact checksum confirmation required.",
                        "confidence": 1.0,
                        "warning": "Approval will not execute until the exact checksum is confirmed.",
                        "requires_confirmation": True,
                        "pending_confirmation": True,
                        "exact_checksum": context.checksum,
                    },
                    "available_actions": _approval_review_available_actions(
                        blocked_revision=blocked_revision_card is not None
                    ),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            if intent.action_type == "reject_from_gate" or question_lower == "reject":
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=_format_approval_review_preview(context, action_type="reject_from_gate"),
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "reject_from_gate",
                    "executed": False,
                    "action_preview": {
                        "action_type": "reject_from_gate",
                        "reason": "Preview only; exact checksum confirmation required.",
                        "confidence": 1.0,
                        "warning": "Legacy reject is routed through the same checksum flow in approval review.",
                        "requires_confirmation": True,
                        "pending_confirmation": True,
                        "exact_checksum": context.checksum,
                    },
                    "available_actions": _approval_review_available_actions(
                        blocked_revision=blocked_revision_card is not None
                    ),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            if (intent.ambiguous or not intent.action_type) and not is_confirm and not _question_looks_like_approval_review_revision_request(question):
                from migration_factory.control_tower.application.v2_gate_assistant import (
                    AmbiguityHandler,
                )
                explanation = AmbiguityHandler.handle_ambiguous(intent, context)
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=explanation,
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": intent.action_type or "ambiguous",
                    "executed": False,
                    "ambiguous": True,
                    "available_actions": tuple(a.action for a in context.available_actions),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }
            if _question_looks_like_approval_review_explanation(question):
                explanation_text, explanation_model = _format_approval_review_explanation(
                    app=app,
                    context=context,
                    evidence=evidence_pack,
                    question=question,
                )
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=explanation_text,
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "status",
                    "executed": False,
                    "model": explanation_model,
                    "available_actions": _approval_review_available_actions(),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            if _question_looks_like_approval_review_revision_request(question):
                if blocked_revision_card is not None:
                    assistant_msg = service.add_message(
                        job_id=job_id,
                        role="assistant",
                        content=_approval_review_revision_blocked_message(),
                        correlation_id=user_msg.message_id,
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "request_revision",
                        "executed": False,
                        "available_actions": _approval_review_available_actions(blocked_revision=True),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }

                confirmation_store.store(
                    job_id=job_id,
                    gate_id=open_gate.gate_id,
                    action_type="request_revision",
                    expected_gate_checksum=context.checksum,
                    idempotency_key=sha256_canonical_json({
                        "gate_id": open_gate.gate_id,
                        "job_id": job_id,
                        "action_type": "request_revision",
                        "timestamp": utc_now_text(),
                    }),
                    user_feedback=question,
                )
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=(
                        "Revision request preview only. Confirm to record the revision request. "
                        "Transform remains blocked until the revised evidence is reviewed again."
                    ),
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "request_revision",
                    "executed": False,
                    "available_actions": _approval_review_available_actions(
                        blocked_revision=blocked_revision_card is not None
                    ),
                    "action_preview": {
                        "action_type": "request_revision",
                        "reason": "Preview only; confirm to record the revision request.",
                        "confidence": 1.0,
                        "warning": "Transform/build/test will not start until you confirm.",
                        "requires_confirmation": True,
                        "pending_confirmation": True,
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
# -- Handle "confirm" intent (explicit or after preview) ----
        if is_confirm or intent.action_type == "confirm":
            pending = confirmation_store.resolve(
                job_id=job_id,
                gate_id=open_gate.gate_id,
                current_gate_checksum=context.checksum,
            )
            if pending is not None:
                if pending.action_type == "request_revision":
                    _record_approval_review_revision_request(
                        uow=uow,
                        job_id=job_id,
                        gate_id=open_gate.gate_id,
                        stage_index=open_gate.stage_index,
                        gate_checksum=context.checksum,
                        user_request_text=pending.user_feedback or question,
                    )
                    assistant_msg = service.add_message(
                        job_id=job_id,
                        role="assistant",
                        content="Revision request recorded. Transform remains blocked until the evidence is revised and reviewed again.",
                        correlation_id=user_msg.message_id,
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "request_revision",
                        "executed": False,
                        "available_actions": _approval_review_available_actions(blocked_revision=True),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }
                action_service = V2GateActionService(
                    uow.phase_gates,
                    uow.gate_decisions,
                    gate_service,
                    revision_repo=uow.artifact_revisions,
                    command_repo=uow.v2_commands,
                )
                executor = GateActionExecutor(action_service=action_service)
                execution_result = _execute_pending_action(
                    executor=executor,
                    job_id=job_id,
                    gate_id=open_gate.gate_id,
                    checksum=context.checksum,
                    action_type=pending.action_type,
                    user_feedback=pending.user_feedback,
                    idempotency_key=pending.idempotency_key,
                )

                execution_success = (
                    getattr(execution_result, "status", None) == "executed"
                    or getattr(execution_result, "success", False)
                )
                execution_decision_id = getattr(execution_result, "decision_id", None)

                progression_result = None
                if (
                    execution_success
                    and pending.action_type == "continue_from_gate"
                ):
                    if open_gate.gate_phase == "analysis_review":
                        # After analysis_review CONTINUE:
                        # - Gate was resolved by _execute_action
                        # - Planning command was queued by V2GateActionService
                        #   (real planning will produce artifacts, then
                        #   planning_review gate opens)
                        # - No Stage 2 command was created
                        # - No transformation was started
                        # - No synthetic planning_review gate was created
                        from_phase = "analysis_review"
                        to_phase = "planning_review"
                        stage = open_gate.stage_index
                        cmd_id = getattr(execution_result, "result_command_id", None) or ""
                        progression_result = {
                            "status": "planning_queued",
                            "from_phase": from_phase,
                            "to_phase": to_phase,
                            "stage_index": stage,
                            "planning_command_id": cmd_id,
                            "message": (
                                f"Stage {stage} analysis review completed. "
                                f"Stage 1 planning has been queued. "
                                f"When planning completes and produces real "
                                f"planning artifacts, a planning_review gate "
                                f"will open. "
                                f"Migration Stage 2 was not started. "
                                f"No transform/build/test started."
                            ),
                        }
                        # Start the backend-owned planning command
                        if cmd_id:
                            _runner = app.state.v2_orchestrator_runner
                            if _runner is not None:
                                try:
                                    _runner.start(job_id=job_id, command_id=cmd_id)
                                except Exception:
                                    pass
                    elif open_gate.gate_phase == "planning_review":
                        # After planning_review CONTINUE:
                        # - Approval_review gate was created by V2GateActionService
                        progression_result = {
                            "status": "phase_advanced",
                            "from_phase": "planning_review",
                            "to_phase": "approval_review",
                            "stage_index": open_gate.stage_index,
                            "message": (
                                f"Stage {open_gate.stage_index} planning review completed. "
                                f"Approval review gate created."
                            ),
                        }

                content = _format_execution_response(
                    execution_result,
                    progression=progression_result,
                )
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=content,
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": pending.action_type,
                    "executed": execution_success,
                    "execution_result": {
                        "success": execution_success,
                        "status": getattr(execution_result, "status", "unknown"),
                        "decision_id": execution_decision_id,
                        "reason": getattr(execution_result, "reason", ""),
                    },
                    "progression_result": progression_result,
                    "guardrails": {
                        "read_only": False,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            # No pending confirmation — treat as ambiguous if user said confirm
            if is_confirm:
                explanation = (
                    "There is no pending action to confirm. "
                    "Please ask about the current gate first."
                )
                assistant_msg = service.add_message(
                    job_id=job_id,
                    role="assistant",
                    content=explanation,
                    correlation_id=user_msg.message_id,
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": "confirm",
                    "executed": False,
                    "ambiguous": True,
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }
            # Fall through to classification below

        # -- Handle ambiguous / unknown intent ---------------------
        if intent.ambiguous or not intent.action_type:
            from migration_factory.control_tower.application.v2_gate_assistant import (
                AmbiguityHandler,
            )
            explanation = AmbiguityHandler.handle_ambiguous(intent, context)
            assistant_msg = service.add_message(
                job_id=job_id,
                role="assistant",
                content=explanation,
                correlation_id=user_msg.message_id,
            )
            return {
                "job_id": job_id,
                "user_message": service.message_to_dict(user_msg),
                "assistant_message": service.message_to_dict(assistant_msg),
                "gate_aware": True,
                "intent": intent.action_type or "ambiguous",
                "executed": False,
                "ambiguous": True,
                "clarification_question": intent.clarification_question or "",
                "available_actions": list(intent.available_actions),
                "guardrails": {
                    "read_only": True,
                    "cannot_execute": True,
                    "cannot_approve": True,
                    "cannot_write_files": True,
                    "cannot_change_route_or_stage": True,
                    "cannot_override_proof": True,
                },
            }

        # -- Build action preview (state-changing intent) ----------
        preview_builder = GateActionPreviewBuilder()
        preview: ActionPreview = preview_builder.build_preview(
            intent=intent,
            gate_context=context,
        )

        # Store pending confirmation
        idempotency_key = sha256_canonical_json({
            "gate_id": open_gate.gate_id,
            "job_id": job_id,
            "action_type": preview.action_type,
            "timestamp": utc_now_text(),
        })
        confirmation_store.store(
            job_id=job_id,
            gate_id=open_gate.gate_id,
            action_type=preview.action_type,
            expected_gate_checksum=context.checksum,
            idempotency_key=idempotency_key,
        )

        content = _format_preview_response(preview, context)
        assistant_msg = service.add_message(
            job_id=job_id,
            role="assistant",
            content=content,
            correlation_id=user_msg.message_id,
        )
        return {
            "job_id": job_id,
            "user_message": service.message_to_dict(user_msg),
            "assistant_message": service.message_to_dict(assistant_msg),
            "gate_aware": True,
            "intent": intent.action_type,
            "executed": False,
            "action_preview": {
                "action_type": preview.action_type,
                "reason": preview.reason,
                "confidence": preview.confidence,
                "warning": preview.warning,
                "requires_confirmation": preview.requires_confirmation,
                "pending_confirmation": True,
            },
            "guardrails": {
                "read_only": False,
                "cannot_execute": True,
                "cannot_approve": True,
                "cannot_write_files": True,
                "cannot_change_route_or_stage": True,
                "cannot_override_proof": True,
            },
        }


def _execute_pending_action(
    executor: GateActionExecutor,
    job_id: str,
    gate_id: str,
    checksum: str,
    action_type: str,
    user_feedback: str = "",
    idempotency_key: str | None = None,
) -> Any:
    """Execute a confirmed gate action through the executor."""
    action_map = {
        "continue_from_gate": lambda: executor.execute_continue(
            gate_id, checksum, job_id=job_id, idempotency_key=idempotency_key,
        ),
        "request_reanalysis": lambda: executor.execute_reanalysis(
            gate_id, checksum, job_id=job_id, user_feedback=user_feedback, idempotency_key=idempotency_key,
        ),
        "request_plan_revision": lambda: executor.execute_plan_revision(
            gate_id, checksum, job_id=job_id, user_feedback=user_feedback, idempotency_key=idempotency_key,
        ),
        "approve_from_gate": lambda: executor.execute_approve(
            gate_id, checksum, job_id=job_id, idempotency_key=idempotency_key,
        ),
        "reject_from_gate": lambda: executor.execute_reject(
            gate_id, checksum, job_id=job_id, reason=user_feedback, idempotency_key=idempotency_key,
        ),
    }
    handler = action_map.get(action_type)
    if handler is None:
        from migration_factory.control_tower.application.v2_gate_assistant import (
            GateActionResult,
        )
        return GateActionResult(
            success=False,
            message=f"Unknown action type: {action_type}",
        )
    return handler()


def _build_gate_explanation(
    context: GateContext,
    question: str,
    open_gate: Any,
) -> str:
    """Build a human-readable explanation from gate context."""
    lines: list[str] = []
    lines.append(f"**Gate: {context.gate_id[:8]}**")
    lines.append(f"- Phase: {context.gate_phase}")
    lines.append(f"- Stage: {context.stage_index}")
    lines.append(f"- Status: {context.gate_status}")
    lines.append(f"- Checksum: `{context.checksum[:16]}...`")
    lines.append("")
    if context.available_actions:
        lines.append("**Available actions:**")
        for action in context.available_actions:
            status = "[available]" if not getattr(action, "blocked", False) else "[blocked]"
            label = getattr(action, "label", action.action)
            desc = getattr(action, "description", "")
            lines.append(f"- {status} **{label}**: {desc}")
    lines.append("")
    lines.append(
        "I can help you decide the next step. "
        "Would you like to continue, reanalyze, or approve?"
    )
    return "\n".join(lines)


def _question_looks_like_approval_review_explanation(question: str) -> bool:
    lowered = question.lower()
    return any(
        term in lowered
        for term in (
            "what happened",
            "what is happening",
            "explain analysis",
            "explain planning",
            "explain assessment",
            "what will change",
            "what will be transformed",
            "what rewrite will happen",
            "show migration plan",
            "show plan",
            "what is the plan",
            "why blocked",
            "what stage",
            "current state",
            "status",
        )
    )


def _question_looks_like_approval_review_revision_request(question: str) -> bool:
    lowered = question.lower().strip()
    if lowered.startswith(
        (
            "use ",
            "switch to ",
            "replace ",
            "change to ",
            "prefer ",
            "make ",
            "add ",
            "remove ",
            "update ",
            "modify ",
            "refactor ",
            "adopt ",
        )
    ):
        return True
    return any(
        term in lowered
        for term in (
            "request revision",
            "revise the plan",
            "revise this",
            "use securityfilterchain",
            "stateless sessions",
            "spring security",
            "change the plan",
        )
    )


def _extract_confirm_checksum(question: str) -> str:
    match = re.search(r"confirm\s+checksum\s+([^\s,.;:]+)", question, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def _approval_review_pending_card(
    uow: Any,
    *,
    job_id: str,
    gate_phase: str,
    stage_index: int,
    gate_checksum: str,
) -> Any | None:
    pending_cards = [
        card
        for card in uow.v2_approvals.list_cards_by_job(job_id)
        if card.stage_index == stage_index and card.status == "pending"
    ]
    return next(
        (card for card in pending_cards if card.request_checksum == gate_checksum),
        pending_cards[0] if pending_cards else None,
    )


def _approval_review_blocked_revision_card(
    uow: Any,
    *,
    job_id: str,
    stage_index: int,
    gate_checksum: str,
) -> Any | None:
    blocked_cards = [
        card
        for card in uow.v2_approvals.list_cards_by_job(job_id)
        if card.stage_index == stage_index
        and card.request_checksum == gate_checksum
        and card.status == "blocked"
    ]
    return blocked_cards[0] if blocked_cards else None


def _approval_review_revision_blocked_message() -> str:
    return (
        "A revision request is pending. Transform remains blocked. "
        "Approval is disabled until the revision is resolved or new evidence is generated."
    )


def _approval_review_available_actions(*, blocked_revision: bool = False) -> tuple[dict[str, Any], ...]:
    revision_block_reason = (
        "Revision request recorded; transform stays blocked until the revised evidence is reviewed again."
        if blocked_revision
        else "Available during approval review."
    )
    return (
        {
            "action": "status",
            "label": "Explain / Status",
            "description": "Summarize bound analysis, planning, and assessment evidence.",
            "blocked": False,
            "block_reason": "",
        },
        {
            "action": "request_revision",
            "label": "Request revision",
            "description": revision_block_reason,
            "blocked": False,
            "block_reason": "",
        },
        {
            "action": "approve_from_gate",
            "label": "Approve",
            "description": "Preview only; exact checksum confirmation is required.",
            "blocked": True,
            "block_reason": "Approval remains behind the exact checksum flow.",
        },
        {
            "action": "reject_from_gate",
            "label": "Reject",
            "description": "Preview only; exact checksum confirmation is required.",
            "blocked": True,
            "block_reason": "Legacy direct rejection is not primary in approval_review.",
        },
    )


def _approval_review_artifact_excerpt(artifact: Any) -> str:
    kind = str(getattr(artifact, "kind", "") or "").strip()
    content = str(getattr(artifact, "content", "") or "").strip()
    if not content:
        return kind or "artifact"
    first_lines = [line.strip() for line in content.splitlines() if line.strip()]
    excerpt = " | ".join(first_lines[:3])
    if len(excerpt) > 240:
        excerpt = excerpt[:240] + "..."
    return f"{kind}: {excerpt}" if kind else excerpt


def _approval_review_evidence_lines(evidence: Any | None, *, topics: tuple[str, ...]) -> list[str]:
    if evidence is None:
        return []
    lines: list[str] = []
    for artifact in getattr(evidence, "artifacts", ()):
        kind = str(getattr(artifact, "kind", "") or "").lower()
        if any(topic in kind for topic in topics):
            lines.append(f"- {_approval_review_artifact_excerpt(artifact)}")
    return lines


def _format_approval_review_preview(context: GateContext, *, action_type: str = "approve_from_gate") -> str:
    action_label = "Approve" if action_type == "approve_from_gate" else "Reject"
    lines = [
        "**Pre-transform review is open**",
        "",
        f"Stage {context.stage_index} is blocked before transform.",
        "Analysis, planning, and assessment are complete.",
        "Transform, build, and test have not started.",
        "",
        f"Exact checksum: `{context.checksum}`",
        "Confirm it by saying `confirm checksum <exact checksum>`.",
        "",
        f"Selected action: {action_label}.",
        "Available actions: explain/status, request revision, approve, reject.",
        "Legacy Approve/Reject buttons are not primary in approval_review.",
    ]
    return "\n".join(lines)


def _format_approval_review_explanation(
    *,
    app: FastAPI,
    context: GateContext,
    evidence: Any | None,
    question: str,
) -> tuple[str, dict[str, Any] | None]:
    lines: list[str] = []
    lines.append("**Pre-transform review**")
    lines.append("")
    lines.append(f"Stage {context.stage_index} is blocked before transform.")
    lines.append("Analysis, planning, and assessment are complete.")
    lines.append("Transform, build, and test have not started.")
    lines.append("")
    lines.append(f"Gate checksum: `{context.checksum}`")

    model_payload: dict[str, Any] | None = None
    if evidence is not None:
        happened_lines = _approval_review_evidence_lines(
            evidence,
            topics=(
                "analysis_report",
                "analysis_summary",
                "config_inventory",
                "dependency_graph",
                "assessment_report",
                "assessment_summary",
            ),
        )
        will_change_lines = _approval_review_evidence_lines(
            evidence,
            topics=(
                "migration_plan",
                "migration_units",
                "approval_request",
                "rewrite_preview",
                "rewrite_dry_run",
                "rewrite_impact_summary",
                "target_dependency_plan",
                "plan_validation_report",
            ),
        )
        if happened_lines:
            lines.append("")
            lines.append("What happened?")
            lines.extend(happened_lines[:12])
        if will_change_lines:
            lines.append("")
            lines.append("What will change?")
            lines.extend(will_change_lines[:12])
        if getattr(evidence, "summary", ""):
            lines.append("")
            lines.append("Evidence summary:")
            lines.append(str(evidence.summary)[:1200])

        missing = tuple(getattr(evidence, "missing_refs", ()) or ())
        mismatches = tuple(getattr(evidence, "checksum_mismatches", ()) or ())
        if missing:
            lines.append("")
            lines.append("Missing bound refs:")
            for ref in missing:
                lines.append(f"- {ref}")
        if mismatches:
            lines.append("")
            lines.append("Checksum mismatches:")
            for ref in mismatches:
                lines.append(f"- {ref}")

        compact_pack = _approval_review_llm_evidence_pack(
            context=context,
            evidence=evidence,
            question=question,
        )
        prompt = _approval_review_llm_prompt(
            context=context,
            question=question,
            compact_pack=compact_pack,
        )
        fallback_text = "\n".join(lines)
        try:
            model_result = app.state.v2_assistant_model_client.answer(
                prompt=prompt,
                fallback=fallback_text,
            )
        except Exception as exc:
            safe_reason = redact_model_summary(str(exc))
            model_result = V2AssistantModelResult(
                content=fallback_text,
                source="deterministic",
                model_status="fallback",
                provider="deterministic",
                role="assistant",
                success=False,
                redacted_summary=safe_reason,
                failure_reason=safe_reason,
            )
        model_payload = _approval_review_model_payload(model_result)
        return model_result.content, model_payload

    lines.append("")
    lines.append(
        "Ask what happened, what will change, or request a revision before approving."
    )
    if _question_looks_like_approval_review_revision_request(question):
        lines.append("A revision request will be recorded and transform will stay blocked.")
    return "\n".join(lines), model_payload


def _approval_review_llm_evidence_pack(
    *,
    context: GateContext,
    evidence: Any,
    question: str,
) -> dict[str, Any]:
    pack = evidence_pack_to_dict(evidence)
    artifact_priority = (
        "analysis_report",
        "analysis_summary",
        "config_inventory",
        "dependency_graph",
        "migration_plan",
        "migration_units",
        "rewrite_preview",
        "rewrite_dry_run",
        "rewrite_impact_summary",
        "target_dependency_plan",
        "assessment_report",
        "assessment_summary",
        "approval_request",
        "plan_validation_report",
    )
    selected_artifacts: list[dict[str, Any]] = []
    for artifact in pack.get("artifacts", []):
        kind = str(artifact.get("kind", "")).lower()
        if any(token in kind for token in artifact_priority):
            selected_artifacts.append(artifact)
    if not selected_artifacts:
        selected_artifacts = list(pack.get("artifacts", []))[:6]
    return {
        "gate": {
            "gate_id": context.gate_id,
            "gate_phase": context.gate_phase,
            "stage_index": context.stage_index,
            "gate_status": context.gate_status,
            "gate_checksum": context.checksum,
        },
        "question": redact_absolute_paths(redact_model_summary(question)),
        "focus": {
            "what_analysis_found": "analysis_report, analysis_summary, config_inventory, dependency_graph",
            "what_planning_proposes": "migration_plan, migration_units, rewrite_preview, rewrite_dry_run, target_dependency_plan",
            "what_assessment_says": "assessment_report, assessment_summary",
            "what_is_blocked": "approval_review blocks transform/build/test until exact checksum confirmation",
            "available_user_decisions": "explain, request_revision, confirm_checksum",
        },
        "evidence": {
            "summary": redact_absolute_paths(redact_model_summary(str(pack.get("summary", "")))),
            "artifacts": selected_artifacts,
            "missing_refs": [redact_absolute_paths(redact_model_summary(str(ref))) for ref in pack.get("missing_refs", [])],
            "checksum_mismatches": [redact_absolute_paths(redact_model_summary(str(ref))) for ref in pack.get("checksum_mismatches", [])],
            "failure_message": redact_absolute_paths(redact_model_summary(str(pack.get("failure_message") or ""))),
        },
    }


def _approval_review_llm_prompt(
    *,
    context: GateContext,
    question: str,
    compact_pack: dict[str, Any],
) -> str:
    safe_pack = redact_absolute_paths(
        redact_model_summary(json.dumps(compact_pack, sort_keys=True, separators=(",", ":")))
    )
    return "\n".join(
        (
            "You are explaining an approval_review gate. Advisory only.",
            "Do not approve, reject, execute, or invent artifact facts.",
            "Use only the provided evidence pack and stay checksum-bound.",
            "Answer with these sections: what analysis found, what planning proposes, what assessment/risk says, what will change, what is still blocked, available user decisions.",
            "",
            f"Gate checksum: {context.checksum}",
            f"Question: {redact_absolute_paths(redact_model_summary(question))}",
            "",
            "Evidence pack:",
            safe_pack,
        )
    )


def _approval_review_model_payload(model_result: V2AssistantModelResult) -> dict[str, Any]:
    source = "llm" if model_result.success else "deterministic"
    status = "live_ok" if model_result.success else "fallback"
    provider = model_result.provider if model_result.success else "deterministic"
    return {
        "status": status,
        "source": source,
        "provider": provider,
        "role": model_result.role,
        "failure_reason": model_result.failure_reason,
    }


def _resume_launch_state_from_events(uow: Any, *, job_id: str, resume_id: str) -> str | None:
    events = uow.v2_events.list_by_job(job_id)
    for event in reversed(events):
        if event.type not in {"approval_resume_queued", "resume_started"}:
            continue
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        event_resume_id = str(payload.get("resume_id") or payload.get("command_id") or "").strip()
        if event_resume_id != resume_id:
            continue
        if event.type == "resume_started":
            return "started"
        launch_status = str(payload.get("resume_status") or event.status or "queued").strip()
        return launch_status or "queued"
    return None


def _start_resume_command(
    app: FastAPI,
    *,
    job_id: str,
    resume_id: str,
    stage_index: int,
) -> V2OrchestratorStart:
    runner = getattr(app.state, "v2_orchestrator_runner", None)
    if runner is None:
        return V2OrchestratorStart(
            command_id=resume_id,
            job_id=job_id,
            stage_index=stage_index,
            pid=None,
            status="queued",
            message="runner unavailable",
        )
    try:
        return runner.start_resume(job_id=job_id, resume_id=resume_id)
    except sqlite3.OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return V2OrchestratorStart(
                command_id=resume_id,
                job_id=job_id,
                stage_index=stage_index,
                pid=None,
                status="retrying",
                message=str(exc),
            )
        raise


def _is_sqlite_locked_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    lowered = str(exc).lower()
    return "database is locked" in lowered or "database table is locked" in lowered or "locked" in lowered


def _approval_review_revision_payload(
    *,
    job_id: str,
    gate_id: str,
    stage_index: int,
    gate_checksum: str,
    user_request_text: str,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "gate_id": gate_id,
        "stage_index": stage_index,
        "gate_checksum": gate_checksum,
        "user_request_text": user_request_text,
        "actor": "human",
        "timestamp": _utc_now_text(),
        "status": "revision_requested",
    }


def _record_approval_review_revision_request(
    *,
    uow: Any,
    job_id: str,
    gate_id: str,
    stage_index: int,
    gate_checksum: str,
    user_request_text: str,
) -> None:
    pending_card = _approval_review_pending_card(
        uow,
        job_id=job_id,
        gate_phase="approval_review",
        stage_index=stage_index,
        gate_checksum=gate_checksum,
    )
    if pending_card is not None:
        uow.v2_approvals.update_card_status(pending_card.card_id, "blocked")
    uow.v2_events.save(
        job_id=job_id,
        stage=stage_index,
        event_type="approval_revision_requested",
        status="blocked",
        message="Revision requested during approval review.",
        payload=_approval_review_revision_payload(
            job_id=job_id,
            gate_id=gate_id,
            stage_index=stage_index,
            gate_checksum=gate_checksum,
            user_request_text=user_request_text,
        ),
    )


def _utc_now_text() -> str:
    from migration_factory.control_tower.domain.checksums import utc_now_text

    return utc_now_text()


def _format_preview_response(preview: ActionPreview, context: GateContext) -> str:
    """Format an action preview as an assistant message."""
    lines: list[str] = []
    lines.append("**Action Preview**")
    lines.append("")
    lines.append(f"I understand you want to: **{preview.reason}**")
    lines.append("")
    lines.append("Here is what I would do:")
    lines.append(f"- **Action:** `{preview.action_type}`")
    lines.append(f"- **Confidence:** {preview.confidence:.0%}")
    if preview.warning:
        lines.append(f"- **Warning:** {preview.warning}")
    lines.append("")
    lines.append("To proceed, please confirm by saying **yes** or **confirm**.")
    lines.append("To cancel, ask a different question or say **no**.")
    return "\n".join(lines)


def _format_execution_response(
    execution_result: Any,
    progression: dict[str, Any] | None = None,
) -> str:
    """Format an execution result as an assistant message."""
    status = getattr(execution_result, "status", "")
    success = status == "executed" or getattr(execution_result, "success", False)
    message = getattr(execution_result, "message", getattr(execution_result, "reason", ""))
    decision_id = getattr(execution_result, "decision_id", None)

    lines: list[str] = []
    if success:
        lines.append("**Action Completed Successfully**")
        lines.append("")
        if decision_id:
            lines.append(f"- **Decision ID:** `{decision_id}`")
        if message:
            lines.append(f"- **Result:** {message}")
        lines.append("")
        if progression:
            prog_status = progression.get("status", "unknown")
            if prog_status == "queued":
                lines.append("**Planning has been queued.**")
                to_stage = progression.get("to_stage")
                if to_stage:
                    lines.append(f"- **Next stage:** Stage {to_stage}")
                lines.append("- The backend will process planning automatically.")
            elif prog_status == "planning_queued":
                lines.append("**Stage 1 planning has been queued.**")
                lines.append("- Analysis review is complete and accepted.")
                lines.append("- Stage 1 planning will run next and produce planning artifacts.")
                lines.append("- A planning_review gate will open after planning completes.")
                lines.append("- Migration Stage 2 was not started.")
                lines.append("- No transform/build/test started.")
                cmd_id = progression.get("planning_command_id", "")
                if cmd_id:
                    lines.append(f"- **Planning command:** `{cmd_id[:12]}...`")
            elif prog_status == "blocked":
                reason = progression.get("reason", "policy_blocked")
                lines.append(f"**Planning blocked:** {reason}")
                lines.append("The gate is resolved but automated progression is blocked.")
            elif prog_status == "phase_advanced":
                from_phase = progression.get("from_phase", "")
                to_phase = progression.get("to_phase", "")
                stage = progression.get("stage_index", "")
                lines.append(f"**Stage {stage} phase advanced: {from_phase} ? {to_phase}**")
                message = progression.get("message", "")
                if message:
                    lines.append(f"- {message}")
                lines.append("- Next gate is open and ready for review.")
                lines.append("- Migration Stage 2 was not started.")
                lines.append("- No source code was mutated.")
            else:
                lines.append(f"**Progression status:** {prog_status}")
                lines.append("The gate is resolved but check the job for details.")
        else:
            lines.append("The gate action has been applied. You can check the job status for updates.")
    else:
        lines.append("**Action Failed**")
        lines.append("")
        if status:
            lines.append(f"- **Status:** {status}")
        if message:
            lines.append(f"- **Error:** {message}")
        lines.append("")
        lines.append("Please try again or contact support if the issue persists.")
    return "\n".join(lines)


def _assistant_question_requires_write(*, question_lower: str, assistant_intent: str) -> bool:
    if assistant_intent in {"apply_dependency_change", "rollback_pom_change", "continue_from_gate", "request_revision"}:
        return True
    if assistant_intent == "confirm":
        return True
    confirm_patterns = (
        "confirm",
        "yes",
        "yeah",
        "sure",
        "go ahead",
        "do it",
        "apply",
        "proceed",
        "okay",
        "ok",
    )
    if any(
        question_lower == pattern
        or question_lower.startswith(pattern + " ")
        or question_lower.startswith(pattern + ",")
        or question_lower.startswith(pattern + ".")
        for pattern in confirm_patterns
    ):
        return True
    gate_action_terms = (
        "reanalyze",
        "re-analyze",
        "rescan",
        "scan again",
        "accept analysis",
        "continue analysis",
        "continue to planning",
        "request revision",
        "revise the plan",
        "revise this",
    )
    return any(term in question_lower for term in gate_action_terms)


def _handle_v2_assistant_read_only_ask(
    app: Any,
    job_id: str,
    question: str,
    correlation_id: str | None,
    unit_of_work_factory: Any,
) -> dict[str, Any]:
    from migration_factory.control_tower.application.v2_assistant_service import (
        AssistantMessage,
        V2AssistantService,
    )

    try:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            job = _require_v2_job(uow, job_id)
            events = uow.v2_events.list_by_job(job_id)
            approvals = uow.v2_approvals.list_cards_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)
            pipeline = _v2_pipeline_projection(job_id, events)
            service = V2AssistantService(assistant_repo=uow.v2_assistant)
            assistant_intent = _classify_v2_assistant_intent(question.strip().lower())
            setup = uow.v2_setups.get(job.setup_id) if job.setup_id else None
            artifact_previews_list = _resolve_assistant_artifact_previews(
                question=question,
                events=events,
                commands=commands,
                setup=setup,
                assistant_intent=assistant_intent,
            )
            artifact_previews = tuple(artifact_previews_list)
            fallback_answer = _build_v2_assistant_answer(
                question=question,
                events=events,
                approvals=approvals,
                commands=commands,
                artifact_previews=artifact_previews if artifact_previews else None,
                assistant_intent=assistant_intent,
            )
            if assistant_intent in {"apply_dependency_change", "rollback_pom_change"}:
                model_result = V2AssistantModelResult(
                    content=fallback_answer,
                    source="backend_controlled",
                    model_status="not_used",
                    provider="backend",
                    role="assistant",
                    success=True,
                    redacted_summary="Backend-controlled assistant action completed.",
                    failure_reason="",
                )
            else:
                assistant_client = app.state.v2_assistant_model_client
                assistant_prompt = _build_v2_assistant_prompt(
                    question=question,
                    job=job,
                    pipeline=pipeline,
                    events=events,
                    approvals=approvals,
                    artifact_previews=artifact_previews if artifact_previews else None,
                    assistant_intent=assistant_intent,
                    conversation_history=(),
                )
                if hasattr(assistant_client, "answer_with_role"):
                    model_result = assistant_client.answer_with_role(
                        role=V2ModelRole.ASSISTANT,
                        prompt=assistant_prompt,
                        fallback=fallback_answer,
                        conversation_history=(),
                    )
                else:
                    model_result = assistant_client.answer(
                        prompt=assistant_prompt,
                        fallback=fallback_answer,
                        conversation_history=(),
                    )

            now = utc_now_text()
            user_msg = AssistantMessage(
                message_id=uuid4().hex,
                job_id=job_id,
                role="user",
                content=question,
                correlation_id=correlation_id,
                created_at=now,
            )
            assistant_msg = AssistantMessage(
                message_id=uuid4().hex,
                job_id=job_id,
                role="assistant",
                content=model_result.content,
                correlation_id=user_msg.message_id,
                created_at=now,
            )
            response = {
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
            return response
    except sqlite3.OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return {
                "job_id": job_id,
                "user_message": {
                    "message_id": None,
                    "job_id": job_id,
                    "role": "user",
                    "content": question,
                    "correlation_id": correlation_id,
                    "created_at": utc_now_text(),
                },
                "assistant_message": {
                    "message_id": None,
                    "job_id": job_id,
                    "role": "assistant",
                    "content": "The orchestrator is busy right now. Retry shortly.",
                    "correlation_id": correlation_id,
                    "created_at": utc_now_text(),
                },
                "model": {
                    "status": "busy",
                    "source": "backend_controlled",
                    "provider": "backend",
                    "role": "assistant",
                    "failure_reason": "database is locked",
                },
                "guardrails": {
                    "read_only": True,
                    "cannot_execute": True,
                    "cannot_approve": True,
                    "cannot_write_files": True,
                    "cannot_change_route_or_stage": True,
                    "cannot_override_proof": True,
                },
                "busy": True,
            }
        raise


def _handle_resolved_gate_checksum_confirm(
    *,
    job_id: str,
    question: str,
    correlation_id: str | None,
    unit_of_work_factory: Any,
) -> dict[str, Any] | None:
    exact_checksum = _extract_confirm_checksum(question)
    if not exact_checksum:
        return None

    from migration_factory.control_tower.application.v2_assistant_service import (
        V2AssistantService,
    )

    with unit_of_work_factory() as uow:
        _require_v2_job(uow, job_id)
        matched_gate = None
        for gate in uow.phase_gates.list_by_job(job_id):
            try:
                refs_raw = json.loads(gate.source_artifact_refs_json or "[]")
            except (json.JSONDecodeError, TypeError):
                refs_raw = []
            refs = tuple(str(ref) for ref in refs_raw) if isinstance(refs_raw, list) else tuple(
                str(ref) for ref in refs_raw.values()
            ) if isinstance(refs_raw, dict) else ()
            checksum = gate_checksum(
                gate_id=gate.gate_id,
                job_id=gate.job_id,
                gate_phase=gate.gate_phase,
                stage_index=gate.stage_index,
                source_artifact_checksum=gate.source_artifact_checksum,
                source_artifact_refs=refs,
            )
            if checksum == exact_checksum:
                matched_gate = gate
                break
        if matched_gate is None:
            return None

        resume_status = None
        resume_id = ""
        for event in reversed(uow.v2_events.list_by_job(job_id)):
            if event.type not in {"approval_resume_queued", "resume_started"}:
                continue
            try:
                payload = json.loads(event.payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            resume_id = str(payload.get("resume_id") or payload.get("command_id") or resume_id or "")
            resume_status = str(payload.get("resume_status") or event.status or "queued")
            break

        service = V2AssistantService(assistant_repo=uow.v2_assistant)
        user_msg = service.add_message(
            job_id=job_id,
            role="user",
            content=question,
            correlation_id=correlation_id,
        )
        assistant_msg = service.add_message(
            job_id=job_id,
            role="assistant",
            content="Checksum already resolved. The approval resume is already queued or running.",
            correlation_id=user_msg.message_id,
        )
        return {
            "job_id": job_id,
            "user_message": service.message_to_dict(user_msg),
            "assistant_message": service.message_to_dict(assistant_msg),
            "gate_aware": True,
            "intent": "confirm_checksum",
            "executed": matched_gate.gate_status == "resolved",
            "execution_result": {
                "success": matched_gate.gate_status == "resolved",
                "status": "already_resolved" if matched_gate.gate_status == "resolved" else matched_gate.gate_status,
                "decision_id": "",
                "reason": "Gate checksum matched an existing non-open gate.",
                "resume_id": resume_id,
                "resume_status": resume_status or "queued",
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

def _handle_gate_aware_read_only_ask(
    app: Any,
    job_id: str,
    open_gate: Any,
    question: str,
    correlation_id: str | None,
    unit_of_work_factory: Any,
) -> dict[str, Any]:
    from migration_factory.control_tower.application.v2_assistant_service import (
        AssistantMessage,
        V2AssistantService,
    )

    try:
        with _read_unit_of_work(unit_of_work_factory) as uow:
            gate_repo = uow.phase_gates
            gate_service = V2PhaseGateService(gate_repo)
            job = uow.v2_jobs.get(job_id)
            setup = None
            if job is not None and getattr(job, "setup_id", None):
                setup = uow.v2_setups.get(job.setup_id)
            storage_root = getattr(setup, "output_parent_path", None) if setup is not None else None
            resolver = V2GateArtifactResolver(gate_repo, storage_root=storage_root)
            loader = GateContextLoader(
                gate_service=gate_service,
                resolver=resolver,
            )
            context, evidence_pack = loader.load_gate_with_evidence(open_gate.gate_id)
            if context is None:
                return _handle_v2_assistant_read_only_ask(
                    app=app,
                    job_id=job_id,
                    question=question,
                    correlation_id=correlation_id,
                    unit_of_work_factory=unit_of_work_factory,
                )

            service = V2AssistantService(assistant_repo=uow.v2_assistant)
            user_msg = AssistantMessage(
                message_id=uuid4().hex,
                job_id=job_id,
                role="user",
                content=question,
                correlation_id=correlation_id,
                created_at=utc_now_text(),
            )
            question_lower = question.strip().lower()
            classifier = GateIntentClassifier()
            intent: ClassifiedIntent = classifier.classify(
                user_input=question,
                available_actions=context.available_actions,
                gate_phase=context.gate_phase,
            )

            if open_gate.gate_phase == "approval_review":
                blocked_revision_card = _approval_review_blocked_revision_card(
                    uow,
                    job_id=job_id,
                    stage_index=open_gate.stage_index,
                    gate_checksum=context.checksum,
                )
                if blocked_revision_card is not None and (
                    intent.action_type == "approve_from_gate"
                    or question_lower == "approve"
                    or intent.action_type == "reject_from_gate"
                    or question_lower == "reject"
                ):
                    assistant_msg = AssistantMessage(
                        message_id=uuid4().hex,
                        job_id=job_id,
                        role="assistant",
                        content=_approval_review_revision_blocked_message(),
                        correlation_id=user_msg.message_id,
                        created_at=utc_now_text(),
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "approve_from_gate",
                        "executed": False,
                        "available_actions": _approval_review_available_actions(blocked_revision=True),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }
                exact_checksum = _extract_confirm_checksum(question)
                if intent.action_type == "approve_from_gate" or question_lower == "approve":
                    assistant_msg = AssistantMessage(
                        message_id=uuid4().hex,
                        job_id=job_id,
                        role="assistant",
                        content=_format_approval_review_preview(context),
                        correlation_id=user_msg.message_id,
                        created_at=utc_now_text(),
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "approve_from_gate",
                        "executed": False,
                        "action_preview": {
                            "action_type": "approve_from_gate",
                            "reason": "Preview only; exact checksum confirmation required.",
                            "confidence": 1.0,
                            "warning": "Approval will not execute until the exact checksum is confirmed.",
                            "requires_confirmation": True,
                            "pending_confirmation": True,
                            "exact_checksum": context.checksum,
                        },
                        "available_actions": _approval_review_available_actions(),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }
                if exact_checksum and exact_checksum != context.checksum:
                    assistant_msg = AssistantMessage(
                        message_id=uuid4().hex,
                        job_id=job_id,
                        role="assistant",
                        content="Checksum mismatch. Confirm the latest gate checksum from the review surface.",
                        correlation_id=user_msg.message_id,
                        created_at=utc_now_text(),
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "confirm_checksum",
                        "executed": False,
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }
                if _question_looks_like_approval_review_explanation(question):
                    explanation_text, explanation_model = _format_approval_review_explanation(
                        app=app,
                        context=context,
                        evidence=evidence_pack,
                        question=question,
                    )
                    assistant_msg = AssistantMessage(
                        message_id=uuid4().hex,
                        job_id=job_id,
                        role="assistant",
                        content=explanation_text,
                        correlation_id=user_msg.message_id,
                        created_at=utc_now_text(),
                    )
                    return {
                        "job_id": job_id,
                        "user_message": service.message_to_dict(user_msg),
                        "assistant_message": service.message_to_dict(assistant_msg),
                        "gate_aware": True,
                        "intent": "status",
                        "executed": False,
                        "model": explanation_model,
                        "available_actions": _approval_review_available_actions(),
                        "guardrails": {
                            "read_only": True,
                            "cannot_execute": True,
                            "cannot_approve": True,
                            "cannot_write_files": True,
                            "cannot_change_route_or_stage": True,
                            "cannot_override_proof": True,
                        },
                    }

            if (intent.ambiguous or not intent.action_type) and not _question_looks_like_approval_review_revision_request(question):
                from migration_factory.control_tower.application.v2_gate_assistant import (
                    AmbiguityHandler,
                )
                explanation = AmbiguityHandler.handle_ambiguous(intent, context)
                assistant_msg = AssistantMessage(
                    message_id=uuid4().hex,
                    job_id=job_id,
                    role="assistant",
                    content=explanation,
                    correlation_id=user_msg.message_id,
                    created_at=utc_now_text(),
                )
                return {
                    "job_id": job_id,
                    "user_message": service.message_to_dict(user_msg),
                    "assistant_message": service.message_to_dict(assistant_msg),
                    "gate_aware": True,
                    "intent": intent.action_type or "ambiguous",
                    "executed": False,
                    "ambiguous": True,
                    "available_actions": tuple(a.action for a in context.available_actions),
                    "guardrails": {
                        "read_only": True,
                        "cannot_execute": True,
                        "cannot_approve": True,
                        "cannot_write_files": True,
                        "cannot_change_route_or_stage": True,
                        "cannot_override_proof": True,
                    },
                }

            assistant_msg = AssistantMessage(
                message_id=uuid4().hex,
                job_id=job_id,
                role="assistant",
                content=_format_approval_review_preview(context),
                correlation_id=user_msg.message_id,
                created_at=utc_now_text(),
            )
            return {
                "job_id": job_id,
                "user_message": service.message_to_dict(user_msg),
                "assistant_message": service.message_to_dict(assistant_msg),
                "gate_aware": True,
                "intent": intent.action_type or "status",
                "executed": False,
                "available_actions": list(intent.available_actions),
                "guardrails": {
                    "read_only": True,
                    "cannot_execute": True,
                    "cannot_approve": True,
                    "cannot_write_files": True,
                    "cannot_change_route_or_stage": True,
                    "cannot_override_proof": True,
                },
            }
    except sqlite3.OperationalError as exc:
        if _is_sqlite_locked_error(exc):
            return {
                "job_id": job_id,
                "user_message": {
                    "message_id": None,
                    "job_id": job_id,
                    "role": "user",
                    "content": question,
                    "correlation_id": correlation_id,
                    "created_at": utc_now_text(),
                },
                "assistant_message": {
                    "message_id": None,
                    "job_id": job_id,
                    "role": "assistant",
                    "content": "The orchestrator is busy right now. Retry shortly.",
                    "correlation_id": correlation_id,
                    "created_at": utc_now_text(),
                },
                "gate_aware": True,
                "intent": "status",
                "executed": False,
                "busy": True,
                "guardrails": {
                    "read_only": True,
                    "cannot_execute": True,
                    "cannot_approve": True,
                    "cannot_write_files": True,
                    "cannot_change_route_or_stage": True,
                    "cannot_override_proof": True,
                },
            }
        raise


def _fallback_to_existing_assistant(
    app: Any,
    job_id: str,
    question: str,
    correlation_id: str | None,
    unit_of_work_factory: Any,
) -> dict[str, Any]:
    """Fall back to the existing V2AssistantService when gate load fails."""
    from migration_factory.control_tower.application.v2_assistant_service import (
        V2AssistantService,
    )
    with unit_of_work_factory() as uow:
        job = _require_v2_job(uow, job_id)
        events = uow.v2_events.list_by_job(job_id)
        approvals = uow.v2_approvals.list_cards_by_job(job_id)
        commands = uow.v2_commands.list_by_job(job_id)
        pipeline = _v2_pipeline_projection(job_id, events)
        service = V2AssistantService(assistant_repo=uow.v2_assistant)
        assistant_intent = _classify_v2_assistant_intent(question)
        prior_messages = service.get_messages(job_id)
        user_msg = service.add_message(
            job_id=job_id,
            role="user",
            content=question,
            correlation_id=correlation_id,
        )
        conversation_history = _build_bounded_conversation_history(
            messages=prior_messages,
        )
        uow.v2_events.save(
            job_id=job_id,
            stage=None,
            event_type="model_invocation_started",
            status="running",
            message="Assistant model invocation started.",
            payload={"provider": "azure_openai", "role": "assistant"},
        )
        setup = uow.v2_setups.get(job.setup_id) if job.setup_id else None
        artifact_previews_list = _resolve_assistant_artifact_previews(
            question=question,
            events=events,
            commands=commands,
            setup=setup,
            assistant_intent=assistant_intent,
        )
        artifact_previews = tuple(artifact_previews_list)
        if assistant_intent in {"apply_dependency_change", "rollback_pom_change"} and uow.connection.in_transaction:
            uow.connection.execute("COMMIT")
        fallback_answer = _build_v2_assistant_answer(
            question=question,
            events=events,
            approvals=approvals,
            commands=commands,
            artifact_previews=artifact_previews if artifact_previews else None,
            assistant_intent=assistant_intent,
        )
        if assistant_intent in {"apply_dependency_change", "rollback_pom_change"}:
            model_result = V2AssistantModelResult(
                content=fallback_answer,
                source="backend_controlled",
                model_status="not_used",
                provider="backend",
                role="assistant",
                success=True,
                redacted_summary="Backend-controlled assistant action completed.",
                failure_reason="",
            )
        else:
            assistant_client = app.state.v2_assistant_model_client
            assistant_prompt = _build_v2_assistant_prompt(
                question=question,
                job=job,
                pipeline=pipeline,
                events=events,
                approvals=approvals,
                artifact_previews=artifact_previews if artifact_previews else None,
                assistant_intent=assistant_intent,
                conversation_history=conversation_history,
            )
            if hasattr(assistant_client, "answer_with_role"):
                model_result = assistant_client.answer_with_role(
                    role=V2ModelRole.ASSISTANT,
                    prompt=assistant_prompt,
                    fallback=fallback_answer,
                    conversation_history=conversation_history,
                )
            else:
                model_result = assistant_client.answer(
                    prompt=assistant_prompt,
                    fallback=fallback_answer,
                    conversation_history=conversation_history,
                )
        assistant_msg = service.add_message(
            job_id=job_id,
            role="assistant",
            content=model_result.content,
            correlation_id=user_msg.message_id,
        )
    with unit_of_work_factory() as uow:
        is_fallback = (
            not model_result.success
            and model_result.source == "deterministic"
        )
        _append_v2_event(
            uow,
            job_id=job_id,
            stage=None,
            event_type="model_invocation_completed" if model_result.success else "model_invocation_failed",
            status="completed" if model_result.success else ("fallback" if is_fallback else "failed"),
            message=model_result.redacted_summary,
            payload={
                "provider": model_result.provider,
                "role": model_result.role,
                "source": model_result.source,
                "success": model_result.success,
                "is_fallback": is_fallback,
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


def _build_bounded_conversation_history(
    messages: tuple[Any, ...],
    max_messages: int = 8,
) -> list[dict[str, str]]:
    """Build a bounded, redacted conversation history from prior messages.

    Returns up to max_messages recent role/content pairs.
    Redacts content, excludes raw paths, secrets, and approval tokens.
    """
    from migration_factory.control_tower.application.redaction import redact_model_summary

    if not messages:
        return []
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    history: list[dict[str, str]] = []
    for msg in recent:
        role = str(getattr(msg, "role", "user") or "user")
        content = str(getattr(msg, "content", "") or "")
        if not content.strip():
            continue
        safe = redact_model_summary(str(content))
        safe = safe[:512]  # Bound each message
        safe = re.sub(r'/[^\s"]+/[^\s"]*', "[path-redacted]", safe)
        safe = re.sub(r'\b[0-9a-f]{32,}\b', "[token-redacted]", safe)
        history.append({"role": role, "content": safe})
    return history


def _question_looks_like_artifact_content(question: str) -> bool:
    """Detect if a user question is asking for artifact content."""
    lowered = str(question or "").lower()
    # Quick guard: must be asking for something
    if not any(pattern in lowered for pattern in _ARTIFACT_CONTENT_QUESTION_PATTERNS):
        return False
    # Must mention artifact-related terms
    return any(keyword in lowered for keyword in _ARTIFACT_CONTENT_KEYWORDS)


def _question_requests_root_pom_alias(question: str) -> bool:
    """Detect requests for the fixed root_pom alias, not arbitrary paths."""
    lowered = str(question or "").lower()
    if not any(pattern in lowered for pattern in _ARTIFACT_CONTENT_QUESTION_PATTERNS):
        return False
    return any(term in lowered for term in _ROOT_POM_ALIAS_TERMS)


def _stage_index_from_question(question: str) -> int | None:
    lowered = str(question or "").lower()
    match = re.search(r"\b(?:stage|phase)\s*([1-3])\b", lowered)
    if match:
        return int(match.group(1))
    if any(term in lowered for term in ("final stage", "target stage", "final pom", "target pom", "final target")):
        return 3
    return None


def _get_requested_stage(question: str, intent: str = "") -> int | None:
    """Extract requested stage from question, with intent-aware defaults.

    - 'stage 3', 'phase 3', 'final stage', 'target stage', 'final pom' -> stage=3
    - 'stage 1' -> stage=1
    - 'stage 2' -> stage=2
    - If no stage given and intent is stage3_dependency_review, default to stage=3
    - If no stage given and intent is pom_dependency_change_request, prefer stage 3 if evidence available
    - Otherwise returns None (keep existing behavior)
    """
    lowered = str(question or "").lower()
    match = re.search(r"\b(?:stage|phase)\s*([1-3])\b", lowered)
    if match:
        return int(match.group(1))
    # Named stage references
    if any(term in lowered for term in ("stage 3", "phase 3", "final stage", "target stage", "final pom", "final target")):
        return 3
    if "stage 2" in lowered or "phase 2" in lowered:
        return 2
    if "stage 1" in lowered or "phase 1" in lowered:
        return 1
    # Intent-based defaults
    if intent in ("stage3_dependency_review",):
        return 3
    # If user asks for full/root/current/final POM without explicit stage,
    # prefer Stage 3 if it is complete (checked via events)
    if any(term in lowered for term in ("full pom", "root pom", "current pom", "final pom", "the pom")):
        return None  # Let caller resolve via _default_stage_from_events
    return None


def _is_final_dependency_review_allowed(
    stage_index: int,
    root_pom_preview: dict[str, Any] | None,
    events: tuple[Any, ...],
) -> tuple[bool, str]:
    """Check if a final dependency review is allowed at the given stage.

    Returns (allowed: bool, reason: str).
    Reasons: ok, stage_not_3, root_pom_unavailable, stage_running,
    stage_not_completed, proof_missing, build_or_tests_missing.
    """
    if stage_index != 3:
        return False, "stage_not_3"
    if not root_pom_preview or not root_pom_preview.get("exists"):
        return False, "root_pom_unavailable"
    # Check stage 3 events for stability
    stage_events = sorted(
        [event for event in events if getattr(event, "stage", None) == 3],
        key=lambda event: getattr(event, "sequence", 0),
    )
    if not stage_events:
        return False, "stage_not_completed"
    latest_stage_event = stage_events[-1]
    if getattr(latest_stage_event, "status", "") == "running" or str(
        getattr(latest_stage_event, "type", "")
    ).endswith("_started"):
        return False, "stage_running"
    if not any(
        getattr(event, "type", "") in {"sandbox_transform_completed", "stage_completed"}
        or (
            getattr(event, "status", "") == "completed"
            and str(getattr(event, "type", ""))
            in {"transform_completed", "build_completed", "test_completed"}
        )
        for event in stage_events
    ):
        return False, "stage_not_completed"
    has_build = any(
        getattr(e, "type", "") in {"build_completed", "test_completed"} for e in stage_events
    )
    if not has_build:
        return True, "ok"  # Not blocking on missing build/test — just warn
    return True, "ok"


def _default_stage_when_stage3_complete(events: tuple[Any, ...]) -> int | None:
    """If Stage 3 is complete (has completion events), default to stage=3.

    Used when user asks for "full POM" or "root POM" without explicit stage number.
    Returns 3 if Stage 3 is complete, None otherwise.
    """
    stage_events = sorted(
        [event for event in events if getattr(event, "stage", None) == 3],
        key=lambda event: getattr(event, "sequence", 0),
    )
    if not stage_events:
        return None
    latest_stage_event = stage_events[-1]
    if getattr(latest_stage_event, "status", "") == "running" or str(
        getattr(latest_stage_event, "type", "")
    ).endswith("_started"):
        return None
    if any(
        getattr(event, "type", "") in {"sandbox_transform_completed", "stage_completed"}
        or (
            getattr(event, "status", "") == "completed"
            and str(getattr(event, "type", ""))
            in {"transform_completed", "build_completed", "test_completed"}
        )
        for event in stage_events
    ):
        return 3
    return None



def _resolve_assistant_artifact_previews(
    *,
    question: str,
    events: tuple[Any, ...],
    commands: tuple[Any, ...],
    setup: Any | None = None,
    assistant_intent: str = "",
) -> list[dict[str, Any]]:
    """Resolve bounded artifact previews for assistant artifact-content questions.

    Only resolves safe artifact kinds from persisted events.
    Returns list of preview dicts, bounded to 3 artifacts at 2 KB each.
    Never reads from user-supplied paths.
    """
    # Always resolve root_pom for pom-related intents even if question doesn't mention "pom"
    pom_related_intents = {"pom_change_proposal", "pom_dependency_change_request", "stage3_dependency_review", "pom_or_dependency_explanation"}
    resolve_root_pom = _question_requests_root_pom_alias(question) or assistant_intent in pom_related_intents

    if not _question_looks_like_artifact_content(question) and not resolve_root_pom:
        return []

    previews: list[dict[str, Any]] = []
    max_previews = 3
    max_chars_per_preview = 2048

    if resolve_root_pom:
        requested_stage = (
            _get_requested_stage(question, assistant_intent)
            or _stage_index_from_question(question)
            or _default_stage_when_stage3_complete(events)
            or 1
        )
        root_pom_preview = _resolve_root_pom_file_alias_preview(
            job_id="",
            stage_index=requested_stage,
            events=events,
            commands=commands,
            max_bytes=max_chars_per_preview * 2,
        )
        root_pom_preview.pop("_path", None)
        previews.append(root_pom_preview)
        # If only root_pom was requested (not a broader artifact content question), return it
        if not _question_looks_like_artifact_content(question):
            return previews

    # Collect artifact kinds mentioned in events
    available_kinds: dict[str, int] = {}
    for event in events:
        if event.type != "artifact_written":
            continue
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        kind = str(payload.get("artifact_kind", ""))
        if kind:
            available_kinds[kind] = getattr(event, "sequence", 0)

    if not available_kinds:
        # Return root_pom only if it was resolved (other artifact kinds not available)
        return previews

    # Only resolve kinds that are both in safe_kinds AND appear in events
    safe_kinds = {
        "phase2_log", "post_transform_test_log", "failure_classification",
        "repair_plan", "deterministic_repair_plan", "copilot_repair_response",
        "dependency_policy_report", "dependency_policy_summary",
        "dependency_repair_plan", "orchestration_summary",
        "target_dependency_plan", "rewrite_dry_run.patch",
        "rewrite_impact_summary.json", "repair_ledger", "migration_ledger",
        "openrewrite_plugin_xml", "approved_plan_lock",
    }

    # Prefer kinds mentioned in the question, then fall back to all available
    lowered = str(question or "").lower()
    preferred_order: list[str] = []
    for kind in available_kinds:
        if any(part in lowered for part in kind.lower().replace("_", " ").split()):
            preferred_order.append(kind)
    for kind in sorted(available_kinds, key=lambda k: -available_kinds[k]):
        if kind not in preferred_order and kind in safe_kinds:
            preferred_order.append(kind)

    for kind in preferred_order:
        if len(previews) >= max_previews:
            break
        if kind not in safe_kinds:
            continue
        preview = _resolve_single_artifact_preview(
            artifact_kind=kind,
            events=events,
            commands=commands,
            setup=setup,
            max_chars=max_chars_per_preview,
        )
        if preview:
            previews.append(preview)

    return previews


def _resolve_single_artifact_preview(
    *,
    artifact_kind: str,
    events: tuple[Any, ...],
    commands: tuple[Any, ...],
    setup: Any | None = None,
    max_chars: int = 2048,
) -> dict[str, Any] | None:
    """Resolve a single artifact preview from backend events only.

    Never reads from user-supplied paths.
    """
    import json as _json
    from pathlib import Path as _Path
    from migration_factory.control_tower.application.redaction import redact_model_summary

    artifact_path = None
    best_sequence = -1
    for event in events:
        if event.type != "artifact_written":
            continue
        try:
            payload = _json.loads(event.payload_json or "{}")
        except (_json.JSONDecodeError, TypeError):
            continue
        kind = str(payload.get("artifact_kind", ""))
        if kind != artifact_kind:
            continue
        path_val = payload.get("relative_path") or payload.get("path")
        if path_val and getattr(event, "sequence", 0) > best_sequence:
            artifact_path = str(path_val)
            best_sequence = getattr(event, "sequence", 0)

    if not artifact_path:
        return None

    if setup is None or not getattr(setup, "output_parent_path", ""):
        return None

    try:
        candidate = _resolve_v2_artifact_preview_path(
            artifact_ref=artifact_path,
            setup=setup,
            commands=commands,
        )
        if candidate is None:
            return None

        raw = candidate.read_bytes()[:max_chars * 2]
        if raw[:3] == b"\xef\xbb\xbf":
            raw = raw[3:]
        try:
            text = raw.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, LookupError):
            text = raw.decode("latin-1", errors="replace")
        preview = redact_model_summary(text)[:max_chars]
        truncated = len(text) > max_chars
    except Exception:
        return None

    return {
        "artifact_kind": artifact_kind,
        "source_type": "artifact",
        "exists": True,
        "preview": preview,
        "truncated": truncated,
    }


def _resolve_root_pom_file_alias_preview(
    *,
    job_id: str,
    stage_index: int,
    events: tuple[Any, ...],
    commands: tuple[Any, ...],
    max_bytes: int,
) -> dict[str, Any]:
    from migration_factory.control_tower.application.redaction import redact_model_summary

    response: dict[str, Any] = {
        "job_id": job_id,
        "artifact_kind": "root_pom",
        "source_type": "file_alias",
        "file_alias": "root_pom",
        "stage_index": stage_index,
        "exists": False,
        "preview": "",
        "content": "",
        "truncated": False,
        "content_type": "application/xml",
        "download_url": None,
        "source_ref": None,
        "reason": "not_available",
    }
    if stage_index not in (1, 2, 3, 4):
        response["reason"] = "invalid_stage"
        return response

    stage_events = sorted(
        [event for event in events if getattr(event, "stage", None) == stage_index],
        key=lambda event: getattr(event, "sequence", 0),
    )
    latest_stage_event = stage_events[-1] if stage_events else None
    is_stage_running = latest_stage_event is not None and (
        getattr(latest_stage_event, "status", "") == "running"
        or str(getattr(latest_stage_event, "type", "")).endswith("_started")
    )
    stage_has_completed_evidence = any(
        getattr(event, "type", "") in {"sandbox_transform_completed", "stage_completed"}
        or (
            getattr(event, "status", "") == "completed"
            and str(getattr(event, "type", "")) in {"transform_completed", "build_completed", "test_completed"}
        )
        for event in stage_events
    )
    if is_stage_running and stage_index != 3:
        response["reason"] = "stage_running"
        return response
    if not stage_has_completed_evidence and not (is_stage_running and stage_index == 3):
        response["reason"] = "stage_not_completed"
        return response

    resolved = _resolve_stage_sandbox_root(
        stage_index=stage_index,
        events=events,
        commands=commands,
    )
    if resolved is None:
        response["reason"] = "sandbox_unresolved"
        return response
    sandbox_root, source_ref = resolved
    response["source_ref"] = source_ref

    try:
        resolved_root = sandbox_root.resolve(strict=True)
        candidate = (resolved_root / "pom.xml").resolve(strict=True)
        candidate.relative_to(resolved_root)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        response["reason"] = "file_missing_or_unsafe"
        return response
    if not candidate.is_file():
        response["reason"] = "file_missing_or_unsafe"
        return response

    try:
        file_size = candidate.stat().st_size
        raw = candidate.read_bytes()[:max_bytes]
    except (OSError, RuntimeError, ValueError):
        response["reason"] = "file_unreadable"
        return response
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    try:
        text = raw.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, LookupError):
        text = raw.decode("latin-1", errors="replace")
    preview = redact_model_summary(text)
    response.update({
        "exists": True,
        "preview": preview,
        "content": preview,
        "truncated": file_size > max_bytes,
        "download_url": f"/v1/v2/jobs/{job_id}/files/root-pom?stage={stage_index}&mode=download" if job_id else None,
        "reason": None,
        "label": "live Stage 3 sandbox POM during validation" if is_stage_running and stage_index == 3 else "root_pom",
        "_path": candidate,
    })
    return response


def _resolve_stage_sandbox_root(
    *,
    stage_index: int,
    events: tuple[Any, ...],
    commands: tuple[Any, ...],
) -> tuple[Path, dict[str, str]] | None:
    stage_commands = [
        command for command in commands
        if int(getattr(command, "stage_index", 0) or 0) == stage_index
    ]
    for command in sorted(stage_commands, key=lambda c: getattr(c, "updated_at", "") or getattr(c, "created_at", ""), reverse=True):
        result_json = getattr(command, "result_json", None)
        if not result_json:
            continue
        try:
            result = json.loads(result_json)
        except (json.JSONDecodeError, TypeError):
            continue
        sandbox_path = _sandbox_path_from_mapping(result)
        if sandbox_path:
            return Path(sandbox_path), {
                "command_id": str(getattr(command, "command_id", "")),
                "source": "command_result",
            }

    for event in sorted(events, key=lambda e: getattr(e, "sequence", 0), reverse=True):
        if getattr(event, "stage", None) != stage_index:
            continue
        if getattr(event, "type", "") not in {
            "sandbox_transform_completed", "stage_completed", "artifact_written",
            "build_completed", "test_completed",
        }:
            continue
        try:
            payload = json.loads(getattr(event, "payload_json", "") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        sandbox_path = _sandbox_path_from_mapping(payload)
        if sandbox_path:
            return Path(sandbox_path), {
                "event_id": str(getattr(event, "event_id", "")),
                "source": "event_payload",
            }
    return None


def _sandbox_path_from_mapping(value: dict[str, Any]) -> str:
    candidates: list[Any] = [
        value.get("sandbox_path"),
        value.get("sandbox"),
        value.get("relative_path"),
    ]
    artifact_refs = value.get("artifact_refs")
    if isinstance(artifact_refs, dict):
        candidates.extend([
            artifact_refs.get("sandbox"),
            artifact_refs.get("sandbox_path"),
        ])
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text or _is_unsafe_sandbox_root(text):
            continue
        return text
    return ""


def _is_unsafe_sandbox_root(value: str) -> bool:
    if value.startswith(("\\", "//")):
        return True
    path = Path(value)
    win_path = PureWindowsPath(value)
    if not (path.is_absolute() or win_path.is_absolute() or win_path.drive):
        return True
    return any(part == ".." for part in path.parts)


def _build_v2_assistant_answer(
    *,
    question: str,
    events: tuple[Any, ...],
    approvals: tuple[Any, ...],
    commands: tuple[Any, ...],
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    assistant_intent: str = "general_question",
) -> str:
    # â”€â”€ Intent-adaptive fallback paths â”€â”€
    # Auto-detect status questions when intent not explicitly set
    effective_intent = assistant_intent
    if effective_intent == "general_question":
        effective_intent = _classify_v2_assistant_intent(question)

    if effective_intent == "pom_or_dependency_explanation":
        # Detect if user is asking for raw XML (not structured summary)
        raw_xml_requested = any(w in str(question or "").lower() for w in ("raw", "not summarize", "do not summarize", "don't summarize", "full raw"))
        job_id = _resolve_assistant_job_id(events=events, commands=commands)
        return _build_pom_explanation_answer(
            artifact_previews=artifact_previews,
            events=events,
            raw_xml_requested=raw_xml_requested,
            job_id=job_id,
        )

    if effective_intent == "pom_dependency_change_request":
        return _build_pom_dependency_change_request_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "apply_dependency_change":
        return _build_apply_dependency_change_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "rollback_pom_change":
        return _build_rollback_pom_change_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "pom_validation_result":
        return _build_pom_validation_result_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "stage3_dependency_review":
        return _build_stage3_dependency_review_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "pom_change_proposal":
        return _build_pom_change_proposal_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
            approvals=approvals,
            commands=commands,
        )

    if effective_intent == "capability_boundary":
        return _build_capability_boundary_answer()

    if effective_intent == "model_status":
        return _build_model_status_answer()

    if effective_intent == "general_question" or effective_intent == "artifact_content":
        return _build_general_or_artifact_answer(
            question=question,
            artifact_previews=artifact_previews,
            events=events,
        )

    # Default: operational status template
    return _build_status_answer(
        question=question,
        events=events,
        approvals=approvals,
        commands=commands,
        artifact_previews=artifact_previews,
    )


# â”€â”€ POM change proposal builder â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _extract_pom_summary(xml_text: str) -> dict[str, Any]:
    """Extract structured POM fields from XML text.

    Uses xml.etree.ElementTree when possible, regex as fallback.
    Returns a dict with project coordinates, properties, dependencies,
    plugins, dependencyManagement/parent presence, parent info,
    dependencyManagement BOM imports, and repositories.
    Maven namespace/schema URLs are preserved.
    """
    import xml.etree.ElementTree as ET

    result: dict[str, Any] = {
        "parse_ok": False,
        "coordinates": {},
        "parent": {},
        "properties": {},
        "dependencies": [],
        "plugins": [],
        "has_dependency_management": False,
        "has_parent": False,
        "has_repositories": False,
        "dependency_management_boms": [],
        "packaging": "jar",
    }

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Fallback: regex extraction
        result["parse_ok"] = False
        result["fallback_extracted"] = True
        # Extract groupId/artifactId/version with regex
        for field in ("groupId", "artifactId", "version", "packaging"):
            m = re.search(
                rf"<{field}>([^<]*)</{field}>", xml_text, re.IGNORECASE
            )
            if m:
                result["coordinates"][field] = m.group(1).strip()
        # Extract properties
        props_match = re.search(
            r"<properties>(.*?)</properties>", xml_text, re.DOTALL | re.IGNORECASE
        )
        if props_match:
            prop_section = props_match.group(1)
            for pm in re.finditer(
                r"<([^>!\s]+)>([^<]*)</\1>", prop_section, re.IGNORECASE
            ):
                result["properties"][pm.group(1)] = pm.group(2).strip()
        # Extract dependencies
        for dm in re.finditer(
            r"<dependency>(.*?)</dependency>", xml_text, re.DOTALL | re.IGNORECASE
        ):
            dep: dict[str, str] = {}
            for field in ("groupId", "artifactId", "version", "scope"):
                fm = re.search(
                    rf"<{field}>([^<]*)</{field}>", dm.group(1), re.IGNORECASE
                )
                if fm:
                    dep[field] = fm.group(1).strip()
            if dep:
                result["dependencies"].append(dep)
        # Extract plugins
        for dm in re.finditer(
            r"<plugin>(.*?)</plugin>", xml_text, re.DOTALL | re.IGNORECASE
        ):
            plug: dict[str, str] = {}
            for field in ("groupId", "artifactId", "version"):
                fm = re.search(
                    rf"<{field}>([^<]*)</{field}>", dm.group(1), re.IGNORECASE
                )
                if fm:
                    plug[field] = fm.group(1).strip()
            if plug:
                result["plugins"].append(plug)
        result["has_dependency_management"] = bool(
            re.search(r"<dependencyManagement>", xml_text, re.IGNORECASE)
        )
        result["has_parent"] = bool(
            re.search(r"<parent>", xml_text, re.IGNORECASE)
        )
        result["has_repositories"] = bool(
            re.search(r"<repositor(?:y|ies)>", xml_text, re.IGNORECASE)
        )
        # Extract parent coordinates via regex
        parent_match = re.search(
            r"<parent>(.*?)</parent>", xml_text, re.DOTALL | re.IGNORECASE
        )
        if parent_match:
            for pf in ("groupId", "artifactId", "version"):
                pm = re.search(
                    rf"<{pf}>([^<]*)</{pf}>", parent_match.group(1), re.IGNORECASE
                )
                if pm:
                    result["parent"][pf] = pm.group(1).strip()
        # Extract dependencyManagement BOM imports via regex
        dm_match = re.search(
            r"<dependencyManagement>(.*?)</dependencyManagement>", xml_text, re.DOTALL | re.IGNORECASE
        )
        if dm_match:
            for bom_m in re.finditer(
                r"<dependency>(.*?)</dependency>", dm_match.group(1), re.DOTALL | re.IGNORECASE
            ):
                bom: dict[str, str] = {}
                for field in ("groupId", "artifactId", "version"):
                    fm = re.search(
                        rf"<{field}>([^<]*)</{field}>", bom_m.group(1), re.IGNORECASE
                    )
                    if fm:
                        bom[field] = fm.group(1).strip()
                if bom.get("type") or "bom" in bom.get("artifactId", "").lower() or "dependencies" in bom.get("artifactId", ""):
                    bom["type"] = "pom"
                    bom["scope"] = "import"
                if bom:
                    result["dependency_management_boms"].append(bom)
        return result

    # Namespace-aware tag helpers â€” handle both Maven namespace and plain XML
    ns = "{http://maven.apache.org/POM/4.0.0}"
    # Detect if root uses Maven namespace
    _has_maven_ns = root.tag == f"{ns}project"

    def _tag(local: str) -> str:
        return f"{ns}{local}" if _has_maven_ns else local

    def _text(el: Any, local: str) -> str | None:
        child = el.find(_tag(local))
        if child is None and _has_maven_ns:
            # Fallback: try without namespace
            child = el.find(local)
        return child.text.strip() if child is not None and child.text else None

    def _find_all(el: Any, local: str) -> list:
        """Find all children matching a tag, namespace-aware."""
        results = list(el.findall(_tag(local)))
        if not results and _has_maven_ns:
            results = list(el.findall(local))
        return results

    result["parse_ok"] = True
    result["coordinates"] = {
        "groupId": _text(root, "groupId") or "",
        "artifactId": _text(root, "artifactId") or "",
        "version": _text(root, "version") or "",
        "packaging": _text(root, "packaging") or "jar",
    }

    # Properties
    props_el = root.find(_tag("properties"))
    if props_el is None and _has_maven_ns:
        props_el = root.find("properties")
    if props_el is not None:
        for child in props_el:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            result["properties"][local] = (child.text or "").strip()

    # Dependencies
    deps_el = root.find(_tag("dependencies"))
    if deps_el is None and _has_maven_ns:
        deps_el = root.find("dependencies")
    if deps_el is not None:
        for dep_el in _find_all(deps_el, "dependency"):
            dep = {}
            for field in ("groupId", "artifactId", "version", "scope"):
                val = _text(dep_el, field)
                if val:
                    dep[field] = val
            if dep:
                result["dependencies"].append(dep)

    # Plugins
    build_el = root.find(_tag("build"))
    if build_el is None and _has_maven_ns:
        build_el = root.find("build")
    if build_el is not None:
        plugins_el = build_el.find(_tag("plugins"))
        if plugins_el is None and _has_maven_ns:
            plugins_el = build_el.find("plugins")
        if plugins_el is not None:
            for plug_el in _find_all(plugins_el, "plugin"):
                plug = {}
                for field in ("groupId", "artifactId", "version"):
                    val = _text(plug_el, field)
                    if val:
                        plug[field] = val
                if plug:
                    result["plugins"].append(plug)

    # Presence checks
    _dm = root.find(_tag("dependencyManagement"))
    if _dm is None and _has_maven_ns:
        _dm = root.find("dependencyManagement")
    result["has_dependency_management"] = _dm is not None

    # Extract parent coordinates
    _parent = root.find(_tag("parent"))
    if _parent is None and _has_maven_ns:
        _parent = root.find("parent")
    result["has_parent"] = _parent is not None
    if _parent is not None:
        result["parent"] = {}
        for pf in ("groupId", "artifactId", "version"):
            val = _text(_parent, pf)
            if val:
                result["parent"][pf] = val

    # Extract dependencyManagement BOM imports
    if _dm is not None:
        dm_deps_el = _dm.find(_tag("dependencies"))
        if dm_deps_el is None and _has_maven_ns:
            dm_deps_el = _dm.find("dependencies")
        if dm_deps_el is not None:
            for dep_el in _find_all(dm_deps_el, "dependency"):
                bom: dict[str, str] = {}
                for field in ("groupId", "artifactId", "version"):
                    val = _text(dep_el, field)
                    if val:
                        bom[field] = val
                type_val = _text(dep_el, "type")
                scope_val = _text(dep_el, "scope")
                if type_val:
                    bom["type"] = type_val
                if scope_val:
                    bom["scope"] = scope_val
                if bom:
                    result["dependency_management_boms"].append(bom)

    _repos = root.find(_tag("repositories")) or root.find(_tag("pluginRepositories"))
    if _repos is None and _has_maven_ns:
        _repos = root.find("repositories") or root.find("pluginRepositories")
    result["has_repositories"] = _repos is not None
    return result


def _format_xml_snippet(element: str, children: list[tuple[str, str]]) -> str:
    """Format an XML snippet for proposal display."""
    lines = [f"<{element}>"]
    for tag, value in children:
        lines.append(f"  <{tag}>{value}</{tag}>")
    lines.append(f"</{element}>")
    return "\n".join(lines)


def _redact_xml_preserve_maven_urls(text: str) -> str:
    """Redact XML content while preserving Maven namespace/schema URLs
    and XML tag structure. Redacts filesystem paths, secrets, and
    private repository URLs but keeps Maven URL intact."""

    text = re.sub(
        r"(<project\.testresult\.directory>)(.*?)(</project\.testresult\.directory>)",
        r"\1[redacted-path]\3",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Redact common POSIX-file-like paths: /usr/, /home/, /tmp/, /opt/, /etc/, /dev/
    # but NOT inside URLs (preceded by ://)
    text = re.sub(
        r"(?<![:/A-Za-z0-9_-])/(?:usr|home|tmp|opt|etc|var|boot|root|dev|proc|sys|srv|mnt|media|run)/[^\s<>\"']*",
        "[redacted-path]",
        text,
    )

    # Redact file: prefixed paths like file:/dev/./urandom (Java security)
    text = re.sub(
        r"\bfile:/(?:usr|home|tmp|opt|etc|var|boot|root|dev|proc|sys|srv|mnt|media|run)/[^\s<>\"']*",
        "file:[redacted-path]",
        text,
    )

    # Redact secret-like XML elements â€” replace their content with [redacted]
    for tag in ("password", "secret", "token", "apiKey", "api_key"):
        text = re.sub(
            rf"<{tag}>[^<]*</{tag}>",
            f"<{tag}>[redacted]</{tag}>",
            text,
            flags=re.IGNORECASE,
        )

    # Redact private/internal repository URLs (but not central/maven)
    text = re.sub(
        r"<url>https?://[^<]*(?:private|internal|nexus|artifactory|token)[^<]*</url>",
        "<url>[redacted-private-repo]</url>",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _build_pom_change_proposal_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Build a governed POM change proposal from available evidence.

    If the question contains a specific property/dependency change request
    (e.g., "propose changing example.version to 1.2.3"), calls the
    PomDependencyEditor.propose_change() service to produce a real proposal
    with proposal_id, risk, control_mode, and can_apply.

    For vague requests ("propose pom changes"), produces a generic checklist.
    """
    # ── Detect specific property/dependency change and delegate to editor ──
    import re as _re
    lowered = str(question or "").lower()

    # Detect specific change: "propose changing/updating X to Y" (with : for GAV)
    specific_change = _re.search(
        r"(?:propose|suggest|draft|recommend).*?(?:chang|updat|upgrad|set|bump).*?(?:ing|e)?\s+"
        r"([\w.\-:]+)\s+(?:to|version|from)\s+([\d.]+(?:[\-.]?[\w]+)*)",
        lowered, _re.IGNORECASE,
    )
    if not specific_change:
        # Pattern: "update dependency GROUP:ARTIFACT to VERSION"
        specific_change = _re.search(
            r"(?:update|updat|chang|set|bump)\s+dependency\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            lowered, _re.IGNORECASE,
        )
    if not specific_change:
        # Pattern: "change X to Y" (artifact name or GAV)
        specific_change = _re.search(
            r"(?:chang(?:e|ing)?|updat(?:e|ing)?|upgrad(?:e|ing)?|set(?:ting)?|bump(?:ing)?)\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            lowered, _re.IGNORECASE,
        )

    # Resolve job_id from events/commands
    job_id = ""
    if events:
        for evt in events:
            jid = getattr(evt, "job_id", "") or ""
            if jid:
                job_id = str(jid)
                break
    if not job_id and commands:
        for cmd in commands:
            jid = getattr(cmd, "job_id", "") or ""
            if jid:
                job_id = str(jid)
                break

    # ── If specific change detected + job_id available, call editor ──
    if specific_change and job_id:
        try:
            editor = _build_pom_dependency_editor()
            proposal = editor.propose_change(
                job_id=job_id,
                user_request=question,
                idempotency_key=f"ask:{job_id}:{_bounded_event_text(question)[:40]}",
            )
            public = proposal.to_public_dict()
            lines: list[str] = []
            lines.append("## POM Change Proposal\n")
            lines.append(f"**Proposal ID:** `{public.get('proposal_id', '')}`")
            lines.append(f"**Status:** proposed (not applied)")
            lines.append(f"**Can Apply:** {public.get('can_apply', False)}")
            lines.append(f"**Risk:** {public.get('risk', 'unknown')}")
            lines.append(f"**Control Mode:** {public.get('control_mode', 'unknown')}")
            plan = public.get("server_validated_plan_preview", {})
            if plan:
                op = plan.get("operation", "")
                target = plan.get("target", {})
                lines.append(f"**Operation:** {op}")
                if target.get("property_name"):
                    lines.append(f"**Property:** `{target['property_name']}`")
                if target.get("group_id") and target.get("artifact_id"):
                    lines.append(f"**Artifact:** `{target['group_id']}:{target['artifact_id']}`")
                current = plan.get("current_version", "")
                requested = plan.get("requested_version", "")
                if current:
                    lines.append(f"**Current:** {current}")
                if requested:
                    lines.append(f"**Requested:** {requested}")
            lines.append(f"\nThis proposal has **not** been applied. "
                          f"Use the UI or ask me to apply it after human review.")
            return "\n".join(lines)
        except Exception as exc:
            # Fall through to generic answer if editor call fails
            return (
                f"I tried to create a proposal through the POM editor, but it failed: {exc}. "
                f"Please try again or use the Stage 3 Dependency Review panel."
            )

    # ── Generic proposal (no specific change detected) ──
    lines = []
    lines.append(
        "I cannot apply this directly, but I can draft a human-reviewable "
        "POM change proposal.\n"
    )

    # ── Resolve root_pom preview ──
    root_pom_preview: dict[str, Any] | None = None
    root_pom_exists = False
    if artifact_previews:
        for pv in artifact_previews:
            if pv.get("source_type") == "file_alias" and pv.get("artifact_kind") == "root_pom":
                root_pom_preview = pv
                root_pom_exists = bool(pv.get("exists"))
                break

    # ── Resolve other artifact previews for evidence ──
    available_artifact_kinds: list[str] = []
    if artifact_previews:
        for pv in artifact_previews:
            kind = pv.get("artifact_kind", "")
            if kind and kind not in available_artifact_kinds and pv.get("exists"):
                available_artifact_kinds.append(kind)
    event_artifact_kinds = _extract_artifact_kinds_list(events)
    all_evidence_kinds = sorted(set(available_artifact_kinds + event_artifact_kinds))

    # ── Extract POM summary ──
    pom_summary: dict[str, Any] | None = None
    if root_pom_preview and root_pom_exists:
        raw_preview = str(root_pom_preview.get("preview", ""))
        if raw_preview.strip():
            pom_summary = _extract_pom_summary(raw_preview)

    # ── Section 1: Proposed change ──
    lines.append("## 1. Proposed Change\n")

    if not root_pom_exists:
        reason = (
            str(root_pom_preview.get("reason", "not_available")).replace("_", " ")
            if root_pom_preview
            else "root_pom not resolved"
        )
        lines.append(
            f"The root pom.xml is not available yet (reason: {reason}). "
            "I can draft a generic migration checklist, but exact XML edits "
            "require backend evidence to be published first."
        )
        lines.append("")
        lines.append("### Generic safe preparation checklist (pending root_pom):")
        lines.append(
            "- Ensure a dependencyManagement section exists (or parent POM) "
            "to control transitive versions.\n"
            "- Align dependency versions to a single Spring Boot BOM.\n"
            "- Remove explicit version tags from Boot-managed dependencies.\n"
            "- Review javax.* → jakarta.* migration readiness."
        )
    elif pom_summary:
        props = pom_summary.get("properties", {})
        deps = pom_summary.get("dependencies", [])
        coords = pom_summary.get("coordinates", {})

        java_version = props.get("java.version", "")
        boot_version = props.get(
            "spring-boot.version",
            props.get("spring-boot-dependencies.version", ""),
        )
        spring_version = props.get("org.springframework.version", "")
        hibernate_version = props.get("hibernate.version", "")

        lines.append("### Preparation option (safe, current Spring Boot):")
        lines.append("")

        # Dependency management suggestion
        if not pom_summary.get("has_dependency_management") and not pom_summary.get("has_parent"):
            lines.append(
                "**Add dependencyManagement** to import `spring-boot-dependencies` "
                "BOM so that managed dependency versions are controlled centrally:"
            )
            lines.append("~~~xml")
            lines.append("<dependencyManagement>")
            lines.append("  <dependencies>")
            lines.append("    <dependency>")
            lines.append("      <groupId>org.springframework.boot</groupId>")
            lines.append("      <artifactId>spring-boot-dependencies</artifactId>")
            if boot_version:
                lines.append(f"      <version>${{spring-boot.version}}</version>")
            else:
                lines.append("      <version><!-- from plan/target_dependency_plan --></version>")
            lines.append("      <type>pom</type>")
            lines.append("      <scope>import</scope>")
            lines.append("    </dependency>")
            lines.append("  </dependencies>")
            lines.append("</dependencyManagement>")
            lines.append("~~~")
            lines.append("")

        if boot_version:
            lines.append(
                f"Current Spring Boot version: `{boot_version}`. "
            )
            lines.append(
                "**Align explicit versions** of Boot-managed dependencies "
                "to `${spring-boot.version}`. Remove the version tag from "
                "dependencies that are managed by the Boot BOM."
            )
            # Show specific dependencies with explicit versions
            boot_managed_prefixes = (
                "org.springframework.boot",
                "org.springframework",
                "org.hibernate",
                "com.fasterxml",
                "org.slf4j",
                "ch.qos.logback",
                "org.junit",
            )
            explicit_boot_deps = [
                d for d in deps
                if any(
                    d.get("groupId", "").startswith(pfx)
                    for pfx in boot_managed_prefixes
                )
                and d.get("version")
            ]
            if explicit_boot_deps:
                lines.append("")
                lines.append("Dependencies with explicit versions (candidates for BOM alignment):")
                for d in explicit_boot_deps[:8]:
                    lines.append(
                        f"- `{d.get('groupId')}:{d.get('artifactId')}` "
                        f"(current: `{d.get('version')}`)"
                    )
                if len(explicit_boot_deps) > 8:
                    lines.append(f"  ... and {len(explicit_boot_deps) - 8} more.")
            lines.append("")

        # Spring Boot 3 migration option
        lines.append("### Migration option (Spring Boot 3 target):")
        lines.append("")
        if java_version and java_version == "11":
            lines.append(
                "- **`java.version`**: change `11` → `17` (Spring Boot 3 requires Java 17)."
            )
        elif java_version:
            lines.append(
                f"- Current `java.version` is `{java_version}`. "
                "Spring Boot 3 requires Java 17 or later."
            )
        else:
            lines.append(
                "- **`java.version`**: Spring Boot 3 requires Java 17; "
                "ensure the property is set to 17."
            )

        if boot_version:
            lines.append(
                f"- **`spring-boot.version`**: change `{boot_version}` → "
                "target version from `target_dependency_plan` or approved migration plan."
            )
        else:
            lines.append(
                "- **`spring-boot.version`**: set to target Spring Boot 3.x version "
                "from `target_dependency_plan`."
            )

        # javax → jakarta migration candidates
        javax_deps = [
            d for d in deps
            if any(pfx in d.get("groupId", "").lower() for pfx in ("javax",))
            or any(pfx in d.get("artifactId", "").lower() for pfx in ("javax.servlet", "servlet-api", "javax.persistence"))
        ]
        if javax_deps:
            lines.append("")
            lines.append("**javax.* → jakarta.* migration candidates:**")
            javax_to_jakarta_map = {
                "javax.persistence": ("jakarta.persistence", "jakarta.persistence-api"),
                "javax.servlet": ("jakarta.servlet", "jakarta.servlet-api"),
                "javax.annotation": ("jakarta.annotation", "jakarta.annotation-api"),
                "javax.transaction": ("jakarta.transaction", "jakarta.transaction-api"),
                "javax.validation": ("jakarta.validation", "jakarta.validation-api"),
            }
            for d in javax_deps:
                gid = d.get("groupId", "")
                aid = d.get("artifactId", "")
                ver = d.get("version", "(managed)")
                # Find mapping
                mapped = None
                for javax_pfx, (jak_gid, jak_aid) in javax_to_jakarta_map.items():
                    if javax_pfx in gid.lower() or javax_pfx in aid.lower():
                        mapped = (jak_gid, jak_aid)
                        break
                if mapped:
                    lines.append(
                        f"  - `{gid}:{aid}` ({ver}) → `{mapped[0]}:{mapped[1]}`"
                    )
                else:
                    lines.append(
                        f"  - `{gid}:{aid}` ({ver}) → check jakarta equivalent"
                    )

        # Hibernate note
        if hibernate_version:
            lines.append("")
            lines.append(
                f"- **`hibernate.version`** (`{hibernate_version}`): "
                "Spring Boot 3 / Spring Framework 6 requires a compatible "
                "Hibernate 6.x with Jakarta namespace support. "
                "If managed by the Boot BOM, this is handled automatically; "
                "if explicit, update to a compatible version."
            )

        # Spring Aspects note
        if spring_version and "5.3" in spring_version:
            lines.append(
                f"- **Spring Framework `{spring_version}`**: Spring Boot 3 "
                "requires Spring Framework 6.x. Update `org.springframework.version` "
                "if set explicitly."
            )

        # Azure Service Bus note
        azure_deps = [
            d for d in deps
            if "azure" in d.get("groupId", "").lower()
            or "servicebus" in d.get("artifactId", "").lower()
        ]
        if azure_deps:
            lines.append("")
            lines.append("**Azure Service Bus compatibility check:**")
            for d in azure_deps:
                lines.append(
                    f"  - `{d.get('groupId')}:{d.get('artifactId')}` "
                    f"(`{d.get('version', 'managed')}`): verify Spring Boot 3 compatibility."
                )

        # Exact property edits
        lines.append("")
        lines.append("### Exact XML property edits (candidate snippets)")
        lines.append("")
        lines.append("~~~xml")
        lines.append("<properties>")
        if java_version == "11":
            lines.append("  <java.version>17</java.version>  <!-- was 11 -->")
        if boot_version:
            lines.append(
                f"  <spring-boot.version><!-- see target_dependency_plan --></spring-boot.version>"
                f"  <!-- was {boot_version} -->"
            )
        lines.append("</properties>")
        lines.append("~~~")
    else:
        lines.append(
            "The root pom.xml preview could not be parsed into structured fields. "
            "A generic preparation checklist follows."
        )
        lines.append("")
        lines.append("- Verify dependencyManagement or parent POM presence.")
        lines.append("- Align dependency versions to Spring Boot BOM.")
        lines.append("- Audit javax.* dependencies for jakarta migration.")
        lines.append("- Confirm Java 17+ readiness for Spring Boot 3.")

    # ── Section 2: Why ──
    lines.append("")
    lines.append("## 2. Why\n")
    lines.append(
        "Aligning dependencies to a managed BOM reduces version conflicts, "
        "transitive dependency drift, and build reproducibility risks. "
        "Spring Boot 3 migration is a structural upgrade that improves "
        "security support, JDK 17+ compatibility, and Jakarta namespace alignment."
    )

    # ── Section 3: Risk ──
    lines.append("")
    lines.append("## 3. Risk\n")

    has_javax = pom_summary and any(
        "javax" in d.get("groupId", "").lower()
        or "servlet-api" in d.get("artifactId", "").lower()
        or "javax.persistence" in d.get("artifactId", "").lower()
        for d in pom_summary.get("dependencies", [])
    ) if pom_summary else False

    java11 = pom_summary and pom_summary.get("properties", {}).get("java.version") == "11" if pom_summary else False

    if java11 or has_javax:
        lines.append(
            "**Medium/High** — Spring Boot 3 requires Java 17 and Jakarta "
            "namespace migration. Source imports, transitive dependency chains, "
            "and annotation processors may break. Backend build/test validation "
            "is required before acceptance."
        )
    else:
        lines.append(
            "**Low/Medium** — Dependency version alignment through BOM "
            "management is generally safe if the target versions are tested. "
            "Backend build validation is still required."
        )
    lines.append(
        "- Compatibility: verify `mvn dependency:tree` after change.\n"
        "- Breaking changes: Spring Boot 3 removes deprecated APIs; "
        "`javax.*` → `jakarta.*` migration requires source changes."
    )

    # ── Section 4: Evidence to review ──
    lines.append("")
    lines.append("## 4. Evidence to Review\n")
    evidence_artifacts = [
        k for k in all_evidence_kinds
        if k in (
            "root_pom", "target_dependency_plan", "rewrite_preview.json",
            "rewrite_dry_run.patch", "rewrite_plugin_plan.json",
            "plan_validation_report.json", "dependency_graph.json",
            "dependency_policy_report", "dependency_policy_summary",
            "migration_plan.yaml", "migration_units.yaml",
            "repair_ledger", "migration_ledger",
        )
    ]
    if evidence_artifacts:
        lines.append("Available evidence artifacts to justify or verify the proposal:")
        for k in evidence_artifacts:
            lines.append(f"- `{k}`")
    else:
        lines.append(
            "No evidence artifacts are currently available. "
            "A meaningful proposal requires at minimum `root_pom` "
            "and ideally `target_dependency_plan` or `migration_plan.yaml`."
        )
    lines.append(
        "\nThe operator should review these artifacts before approving any change."
    )

    # ── Section 5: Approval / gate ──
    lines.append("")
    lines.append("## 5. Approval / Gate\n")
    lines.append(
        "This proposal is a draft only. To proceed:\n\n"
        "1. **Human** reviews and approves the proposed changes.\n"
        "2. **Backend** creates a governed repair/proposal with checksum.\n"
        "3. **Backend** applies the patch in the sandbox.\n"
        "4. **Backend** runs `mvn build` and `mvn test` validation.\n"
        "5. **Proof gate** confirms build/test pass before the change is accepted.\n"
        "6. No deployment, stage change, or approval bypass is possible "
        "through this chat interface."
    )

    # ── Section 6: Not applied ──
    lines.append("")
    lines.append("## 6. Not Applied\n")
    lines.append(
        "No file was written, no command was executed, no stage was changed, "
        "and no patch was applied by this chat. "
        "This is a human-reviewable proposal only. "
        "All execution remains backend-owned and human-gated."
    )

    answer = "\n".join(lines)
    # Apply redactions but preserve code blocks (no raw prompt redaction)
    from migration_factory.control_tower.application.redaction import (
        redact_absolute_paths,
        redact_deployment_identifiers,
        redact_secret_keys,
    )
    redacted = answer
    redacted = redact_absolute_paths(redacted)
    redacted = redact_secret_keys(redacted)
    redacted = redact_deployment_identifiers(redacted)
    return redacted


# ── Stage 3 helpers ──────────────────────────────────────────────────


def _detect_stage3_baseline(
    pom_summary: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Detect Java and Spring Boot baseline from Stage 3 POM summary and evidence.

    Detection priority:
    1. root_pom parent spring-boot-starter-parent version
    2. root_pom dependencyManagement spring-boot-dependencies BOM version
    3. root_pom property spring-boot.version
    4. target_dependency_plan / migration_plan.yaml / dependency_graph
    """
    props = pom_summary.get("properties", {})
    deps = pom_summary.get("dependencies", [])
    parent_info = pom_summary.get("parent", {}) if isinstance(pom_summary.get("parent"), dict) else {}
    dm_boms = pom_summary.get("dependency_management_boms", []) if isinstance(pom_summary.get("dependency_management_boms"), list) else []

    java_version = props.get("java.version", "")
    spring_boot_version = ""
    spring_boot_source = "unknown"
    has_spring_boot_bom = False
    has_spring_boot_parent = False
    spring_framework_version = props.get(
        "spring-framework.version",
        props.get("spring.framework.version", props.get("org.springframework.version", "")),
    )

    # 1. Check parent for spring-boot-starter-parent
    parent_version = parent_info.get("version", "")
    if "spring-boot-starter-parent" in parent_info.get("artifactId", ""):
        has_spring_boot_parent = True
        if parent_version:
            spring_boot_version = parent_version
            spring_boot_source = "parent"

    # 2. Check dependencyManagement BOM imports
    for bom in dm_boms:
        if "spring-boot-dependencies" in bom.get("artifactId", ""):
            has_spring_boot_bom = True
            if not spring_boot_version and bom.get("version"):
                spring_boot_version = bom["version"]
                spring_boot_source = "dependency_management_bom"
            break

    # Also scan raw deps for BOM import
    if not spring_boot_version:
        for d in deps:
            if "spring-boot-dependencies" in d.get("artifactId", ""):
                has_spring_boot_bom = True
                if d.get("version"):
                    spring_boot_version = d["version"]
                    spring_boot_source = "dependency_management_bom"
                    break

    # 3. Check property
    if not spring_boot_version:
        sb_prop = props.get("spring-boot.version", props.get("spring-boot-dependencies.version", ""))
        if sb_prop:
            spring_boot_version = sb_prop
            spring_boot_source = "property"

    # 4. Check evidence artifacts
    evidence_data = evidence or {}
    if not spring_boot_version:
        tdp = evidence_data.get("target_dependency_plan", {})
        if isinstance(tdp, dict) and tdp.get("spring_boot_version"):
            spring_boot_version = str(tdp["spring_boot_version"])
            spring_boot_source = "target_dependency_plan"
    if not spring_boot_version:
        mp = evidence_data.get("migration_plan", {})
        if isinstance(mp, dict) and mp.get("target_spring_boot_version"):
            spring_boot_version = str(mp["target_spring_boot_version"])
            spring_boot_source = "migration_plan"

    # Spring Framework version - only trust explicit properties
    if spring_framework_version and spring_boot_version and not spring_boot_source.startswith("property"):
        # If there's a dedicated spring-boot.version property and org.springframework.version, prefer boot
        # Only mark spring_framework_version as weak if it was found via org.springframework.version
        pass  # Keep as-is from property extraction

    baseline_confirmed = bool(java_version and spring_boot_version)
    missing = []
    if not java_version:
        missing.append("java.version")
    if not spring_boot_version:
        missing.append("spring_boot_version")

    return {
        "java_version": java_version or "unknown",
        "spring_boot_version": spring_boot_version or "unknown",
        "spring_boot_source": spring_boot_source,
        "has_spring_boot_bom": has_spring_boot_bom,
        "has_spring_boot_parent": has_spring_boot_parent,
        "spring_framework_version": spring_framework_version or "unknown",
        "baseline_confirmed": baseline_confirmed,
        "missing": missing,
    }


def _classify_stage3_dependencies(
    pom_summary: dict[str, Any],
    baseline: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify dependencies into buckets for Stage 3 review.

    Buckets:
    A. boot_managed â€” dependencies normally managed by Spring Boot BOM/parent
    B. jakarta_platform â€” javax.* dependencies (may need migration)
    C. app_specific_third_party â€” not controlled by Boot/OpenRewrite
    D. build_plugins â€” Maven plugins
    E. transitive_or_bom_managed_risk â€” requests for transitive deps
    """
    deps = pom_summary.get("dependencies", [])
    plugins = pom_summary.get("plugins", [])
    props = pom_summary.get("properties", {})

    boot_managed_prefixes = (
        "org.springframework.boot",
        "org.springframework",
        "org.hibernate.validator",
        "com.fasterxml",
        "org.slf4j",
        "ch.qos.logback",
    )
    boot_managed_artifacts = (
        "spring-boot-starter",
        "hibernate-core",
        "tomcat-embed",
        "jackson-",
        "slf4j-",
        "logback-",
        "assertj-core",
        "junit-jupiter",
        "mockito-",
    )

    app_specific_ga = (
        ("org.zalando", "problem-spring-web"),
        ("com.microsoft.azure", "azure-servicebus"),
        ("com.microsoft.azure", "azure-servicebus-spring-boot-starter"),
        ("org.apache.juneau", ""),
        ("io.jsonwebtoken", ""),
        ("com.google.code.gson", "gson"),
        ("org.modelmapper", "modelmapper"),
        ("org.projectlombok", "lombok"),
        ("org.assertj", "assertj-core"),
    )

    boot_managed: list[dict[str, str]] = []
    jakarta_platform: list[dict[str, str]] = []
    app_specific: list[dict[str, str]] = []
    build_plugins_list: list[dict[str, str]] = []

    for d in deps:
        gid = d.get("groupId", "")
        aid = d.get("artifactId", "")

        # B. javax â†’ jakarta check
        if "javax." in gid or any(
            aid.startswith(pfx)
            for pfx in ("javax.servlet", "javax.persistence", "javax.annotation", "javax.validation")
        ):
            jakarta_platform.append(d)
            continue

        # A. Boot-managed check
        if any(gid.startswith(pfx) for pfx in boot_managed_prefixes):
            boot_managed.append(d)
            continue
        if any(pfx in aid for pfx in boot_managed_artifacts):
            boot_managed.append(d)
            continue

        # C. App-specific check
        is_app_specific = False
        for ag_gid, ag_aid in app_specific_ga:
            if (ag_gid == gid or (ag_gid and gid and ag_gid in gid)) and (
                not ag_aid or ag_aid in aid
            ):
                app_specific.append(d)
                is_app_specific = True
                break
        if is_app_specific:
            continue

        # Default: if not recognized, put in app_specific
        app_specific.append(d)

    for p in plugins:
        build_plugins_list.append(p)

    return {
        "boot_managed": boot_managed,
        "jakarta_platform": jakarta_platform,
        "app_specific_third_party": app_specific,
        "build_plugins": build_plugins_list,
        "transitive_or_bom_managed_risk": [],  # populated during review
    }


def _build_apply_dependency_change_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Build an answer for apply_dependency_change intent.

    Routes through the same PomDependencyEditor service path as the UI.
    Actually applies the change to the Stage 3 sandbox and returns
    the result from PomApplyResult.
    """

    job_id = _resolve_assistant_job_id(events=events, commands=commands)

    if not job_id:
        return (
            "I cannot apply this change because I cannot determine which job "
            "to target. Please navigate to a migration job first."
        )

    # ── Parse the target from the question ──
    dep_name = ""
    target_version = ""
    is_property_update = False
    q = str(question or "")

    # Pattern 1: "apply this ... update dependency GROUP:ARTIFACT to VERSION" (GAV with colon)
    gav_apply_dep_match = re.search(
        r"(?:apply|execute|write).*?(?:update|change|set|bump)\s+dependency\s+([\w.\-]+):([\w.\-]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
        q, re.IGNORECASE,
    )
    if gav_apply_dep_match:
        dep_name = f"{gav_apply_dep_match.group(1)}:{gav_apply_dep_match.group(2)}"
        target_version = gav_apply_dep_match.group(3).strip().rstrip(".,;:")

    # Pattern 2: "update dependency GROUP:ARTIFACT to VERSION" (GAV with colon, no apply prefix)
    if not dep_name or not target_version:
        gav_dep_match = re.search(
            r"(?:update|change|set|bump|upgrade)\s+dependency\s+([\w.\-]+):([\w.\-]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if gav_dep_match:
            dep_name = f"{gav_dep_match.group(1)}:{gav_dep_match.group(2)}"
            target_version = gav_dep_match.group(3).strip().rstrip(".,;:")

    # Pattern 3: "change dependency GROUP:ARTIFACT to VERSION"
    if not dep_name or not target_version:
        gav_change_dep_match = re.search(
            r"(?:change|update|set)\s+dependency\s+([\w.\-]+):([\w.\-]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if gav_change_dep_match:
            dep_name = f"{gav_change_dep_match.group(1)}:{gav_change_dep_match.group(2)}"
            target_version = gav_change_dep_match.group(3).strip().rstrip(".,;:")

    # Pattern 4: Generic "update/change GROUP:ARTIFACT to VERSION" (single word before colon)
    if not dep_name or not target_version:
        update_match = re.search(
            r"(?:update|upgrade|change|set|bump|replace)\s+([\w.\-]+):([\w.\-]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if update_match:
            dep_name = f"{update_match.group(1)}:{update_match.group(2)}"
            target_version = update_match.group(3).strip().rstrip(".,;:")

    # Pattern 5: Generic "update X to Y" (artifact without colon)
    if not dep_name or not target_version:
        update_match = re.search(
            r"(?:update|upgrade|change|set|bump|replace)\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if update_match:
            dep_name = update_match.group(1).strip()
            target_version = update_match.group(2).strip().rstrip(".,;:")

    # Pattern 6: "update property X to Y" or "update X.version to Y"
    if not dep_name or not target_version:
        prop_match = re.search(
            r"(?:update|change|set|bump)\s+property\s+([\w.\-]+(?:\.[\w.\-]+)?)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if prop_match:
            dep_name = prop_match.group(1).strip()
            target_version = prop_match.group(2).strip().rstrip(".,;:")
            is_property_update = True

    # Pattern 7: "update X.version to Y.Z"
    if not dep_name or not target_version:
        dot_ver_match = re.search(
            r"(?:update|change|set|bump)\s+([\w.\-]+)\.version\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if dot_ver_match:
            dep_name = dot_ver_match.group(1).strip() + ".version"
            target_version = dot_ver_match.group(2).strip().rstrip(".,;:")
            is_property_update = True

    # Pattern 8: "apply this ... change: update property X to Y"
    if not dep_name or not target_version:
        apply_prop_match = re.search(
            r"apply.*?change.*?(?:update|change|set)\s+(?:property\s+)?([\w.\-]+(?:\.[\w.\-]+)?)\s+(?:to|version)\s+([\d.]+(?:[\-.]?[\w]+)*)",
            q, re.IGNORECASE,
        )
        if apply_prop_match:
            dep_name = apply_prop_match.group(1).strip()
            target_version = apply_prop_match.group(2).strip().rstrip(".,;:")
            if "version" in apply_prop_match.group(0).lower():
                is_property_update = True

    if not dep_name or not target_version:
        return (
            "I need a specific dependency name and target version to apply a change. "
            'For example: "apply change library-name to 1.2.3" or "update dependency com.example:library-name to 1.2.3".'
        )

    # Route through the same PomDependencyEditor service path as UI
    try:
        editor = _build_pom_dependency_editor()
        idempotency_key = _assistant_action_idempotency_key(
            "apply_dependency_change", job_id, question
        )
        result = editor.apply_change_from_user_request(
            job_id=job_id,
            user_request=question,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        return (
            f"Backend could not apply the change: {e}. "
            "Please try again or use the Stage 3 Dependency Review panel."
        )

    if result.status == "blocked":
        card = AssistantResponseCard(
            headline="Change blocked safely",
            status="blocked",
            summary="The backend refused to apply this change.",
            sections=(
                AssistantResponseSection(title="Reason", lines=(result.message,)),
            ),
            safety_note=(
                "Ask for a proposal instead of a direct apply:\n"
                '"Explain how Tomcat is managed and propose whether a Tomcat override is needed."'
            ),
        )
        return _ASSISTANT_RESPONSE_COMPOSER.render(card)

    if result.status == "noop":
        lines = [
            "## POM change not applied",
            f"**{result.message}**",
            f"- **Operation:** {result.operation}",
            f"- **Target:** {result.target_desc}",
        ]
        if result.before_version:
            lines.append(f"- **Current:** {result.before_version}")
        lines.append(f"- **Requested:** {result.after_version}")
        lines.append("- **Status:** noop")
        return "\n".join(lines)

    if result.status == "error":
        return (
            f"The backend could not apply this change: {result.message}\n\n"
            "Please check the Stage 3 sandbox is available and try again."
        )

    card = AssistantResponseCard(
        headline="POM change applied",
        status="done",
        summary="The change was written to the Stage 3 sandbox.",
        sections=(
            AssistantResponseSection(
                title="Change",
                lines=(
                    f"Operation: {result.operation}",
                    f"Target: {result.target_desc}",
                    f"Before: {result.before_version}" if result.before_version else "",
                    f"After: {result.after_version}",
                    f"Change ID: `{result.change_id}`",
                ),
            ),
            AssistantResponseSection(
                title="Validation",
                lines=(
                    "Status: running",
                    f"Result: {result.status}",
                    f"Validation ID: `{result.validation_id}`" if result.validation_id else "",
                    "Rollback: available" if result.rollback_available else "",
                ),
            ),
        ),
        next_step="Open Stage 3 Dependency Review to inspect validation results.",
    )
    return _ASSISTANT_RESPONSE_COMPOSER.render(card)


def _assistant_action_idempotency_key(action: str, job_id: str, question: str) -> str:
    canonical = re.sub(r"\s+", " ", str(question or "").strip().lower())
    digest = hashlib.sha256(f"{action}:{job_id}:{canonical}".encode("utf-8")).hexdigest()[:24]
    return f"ask:{action}:{job_id}:{digest}"


def _resolve_assistant_job_id(*, events: tuple[Any, ...], commands: tuple[Any, ...]) -> str:
    for evt in events:
        jid = getattr(evt, "job_id", "") or ""
        if jid:
            return str(jid)
    for cmd in commands:
        jid = getattr(cmd, "job_id", "") or ""
        if jid:
            return str(jid)
    return ""


def _build_rollback_pom_change_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Build an answer for rollback_pom_change intent through PomDependencyEditor."""
    job_id = _resolve_assistant_job_id(events=events, commands=commands)
    if not job_id:
        return (
            "I cannot rollback a Stage 3 POM change because I cannot determine "
            "which job to target. Please navigate to a migration job first."
        )

    try:
        editor = _build_pom_dependency_editor()
        changes = editor.list_changes(job_id)
    except Exception as exc:
        return (
            f"Backend could not inspect Stage 3 POM changes: {exc}. "
            "Please try again or use the Stage 3 Dependency Review panel."
        )

    rollback_candidates = [
        change for change in changes
        if str(getattr(change, "status", "")) in {
            "applied_pending_validation",
            "validation_running",
            "validated_passed",
            "validated_failed",
            "repair_applied",
        }
        and not getattr(change, "rollback_id", None)
        and str(getattr(change, "change_id", ""))
    ]
    if not rollback_candidates:
        return "No applied Stage 3 POM change found to rollback."

    rollback_candidates.sort(key=lambda c: str(getattr(c, "created_at", "")))
    change_id = str(getattr(rollback_candidates[-1], "change_id", ""))
    try:
        result = editor.rollback_change(
            job_id,
            change_id,
            _assistant_action_idempotency_key("rollback_pom_change", job_id, change_id),
        )
    except Exception as exc:
        return (
            f"Backend could not rollback the Stage 3 POM change: {exc}. "
            "Please try again or use the Stage 3 Dependency Review panel."
        )

    if result.status != "rolled_back":
        return (
            f"Stage 3 POM rollback did not complete. Status: {result.status}. "
            f"Checksum restored: {result.checksum_restored}."
        )

    card = AssistantResponseCard(
        headline="POM change rolled back",
        status="done",
        summary="The Stage 3 sandbox has been restored.",
        sections=(
            AssistantResponseSection(
                title="Change",
                lines=(
                    f"Change ID: `{result.change_id}`",
                    f"Rollback ID: `{result.rollback_id}`",
                ),
            ),
            AssistantResponseSection(
                title="Status",
                lines=(
                    f"**Checksum restored:** {result.checksum_restored}",
                    f"Status: {result.status}",
                ),
            ),
        ),
    )
    return _ASSISTANT_RESPONSE_COMPOSER.render(card)


def _build_pom_validation_result_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Return validation status from F14 backend validation records."""
    job_id = _resolve_assistant_job_id(events=events, commands=commands)
    if not job_id:
        return "I cannot look up validation because I cannot determine the migration job."

    try:
        editor = _build_pom_dependency_editor()
        changes = [
            change for change in editor.list_changes(job_id)
            if getattr(change, "validation_id", None)
        ]
    except Exception as exc:
        return f"Backend could not inspect Stage 3 POM validation records: {exc}."

    if not changes:
        return "No Stage 3 POM validation record found for this job."

    changes.sort(key=lambda c: str(getattr(c, "created_at", "")))
    latest = changes[-1]
    validation_id = str(getattr(latest, "validation_id", "") or "")
    try:
        result = editor.get_validation_result(job_id, validation_id)
    except Exception as exc:
        return f"Backend could not load Stage 3 POM validation `{validation_id}`: {exc}."

    if result is None:
        return f"No backend validation record found for `{validation_id}`."

    card = AssistantResponseCard(
        headline="Stage 3 POM validation result",
        status="info",
        summary=f"Build: {result.build_status} | Tests: {result.test_status}",
        sections=(
            AssistantResponseSection(
                title="Validation",
                lines=(
                    f"Change ID: `{result.change_id}`",
                    f"Validation ID: `{result.validation_id}`",
                    f"**Status:** {result.status}",
                    f"Exit code: {result.exit_code}" if result.exit_code is not None else "",
                ),
            ),
            AssistantResponseSection(
                title="Reason",
                lines=(
                    f"Diagnosis: {result.diagnosis.failure_classification}" if result.diagnosis else "",
                    "Evidence: evidence_insufficient"
                    if result.diagnosis and result.diagnosis.failure_classification == "evidence_insufficient"
                    else "",
                    f"Log ref: {result.log_ref}" if result.log_ref else "",
                ),
            ),
        ),
    )
    return _ASSISTANT_RESPONSE_COMPOSER.render(card)


def _build_pom_dependency_change_request_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Build a governed dependency change request for an explicit single dependency edit.

    Examples: 'Update library-name to 1.2.3', 'Change server-runtime to 4.5.6 at stage 3'
    Produces exact before/after XML, risk, evidence, and approval path.
    """
    lines: list[str] = []
    lines.append(
        "I cannot apply this directly, but I can draft a human-reviewable "
        "dependency change request.\n"
    )

    # ── Resolve root_pom preview ──
    root_pom_preview: dict[str, Any] | None = None
    root_pom_exists = False
    requested_stage = (
        _get_requested_stage(question, "pom_dependency_change_request")
        or _default_stage_when_stage3_complete(events)
        or 1
    )
    if artifact_previews:
        for pv in artifact_previews:
            if pv.get("source_type") == "file_alias" and pv.get("artifact_kind") == "root_pom":
                root_pom_preview = pv
                root_pom_exists = bool(pv.get("exists"))
                break

    pom_summary: dict[str, Any] | None = None
    if root_pom_preview and root_pom_exists:
        raw_preview = str(root_pom_preview.get("preview", ""))
        if raw_preview.strip():
            pom_summary = _extract_pom_summary(raw_preview)

    # ── Parse target dependency/property from question ──
    # Patterns: "update library-name to 1.2.3", "change server-runtime to 4.5.6"
    # Also: "update property example.version to 1.2.3"
    dep_name = ""
    target_version = ""
    is_property_update = False
    update_match = re.search(
        r"(?:update|upgrade|change|set|bump|replace)\s+([\w.\-:]+)\s+(?:to|version)\s+([\d.]+)",
        str(question or ""), re.IGNORECASE,
    )
    if update_match:
        dep_name = update_match.group(1).strip()
        target_version = update_match.group(2).strip()

    # Try property patterns
    if not dep_name or not target_version:
        prop_match = re.search(
            r"(?:update|change|set|bump)\s+property\s+([\w.\-]+(?:\.[\w.\-]+)?)\s+(?:to|version)\s+([\d.]+)",
            str(question or ""), re.IGNORECASE,
        )
        if prop_match:
            dep_name = prop_match.group(1).strip()
            target_version = prop_match.group(2).strip()
            is_property_update = True

    # Try X.version to Y.Z pattern
    if not dep_name or not target_version:
        dot_ver_match = re.search(
            r"(?:update|change|set|bump)\s+([\w.\-]+)\.version\s+(?:to|version)\s+([\d.]+)",
            str(question or ""), re.IGNORECASE,
        )
        if dot_ver_match:
            dep_name = dot_ver_match.group(1).strip() + ".version"
            target_version = dot_ver_match.group(2).strip()
            is_property_update = True

    if not dep_name and not target_version:
        # Fallback: try to find dependency name
        dep_match = re.search(
            r"(?:update|upgrade|change)\s+(?:dependency|version of)\s+([\w.\-:]+)",
            str(question or ""), re.IGNORECASE,
        )
        if dep_match:
            dep_name = dep_match.group(1).strip()

    # ── Detect if dependency is transitive/BOM-managed ──
    is_transitive = False
    found_dep: dict[str, str] | None = None
    if pom_summary and (dep_name or target_version):
        deps = pom_summary.get("dependencies", [])
        search_id = dep_name.lower()
        for d in deps:
            aid = d.get("artifactId", "").lower()
            gid = d.get("groupId", "").lower()
            if search_id in aid or search_id in gid or search_id in f"{gid}:{aid}":
                found_dep = d
                break
        if not found_dep and dep_name:
            # Dependency not found in POM — likely transitive
            is_transitive = True

    # ── Section 1: Proposed Change ──
    lines.append("## 1. Proposed Change\n")

    # ── Property update path ──
    if is_property_update and pom_summary:
        props = pom_summary.get("properties", {})
        current_ver = props.get(dep_name, "unknown")
        lines.append(f"**Property:** `{dep_name}` currently `{current_ver}` in Stage {requested_stage} root_pom.\n")
        if target_version:
            lines.append(f"**Requested change:** `{current_ver}` → `{target_version}`\n")
            lines.append("**Exact XML edit:**\n")
            lines.append("~~~xml")
            lines.append("<!-- Before -->")
            lines.append(f"<{dep_name}>{current_ver}</{dep_name}>")
            lines.append("")
            lines.append("<!-- After -->")
            lines.append(f"<{dep_name}>{target_version}</{dep_name}>")
            lines.append("~~~\n")

        # Risk
        lines.append("## 2. Risk\n")
        lines.append("- **Risk Level:** Low")
        lines.append("- **Scope:** Single property update in `<properties>` section")
        lines.append("- **Impact:** Changes version of dependencies/sub-modules that reference this property")
        lines.append("- **Rollback:** Simple version downgrade if needed\n")

        # Evidence
        lines.append("## 3. Evidence\n")
        lines.append("- Stage {stage} root pom.xml\n".format(stage=requested_stage))

        # Approval
        lines.append("## 4. Required Approval\n")
        lines.append("- Human review required before apply")
        lines.append("- Patch gate: checksum verification before write")
        lines.append("- Built-in rollback capability\n")

        # Closing
        lines.append("## 5. Next Steps\n")
        lines.append("- This change is NOT applied. It must be reviewed first.")
        lines.append("- Use the \"Apply\" button in the Stage 3 Dependency Review panel or say \"apply this change\" to proceed.")
        lines.append("- Or respond with \"reject\" to discard.\n")
        lines.append("**Status:** Proposed (NOT applied). Requires human approval.")
        return "\n".join(lines)

    if not root_pom_exists and not pom_summary:
        reason = (
            str(root_pom_preview.get("reason", "not_available")).replace("_", " ")
            if root_pom_preview
            else "root_pom not resolved"
        )
        lines.append(
            f"The root pom.xml is not available yet (reason: {reason}). "
            "I need the root_pom to draft an exact dependency change."
        )
    elif is_transitive:
        lines.append(
            f"No direct `{dep_name}` dependency was found in the root pom.xml. "
            f"This artifact is likely **managed transitively** by Spring Boot "
            f"starter or BOM.\n\n"
            f"**Recommendation:** Do not inject a direct dependency unless "
            f"`dependency_policy_report` or `dependency_graph` evidence "
            f"shows an effective dependency version conflict that requires "
            f"a managed override.\n\n"
            f"If a managed override is needed, add a `<dependencyManagement>` "
            f"entry with the desired version instead of a direct dependency."
        )
    elif found_dep:
        gid = found_dep.get("groupId", "?")
        aid = found_dep.get("artifactId", "?")
        current_ver = found_dep.get("version", "(managed)")
        scope = found_dep.get("scope", "")
        scope_note = f" [{scope}]" if scope and scope != "compile" else ""

        lines.append(f"**Current match:** `{gid}:{aid}` currently uses `{current_ver}`{scope_note} in Stage {requested_stage} root_pom.\n")
        if target_version:
            lines.append(f"**Requested change:** `{current_ver}` → `{target_version}`\n")
            lines.append("**Exact XML edit:**\n")
            lines.append("~~~xml")
            lines.append("<!-- Before -->")
            lines.append(f"<dependency>")
            lines.append(f"  <groupId>{gid}</groupId>")
            lines.append(f"  <artifactId>{aid}</artifactId>")
            lines.append(f"  <version>{current_ver}</version>")
            if scope:
                lines.append(f"  <scope>{scope}</scope>")
            lines.append(f"</dependency>")
            lines.append("")
            lines.append("<!-- After -->")
            lines.append(f"<dependency>")
            lines.append(f"  <groupId>{gid}</groupId>")
            lines.append(f"  <artifactId>{aid}</artifactId>")
            lines.append(f"  <version>{target_version}</version>")
            if scope:
                lines.append(f"  <scope>{scope}</scope>")
            lines.append(f"</dependency>")
            lines.append("~~~\n")
            lines.append(
                f"**Candidate backend action:** OpenRewrite `UpgradeDependencyVersion` "
                f"configured with `groupId={gid}`, `artifactId={aid}`, `newVersion={target_version}`."
            )
        else:
            lines.append(
                "I need a target version to propose an exact change. "
                "Please specify the target version or provide evidence from "
                "`target_dependency_plan` or `dependency_policy_report`."
            )
    else:
        lines.append(
            "I found the root pom.xml but could not identify a matching dependency. "
            "Please check the exact dependency groupId and artifactId."
        )

    # ── Section 2: Risk ──
    lines.append("")
    lines.append("## 2. Risk\n")
    if is_transitive:
        lines.append(
            "**Medium** — Adding a direct transitive dependency can create version conflicts "
            "and override BOM-managed versions. Backend build/test validation is required."
        )
    elif found_dep and target_version:
        lines.append(
            "**Low/Medium** — A direct dependency version change may affect transitive "
            "dependency resolution. Backend `mvn dependency:tree` and build/test "
            "validation are required before acceptance."
        )
    else:
        lines.append("Risk cannot be assessed without a specific dependency match.")

    # ── Section 3: Evidence ──
    lines.append("")
    lines.append("## 3. Evidence\n")
    available_artifact_kinds: list[str] = []
    if artifact_previews:
        for pv in artifact_previews:
            kind = pv.get("artifact_kind", "")
            if kind and kind not in available_artifact_kinds and pv.get("exists"):
                available_artifact_kinds.append(kind)
    event_artifact_kinds = _extract_artifact_kinds_list(events)
    all_kinds = sorted(set(available_artifact_kinds + event_artifact_kinds))
    evidence_items = [k for k in all_kinds if k in (
        "root_pom", "target_dependency_plan", "dependency_policy_report",
        "dependency_graph", "dependency_policy_summary", "rewrite_preview.json",
        "migration_plan.yaml",
    )]
    if evidence_items:
        lines.append("Available evidence to justify the change:")
        for k in evidence_items:
            lines.append(f"- `{k}`")
    else:
        lines.append("No dependency evidence artifacts are currently available.")

    # ── Section 4: Approval ──
    lines.append("")
    lines.append("## 4. Approval\n")
    lines.append(
        "This is a draft dependency change request. To proceed:\n\n"
        "1. **Human** reviews and approves the exact before/after change.\n"
        "2. **Backend** creates a governed repair/proposal with checksum.\n"
        "3. **Backend** applies the patch in the sandbox.\n"
        "4. **Backend** validates with build and test.\n"
        "5. **Proof gate** confirms acceptance before the change is final."
    )

    # ── Section 5: Not Applied ──
    lines.append("")
    lines.append("## 5. Not Applied\n")
    lines.append(
        "No file was written, no command was executed, no stage was changed, "
        "and no patch was applied by this chat. "
        "This is a human-reviewable change request only."
    )

    answer = "\n".join(lines)
    from migration_factory.control_tower.application.redaction import (
        redact_absolute_paths,
        redact_deployment_identifiers,
        redact_secret_keys,
    )
    redacted = answer
    redacted = redact_absolute_paths(redacted)
    redacted = redact_secret_keys(redacted)
    redacted = redact_deployment_identifiers(redacted)
    return redacted


def _build_stage3_dependency_review_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    approvals: tuple[Any, ...] = (),
    commands: tuple[Any, ...] = (),
) -> str:
    """Build a Stage 3 dependency modernization review.

    Detects baseline from Stage 3 root_pom/evidence, buckets dependencies,
    proposes evidence-backed changes, and lists policy decisions needed.
    """
    lines: list[str] = []

    # ── Determine requested stage ──
    requested_stage = _get_requested_stage(question, "stage3_dependency_review") or 3

    # ── Resolve root_pom preview ──
    root_pom_preview: dict[str, Any] | None = None
    root_pom_exists = False
    stage_of_preview = 1
    if artifact_previews:
        for pv in artifact_previews:
            if pv.get("source_type") == "file_alias" and pv.get("artifact_kind") == "root_pom":
                root_pom_preview = pv
                root_pom_exists = bool(pv.get("exists"))
                stage_of_preview = int(pv.get("stage_index", 1) or 1)
                break

    # ── Check if Stage 3 review is allowed ──
    allowed, reason = _is_final_dependency_review_allowed(
        stage_index=requested_stage if root_pom_exists else stage_of_preview,
        root_pom_preview=root_pom_preview,
        events=events,
    )

    # ── If not Stage 3 (or stage 1/2), defer final recommendations ──
    if requested_stage in (1, 2) and not allowed:
        return _build_stage1_or_2_deferred_dependency_answer(
            requested_stage=requested_stage,
            root_pom_preview=root_pom_preview,
            events=events,
        )

    if root_pom_exists and not allowed:
        reason_text = str(reason or "not_available").replace("_", " ")
        lines.append(
            f"I cannot confirm the Stage 3 baseline yet. "
            f"Stage 3 root_pom is available, but final dependency review is not stable "
            f"(reason: {reason_text}). "
            "Please wait for the backend validation/stage activity to finish."
        )
        return "\n".join(lines)

    if not root_pom_exists:
        reason_text = str(root_pom_preview.get("reason", "not_available")).replace("_", " ") if root_pom_preview else "not_available"
        lines.append(
            f"I cannot confirm the Stage 3 baseline yet. "
            f"Stage 3 root_pom is not available (reason: {reason_text}). "
            "Please wait for the backend to complete Stage 3 transformation "
            "and publish root_pom evidence."
        )
        return "\n".join(lines)

    # ── Extract POM summary and detect baseline ──
    raw_preview = str(root_pom_preview.get("preview", ""))
    pom_summary: dict[str, Any] | None = None
    baseline: dict[str, Any] = {}
    if raw_preview.strip():
        pom_summary = _extract_pom_summary(raw_preview)
        baseline = _detect_stage3_baseline(pom_summary)

    if not pom_summary:
        lines.append(
            "The Stage 3 root pom.xml could not be parsed into structured fields. "
            "Cannot perform dependency review without a parseable POM."
        )
        return "\n".join(lines)

    # ── Section 1: Detected Stage 3 Baseline ──
    lines.append("## 1. Detected Stage 3 Baseline\n")
    java_ver = baseline.get("java_version", "unknown")
    boot_ver = baseline.get("spring_boot_version", "unknown")
    boot_src = baseline.get("spring_boot_source", "unknown")
    confirmed = baseline.get("baseline_confirmed", False)

    if confirmed:
        lines.append(
            f"Detected target baseline:\n"
            f"- **Java:** {java_ver}\n"
            f"- **Spring Boot:** {boot_ver}\n"
            f"- **Source:** {boot_src.replace('_', ' ')}\n"
        )
        if baseline.get("has_spring_boot_parent"):
            lines.append("- **Parent:** spring-boot-starter-parent\n")
        if baseline.get("has_spring_boot_bom"):
            lines.append("- **BOM:** spring-boot-dependencies (dependencyManagement)\n")
    else:
        missing = baseline.get("missing", [])
        lines.append(
            f"I cannot confirm the Stage 3 baseline yet. "
            f"Missing: {', '.join(missing) if missing else 'insufficient evidence'}. "
            f"Stage 3 root_pom or target_dependency_plan is needed."
        )
        return "\n".join(lines) + "\n\nNot applied.\n"

    # ── Section 2: What I Will Not Do ──
    lines.append("\n## 2. What I Will Not Do\n")
    lines.append(
        "- I will **not** propose Java/Spring Boot upgrades if Stage 3 already reached the target baseline.\n"
        "- I will **not** guess latest versions.\n"
        "- I will **not** apply anything directly.\n"
    )

    # ── Section 3: Dependency Buckets ──
    lines.append("\n## 3. Dependency Buckets\n")
    buckets = _classify_stage3_dependencies(pom_summary, baseline)

    boot_managed_deps = buckets.get("boot_managed", [])
    jakarta_deps = buckets.get("jakarta_platform", [])
    app_deps = buckets.get("app_specific_third_party", [])
    build_plugins = buckets.get("build_plugins", [])

    lines.append(f"**A. Boot-Managed** ({len(boot_managed_deps)} dependencies)\n")
    if boot_managed_deps:
        lines.append("These are normally managed by Spring Boot BOM/parent:")
        for d in boot_managed_deps[:10]:
            gid = d.get("groupId", "?")
            aid = d.get("artifactId", "?")
            ver = d.get("version", "(managed)")
            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
        if len(boot_managed_deps) > 10:
            lines.append(f"  ... and {len(boot_managed_deps) - 10} more.")
    lines.append(
        "**Action:** Prefer BOM/parent management. Remove explicit version tags "
        "unless dependency_policy_report requires an override.\n"
    )

    lines.append(f"**B. Jakarta/Platform** ({len(jakarta_deps)} dependencies)\n")
    if jakarta_deps:
        lines.append(
            "These may indicate old Java EE / Jakarta migration risk "
            "(remaining javax.* in Stage 3 is suspicious for Boot 3.x):"
        )
        for d in jakarta_deps:
            gid = d.get("groupId", "?")
            aid = d.get("artifactId", "?")
            ver = d.get("version", "(managed)")
            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
    else:
        lines.append("No javax.* dependencies remain in Stage 3 POM.")

    lines.append(f"\n**C. App-Specific Third-Party** ({len(app_deps)} dependencies)\n")
    if app_deps:
        lines.append("These are not controlled by Boot/OpenRewrite generic migration:")
        for d in app_deps[:15]:
            gid = d.get("groupId", "?")
            aid = d.get("artifactId", "?")
            ver = d.get("version", "(managed)")
            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
        if len(app_deps) > 15:
            lines.append(f"  ... and {len(app_deps) - 15} more.")
    lines.append("**Action:** Review against target_dependency_plan, dependency_policy_report, or operator target version.\n")

    lines.append(f"**D. Build/Test Plugins** ({len(build_plugins)} plugins)\n")
    if build_plugins:
        for p in build_plugins[:10]:
            gid = p.get("groupId", "?")
            aid = p.get("artifactId", "?")
            ver = p.get("version", "(managed)")
            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
        if len(build_plugins) > 10:
            lines.append(f"  ... and {len(build_plugins) - 10} more.")
    lines.append("**Action:** Check Java {java_ver} compatibility; do not upgrade blindly without plugin policy or build failure evidence.\n".format(java_ver=java_ver))

    lines.append("**E. Transitive/BOM-Managed Risk**")
    lines.append(
        "Requests like 'change Tomcat' when no direct Tomcat dependency exists "
        "should be handled as BOM-managed override only if dependency_policy_report requires it. "
        "Do not inject direct transitive dependencies.\n"
    )

    # ── Section 4: Recommended Dependency Actions ──
    lines.append("## 4. Recommended Dependency Actions\n")

    recommendations: list[str] = []
    # Boot-managed: prefer BOM management
    for d in boot_managed_deps[:5]:
        gid = d.get("groupId", "?")
        aid = d.get("artifactId", "?")
        ver = d.get("version", "(managed)")
        if d.get("version") and d.get("version") not in ("${spring-boot.version}", "${project.parent.version}"):
            recommendations.append(
                f"**`{gid}:{aid}`** — current: `{ver}` → **Action:** Remove explicit version; let Boot BOM manage it. "
                "Reason: managed by Spring Boot BOM. Risk: Low."
            )
    if len(boot_managed_deps) > 5:
        recommendations.append(
            f"... and {len(boot_managed_deps) - 5} more Boot-managed dependencies "
            "should be reviewed for BOM alignment."
        )

    # Jakarta: flag for migration
    for d in jakarta_deps:
        gid = d.get("groupId", "?")
        aid = d.get("artifactId", "?")
        ver = d.get("version", "(managed)")
        recommendations.append(
            f"**`{gid}:{aid}`** — current: `{ver}` → "
            "**Action:** Replace javax→jakarta equivalent. "
            "Reason: Spring Boot 3 requires Jakarta namespace. "
            f"Risk: Medium/High (source imports may break). "
            "Evidence: Stage 3 root_pom."
        )

    # App-specific: needs policy decision
    policy_candidates = []
    for d in app_deps:
        gid = d.get("groupId", "")
        aid = d.get("artifactId", "")
        ver = d.get("version", "(managed)")
        if any(
            ag_gid in gid
            for ag_gid in (
                "org.zalando", "microsoft.azure", "org.apache.juneau",
                "io.jsonwebtoken", "org.modelmapper",
            )
        ):
            policy_candidates.append(d)
            recommendations.append(
                f"**`{gid}:{aid}`** — current: `{ver}` → "
                "**Action: Needs policy decision.** "
                "No target version in evidence artifacts. "
                "Provide operator target version or reference dependency_policy_report."
            )
        else:
            recommendations.append(
                f"**`{gid}:{aid}`** — current: `{ver}` → "
                "**Action:** Review against dependency_policy_report or operator target."
            )

    if recommendations:
        for rec in recommendations:
            lines.append(f"- {rec}")
    else:
        lines.append("No specific dependency actions recommended at this stage.")

    # ── Section 5: Human Decisions Needed ──
    lines.append("")
    lines.append("## 5. Human Decisions Needed\n")
    if policy_candidates:
        lines.append(
            "The following dependencies require operator/business/policy target versions "
            "before a governed change proposal can be drafted:"
        )
        for d in policy_candidates:
            gid = d.get("groupId", "?")
            aid = d.get("artifactId", "?")
            ver = d.get("version", "(managed)")
            lines.append(f"  - `{gid}:{aid}` (current: `{ver}`)")
        lines.append(
            "\nTo proceed, specify an exact target version, e.g.: "
            "`Update <artifact> to <version> at stage 3`"
        )
    else:
        lines.append("No policy decisions are currently outstanding.")

    # ── Section 6: Governed Change Proposal Next Step ──
    lines.append("")
    lines.append("## 6. Governed Change Proposal Next Step\n")
    lines.append(
        "- An exact dependency change can be turned into a `pom_dependency_change_request`.\n"
        "- Backend/OpenRewrite candidate recipe is available.\n"
        "- Human approval with checksum is required.\n"
        "- Sandbox apply → build/test/proof validates the change."
    )

    # ── Section 7: Not Applied ──
    lines.append("")
    lines.append("## 7. Not Applied\n")
    lines.append(
        "No file was written, no command was executed, no approval was recorded."
    )

    answer = "\n".join(lines)
    from migration_factory.control_tower.application.redaction import (
        redact_absolute_paths,
        redact_deployment_identifiers,
        redact_secret_keys,
    )
    redacted = answer
    redacted = redact_absolute_paths(redacted)
    redacted = redact_secret_keys(redacted)
    redacted = redact_deployment_identifiers(redacted)
    return redacted


def _build_stage1_or_2_deferred_dependency_answer(
    *,
    requested_stage: int,
    root_pom_preview: dict[str, Any] | None = None,
    events: tuple[Any, ...] = (),
) -> str:
    """Build a response that defers final dependency modernization for Stage 1/2.

    Explains current POM, identifies obvious risks, but does not propose
    final app-specific dependency modernization.
    """
    lines: list[str] = []
    lines.append(
        "We are not at the final target baseline yet. "
        "I can explain current dependencies and identify obvious risks, "
        "but final app-specific dependency modernization should wait for "
        "Stage 3 after OpenRewrite/backend migration produces the "
        "Java/Spring Boot target POM.\n"
    )

    if root_pom_preview and root_pom_preview.get("exists"):
        preview = str(root_pom_preview.get("preview", ""))
        pom_summary = _extract_pom_summary(preview)
        props = pom_summary.get("properties", {})
        deps = pom_summary.get("dependencies", [])

        java_ver = props.get("java.version", "unknown")
        boot_ver = props.get("spring-boot.version", props.get("spring-boot-dependencies.version", "unknown"))

        lines.append(f"**Current stage {requested_stage} POM summary:**")
        lines.append(f"- `java.version`: `{java_ver}`")
        if boot_ver != "unknown":
            lines.append(f"- `spring-boot.version`: `{boot_ver}`")

        # List obvious risks
        lines.append("\n**Obvious risks identified:**")
        javax_deps = [
            d for d in deps
            if "javax." in d.get("groupId", "").lower()
            or any(pfx in d.get("artifactId", "").lower() for pfx in ("javax.",))
        ]
        if javax_deps:
            lines.append(
                f"- {len(javax_deps)} javax.* dependencies detected "
                "(will need Jakarta migration at Stage 3)."
            )
        if java_ver == "11" or java_ver == "1.8":
            lines.append(
                f"- Java {java_ver} detected (Spring Boot 3 requires Java 17+)."
            )
        if not pom_summary.get("has_dependency_management") and not pom_summary.get("has_parent"):
            lines.append("- No dependencyManagement or parent POM — version drift risk.")
    else:
        reason = "not_available"
        if root_pom_preview:
            reason = str(root_pom_preview.get("reason", "not_available")).replace("_", " ")
        lines.append(
            f"The root pom.xml for stage {requested_stage} is not available yet "
            f"(reason: {reason})."
        )

    lines.append("")
    lines.append(
        "**What I can do now:**\n"
        "- Explain POM content and dependencies\n"
        "- Compare artifact versions across stages\n"
        "- Identify obvious migration risks\n"
        "- Handle explicit single-dependency edits you specify directly "
        "(e.g., 'update library-name to 1.2.3')\n\n"
        "**What should wait for Stage 3:**\n"
        "- Final app-specific dependency modernization recommendations\n"
        "- Broad dependency upgrade plans\n"
        "- Jakarta migration proposals"
    )

    lines.append("")
    lines.append("Not applied: no file was written, no command was executed.")
    return "\n".join(lines)


def _build_pom_explanation_answer(
    *,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
    raw_xml_requested: bool = False,
    job_id: str = "",
) -> str:
    """Build POM/dependency explanation fallback.

    When raw_xml_requested=True (e.g., "show raw XML"), presents
    a redacted but structurally intact XML preview.
    Otherwise uses structured extraction for readability.

    For "find" operations, reads the live Stage 3 sandbox POM
    instead of just the truncated preview.
    """
    # ── For "find" / "show raw" operations, use live POM from editor ──
    if job_id:
        try:
            editor = _build_pom_dependency_editor()
            view = editor.get_stage3_pom(job_id=job_id)
            if view.exists:
                live_content = str(view.content or "")
                if live_content.strip():
                    stage = 3
                    if raw_xml_requested:
                        safe_xml = _redact_xml_preserve_maven_urls(live_content)
                        if view.truncated:
                            note = " (excerpt — full XML truncated for safety)"
                        else:
                            note = ""
                        answer = (
                            f"The backend-resolved root pom.xml for Stage {stage} is available{note}. "
                            f"Here is what it contains (redacted for safety):\n\n"
                            f"--- pom.xml ---\n{safe_xml}\n--- end ---\n\n"
                            f"Focus on dependencies (<dependencies>), plugins (<build><plugins>), "
                            f"properties (<properties>), parent POM, and repositories. "
                            f"These are the migration-relevant sections."
                        )
                        return answer
                    # Structured extraction from live content
                    pom_summary = _extract_pom_summary(live_content)
                    # ... proceed to structured summary (fall-through to existing logic)
                    lines: list[str] = []
                    lines.append(
                        f"The backend-resolved root pom.xml for Stage {stage} is available. "
                        f"Here is a structured summary:\n"
                    )
                    coords = pom_summary.get("coordinates", {})
                    if coords:
                        parts = []
                        if coords.get("groupId"):
                            parts.append(f"groupId: {coords['groupId']}")
                        if coords.get("artifactId"):
                            parts.append(f"artifactId: {coords['artifactId']}")
                        if coords.get("version"):
                            parts.append(f"version: {coords['version']}")
                        if coords.get("packaging") and coords["packaging"] != "jar":
                            parts.append(f"packaging: {coords['packaging']}")
                        if parts:
                            lines.append("**Project:** " + " | ".join(parts))
                    if pom_summary.get("has_parent"):
                        lines.append("**Parent POM:** present")
                    if pom_summary.get("has_dependency_management"):
                        lines.append("**Dependency Management:** present")
                    if pom_summary.get("has_repositories"):
                        lines.append("**Repositories:** present [redacted]")
                    props = pom_summary.get("properties", {})
                    if props:
                        lines.append("\n**Key Properties:**")
                        for k, v in sorted(props.items()):
                            if len(v) > 80:
                                v = v[:77] + "..."
                            lines.append(f"  - `{k}` = `{v}`")
                    deps = pom_summary.get("dependencies", [])
                    if deps:
                        lines.append("\n**Dependencies:**")
                        for d in deps[:20]:
                            gid = d.get("groupId", "?")
                            aid = d.get("artifactId", "?")
                            ver = d.get("version", "(managed)")
                            scope = d.get("scope", "")
                            scope_suffix = f" [{scope}]" if scope and scope != "compile" else ""
                            lines.append(
                                f"  - `{gid}:{aid}` = `{ver}`{scope_suffix}"
                            )
                        if len(deps) > 20:
                            lines.append(f"  ... and {len(deps) - 20} more dependencies.")
                    plugs = pom_summary.get("plugins", [])
                    if plugs:
                        lines.append("\n**Plugins:**")
                        for p in plugs[:15]:
                            gid = p.get("groupId", "?")
                            aid = p.get("artifactId", "?")
                            ver = p.get("version", "(managed)")
                            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
                        if len(plugs) > 15:
                            lines.append(f"  ... and {len(plugs) - 15} more plugins.")
                    lines.append(
                        "\nTo see the full raw XML (redacted for safety), "
                        "ask 'show the raw pom.xml'."
                    )
                    answer = "\n".join(lines)
                    return str(redact_public_data(answer))
        except Exception:
            # Live POM read failed; fall through to preview-based answer
            pass

    if artifact_previews:
        for pv in artifact_previews:
            if pv.get("source_type") == "file_alias":
                if pv.get("exists") is True:
                    preview = str(pv.get("preview", ""))
                    stage = pv.get("stage_index", "?")

                    if raw_xml_requested:
                        # XML-safe redaction: preserve Maven URLs, redact paths/secrets
                        safe_xml = _redact_xml_preserve_maven_urls(preview)
                        answer = (
                            f"The backend-resolved root pom.xml for Stage {stage} is available. "
                            f"Here is what it contains (redacted for safety):\n\n"
                            f"--- pom.xml ---\n{safe_xml}\n--- end ---\n\n"
                            f"Focus on dependencies (<dependencies>), plugins (<build><plugins>), "
                            f"properties (<properties>), parent POM, and repositories. "
                            f"These are the migration-relevant sections."
                        )
                        return answer

                    # Structured extraction (default): extract fields from XML
                    pom_summary = _extract_pom_summary(preview)
                    lines: list[str] = []
                    lines.append(
                        f"The backend-resolved root pom.xml for Stage {stage} is available. "
                        f"Here is a structured summary:\n"
                    )

                    coords = pom_summary.get("coordinates", {})
                    if coords:
                        parts = []
                        if coords.get("groupId"):
                            parts.append(f"groupId: {coords['groupId']}")
                        if coords.get("artifactId"):
                            parts.append(f"artifactId: {coords['artifactId']}")
                        if coords.get("version"):
                            parts.append(f"version: {coords['version']}")
                        if coords.get("packaging") and coords["packaging"] != "jar":
                            parts.append(f"packaging: {coords['packaging']}")
                        if parts:
                            lines.append("**Project:** " + " | ".join(parts))

                    if pom_summary.get("has_parent"):
                        lines.append("**Parent POM:** present")
                    if pom_summary.get("has_dependency_management"):
                        lines.append("**Dependency Management:** present")
                    if pom_summary.get("has_repositories"):
                        lines.append("**Repositories:** present [redacted]")

                    props = pom_summary.get("properties", {})
                    if props:
                        lines.append("\n**Key Properties:**")
                        for k, v in sorted(props.items()):
                            if len(v) > 80:
                                v = v[:77] + "..."
                            lines.append(f"  - `{k}` = `{v}`")

                    deps = pom_summary.get("dependencies", [])
                    if deps:
                        lines.append("\n**Dependencies:**")
                        for d in deps[:20]:
                            gid = d.get("groupId", "?")
                            aid = d.get("artifactId", "?")
                            ver = d.get("version", "(managed)")
                            scope = d.get("scope", "")
                            scope_suffix = f" [{scope}]" if scope and scope != "compile" else ""
                            lines.append(
                                f"  - `{gid}:{aid}` = `{ver}`{scope_suffix}"
                            )
                        if len(deps) > 20:
                            lines.append(f"  ... and {len(deps) - 20} more dependencies.")

                    plugs = pom_summary.get("plugins", [])
                    if plugs:
                        lines.append("\n**Plugins:**")
                        for p in plugs[:15]:
                            gid = p.get("groupId", "?")
                            aid = p.get("artifactId", "?")
                            ver = p.get("version", "(managed)")
                            lines.append(f"  - `{gid}:{aid}` = `{ver}`")
                        if len(plugs) > 15:
                            lines.append(f"  ... and {len(plugs) - 15} more plugins.")

                    lines.append(
                        "\nTo see the full raw XML (redacted for safety), "
                        "ask 'show the raw pom.xml'."
                    )
                    answer = "\n".join(lines)
                    return str(redact_public_data(answer))

                reason = str(pv.get("reason") or "not_available").replace("_", " ")
                stage = pv.get("stage_index", "?")
                artifact_list = _extract_artifact_kinds_list(events)
                artifact_note = f" Available artifact kinds: {', '.join(artifact_list)}." if artifact_list else " No artifacts are available yet."
                answer = (
                    f"The root pom.xml for Stage {stage} is not available yet. "
                    f"Reason: {reason}. I can explain it once the backend publishes root_pom.{artifact_note}"
                )
                return str(redact_public_data(answer))
    artifact_list = _extract_artifact_kinds_list(events)
    artifact_note = f" Available artifact kinds: {', '.join(artifact_list)}." if artifact_list else ""
    answer = (
        "The root pom.xml is not available yet. "
        f"I can explain it once the backend resolves and publishes root_pom content. "
        "Ask about available artifact kinds instead.{artifact_note}"
    )
    return str(redact_public_data(answer))


def _extract_artifact_kinds_list(events: tuple[Any, ...]) -> list[str]:
    """Extract unique artifact kinds from events."""
    kinds: list[str] = []
    for event in events:
        if getattr(event, "type", "") == "artifact_written":
            try:
                payload = json.loads(getattr(event, "payload_json", "") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            kind = str(payload.get("artifact_kind", ""))
            if kind and kind not in kinds:
                kinds.append(kind)
    return kinds


def _build_capability_boundary_answer() -> str:
    """Build capability boundary fallback â€” no stage status template."""
    answer = (
        "I cannot apply changes, approve gates, execute commands, or modify stages. "
        "The backend owns all execution. A human must approve decisions.\n\n"
        "What I can do:\n"
        "- Explain POM content, dependencies, plugins, and migration changes\n"
        "- Summarize evidence, failure diagnostics, and repair proposals\n"
        "- Compare artifacts across stages\n"
        "- Identify what needs approval or evidence next\n"
        "- Draft a repair request for human review"
    )
    return str(redact_public_data(answer))


def _build_model_status_answer() -> str:
    """Build model/provider status answer."""
    available = _model_client_available()
    if available:
        answer = (
            "The Azure OpenAI model is configured and connected. "
            "AI-backed coaching is active. Source: azure_openai."
        )
    else:
        answer = (
            "The Azure OpenAI model is not fully configured "
            "(missing endpoint, key, or deployment). "
            "Assistant responses use deterministic fallback logic. "
            "AI-backed coaching is unavailable until model readiness is restored."
        )
    return str(redact_public_data(answer))


def _build_general_or_artifact_answer(
    *,
    question: str,
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    events: tuple[Any, ...] = (),
) -> str:
    """Build a short general or artifact-content answer from evidence."""
    preview_text = ""
    if artifact_previews:
        preview_parts: list[str] = []
        for pv in artifact_previews:
            kind = pv.get("artifact_kind", "unknown")
            preview = str(pv.get("preview", ""))
            if pv.get("source_type") == "file_alias" and not pv.get("exists"):
                reason = str(pv.get("reason") or "not_available").replace("_", " ")
                stage = pv.get("stage_index", "?")
                preview_parts.append(
                    f"root_pom for Stage {stage} is not available: {reason}."
                )
                continue
            label = "root_pom" if pv.get("source_type") == "file_alias" else kind
            truncated = pv.get("truncated", False)
            tag = " (truncated)" if truncated else ""
            preview_parts.append(f"{label}{tag}:\n{preview[:512]}")
        if preview_parts:
            preview_text = (
                "\n\nArtifact Content (backend-resolved):\n" + "\n---\n".join(preview_parts)
            )
    artifact_list = _extract_artifact_kinds_list(events)
    artifact_note = ""
    if artifact_list:
        artifact_note = f"\n\nAvailable artifact kinds: {', '.join(artifact_list)}."
    answer = (
        f"Question: {_bounded_event_text(question)}\n\n"
        f"Answer from available evidence.{preview_text}{artifact_note}\n\n"
        "I can also explain POM content, summarize evidence, "
        "or help you determine what needs approval."
    )
    return str(redact_public_data(answer))


def _build_status_answer(
    *,
    question: str,
    events: tuple[Any, ...],
    approvals: tuple[Any, ...],
    commands: tuple[Any, ...],
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
) -> str:
    """Build full operational status fallback (preserved for status intent)."""
    latest = events[-1] if events else None
    failures = [event for event in events if event.status == "failed" or event.type in {"stage_failed", "transform_failed", "build_failed"}]
    pending_approvals = [card for card in approvals if card.status == "pending"]
    approved_cards = [card for card in approvals if card.status == "approved"]
    completed = [event for event in events if event.type == "stage_completed"]
    repair_events = [event for event in events if event.type in {"repair_started", "repair_fallback_generated"}]
    running_events = [event for event in events if event.status == "running"]

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

    # Determine action
    if failures:
        failure_msgs = [f"{event.type}: {event.message}" for event in failures[-3:]]
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
    elif running_events:
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

    # â”€â”€ Artifact preview content â”€â”€
    artifact_preview_text = ""
    if artifact_previews:
        preview_parts: list[str] = []
        for pv in artifact_previews:
            kind = pv.get("artifact_kind", "unknown")
            truncated = pv.get("truncated", False)
            preview = str(pv.get("preview", ""))
            if pv.get("source_type") == "file_alias" and not pv.get("exists"):
                reason = str(pv.get("reason") or "not_available").replace("_", " ")
                stage = pv.get("stage_index", "?")
                preview_parts.append(
                    f"--- root_pom (file alias) ---\n"
                    f"Full root pom.xml for Stage {stage} is not available: {reason}."
                )
                continue
            tag = f"(truncated preview)" if truncated else "(preview)"
            label = "root pom.xml" if pv.get("source_type") == "file_alias" else kind
            download_url = pv.get("download_url")
            download_note = f"\nDownload: {download_url}" if download_url and truncated else ""
            preview_parts.append(f"--- {label} {tag} ---\n{preview}{download_note}")
        if preview_parts:
            artifact_preview_text = (
                "\n\nArtifact Content (backend-resolved from persisted events):\n"
                + "\n\n".join(preview_parts)
                + "\n\nNote: Content is backend-resolved and bounded in chat. "
                "Patch artifacts are diffs/proposed changes, not the full resulting POM."
            )

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
        f"{artifact_preview_text}\n"
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
    artifact_previews: tuple[dict[str, Any], ...] | None = None,
    assistant_intent: str = "general_question",
    conversation_history: list[dict[str, str]] | None = None,
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
        "assistant_intent": assistant_intent,
        "requested_stage": _get_requested_stage(question, assistant_intent),
        "conversation_history": conversation_history if conversation_history else [],
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
        "artifact_previews": [
            {
                "kind": p.get("artifact_kind", ""),
                "source_type": p.get("source_type", ""),
                "file_alias": p.get("file_alias", ""),
                "stage_index": p.get("stage_index"),
                "exists": p.get("exists", False),
                "reason": p.get("reason", ""),
                "preview": str(p.get("preview", ""))[:1024],
                "truncated": p.get("truncated", False),
                "download_url": p.get("download_url", "") or "",
            }
            for p in (artifact_previews or ())
        ] if artifact_previews else [],
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
    if ref.startswith(("\\", "//")):
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


_REPAIR_EVENT_TYPES = {
    "repair_started",
    "repair_fallback_generated",
    "copilot_repair_invalid_response",
    "repair_proposal_revised",
    "reviewer_critique_created",
    "repair_patch_gate_completed",
    "repair_patch_applied",
    "repair_validation_completed",
    "repair_rollback_completed",
}


def _is_fallback_model_event(event: Any) -> bool:
    """Check if a model_invocation_failed event is a deterministic fallback.

    Fallback model events should be telemetry, not migration failure/repair.
    """
    if event.type != "model_invocation_failed":
        return False
    try:
        payload = json.loads(event.payload_json or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    source = str(payload.get("source", "")).lower()
    is_fallback = bool(payload.get("is_fallback", False))
    return source == "deterministic" or is_fallback


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
        and not _is_fallback_model_event(event)
    ]
    repair_events_typed = [
        event for event in events
        if event.type in _REPAIR_EVENT_TYPES
    ]
    supervision_by_stage = _v2_supervision_traces(events)

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
            "supervision_trace": supervision_by_stage.get(primary.stage, _empty_supervision_trace()),
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


def _empty_supervision_trace() -> dict[str, Any]:
    return {
        "ai_diagnosis": None,
        "evidence_used": [],
        "pom_analysis": None,
        "repair_proposal": None,
        "reviewer_verdict": None,
        "validation_result": None,
    }


def _v2_supervision_traces(events: tuple[Any, ...]) -> dict[int | None, dict[str, Any]]:
    traces: dict[int | None, dict[str, Any]] = {}

    def trace_for(stage: int | None) -> dict[str, Any]:
        if stage not in traces:
            traces[stage] = _empty_supervision_trace()
        return traces[stage]

    for event in events:
        try:
            payload = json.loads(event.payload_json or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        trace = trace_for(event.stage)

        if event.type == "ai_diagnosis_created":
            evidence_refs = _safe_failure_list(payload.get("evidence_refs"))
            context_pack_id = _safe_failure_str(payload.get("context_pack_id"))
            context_pack_checksum = _safe_failure_str(payload.get("context_pack_checksum"))
            if context_pack_id:
                evidence_refs.append(context_pack_id)
            if context_pack_checksum:
                evidence_refs.append(context_pack_checksum)
            trace["ai_diagnosis"] = {
                "diagnosis_id": _safe_failure_str(payload.get("diagnosis_id")),
                "command_id": _safe_failure_str(payload.get("command_id")),
                "trigger_event_type": _safe_failure_str(payload.get("event_type")),
                "failure_type": _safe_failure_str(payload.get("failure_type")),
                "context_pack_id": context_pack_id,
                "context_pack_checksum": context_pack_checksum,
                "repair_proposal_id": _safe_failure_str(payload.get("repair_proposal_id")),
                "model_invocation_id": _safe_failure_str(payload.get("model_invocation_id")),
                "redaction_status": _safe_failure_str(payload.get("redaction_status")),
                "created_at": event.created_at,
            }
            trace["evidence_used"] = _unique_trace_values(trace["evidence_used"] + evidence_refs)

        elif event.type == "pom_summary_created":
            pom_summary_ref = _safe_failure_str(payload.get("pom_summary_ref"))
            trace["pom_analysis"] = {
                "pom_summary_ref": pom_summary_ref,
                "spring_boot_version": _safe_failure_str(payload.get("spring_boot_version")),
                "java_version": _safe_failure_str(payload.get("java_version")),
                "packaging": _safe_failure_str(payload.get("packaging")),
                "candidate_rules": _safe_failure_list(payload.get("candidate_rules")),
                "created_at": event.created_at,
            }
            if pom_summary_ref:
                trace["evidence_used"] = _unique_trace_values(trace["evidence_used"] + [pom_summary_ref])

        elif event.type == "repair_proposal_revised":
            proposal_id = _safe_failure_str(
                payload.get("revised_proposal_id") or payload.get("proposal_id")
            )
            trace["repair_proposal"] = {
                "proposal_id": proposal_id,
                "source_proposal_id": _safe_failure_str(payload.get("source_proposal_id")),
                "command_id": _safe_failure_str(payload.get("command_id")),
                "revision_number": payload.get("revision_number"),
                "allowed_scope": _safe_failure_str(payload.get("allowed_scope")),
                "proposal_checksum": _safe_failure_str(payload.get("proposal_checksum")),
                "status": _safe_failure_str(payload.get("status") or event.status),
                "created_at": event.created_at,
            }

        elif event.type == "reviewer_critique_created":
            trace["reviewer_verdict"] = {
                "critique_id": _safe_failure_str(payload.get("critique_id")),
                "proposal_id": _safe_failure_str(payload.get("proposal_id")),
                "proposal_type": _safe_failure_str(payload.get("proposal_type")),
                "proposal_checksum": _safe_failure_str(payload.get("proposal_checksum")),
                "context_pack_checksum": _safe_failure_str(payload.get("context_pack_checksum")),
                "decision": _safe_failure_str(payload.get("decision")),
                "reasoning": _safe_failure_str(payload.get("reasoning")),
                "missing_evidence": _safe_failure_list(payload.get("missing_evidence")),
                "unsafe_assumptions": _safe_failure_list(payload.get("unsafe_assumptions")),
                "created_at": event.created_at,
            }

        elif event.type == "repair_patch_gate_completed":
            validation = dict(trace["validation_result"] or {})
            validation.update({
                "proposal_id": _safe_failure_str(payload.get("proposal_id")),
                "binding_checksum": _safe_failure_str(payload.get("binding_checksum")),
                "patch_gate_status": _safe_failure_str(payload.get("patch_gate_status")),
                "deterministic_rule_id": _safe_failure_str(payload.get("deterministic_rule_id")),
                "touched_paths": _safe_failure_list(payload.get("touched_paths")),
                "ledger_ref": _safe_failure_str(payload.get("ledger_ref")),
                "updated_at": event.created_at,
            })
            trace["validation_result"] = validation

        elif event.type == "repair_patch_applied":
            validation = dict(trace["validation_result"] or {})
            validation.update({
                "proposal_id": _safe_failure_str(payload.get("proposal_id")),
                "patch_ref": _safe_failure_str(payload.get("patch_ref")),
                "patch_status": _safe_failure_str(payload.get("patch_status")),
                "touched_paths": _safe_failure_list(payload.get("touched_paths")),
                "ledger_ref": _safe_failure_str(payload.get("ledger_ref") or validation.get("ledger_ref")),
                "updated_at": event.created_at,
            })
            trace["validation_result"] = validation

        elif event.type == "repair_validation_completed":
            validation = dict(trace["validation_result"] or {})
            artifact_refs_raw = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), dict) else {}
            validation.update({
                "proposal_id": _safe_failure_str(payload.get("proposal_id")),
                "passed": bool(payload.get("passed")),
                "build_status": _safe_failure_str(payload.get("build_status")),
                "test_status": _safe_failure_str(payload.get("test_status")),
                "h2_status": _safe_failure_str(payload.get("h2_status")),
                "artifact_refs": {
                    _safe_failure_str(key): _safe_failure_str(value)
                    for key, value in artifact_refs_raw.items()
                },
                "ledger_ref": _safe_failure_str(payload.get("ledger_ref") or validation.get("ledger_ref")),
                "updated_at": event.created_at,
            })
            trace["validation_result"] = validation

        elif event.type == "repair_rollback_completed":
            validation = dict(trace["validation_result"] or {})
            validation.update({
                "proposal_id": _safe_failure_str(payload.get("proposal_id")),
                "rollback_status": _safe_failure_str(payload.get("rollback_status")),
                "rollback_reason": _safe_failure_str(payload.get("reason")),
                "updated_at": event.created_at,
            })
            trace["validation_result"] = validation

    return traces


def _unique_trace_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result[:12]


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
    # Chronological lifecycle reducer â€” processes events in sequence order.
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

    * failed         â†’ terminal (highest priority)
    * completed      â†’ terminal unless a later failure arrives
    * running        â†’ overrides blocked/pending/queued
    * blocked        â†’ applies only if not already running/completed/failed
    * queued         â†’ applies only if not already past it
    * pending        â†’ no change
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
        with _read_unit_of_work(unit_of_work_factory) as uow:
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
