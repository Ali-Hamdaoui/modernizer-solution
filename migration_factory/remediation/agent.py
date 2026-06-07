from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import json
import yaml

from migration_factory.remediation.policy import (
    HUMAN_REVIEW_ONLY,
    LLM_DISABLED_REPORT_ONLY,
    LLM_PROPOSAL_ALLOWED,
    LlmPolicy,
)

AUTO_APPLY_DETERMINISTIC_CANDIDATE = "AUTO_APPLY_DETERMINISTIC_CANDIDATE"
NO_REMEDIATION_AVAILABLE = "NO_REMEDIATION_AVAILABLE"
DEPENDENCY_ALIGNMENT = "DEPENDENCY_ALIGNMENT"

_BEHAVIORAL_CATEGORIES = {
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
    "HTTP_STATUS_CONTRACT_DRIFT",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH",
    "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION",
    "APPLICATION_BEHAVIOR_REGRESSION",
    "UNKNOWN_TEST_FAILURE",
}
_DETERMINISTIC_RESULT_KINDS = {"dependency_error", "compilation_error", "missing_config"}
_DEFAULT_ACTIONS = {
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": "Review Spring MVC / exception handler contract under Boot 3.",
    "HTTP_STATUS_CONTRACT_DRIFT": "Review expected HTTP status and response contract under Boot 3.",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH": "Review Jakarta validation exception handling and advice mappings.",
    "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION": "Review Mockito final-class mocking strategy for migrated test stack.",
    "APPLICATION_BEHAVIOR_REGRESSION": "Review migrated behavior against baseline functional expectations.",
    "UNKNOWN_TEST_FAILURE": "Review failing stack trace manually and add deterministic classifier if pattern repeats.",
    DEPENDENCY_ALIGNMENT: "Review deterministic dependency alignment candidate before any application.",
}


@dataclass(frozen=True)
class RemediationCandidate:
    category: str
    safe_to_auto_apply: bool
    requires_human_approval: bool
    llm_candidate: bool
    recommended_action: str
    deterministic_rule: str = ""
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["deterministic_rule"]:
            payload.pop("deterministic_rule")
        return payload


@dataclass(frozen=True)
class RemediationPlanResult:
    path: Path
    payload: dict[str, Any]


def generate_remediation_plan(
    *,
    state: dict[str, Any],
    output_dir: str | Path,
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
    orchestration_summary: dict[str, Any] | None = None,
    migration_ledger: dict[str, Any] | None = None,
    migration_plan: dict[str, Any] | None = None,
) -> RemediationPlanResult:
    build_error_contract = build_error_contract or _read_optional_json(
        state.get("artifact_refs", {}).get("build_error_contract")
    )
    failure_classification = failure_classification or _read_optional_json(
        state.get("artifact_refs", {}).get("post_transform_failure_classification")
    )
    orchestration_summary = orchestration_summary or _read_optional_json(
        state.get("artifact_refs", {}).get("orchestration_summary")
    )
    migration_ledger = migration_ledger or _read_optional_json(
        state.get("artifact_refs", {}).get("migration_ledger")
    )
    migration_plan = migration_plan or _read_optional_yaml(
        state.get("artifact_refs", {}).get("migration_plan")
        or (Path(str(state.get("planning_dir") or "")) / "migration_plan.yaml")
    )

    candidates = _build_candidates(
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    )
    remediation_decision = _decide_remediation(candidates=candidates, llm_policy=llm_policy)
    blocked_reasons = _blocked_reasons(
        remediation_decision=remediation_decision,
        llm_policy=llm_policy,
        candidates=candidates,
    )
    recommended_next_actions = _recommended_next_actions(candidates, remediation_decision)
    failed_unit = _failed_unit(state, build_error_contract, migration_ledger)

    payload = {
        "run_id": str(state.get("run_id") or ""),
        "failed_unit": failed_unit,
        "final_status": str(state.get("final_status") or ""),
        "build_status": str(state.get("build_status") or ""),
        "test_status": str(state.get("test_status") or ""),
        "llm_policy": llm_policy.to_dict(),
        "human_review_required": True,
        "remediation_decision": remediation_decision,
        "remediation_candidates": [candidate.to_dict() for candidate in candidates],
        "blocked_reasons": blocked_reasons,
        "recommended_next_actions": recommended_next_actions,
        "category_counts": _category_counts(failure_classification),
        "build_error_contract_path": str(state.get("artifact_refs", {}).get("build_error_contract") or ""),
        "post_transform_failure_classification_path": str(
            state.get("artifact_refs", {}).get("post_transform_failure_classification") or ""
        ),
        "migration_ledger_path": str(state.get("artifact_refs", {}).get("migration_ledger") or ""),
        "orchestration_summary_path": str(state.get("artifact_refs", {}).get("orchestration_summary") or ""),
        "migration_plan_path": str(state.get("artifact_refs", {}).get("migration_plan") or ""),
        "completed_units": list((migration_ledger or {}).get("completed_units", []) or []),
        "selected_route_id": str((migration_plan or {}).get("selected_route_id") or ""),
        "route_strategy": str((migration_plan or {}).get("route_strategy") or ""),
        "orchestration_status": str(
            (orchestration_summary or {}).get("orchestration_status") or state.get("orchestration_status") or ""
        ),
    }

    output_path = Path(output_dir).expanduser().resolve() / "remediation_plan.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return RemediationPlanResult(path=output_path, payload=payload)


def decide_remediation_v1(
    *,
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
) -> str:
    candidates = _build_candidates(
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    )
    return _decide_remediation(candidates=candidates, llm_policy=llm_policy)


def _build_candidates(
    *,
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
) -> list[RemediationCandidate]:
    candidates: list[RemediationCandidate] = []
    category_counts = _category_counts(failure_classification)
    failures = list((failure_classification or {}).get("failures", []) or [])
    for category, count in category_counts.items():
        llm_candidate = category in _BEHAVIORAL_CATEGORIES
        evidence = _category_evidence(category, failures, limit=3)
        candidates.append(
            RemediationCandidate(
                category=category,
                safe_to_auto_apply=False,
                requires_human_approval=True,
                llm_candidate=llm_candidate,
                recommended_action=_DEFAULT_ACTIONS.get(category, _DEFAULT_ACTIONS["UNKNOWN_TEST_FAILURE"]),
                evidence=evidence + [f"count={count}"],
            )
        )

    if candidates:
        return candidates

    result_kind = str((build_error_contract or {}).get("result_kind") or "")
    message = str((build_error_contract or {}).get("message") or "")
    if result_kind in _DETERMINISTIC_RESULT_KINDS:
        return [
            RemediationCandidate(
                category=DEPENDENCY_ALIGNMENT,
                safe_to_auto_apply=True,
                requires_human_approval=False,
                llm_candidate=False,
                recommended_action=_DEFAULT_ACTIONS[DEPENDENCY_ALIGNMENT],
                deterministic_rule="align_dependency_versions",
                evidence=[result_kind, message] if message else [result_kind],
            )
        ]
    return []


def _decide_remediation(*, candidates: list[RemediationCandidate], llm_policy: LlmPolicy) -> str:
    if any(candidate.safe_to_auto_apply for candidate in candidates):
        return AUTO_APPLY_DETERMINISTIC_CANDIDATE
    if any(candidate.llm_candidate for candidate in candidates):
        if not llm_policy.enabled:
            return LLM_DISABLED_REPORT_ONLY
        return LLM_PROPOSAL_ALLOWED if llm_policy.require_human_approval else HUMAN_REVIEW_ONLY
    if candidates:
        return HUMAN_REVIEW_ONLY
    return NO_REMEDIATION_AVAILABLE


def _blocked_reasons(
    *,
    remediation_decision: str,
    llm_policy: LlmPolicy,
    candidates: list[RemediationCandidate],
) -> list[str]:
    reasons: list[str] = []
    if remediation_decision == LLM_DISABLED_REPORT_ONLY:
        reasons.append("LLM remediation disabled by policy.")
    if remediation_decision == LLM_PROPOSAL_ALLOWED:
        reasons.append("Human approval required before any future LLM proposal workflow.")
    if remediation_decision == HUMAN_REVIEW_ONLY:
        reasons.append("Candidate remediation requires human review.")
    if remediation_decision == NO_REMEDIATION_AVAILABLE:
        reasons.append("No deterministic or policy-allowed remediation candidate identified.")
    if any(candidate.llm_candidate for candidate in candidates):
        reasons.append("Behavioral drift categories are not safe for automatic patching in v1.")
    if llm_policy.forbidden_actions:
        reasons.append("Forbidden actions active: " + ", ".join(llm_policy.forbidden_actions))
    return reasons


def _recommended_next_actions(
    candidates: list[RemediationCandidate],
    remediation_decision: str,
) -> list[str]:
    actions: list[str] = []
    for candidate in candidates:
        if candidate.recommended_action not in actions:
            actions.append(candidate.recommended_action)
    if remediation_decision == AUTO_APPLY_DETERMINISTIC_CANDIDATE:
        actions.append("Prepare deterministic remediation rule review before any separate apply phase.")
    elif remediation_decision in {HUMAN_REVIEW_ONLY, LLM_DISABLED_REPORT_ONLY, LLM_PROPOSAL_ALLOWED}:
        actions.append("Review remediation candidates and approve next controlled migration ticket.")
    elif remediation_decision == NO_REMEDIATION_AVAILABLE:
        actions.append("Review build/test evidence manually and extend deterministic remediation catalog if pattern repeats.")
    return actions


def _failed_unit(
    state: dict[str, Any],
    build_error_contract: dict[str, Any] | None,
    migration_ledger: dict[str, Any] | None,
) -> str:
    for value in (
        (build_error_contract or {}).get("unit_id"),
        (migration_ledger or {}).get("blocked_unit"),
        state.get("current_unit"),
        state.get("current_phase"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _category_counts(failure_classification: dict[str, Any] | None) -> dict[str, int]:
    counts = (failure_classification or {}).get("category_counts")
    if not isinstance(counts, dict):
        return {}
    return {str(key): int(value) for key, value in counts.items()}


def _category_evidence(category: str, failures: list[Any], *, limit: int) -> list[str]:
    evidence: list[str] = []
    for item in failures:
        if not isinstance(item, dict) or str(item.get("category") or "") != category:
            continue
        evidence.append(
            f"{item.get('test_class', '')}.{item.get('test_method', '')}: {item.get('symptom', '')}".strip()
        )
        if len(evidence) >= limit:
            break
    return evidence


def _read_optional_json(path_like: Any) -> dict[str, Any] | None:
    path_text = str(path_like or "").strip()
    if not path_text:
        return None
    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_optional_yaml(path_like: Any) -> dict[str, Any] | None:
    path = Path(str(path_like or "")).expanduser()
    if not str(path_like or "").strip() or not path.is_file():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return payload if isinstance(payload, dict) else None
