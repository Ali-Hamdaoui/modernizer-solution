"""Immutable record types for Control Tower persistence contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.domain.commands import CommandState


@dataclass(frozen=True, slots=True)
class RunnerProfileRecord:
    runner_profile_id: str
    runner_profile_version: str
    display_name: str
    schema_version: str
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str
    payload: Any


@dataclass(frozen=True, slots=True)
class PipelineDefinitionRecord:
    pipeline_id: str
    pipeline_version: str
    display_name: str
    schema_version: str
    graph_version: str
    graph_state_schema_version: str
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str
    payload: Any


@dataclass(frozen=True, slots=True)
class MigrationJobRecord:
    job_id: str
    version: int
    status: JobState
    active_slot: int | None
    last_event_sequence: int
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: TargetProofLevel
    achieved_proof_level: TargetProofLevel | None
    legacy_source_ref: str
    output_root_ref: str
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    created_by: str


@dataclass(frozen=True, slots=True)
class RunConfigurationRecord:
    run_configuration_id: str
    job_id: str
    schema_version: str
    runner_profile_id: str
    runner_profile_version: str
    pipeline_id: str
    pipeline_version: str
    target_proof_level: TargetProofLevel
    enabled_gates_json: str
    policy_json: str
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StageRunRecord:
    stage_run_id: str
    job_id: str
    stage_index: int
    stage_id: str
    status: str
    input_source_json: str
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    job_id: str
    stage_run_id: str | None
    artifact_type: str
    registered_root_id: str
    relative_path: str
    normalized_relative_path: str
    content_type: str | None
    size_bytes: int
    checksum_algorithm: str
    checksum: str
    created_at: str
    created_by: str


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    event_id: str
    job_id: str
    sequence: int
    event_type: str
    actor_type: str
    actor_id: str
    correlation_id: str | None
    causation_id: str | None
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class AuditRecord:
    audit_id: str
    job_id: str | None
    actor_type: str
    actor_id: str
    action: str
    prior_state: str | None
    new_state: str | None
    job_version: int | None
    correlation_id: str | None
    causation_id: str | None
    payload_json: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CommandExecutionRecord:
    command_id: str
    job_id: str
    operation: str
    status: CommandState
    created_at: str
    updated_at: str
    correlation_id: str | None
    causation_id: str | None
    command_manifest_artifact_id: str | None = None
    working_directory_root_id: str | None = None
    working_directory_relative_path: str | None = None
    worker_id: str | None = None
    launch_attempt: int | None = None
    process_control_id: str | None = None
    worker_pid: int | None = None
    process_started_at: str | None = None


@dataclass(frozen=True, slots=True)
class CommandManifestRecord:
    command_id: str
    manifest_json: str
    manifest_checksum: str
    run_configuration_artifact_id: str
    run_configuration_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    operation: str
    idempotency_key: str
    request_checksum: str
    resource_type: str
    resource_id: str
    original_status_code: int
    created_at: str


@dataclass(frozen=True, slots=True)
class StageChainLedgerRecord:
    ledger_id: str
    job_id: str
    stage_index: int
    stage_run_id: str
    chain_status: str
    input_source_kind: str
    input_checksum: str | None
    output_artifact_id: str | None
    output_checksum: str | None
    output_registered_at: str | None
    checksum_guard: str
    created_at: str
    created_by: str


@dataclass(frozen=True, slots=True)
class StageOutputRegistryRecord:
    output_id: str
    job_id: str
    stage_index: int
    stage_run_id: str
    artifact_id: str
    artifact_type: str
    output_kind: str
    checksum_algorithm: str
    checksum: str
    registered_at: str
    registered_by: str


@dataclass(frozen=True, slots=True)
class StageChainEventRecord:
    event_id: str
    job_id: str
    stage_index: int | None
    event_type: str
    prior_status: str | None
    new_status: str | None
    ledger_id: str | None
    output_id: str | None
    payload_json: str
    payload_checksum: str
    created_at: str
    created_by: str


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Immutable record of an approval decision.

    Append-only: once inserted, the record is never updated.
    Idempotency is guaranteed by the (interrupt_id, request_checksum) unique constraint.
    """

    approval_id: str
    job_id: str
    interrupt_id: str
    request_checksum: str
    decision: str
    approved_by: str
    approval_comments: str
    actor_type: str
    actor_id: str
    payload_json: str
    payload_checksum: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ApprovalResumeRecord:
    """Immutable record of a queued approval resume command.

    Append-only: the core fields (resume_id, approval_id, etc.) are
    never updated. Only status, executed_at, and failure_reason may
    be updated after execution.
    """

    resume_id: str
    approval_id: str
    job_id: str
    command_type: str
    command_payload_json: str
    status: str
    created_at: str
    executed_at: str | None
    failure_reason: str | None
    correlation_id: str | None
    causation_id: str | None


@dataclass(frozen=True, slots=True)
class V1ModelInvocationRecord:
    """Immutable record of a model invocation call.

    Captures profile ref, token usage, model name, provider kind,
    and a redacted summary. Raw prompts, secrets, and deployment IDs
    are never stored in this record.
    """

    invocation_id: str
    created_at: str
    job_id: str | None = None
    profile_id: str | None = None
    provider_kind: str | None = None
    model_name: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    redacted_summary: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PrivilegedActionExecutionRecord:
    """Immutable record of a privileged action execution.

    Append-only: once inserted, the record is never updated or deleted.
    PK is action_id to prevent duplicate executions on the same action.
    Results are stored as redacted summaries only.
    """

    action_id: str
    job_id: str
    action_type: str
    parameters_checksum: str
    status: str = "executing"  # 'executing', 'completed', 'failed'
    started_at: str = ""
    completed_at: str | None = None
    result_summary: str | None = None
    failure_reason: str | None = None
    executed_by: str = ""
    execution_version: str = "1.0"
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PrivilegedActionDecisionRecord:
    """Immutable record of an approve/reject decision on a privileged action.

    Append-only: once inserted, the record is never updated or deleted.
    PK is action_id to prevent duplicate decisions on the same action.
    """

    action_id: str
    decision: str  # 'approved' or 'rejected'
    decided_by: str
    decided_at: str
    parameters_checksum: str
    rejection_reason: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PrivilegedActionRecord:
    """Immutable record of a pending privileged action request.

    Append-only: once inserted, the record is never updated.
    Status changes are tracked by inserting new records with
    updated status (not by updating existing rows).

    Only typed Maven and write actions are allowed. Shell actions
    are rejected at the service layer.

    Approval logic belongs to V1-17C. Execution belongs to V1-17D.
    Policy/checksum validation beyond basic storage belongs to V1-17B.
    """

    action_id: str
    job_id: str
    action_type: str  # 'maven' or 'write'
    parameters_json: str
    parameters_checksum: str
    status: str = "pending"
    requested_by: str = ""
    requested_at: str = ""
    action_version: str = "1.0"
    policy_json: str | None = None
    policy_version: str | None = None
    approved_by: str | None = None
    approved_at: str | None = None
    rejected_by: str | None = None
    rejected_reason: str | None = None
    executed_at: str | None = None
    failure_reason: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1ContextPackManifestRecord:
    """Immutable record of a context pack manifest.

    Stores evidence references, boundaries, redaction metadata,
    and checksums. Raw prompts, secrets, and deployment IDs are
    never stored.
    """

    manifest_id: str
    pack_type: str
    pack_version: str
    title: str
    checksum_algorithm: str = "sha256"
    checksum: str = ""
    created_at: str = ""
    created_by: str = ""
    job_id: str | None = None
    stage_run_id: str | None = None
    description: str | None = None
    evidence_refs_json: str | None = None
    bounds_json: str | None = None
    redaction_policy: str | None = None
    redacted_summary: str | None = None
    model_profile_id: str | None = None
    model_name: str | None = None
    token_count: int | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PlanAmendmentRecord:
    """Immutable record of a persisted plan amendment request.

    Stores canonical amendment payload and a safe redacted summary.
    The amendment is informational only and never applies source,
    sandbox, or execution changes by itself.
    """

    amendment_id: str
    job_id: str
    source_kind: str
    title: str
    summary: str
    payload_json: str
    payload_checksum: str
    redacted_summary_json: str
    created_at: str
    created_by: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PlanRevisionRecord:
    """Immutable record of a plan revision.

    Revisions are append-only, ordered per amendment, checksum-bound,
    and may become terminal once accepted/finalized.
    """

    revision_id: str
    amendment_id: str
    job_id: str
    revision_order: int
    revision_state: str
    source_kind: str
    payload_json: str
    payload_checksum: str
    redacted_summary_json: str
    created_at: str
    created_by: str
    decided_at: str | None = None
    decided_by: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1PlanReviewDecisionRecord:
    """Immutable reviewer decision bound to an exact plan revision checksum."""

    review_decision_id: str
    revision_id: str
    amendment_id: str
    job_id: str
    decision: str
    reviewed_checksum: str
    review_summary: str
    actor_type: str
    actor_id: str
    created_at: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1RepairClassificationRecord:
    """Immutable repair classification for failed command evidence."""

    classification_id: str
    command_id: str
    job_id: str
    command_status: str
    evidence_kind: str
    evidence_summary: str
    evidence_checksum: str
    classification_code: str
    reason_code: str
    repairable: bool
    attempt_limit: int
    actor_type: str
    actor_id: str
    created_at: str
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True, slots=True)
class V1FakeRepairProposalRecord:
    """Immutable fake repair proposal metadata. No patch content is stored."""

    proposal_id: str
    classification_id: str
    command_id: str
    job_id: str
    proposal_order: int
    proposal_summary: str
    proposal_checksum: str
    actor_type: str
    actor_id: str
    created_at: str
    correlation_id: str | None = None
    causation_id: str | None = None
