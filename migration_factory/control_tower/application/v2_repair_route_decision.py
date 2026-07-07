"""Canonical backend-owned repair route decisions for WF-02A.

This module is intentionally pure for selection: callers must pass already
normalized classification, evidence checksums, context checksums, attempt
bindings, and explicit backend policy signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from migration_factory.control_tower.application.redaction import redact_public_value
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    BACKEND_RECIPE,
    JACKSON_BACKEND_RECIPE,
    JACKSON_FAMILY,
    SORT_BACKEND_RECIPE,
    SORT_FAMILY,
    SUPPORTED_FAMILY,
)
from migration_factory.control_tower.application.v2_repair_family_registry import (
    RepairFamilyPolicy,
    registered_repair_families,
    repair_family_policy,
)


ROUTE_DETERMINISTIC_RECIPE = "deterministic_recipe"
ROUTE_LLM_REVIEWED_UNKNOWN = "llm_reviewed_unknown"
ROUTE_BLOCKED_MISSING_EVIDENCE = "blocked_missing_evidence"
ROUTE_BLOCKED_SENSITIVE_SCOPE = "blocked_sensitive_scope"
ROUTE_BLOCKED_TOOLCHAIN = "blocked_toolchain"
ROUTE_BLOCKED_ATTEMPTS_EXHAUSTED = "blocked_attempts_exhausted"
ROUTE_BLOCKED_UNSUPPORTED = "blocked_unsupported"

SELECTED_ROUTES = frozenset({
    ROUTE_DETERMINISTIC_RECIPE,
    ROUTE_LLM_REVIEWED_UNKNOWN,
})
BLOCKED_ROUTES = frozenset({
    ROUTE_BLOCKED_MISSING_EVIDENCE,
    ROUTE_BLOCKED_SENSITIVE_SCOPE,
    ROUTE_BLOCKED_TOOLCHAIN,
    ROUTE_BLOCKED_ATTEMPTS_EXHAUSTED,
    ROUTE_BLOCKED_UNSUPPORTED,
})
ALLOWED_ROUTES = SELECTED_ROUTES | BLOCKED_ROUTES

REASON_DETERMINISTIC_RECIPE_AVAILABLE = "deterministic_recipe_available"
REASON_LLM_UNKNOWN_ELIGIBLE = "llm_unknown_eligible"
REASON_SENSITIVE_SCOPE_BLOCKED = "sensitive_scope_blocked"
REASON_TOOLCHAIN_BLOCKED = "toolchain_blocked"
REASON_ATTEMPTS_EXHAUSTED = "attempts_exhausted"
REASON_MISSING_EVIDENCE_CHECKSUM = "missing_evidence_checksum"
REASON_MISSING_CONTEXT_CHECKSUM = "missing_context_checksum"
REASON_MISSING_BASE_REPO_STATE_CHECKSUM = "missing_base_repo_state_checksum"
REASON_MISSING_CLASSIFICATION = "missing_classification"
REASON_MISSING_ATTEMPT_BINDING = "missing_attempt_binding"
REASON_CLASSIFICATION_PENDING_EVIDENCE = "classification_pending_evidence"
REASON_MISSING_POLICY_EVIDENCE = "missing_policy_evidence"
REASON_UNSUPPORTED_KNOWN_FAILURE = "unsupported_known_failure"
REASON_FAMILY_NOT_REGISTERED = "family_not_registered"
REASON_BACKEND_RECIPE_UNAVAILABLE = "backend_recipe_unavailable"
REASON_DETERMINISTIC_RULE_ID_MISSING = "deterministic_rule_id_missing"
REASON_HUMAN_REVIEW_GATE = "human_review_gate"
REASON_INCONSISTENT_CLASSIFICATION = "inconsistent_classification"
REASON_LLM_UNKNOWN_POLICY_UNAVAILABLE = "llm_unknown_policy_unavailable"
REASON_LLM_UNKNOWN_STAGE_UNSUPPORTED = "llm_unknown_stage_unsupported"
REASON_UNSUPPORTED_ROUTE = "unsupported_route"

UNKNOWN_STATUSES = frozenset({"unknown", "ambiguous"})
KNOWN_STATUSES = frozenset({"known_family_candidate"})
PENDING_EVIDENCE_STATUSES = frozenset({"blocked_pending_evidence"})
UNSUPPORTED_STATUSES = frozenset({"unsupported_known_failure"})

_DETERMINISTIC_RULE_IDS = {
    SUPPORTED_FAMILY: BACKEND_RECIPE,
    SORT_FAMILY: SORT_BACKEND_RECIPE,
    JACKSON_FAMILY: JACKSON_BACKEND_RECIPE,
}

_ALLOWED_PAYLOAD_KEYS = (
    "job_id",
    "stage_index",
    "command_id",
    "route",
    "reason",
    "failure_type",
    "classification_status",
    "evidence_checksum",
    "context_checksum",
    "base_repo_state_checksum",
    "deterministic_rule_id",
    "llm_eligible",
    "attempt_number",
)


@dataclass(frozen=True, slots=True)
class RepairRouteDecision:
    route: str
    reason: str
    failure_type: str
    classification_status: str
    evidence_checksum: str
    context_checksum: str
    base_repo_state_checksum: str
    deterministic_rule_id: str | None
    llm_eligible: bool
    attempt_number: int


def select_repair_route_decision(
    *,
    job_id: str,
    stage_index: int,
    command_id: str,
    classification: dict[str, Any] | None,
    evidence_checksum: str,
    context_checksum: str,
    base_repo_state_checksum: str,
    attempt_number: int | None,
    max_attempts: int | None,
    sensitive_scope_blocked: bool = False,
    toolchain_blocked: bool = False,
    available_evidence: tuple[str, ...] = (),
) -> RepairRouteDecision:
    """Select exactly one canonical repair route.

    Attempt convention follows existing repair context naming: `cycle_number`
    is 0-based and is passed here as `attempt_number`; `max_cycles` is passed
    as `max_attempts`. Exhausted means `attempt_number >= max_attempts`.
    """

    _validate_correlation(job_id=job_id, stage_index=stage_index, command_id=command_id)
    _validate_attempt_binding(attempt_number=attempt_number, max_attempts=max_attempts)
    classification = classification if isinstance(classification, dict) else None
    status = _classification_status(classification)
    failure_type = _failure_type(classification)

    if sensitive_scope_blocked:
        return _decision(
            route=ROUTE_BLOCKED_SENSITIVE_SCOPE,
            reason=REASON_SENSITIVE_SCOPE_BLOCKED,
            failure_type=failure_type,
            classification_status=status,
            evidence_checksum=evidence_checksum,
            context_checksum=context_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            deterministic_rule_id=None,
            llm_eligible=False,
            attempt_number=attempt_number,
        )
    if toolchain_blocked:
        return _decision(
            route=ROUTE_BLOCKED_TOOLCHAIN,
            reason=REASON_TOOLCHAIN_BLOCKED,
            failure_type=failure_type,
            classification_status=status,
            evidence_checksum=evidence_checksum,
            context_checksum=context_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            deterministic_rule_id=None,
            llm_eligible=False,
            attempt_number=attempt_number,
        )
    if _attempts_exhausted(attempt_number, max_attempts):
        return _decision(
            route=ROUTE_BLOCKED_ATTEMPTS_EXHAUSTED,
            reason=REASON_ATTEMPTS_EXHAUSTED,
            failure_type=failure_type,
            classification_status=status,
            evidence_checksum=evidence_checksum,
            context_checksum=context_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            deterministic_rule_id=None,
            llm_eligible=False,
            attempt_number=attempt_number,
        )

    missing_reason = _missing_evidence_reason(
        classification=classification,
        evidence_checksum=evidence_checksum,
        context_checksum=context_checksum,
        base_repo_state_checksum=base_repo_state_checksum,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        available_evidence=available_evidence,
    )
    if missing_reason:
        return _decision(
            route=ROUTE_BLOCKED_MISSING_EVIDENCE,
            reason=missing_reason,
            failure_type=failure_type,
            classification_status=status,
            evidence_checksum=evidence_checksum,
            context_checksum=context_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            deterministic_rule_id=None,
            llm_eligible=False,
            attempt_number=attempt_number,
        )

    family = _exact_family(classification)
    exact_registered = family in set(registered_repair_families())
    if status in UNSUPPORTED_STATUSES:
        return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_UNSUPPORTED_KNOWN_FAILURE)
    if classification and str(classification.get("governance_gate_type") or "") == "human_review_gate":
        return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_HUMAN_REVIEW_GATE)
    if status in KNOWN_STATUSES and not exact_registered:
        return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_FAMILY_NOT_REGISTERED)

    deterministic = _deterministic_rule_id_for_family(family) if exact_registered else None
    if status in KNOWN_STATUSES:
        policy = repair_family_policy(family)
        if not _stage_applicable(policy, stage_index):
            return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_UNSUPPORTED_ROUTE)
        if not policy.backend_recipe_available:
            return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_BACKEND_RECIPE_UNAVAILABLE)
        if deterministic is None:
            return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_DETERMINISTIC_RULE_ID_MISSING)
        if _looks_unknown_like(classification):
            return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_INCONSISTENT_CLASSIFICATION)
        return _decision(
            route=ROUTE_DETERMINISTIC_RECIPE,
            reason=REASON_DETERMINISTIC_RECIPE_AVAILABLE,
            failure_type=failure_type,
            classification_status=status,
            evidence_checksum=evidence_checksum,
            context_checksum=context_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            deterministic_rule_id=deterministic,
            llm_eligible=False,
            attempt_number=attempt_number,
        )

    if status in UNKNOWN_STATUSES:
        unknown_policy = repair_family_policy("UNKNOWN_FAILURE")
        if not _stage_applicable(unknown_policy, stage_index):
            return _unsupported(
                failure_type,
                status,
                evidence_checksum,
                context_checksum,
                base_repo_state_checksum,
                attempt_number,
                REASON_LLM_UNKNOWN_STAGE_UNSUPPORTED,
            )
        if (
            unknown_policy.llm_proposer_enabled
            and unknown_policy.llm_reviewer_required
            and unknown_policy.fallback_enabled
        ):
            return _decision(
                route=ROUTE_LLM_REVIEWED_UNKNOWN,
                reason=REASON_LLM_UNKNOWN_ELIGIBLE,
                failure_type=failure_type,
                classification_status=status,
                evidence_checksum=evidence_checksum,
                context_checksum=context_checksum,
                base_repo_state_checksum=base_repo_state_checksum,
                deterministic_rule_id=None,
                llm_eligible=True,
                attempt_number=attempt_number,
            )
        return _unsupported(
            failure_type,
            status,
            evidence_checksum,
            context_checksum,
            base_repo_state_checksum,
            attempt_number,
            REASON_LLM_UNKNOWN_POLICY_UNAVAILABLE,
        )

    return _unsupported(failure_type, status, evidence_checksum, context_checksum, base_repo_state_checksum, attempt_number, REASON_UNSUPPORTED_ROUTE)


def emit_repair_route_decision(
    *,
    event_sink: Callable[..., None],
    job_id: str,
    stage_index: int,
    command_id: str,
    decision: RepairRouteDecision,
) -> None:
    """Emit one narrow allow-listed public event for a correlated decision."""

    _validate_correlation(job_id=job_id, stage_index=stage_index, command_id=command_id)
    if decision.route not in ALLOWED_ROUTES:
        raise ValueError("invalid_repair_route")
    event_type = "repair_route_selected" if decision.route in SELECTED_ROUTES else "repair_route_blocked"
    payload = _public_payload(job_id=job_id, stage_index=stage_index, command_id=command_id, decision=decision)
    event_sink(
        job_id=job_id,
        stage=stage_index,
        event_type=event_type,
        status="completed" if event_type == "repair_route_selected" else "blocked",
        message="Repair route decision recorded.",
        payload=payload,
    )


def _public_payload(
    *,
    job_id: str,
    stage_index: int,
    command_id: str,
    decision: RepairRouteDecision,
) -> dict[str, Any]:
    payload = {
        "job_id": job_id,
        "stage_index": stage_index,
        "command_id": command_id,
        "route": decision.route,
        "reason": decision.reason,
        "failure_type": decision.failure_type,
        "classification_status": decision.classification_status,
        "evidence_checksum": decision.evidence_checksum,
        "context_checksum": decision.context_checksum,
        "base_repo_state_checksum": decision.base_repo_state_checksum,
        "deterministic_rule_id": decision.deterministic_rule_id,
        "llm_eligible": decision.llm_eligible,
        "attempt_number": decision.attempt_number,
    }
    redacted = redact_public_value(payload)
    if not isinstance(redacted, dict):
        raise ValueError("repair_route_payload_redaction_failed")
    return {key: redacted.get(key) for key in _ALLOWED_PAYLOAD_KEYS if key in redacted}


def _validate_correlation(*, job_id: str, stage_index: int, command_id: str) -> None:
    if not str(job_id or "").strip():
        raise ValueError("missing_required_correlation:job_id")
    if not isinstance(stage_index, int) or isinstance(stage_index, bool) or stage_index < 1:
        raise ValueError("missing_required_correlation:stage_index")
    if not str(command_id or "").strip():
        raise ValueError("missing_required_correlation:command_id")


def _validate_attempt_binding(*, attempt_number: int | None, max_attempts: int | None) -> None:
    if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 0:
        raise ValueError("invalid_attempt_binding:attempt_number")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts <= 0:
        raise ValueError("invalid_attempt_binding:max_attempts")


def _decision(
    *,
    route: str,
    reason: str,
    failure_type: str,
    classification_status: str,
    evidence_checksum: str,
    context_checksum: str,
    base_repo_state_checksum: str,
    deterministic_rule_id: str | None,
    llm_eligible: bool,
    attempt_number: int,
) -> RepairRouteDecision:
    return RepairRouteDecision(
        route=route,
        reason=reason,
        failure_type=failure_type,
        classification_status=classification_status,
        evidence_checksum=str(evidence_checksum or ""),
        context_checksum=str(context_checksum or ""),
        base_repo_state_checksum=str(base_repo_state_checksum or ""),
        deterministic_rule_id=deterministic_rule_id,
        llm_eligible=bool(llm_eligible),
        attempt_number=attempt_number,
    )


def _classification_status(classification: dict[str, Any] | None) -> str:
    return str((classification or {}).get("classification_status") or "")


def _failure_type(classification: dict[str, Any] | None) -> str:
    return str((classification or {}).get("failure_type") or "")


def _exact_family(classification: dict[str, Any] | None) -> str:
    data = classification or {}
    return str(data.get("repair_family_candidate") or data.get("failure_type") or "")


def _attempts_exhausted(attempt_number: int, max_attempts: int) -> bool:
    return attempt_number >= max_attempts


def _missing_evidence_reason(
    *,
    classification: dict[str, Any] | None,
    evidence_checksum: str,
    context_checksum: str,
    base_repo_state_checksum: str,
    attempt_number: int,
    max_attempts: int,
    available_evidence: tuple[str, ...],
) -> str:
    if not str(evidence_checksum or "").strip():
        return REASON_MISSING_EVIDENCE_CHECKSUM
    if not str(context_checksum or "").strip():
        return REASON_MISSING_CONTEXT_CHECKSUM
    if not str(base_repo_state_checksum or "").strip():
        return REASON_MISSING_BASE_REPO_STATE_CHECKSUM
    if classification is None:
        return REASON_MISSING_CLASSIFICATION
    status = _classification_status(classification)
    if status in PENDING_EVIDENCE_STATUSES:
        return REASON_CLASSIFICATION_PENDING_EVIDENCE
    missing = classification.get("missing_required_evidence")
    if isinstance(missing, (list, tuple)) and any(str(item).strip() for item in missing):
        return REASON_MISSING_POLICY_EVIDENCE
    if str(classification.get("evidence_status") or "") in {"partial", "incomplete"}:
        return REASON_CLASSIFICATION_PENDING_EVIDENCE
    policy = repair_family_policy(_exact_family(classification))
    if _classification_status(classification) in KNOWN_STATUSES | UNKNOWN_STATUSES:
        if _missing_policy_evidence(policy, available_evidence, classification):
            return REASON_MISSING_POLICY_EVIDENCE
    return ""


def _missing_policy_evidence(
    policy: RepairFamilyPolicy,
    available_evidence: tuple[str, ...],
    classification: dict[str, Any],
) -> bool:
    available = _normalized_evidence_kinds(available_evidence)
    available.update(_normalized_evidence_kinds(classification.get("usable_artifacts", ())))
    return any(required not in available for required in policy.evidence_required)


def _normalized_evidence_kinds(value: Any) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        return set()
    result: set[str] = set()
    for item in value:
        if isinstance(item, str) and item.strip():
            result.add(item)
        elif isinstance(item, dict):
            kind = item.get("kind")
            if isinstance(kind, str) and kind.strip():
                result.add(kind)
    return result


def _stage_applicable(policy: RepairFamilyPolicy, stage_index: int) -> bool:
    return f"stage_{stage_index}" in policy.stage_applicability


def _deterministic_rule_id_for_family(family: str) -> str | None:
    return _DETERMINISTIC_RULE_IDS.get(family)


def _looks_unknown_like(classification: dict[str, Any] | None) -> bool:
    data = classification or {}
    metadata = str(data.get("governance_gate_type") or "").lower()
    return metadata in {"unknown", "ambiguous"} or str(data.get("failure_type") or "").lower() in {"unknown", "ambiguous"}


def _unsupported(
    failure_type: str,
    status: str,
    evidence_checksum: str,
    context_checksum: str,
    base_repo_state_checksum: str,
    attempt_number: int,
    reason: str,
) -> RepairRouteDecision:
    return _decision(
        route=ROUTE_BLOCKED_UNSUPPORTED,
        reason=reason,
        failure_type=failure_type,
        classification_status=status,
        evidence_checksum=evidence_checksum,
        context_checksum=context_checksum,
        base_repo_state_checksum=base_repo_state_checksum,
        deterministic_rule_id=None,
        llm_eligible=False,
        attempt_number=attempt_number,
    )
