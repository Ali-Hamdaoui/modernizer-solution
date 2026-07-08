"""WF-03A unknown-family repair review-chain orchestration.

This adapter authorizes the canonical unknown-family route, validates already
authoritative bindings, emits safe public events, and delegates model work to
the existing repair review-chain producer. Results are explicitly
non-actionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.application.redaction import redact_public_value
from migration_factory.control_tower.application.v2_repair_route_decision import (
    ROUTE_LLM_REVIEWED_UNKNOWN,
    RepairRouteDecision,
)
from migration_factory.orchestrator.repair_review_chain import (
    RepairReviewChainProductionError,
    produce_repair_review_chain,
)
from migration_factory.repair_loop.failure_evidence import FailureEvidence
from migration_factory.repair_loop.repair_context import RepairContextPack


EVENT_LLM_REVIEW_CHAIN_STARTED = "llm_review_chain_started"
EVENT_LLM_REVIEW_CHAIN_COMPLETED = "llm_review_chain_completed"
EVENT_LLM_REVIEW_CHAIN_BLOCKED = "llm_review_chain_blocked"

STATUS_STARTED = "started"
STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"

REASON_AUTHORIZED = "authorized_llm_reviewed_unknown"
REASON_ROUTE_NOT_AUTHORIZED = "route_not_llm_reviewed_unknown"
REASON_LLM_NOT_ELIGIBLE = "llm_not_eligible"
REASON_DETERMINISTIC_RULE_PRESENT = "deterministic_rule_present"
REASON_MISSING_FAILURE_EVIDENCE_JOB_ID = "missing_failure_evidence_job_id"
REASON_MISSING_FAILURE_EVIDENCE_COMMAND_ID = "missing_failure_evidence_command_id"
REASON_INVALID_FAILURE_EVIDENCE_STAGE_INDEX = "invalid_failure_evidence_stage_index"
REASON_MISSING_CONTEXT_JOB_ID = "missing_context_job_id"
REASON_MISSING_CONTEXT_COMMAND_ID = "missing_context_command_id"
REASON_INVALID_CONTEXT_STAGE_INDEX = "invalid_context_stage_index"
REASON_JOB_MISMATCH = "job_id_mismatch"
REASON_STAGE_MISMATCH = "stage_index_mismatch"
REASON_COMMAND_MISMATCH = "command_id_mismatch"
REASON_MISSING_EVIDENCE_CHECKSUM = "missing_failure_evidence_checksum"
REASON_MISSING_CONTEXT_CHECKSUM = "missing_context_checksum"
REASON_MISSING_BASE_REPO_STATE_CHECKSUM = "missing_base_repo_state_checksum"
REASON_EVIDENCE_CHECKSUM_MISMATCH = "failure_evidence_checksum_mismatch"
REASON_CONTEXT_CHECKSUM_MISMATCH = "context_checksum_mismatch"
REASON_BASE_REPO_STATE_CHECKSUM_MISMATCH = "base_repo_state_checksum_mismatch"
REASON_INVALID_DECISION_ATTEMPT_NUMBER = "invalid_decision_attempt_number"
REASON_INVALID_CYCLE_NUMBER = "invalid_cycle_number"
REASON_INVALID_MAX_CYCLES = "invalid_max_cycles"
REASON_ATTEMPT_MISMATCH = "attempt_number_mismatch"
REASON_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
REASON_EVENT_SINK_UNAVAILABLE = "event_sink_unavailable"
REASON_LEDGER_UNAVAILABLE = "invocation_ledger_unavailable"
REASON_REDACTION_FAILED = "event_payload_redaction_failed"
REASON_EVENT_SINK_FAILED = "event_sink_failed"
REASON_REVIEW_CHAIN_INVALID_RESULT = "review_chain_invalid_result"
REASON_REVIEW_CHAIN_PRODUCER_FAILED = "review_chain_producer_failed"

FAILURE_KIND_INVOCATION_LEDGER_UNAVAILABLE = "invocation_ledger_unavailable"
FAILURE_KIND_INVOCATION_LEDGER_START_FAILED = "invocation_ledger_start_failed"
FAILURE_KIND_PROPOSER_OUTPUT_TRUNCATED = "proposer_output_truncated"
FAILURE_KIND_PROPOSER_PROVIDER_FAILED = "proposer_provider_failed"
FAILURE_KIND_PROPOSER_SCHEMA_INVALID = "proposer_schema_invalid"
FAILURE_KIND_REVIEWER_OUTPUT_TRUNCATED = "reviewer_output_truncated"
FAILURE_KIND_REVIEWER_PROVIDER_FAILED = "reviewer_provider_failed"
FAILURE_KIND_REVIEWER_SCHEMA_INVALID = "reviewer_schema_invalid"
FAILURE_KIND_REVIEWER_REJECTED = "reviewer_rejected"
FAILURE_KIND_CANDIDATE_PERSISTENCE_FAILED = "candidate_persistence_failed"
FAILURE_KIND_REVIEW_CHAIN_PRODUCER_FAILED = "review_chain_producer_failed"

_ALLOWED_EVENT_PAYLOAD_KEYS = (
    "job_id",
    "stage_index",
    "command_id",
    "route",
    "status",
    "reason",
    "failure_evidence_checksum",
    "context_checksum",
    "base_repo_state_checksum",
    "attempt_number",
    "proposal_id",
    "gate_id",
    "primary_output_checksum",
    "reviewer_output_checksum",
    "reviewed_diff_checksum",
    "final_artifact_checksum",
    "failure_kind",
)


@dataclass(frozen=True, slots=True)
class UnknownRepairReviewChainResult:
    status: str
    reason: str
    route: str
    job_id: str
    stage_index: Any
    command_id: str
    failure_evidence_checksum: str
    context_checksum: str
    base_repo_state_checksum: str
    attempt_number: Any
    proposal_id: str | None = None
    gate_id: str | None = None
    primary_output_checksum: str = ""
    reviewer_output_checksum: str = ""
    reviewed_diff_checksum: str = ""
    final_artifact_checksum: str = ""
    failure_kind: str = ""
    non_actionable: bool = True


def run_unknown_repair_review_chain(
    *,
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    output_dir: str | Path,
    source_profile: str = "",
    target_profile: str = "",
    model_client: Any | None = None,
    invocation_ledger: Any | None = None,
    event_sink: Callable[..., None] | None = None,
    chain_result_sink: Callable[[dict[str, Any]], None] | None = None,
    proposal_id: str | None = None,
    gate_id: str | None = None,
) -> UnknownRepairReviewChainResult:
    """Authorize and run the unknown-family reviewed repair chain."""

    blocked_reason = _authorization_or_binding_block_reason(
        decision=decision,
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        event_sink=event_sink,
        invocation_ledger=invocation_ledger,
    )
    if blocked_reason:
        emit_blocked = (
            event_sink is not None
            and blocked_reason
            not in {
                REASON_MISSING_FAILURE_EVIDENCE_JOB_ID,
                REASON_MISSING_FAILURE_EVIDENCE_COMMAND_ID,
                REASON_INVALID_FAILURE_EVIDENCE_STAGE_INDEX,
            }
        )
        return _blocked_result(
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            reason=blocked_reason,
            event_sink=event_sink if emit_blocked else None,
            proposal_id=proposal_id,
            gate_id=gate_id,
        )

    started = _base_result(
        status=STATUS_STARTED,
        reason=REASON_AUTHORIZED,
        decision=decision,
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        proposal_id=proposal_id,
        gate_id=gate_id,
    )
    start_emit = _emit_event(
        event_sink=event_sink,
        event_type=EVENT_LLM_REVIEW_CHAIN_STARTED,
        result=started,
    )
    if start_emit != "":
        return _base_result(
            status=STATUS_BLOCKED,
            reason=start_emit,
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            proposal_id=proposal_id,
            gate_id=gate_id,
        )

    try:
        chain_result = produce_repair_review_chain(
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            output_dir=Path(output_dir),
            source_profile=source_profile,
            target_profile=target_profile,
            model_client=model_client,
            invocation_ledger=invocation_ledger,
            proposal_id=proposal_id,
            gate_id=gate_id,
            attempt_number=context_pack.cycle_number,
        )
    except Exception as exc:
        return _blocked_result(
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            reason=REASON_REVIEW_CHAIN_PRODUCER_FAILED,
            failure_kind=_classify_review_chain_failure(exc),
            event_sink=event_sink,
            proposal_id=proposal_id,
            gate_id=gate_id,
        )

    completed = _completed_result_from_chain(
        decision=decision,
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        chain_result=chain_result,
        proposal_id=proposal_id,
        gate_id=gate_id,
    )
    if completed is None:
        return _blocked_result(
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            reason=REASON_REVIEW_CHAIN_INVALID_RESULT,
            event_sink=event_sink,
            proposal_id=proposal_id,
            gate_id=gate_id,
        )
    if chain_result_sink is not None:
        chain_result_sink(chain_result)

    complete_emit = _emit_event(
        event_sink=event_sink,
        event_type=EVENT_LLM_REVIEW_CHAIN_COMPLETED,
        result=completed,
    )
    if complete_emit != "":
        return _base_result(
            status=STATUS_BLOCKED,
            reason=complete_emit,
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            proposal_id=proposal_id,
            gate_id=gate_id,
            primary_output_checksum=completed.primary_output_checksum,
            reviewer_output_checksum=completed.reviewer_output_checksum,
            reviewed_diff_checksum=completed.reviewed_diff_checksum,
            final_artifact_checksum=completed.final_artifact_checksum,
        )
    return completed


def _authorization_or_binding_block_reason(
    *,
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    event_sink: Callable[..., None] | None,
    invocation_ledger: Any | None,
) -> str:
    if decision.route != ROUTE_LLM_REVIEWED_UNKNOWN:
        return REASON_ROUTE_NOT_AUTHORIZED
    if decision.llm_eligible is not True:
        return REASON_LLM_NOT_ELIGIBLE
    if decision.deterministic_rule_id is not None:
        return REASON_DETERMINISTIC_RULE_PRESENT
    if not str(failure_evidence.job_id or "").strip():
        return REASON_MISSING_FAILURE_EVIDENCE_JOB_ID
    if not _valid_stage_index(failure_evidence.stage_index):
        return REASON_INVALID_FAILURE_EVIDENCE_STAGE_INDEX
    if not str(failure_evidence.command_id or "").strip():
        return REASON_MISSING_FAILURE_EVIDENCE_COMMAND_ID
    if not str(context_pack.job_id or "").strip():
        return REASON_MISSING_CONTEXT_JOB_ID
    if not _valid_stage_index(context_pack.stage_index):
        return REASON_INVALID_CONTEXT_STAGE_INDEX
    if not str(context_pack.command_id or "").strip():
        return REASON_MISSING_CONTEXT_COMMAND_ID
    if failure_evidence.job_id != context_pack.job_id:
        return REASON_JOB_MISMATCH
    if failure_evidence.stage_index != context_pack.stage_index:
        return REASON_STAGE_MISMATCH
    if failure_evidence.command_id != context_pack.command_id:
        return REASON_COMMAND_MISMATCH
    if not str(failure_evidence.content_checksum or "").strip():
        return REASON_MISSING_EVIDENCE_CHECKSUM
    if not str(context_pack.context_pack_checksum or "").strip():
        return REASON_MISSING_CONTEXT_CHECKSUM
    if not str(context_pack.base_repo_state_checksum or "").strip():
        return REASON_MISSING_BASE_REPO_STATE_CHECKSUM
    if decision.evidence_checksum != failure_evidence.content_checksum:
        return REASON_EVIDENCE_CHECKSUM_MISMATCH
    if decision.context_checksum != context_pack.context_pack_checksum:
        return REASON_CONTEXT_CHECKSUM_MISMATCH
    if decision.base_repo_state_checksum != context_pack.base_repo_state_checksum:
        return REASON_BASE_REPO_STATE_CHECKSUM_MISMATCH
    if not _valid_nonnegative_int(context_pack.cycle_number):
        return REASON_INVALID_CYCLE_NUMBER
    if not _valid_positive_int(context_pack.max_cycles):
        return REASON_INVALID_MAX_CYCLES
    if not _valid_nonnegative_int(decision.attempt_number):
        return REASON_INVALID_DECISION_ATTEMPT_NUMBER
    if decision.attempt_number != context_pack.cycle_number:
        return REASON_ATTEMPT_MISMATCH
    if context_pack.cycle_number >= context_pack.max_cycles:
        return REASON_ATTEMPTS_EXHAUSTED
    if event_sink is None:
        return REASON_EVENT_SINK_UNAVAILABLE
    if invocation_ledger is None:
        return REASON_LEDGER_UNAVAILABLE
    return ""


def _completed_result_from_chain(
    *,
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    chain_result: dict[str, Any],
    proposal_id: str | None,
    gate_id: str | None,
) -> UnknownRepairReviewChainResult | None:
    if not isinstance(chain_result, dict):
        return None
    chain = chain_result.get("review_chain")
    if not isinstance(chain, dict):
        return None
    if chain.get("reviewer_decision") != "accept":
        return None
    if chain.get("proposal_kind") != "llm_repair_review":
        return None
    if chain.get("context_pack_checksum") != context_pack.context_pack_checksum:
        return None
    if chain.get("job_id") != context_pack.job_id:
        return None
    if chain.get("stage_index") != context_pack.stage_index:
        return None
    primary_output_checksum = str(chain.get("primary_output_checksum") or "")
    reviewer_output_checksum = str(chain.get("reviewer_output_checksum") or "")
    proposed_diff_checksum = str(chain.get("proposed_diff_checksum") or "")
    raw_diff_bytes_checksum = str(chain.get("raw_diff_bytes_checksum") or "")
    final_reviewed_diff_checksum = str(chain.get("final_reviewed_diff_checksum") or "")
    final_artifact_checksum = str(chain.get("final_artifact_checksum") or "")
    if not all(
        (
            primary_output_checksum,
            reviewer_output_checksum,
            proposed_diff_checksum,
            raw_diff_bytes_checksum,
            final_reviewed_diff_checksum,
            final_artifact_checksum,
        )
    ):
        return None
    if proposed_diff_checksum != raw_diff_bytes_checksum or proposed_diff_checksum != final_reviewed_diff_checksum:
        return None
    if chain.get("primary_deterministic_fallback_used") is not False:
        return None
    if chain.get("reviewer_deterministic_fallback_used") is not False:
        return None
    return UnknownRepairReviewChainResult(
        status=STATUS_COMPLETED,
        reason=REASON_AUTHORIZED,
        route=decision.route,
        job_id=failure_evidence.job_id,
        stage_index=failure_evidence.stage_index,
        command_id=failure_evidence.command_id,
        failure_evidence_checksum=failure_evidence.content_checksum,
        context_checksum=context_pack.context_pack_checksum,
        base_repo_state_checksum=context_pack.base_repo_state_checksum,
        attempt_number=context_pack.cycle_number,
        proposal_id=proposal_id,
        gate_id=gate_id,
        primary_output_checksum=primary_output_checksum,
        reviewer_output_checksum=reviewer_output_checksum,
        reviewed_diff_checksum=final_reviewed_diff_checksum,
        final_artifact_checksum=final_artifact_checksum,
    )


def _blocked_result(
    *,
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    reason: str,
    event_sink: Callable[..., None] | None,
    proposal_id: str | None,
    gate_id: str | None,
    failure_kind: str = "",
) -> UnknownRepairReviewChainResult:
    result = _base_result(
        status=STATUS_BLOCKED,
        reason=reason,
        decision=decision,
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        proposal_id=proposal_id,
        gate_id=gate_id,
        failure_kind=failure_kind or _failure_kind_for_block_reason(reason),
    )
    emit_reason = _emit_event(
        event_sink=event_sink,
        event_type=EVENT_LLM_REVIEW_CHAIN_BLOCKED,
        result=result,
    )
    if emit_reason:
        return _base_result(
            status=STATUS_BLOCKED,
            reason=emit_reason,
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            proposal_id=proposal_id,
            gate_id=gate_id,
        )
    return result


def _base_result(
    *,
    status: str,
    reason: str,
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    proposal_id: str | None,
    gate_id: str | None,
    primary_output_checksum: str = "",
    reviewer_output_checksum: str = "",
    reviewed_diff_checksum: str = "",
    final_artifact_checksum: str = "",
    failure_kind: str = "",
) -> UnknownRepairReviewChainResult:
    return UnknownRepairReviewChainResult(
        status=status,
        reason=reason,
        route=decision.route,
        job_id=failure_evidence.job_id,
        stage_index=failure_evidence.stage_index,
        command_id=failure_evidence.command_id,
        failure_evidence_checksum=failure_evidence.content_checksum,
        context_checksum=context_pack.context_pack_checksum,
        base_repo_state_checksum=context_pack.base_repo_state_checksum,
        attempt_number=context_pack.cycle_number,
        proposal_id=proposal_id,
        gate_id=gate_id,
        primary_output_checksum=primary_output_checksum,
        reviewer_output_checksum=reviewer_output_checksum,
        reviewed_diff_checksum=reviewed_diff_checksum,
        final_artifact_checksum=final_artifact_checksum,
        failure_kind=failure_kind,
    )


def _emit_event(
    *,
    event_sink: Callable[..., None] | None,
    event_type: str,
    result: UnknownRepairReviewChainResult,
) -> str:
    if event_sink is None:
        return ""
    payload = _public_payload(result)
    if payload is None:
        return REASON_REDACTION_FAILED
    try:
        event_sink(
            job_id=result.job_id,
            stage=result.stage_index,
            event_type=event_type,
            status=result.status,
            message="LLM repair review chain event recorded.",
            payload=payload,
        )
    except Exception:
        return REASON_EVENT_SINK_FAILED
    return ""


def _public_payload(result: UnknownRepairReviewChainResult) -> dict[str, Any] | None:
    payload = {
        "job_id": result.job_id,
        "stage_index": result.stage_index,
        "command_id": result.command_id,
        "route": result.route,
        "status": result.status,
        "reason": result.reason,
        "failure_evidence_checksum": result.failure_evidence_checksum,
        "context_checksum": result.context_checksum,
        "base_repo_state_checksum": result.base_repo_state_checksum,
        "attempt_number": result.attempt_number,
        "proposal_id": result.proposal_id,
        "gate_id": result.gate_id,
        "primary_output_checksum": result.primary_output_checksum,
        "reviewer_output_checksum": result.reviewer_output_checksum,
        "reviewed_diff_checksum": result.reviewed_diff_checksum,
        "final_artifact_checksum": result.final_artifact_checksum,
        "failure_kind": result.failure_kind,
    }
    try:
        redacted = redact_public_value(payload)
    except Exception:
        return None
    if not isinstance(redacted, dict):
        return None
    return {
        key: redacted.get(key)
        for key in _ALLOWED_EVENT_PAYLOAD_KEYS
        if key in redacted and redacted.get(key) not in ("", None)
    }


def _valid_stage_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _valid_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _failure_kind_for_block_reason(reason: str) -> str:
    if reason == REASON_LEDGER_UNAVAILABLE:
        return FAILURE_KIND_INVOCATION_LEDGER_UNAVAILABLE
    if reason == REASON_REVIEW_CHAIN_INVALID_RESULT:
        return FAILURE_KIND_REVIEWER_SCHEMA_INVALID
    return ""


def _classify_review_chain_failure(exc: Exception) -> str:
    failure_code = str(getattr(exc, "failure_code", "") or "")
    if failure_code in {
        FAILURE_KIND_PROPOSER_OUTPUT_TRUNCATED,
        FAILURE_KIND_PROPOSER_SCHEMA_INVALID,
        FAILURE_KIND_PROPOSER_PROVIDER_FAILED,
        FAILURE_KIND_REVIEWER_OUTPUT_TRUNCATED,
        FAILURE_KIND_REVIEWER_SCHEMA_INVALID,
        FAILURE_KIND_REVIEWER_PROVIDER_FAILED,
        FAILURE_KIND_REVIEWER_REJECTED,
        FAILURE_KIND_INVOCATION_LEDGER_UNAVAILABLE,
        FAILURE_KIND_INVOCATION_LEDGER_START_FAILED,
    }:
        return failure_code
    text = str(exc).lower()
    if isinstance(exc, RepairReviewChainProductionError):
        if "mandatory invocation ledger unavailable" in text:
            return FAILURE_KIND_INVOCATION_LEDGER_UNAVAILABLE
        if "invocation ledger start failed" in text:
            return FAILURE_KIND_INVOCATION_LEDGER_START_FAILED
        if "primary repair model failed closed" in text:
            if _looks_schema_failure(text):
                return FAILURE_KIND_PROPOSER_SCHEMA_INVALID
            return FAILURE_KIND_PROPOSER_PROVIDER_FAILED
        if "primary deterministic fallback" in text:
            return FAILURE_KIND_PROPOSER_PROVIDER_FAILED
        if "primary repair chain failed closed" in text or "primary repair output" in text:
            return FAILURE_KIND_PROPOSER_SCHEMA_INVALID
        if "reviewer repair model failed closed" in text:
            if _looks_schema_failure(text):
                return FAILURE_KIND_REVIEWER_SCHEMA_INVALID
            return FAILURE_KIND_REVIEWER_PROVIDER_FAILED
        if "reviewer deterministic fallback" in text:
            return FAILURE_KIND_REVIEWER_PROVIDER_FAILED
        if "reviewer decision failed closed" in text:
            return FAILURE_KIND_REVIEWER_REJECTED
        if "reviewer repair chain failed closed" in text or "reviewer repair output" in text:
            return FAILURE_KIND_REVIEWER_SCHEMA_INVALID
    return FAILURE_KIND_REVIEW_CHAIN_PRODUCER_FAILED


def _looks_schema_failure(text: str) -> bool:
    return any(marker in text for marker in ("schema", "json", "object", "invalid", "checksum mismatch"))
