from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from migration_factory.remediation.policy import LlmPolicy


AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE = "AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE"
APPROVED_PATCH_APPLIED_RERUN_FAILED = "APPROVED_PATCH_APPLIED_RERUN_FAILED"
ESCALATE_TO_LLM_PROPOSAL = "ESCALATE_TO_LLM_PROPOSAL"
HUMAN_REVIEW_ONLY = "HUMAN_REVIEW_ONLY"
LLM_DISABLED_HUMAN_REVIEW_REQUIRED = "LLM_DISABLED_HUMAN_REVIEW_REQUIRED"
NO_BEHAVIORAL_REMEDIATION_NEEDED = "NO_BEHAVIORAL_REMEDIATION_NEEDED"
STOP_REPEATED_BEHAVIORAL_PATCH_CHASING = "STOP_REPEATED_BEHAVIORAL_PATCH_CHASING"
BEHAVIORAL_REMEDIATION_STRATEGY_GATE = "BEHAVIORAL_REMEDIATION_STRATEGY_ROUTER"

_BEHAVIORAL_CATEGORIES = {
    "APPLICATION_BEHAVIOR_REGRESSION",
    "HTTP_STATUS_CONTRACT_DRIFT",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH",
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
    "UNKNOWN_TEST_FAILURE",
}


@dataclass(frozen=True)
class BehavioralRemediationStrategyResult:
    __test__ = False
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]
    warning: str


def generate_behavioral_remediation_strategy(
    *,
    run_dir: str | Path,
    behavioral_failure_context_pack_path: str | Path | None = None,
    legacy_behavior_equivalence_report_path: str | Path | None = None,
    test_context_repair_proposal_path: str | Path | None = None,
    legacy_guided_patch_proposal_path: str | Path | None = None,
    mockito_bean_placement_report_path: str | Path | None = None,
    approved_patch_apply_result_path: str | Path | None = None,
    remediation_attempts_path: str | Path | None = None,
    orchestration_summary_path: str | Path | None = None,
    llm_policy: LlmPolicy | None = None,
    behavioral_failure_context_pack: dict[str, Any] | None = None,
    legacy_behavior_equivalence_report: dict[str, Any] | None = None,
    test_context_repair_proposal: dict[str, Any] | None = None,
    legacy_guided_patch_proposal: dict[str, Any] | None = None,
    mockito_bean_placement_report: dict[str, Any] | None = None,
    approved_patch_apply_result: dict[str, Any] | None = None,
    remediation_attempts: dict[str, Any] | None = None,
    orchestration_summary: dict[str, Any] | None = None,
) -> BehavioralRemediationStrategyResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    context_pack = behavioral_failure_context_pack or _read_optional_json(
        behavioral_failure_context_pack_path or remediation_dir / "behavioral_failure_context_pack.json"
    ) or {}
    equivalence = legacy_behavior_equivalence_report or _read_optional_json(
        legacy_behavior_equivalence_report_path or remediation_dir / "legacy_behavior_equivalence_report.json"
    ) or {}
    repair = test_context_repair_proposal or _read_optional_json(
        test_context_repair_proposal_path or remediation_dir / "test_context_repair_proposal.json"
    ) or {}
    guided = legacy_guided_patch_proposal or _read_optional_json(
        legacy_guided_patch_proposal_path or remediation_dir / "legacy_guided_patch_proposal.json"
    ) or {}
    mockito = mockito_bean_placement_report or _read_optional_json(
        mockito_bean_placement_report_path or remediation_dir / "mockito_bean_placement_report.json"
    ) or {}
    approved = approved_patch_apply_result or _read_optional_json(
        approved_patch_apply_result_path or remediation_dir / "approved_patch_apply_result.json"
    ) or {}
    attempts = remediation_attempts or _read_optional_json(
        remediation_attempts_path or remediation_dir / "remediation_attempts.json"
    ) or {}
    orchestration = orchestration_summary or _read_optional_json(
        orchestration_summary_path or run_root / "orchestration" / "orchestration_summary.json"
    ) or {}
    policy_provided = llm_policy is not None
    policy = llm_policy if policy_provided else LlmPolicy()

    current_blocker_category = _primary_category(context_pack, orchestration)
    behavioral_case = _is_behavioral_case(context_pack, current_blocker_category)
    deterministic_fixes = list(context_pack.get("deterministic_fixes_already_applied") or [])
    approved_patch_applied = str(approved.get("status") or "") in {"applied", "already_applied"}
    rerun = dict(approved.get("rerun") or {})
    rerun_failed = approved_patch_applied and bool(rerun.get("attempted")) and int(rerun.get("exit_code", 0) or 0) != 0
    repeated_same_blocker = bool(rerun_failed and _same_blocker_detected(context_pack, rerun, run_root))
    deterministic_proposal_available = _deterministic_proposal_available(repair, guided, mockito)
    failed_unit = str(
        approved.get("failed_unit_id")
        or approved.get("failed_unit")
        or ""
    ).strip() or str(
        context_pack.get("failed_unit")
        or mockito.get("failed_unit")
        or guided.get("failed_unit")
        or repair.get("failed_unit")
        or equivalence.get("failed_unit")
        or orchestration.get("current_unit")
        or orchestration.get("current_phase")
        or ""
    )

    decision, reason = _route_decision(
        behavioral_case=behavioral_case,
        deterministic_proposal_available=deterministic_proposal_available,
        approved_patch_applied=approved_patch_applied,
        repeated_same_blocker=repeated_same_blocker,
        policy=policy,
        policy_provided=policy_provided,
        current_blocker_category=current_blocker_category,
    )

    payload = {
        "run_id": str(
            context_pack.get("run_id")
            or orchestration.get("run_id")
            or mockito.get("run_id")
            or run_root.name
        ),
        "gate_id": BEHAVIORAL_REMEDIATION_STRATEGY_GATE,
        "decision": decision,
        "reason": reason,
        "current_blocker_category": current_blocker_category,
        "failed_unit": failed_unit,
        "is_behavioral_test_context_case": behavioral_case,
        "deterministic_fixes_already_applied": deterministic_fixes,
        "deterministic_proposal_available": deterministic_proposal_available,
        "human_approved_behavioral_patch_already_applied": approved_patch_applied,
        "approved_patch_apply_result_path": str(
            _resolve_path(approved_patch_apply_result_path or remediation_dir / "approved_patch_apply_result.json") or ""
        ),
        "approved_patch_rerun_failed": rerun_failed,
        "repeated_same_blocker": repeated_same_blocker,
        "patch_chasing_should_stop": repeated_same_blocker,
        "llm_policy": policy.to_dict(),
        "llm_proposal_recommended": decision == ESCALATE_TO_LLM_PROPOSAL,
        "human_review_only_required": decision in {
            HUMAN_REVIEW_ONLY,
            LLM_DISABLED_HUMAN_REVIEW_REQUIRED,
            STOP_REPEATED_BEHAVIORAL_PATCH_CHASING,
        },
        "safe_to_auto_apply": False,
        "production_promotion_allowed": False,
        "sandbox_only": True,
        "human_approval_required": True,
        "expected_future_artifacts": _expected_future_artifacts(decision),
        "model_1_role": "remediation_proposer",
        "model_2_role": "remediation_reviewer_optimizer",
        "model_2_input_requires": [
            "original context pack",
            "model 1 proposal",
            "risk constraints",
            "allowed patch scope",
        ],
        "review_gates_already_triggered": _review_gates(orchestration, context_pack),
        "recommended_next_actions": _recommended_next_actions(
            decision=decision,
            failed_unit=failed_unit,
            current_blocker_category=current_blocker_category,
            repeated_same_blocker=repeated_same_blocker,
        ),
        "warnings": _warnings(
            decision=decision,
            repeated_same_blocker=repeated_same_blocker,
            policy=policy,
        ),
    }

    report_path = remediation_dir / "behavioral_remediation_strategy.json"
    summary_path = remediation_dir / "behavioral_remediation_strategy.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path)

    warning = ""
    if behavioral_case:
        warning = "Behavioral remediation strategy generated; human review remains required before any additional behavioral patching."
    return BehavioralRemediationStrategyResult(
        report_path=report_path,
        summary_path=summary_path,
        payload=payload,
        warning=warning,
    )


def _route_decision(
    *,
    behavioral_case: bool,
    deterministic_proposal_available: bool,
    approved_patch_applied: bool,
    repeated_same_blocker: bool,
    policy: LlmPolicy,
    policy_provided: bool,
    current_blocker_category: str,
) -> tuple[str, str]:
    if not behavioral_case:
        return (
            NO_BEHAVIORAL_REMEDIATION_NEEDED,
            "Current failure is not classified as behavioral/test-context remediation work.",
        )
    if approved_patch_applied and repeated_same_blocker:
        if policy.enabled and _llm_allowed_for_category(policy, current_blocker_category):
            return (
                ESCALATE_TO_LLM_PROPOSAL,
                "Approved behavioral patch rerun failed with the same blocker; escalate to governed two-model LLM proposal flow.",
            )
        if policy_provided and not policy.enabled:
            return (
                LLM_DISABLED_HUMAN_REVIEW_REQUIRED,
                "Approved behavioral patch rerun failed with the same blocker and LLM proposals are disabled by policy.",
            )
        return (
            STOP_REPEATED_BEHAVIORAL_PATCH_CHASING,
            "Approved behavioral patch rerun failed with the same blocker; stop repeated patch chasing and keep case under human review.",
        )
    if approved_patch_applied and not repeated_same_blocker and deterministic_proposal_available:
        return (
            APPROVED_PATCH_APPLIED_RERUN_FAILED,
            "Approved behavioral patch rerun failed, but blocker signature changed; review whether one additional localized proposal is justified.",
        )
    if deterministic_proposal_available:
        return (
            AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE,
            "A localized deterministic behavioral patch proposal exists, but it still requires explicit human approval before any sandbox apply.",
        )
    return (
        HUMAN_REVIEW_ONLY,
        "No new deterministic behavioral proposal is justified; keep remediation under human review.",
    )


def _primary_category(context_pack: dict[str, Any], orchestration: dict[str, Any]) -> str:
    counts = dict(context_pack.get("failure_categories") or {})
    if counts:
        return sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[0][0]
    warnings = " ".join(str(item) for item in list(orchestration.get("warnings") or []))
    if "behavioral" in warnings.lower():
        return "UNKNOWN_TEST_FAILURE"
    return ""


def _is_behavioral_case(context_pack: dict[str, Any], current_blocker_category: str) -> bool:
    if current_blocker_category in _BEHAVIORAL_CATEGORIES:
        return True
    if bool(context_pack.get("llm_candidate")):
        return True
    if bool(context_pack.get("missing_bean_type_errors")):
        return True
    suspected = {str(item) for item in list(context_pack.get("suspected_framework_areas") or [])}
    return bool(
        {"ApplicationContext", "Bean wiring", "ControllerAdvice", "ExceptionHandler", "Spring MVC", "Test configuration"}
        & suspected
    )


def _same_blocker_detected(context_pack: dict[str, Any], rerun: dict[str, Any], run_root: Path) -> bool:
    combined = "\n".join(
        [
            *[str(item) for item in list(rerun.get("stdout_tail") or [])],
            *[str(item) for item in list(rerun.get("stderr_tail") or [])],
        ]
    )
    surefire_text = _surefire_text(run_root)
    for item in list(context_pack.get("missing_bean_type_errors") or []):
        if not isinstance(item, dict):
            continue
        bean_type = str(item.get("bean_type") or "").strip()
        if bean_type and (bean_type in combined or bean_type in surefire_text):
            return True
    primary_message = str(context_pack.get("primary_failure_message") or "").strip()
    if primary_message and (primary_message in combined or primary_message in surefire_text):
        return True
    if "No qualifying bean of type" in primary_message and (
        "No qualifying bean of type" in combined or "No qualifying bean of type" in surefire_text
    ):
        return True
    if "Failed to load ApplicationContext" in primary_message and (
        "Failed to load ApplicationContext" in combined or "Failed to load ApplicationContext" in surefire_text
    ):
        return True
    return False


def _deterministic_proposal_available(
    repair: dict[str, Any],
    guided: dict[str, Any],
    mockito: dict[str, Any],
) -> bool:
    if bool(mockito.get("patch_proposal_available")):
        return True
    if bool(guided.get("patch_proposal_available")):
        return True
    if bool(repair.get("patch_proposal_available")):
        return True
    proposals = list(repair.get("proposals") or [])
    return any(
        isinstance(item, dict) and bool(item.get("provider_exists_but_not_loaded"))
        for item in proposals
    )


def _llm_allowed_for_category(policy: LlmPolicy, current_blocker_category: str) -> bool:
    if not policy.enabled:
        return False
    allowed = {str(item).strip() for item in list(policy.allowed_categories or []) if str(item).strip()}
    if "*" in allowed or "behavioral_test_context" in allowed:
        return True
    return current_blocker_category in allowed


def _expected_future_artifacts(decision: str) -> list[str]:
    if decision != ESCALATE_TO_LLM_PROPOSAL:
        return []
    return [
        "llm_model1_proposal.json",
        "llm_model2_review.json",
        "human_approval_required=true",
    ]


def _review_gates(orchestration: dict[str, Any], context_pack: dict[str, Any]) -> list[str]:
    refs = dict(orchestration.get("artifact_refs", {}) or {})
    gates = []
    for key, gate in (
        ("api_contract_review", "API_CONTRACT_REVIEW_GATE"),
        ("azure_sdk_migration_review", "AZURE_SDK_MIGRATION_PLAYBOOK"),
        ("jakarta_hybrid_strategy", "JAKARTA_HYBRID_STRATEGY"),
        ("powermock_review", "POWERMOCK_LEGACY_TEST_STRATEGY"),
    ):
        if str(refs.get(key) or "").strip():
            gates.append(gate)
    if bool(context_pack):
        gates.append("BEHAVIORAL_FAILURE_CONTEXT_PACK")
    return gates


def _recommended_next_actions(
    *,
    decision: str,
    failed_unit: str,
    current_blocker_category: str,
    repeated_same_blocker: bool,
) -> list[str]:
    if decision == AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE:
        return [
            f"Review the localized behavioral patch proposal for {failed_unit or 'the failed unit'} before any sandbox apply.",
            "Keep scope sandbox-only and rerun only the failed validation path after explicit human approval.",
        ]
    if decision == ESCALATE_TO_LLM_PROPOSAL:
        return [
            f"Prepare model 1 remediation proposal for {current_blocker_category or 'the behavioral blocker'}.",
            "Run model 2 review/optimizer using the original context pack, model 1 proposal, risk constraints, and allowed patch scope.",
            "Require human approval before any behavioral patch is applied.",
        ]
    if decision in {LLM_DISABLED_HUMAN_REVIEW_REQUIRED, STOP_REPEATED_BEHAVIORAL_PATCH_CHASING}:
        return [
            "Stop repeated behavioral patch chasing for the same blocker.",
            "Escalate to human review or future governed LLM proposal workflow instead of issuing another patch proposal now.",
        ]
    if decision == APPROVED_PATCH_APPLIED_RERUN_FAILED:
        return [
            "Review whether rerun failure signature materially changed before considering one more localized proposal.",
            "Do not apply another behavioral patch automatically.",
        ]
    if decision == HUMAN_REVIEW_ONLY:
        return [
            "Keep behavioral remediation under human review.",
            "Use existing context/equivalence artifacts to decide whether a new targeted proposal is justified.",
        ]
    return ["No behavioral remediation routing action is needed for the current failure shape."]


def _warnings(*, decision: str, repeated_same_blocker: bool, policy: LlmPolicy) -> list[str]:
    warnings: list[str] = []
    if repeated_same_blocker:
        warnings.append("Approved behavioral patch rerun failed with the same blocker; repeated patch chasing should stop.")
    if decision == LLM_DISABLED_HUMAN_REVIEW_REQUIRED and not policy.enabled:
        warnings.append("LLM proposal path is disabled by policy; human review remains the only allowed escalation.")
    if decision == ESCALATE_TO_LLM_PROPOSAL:
        warnings.append("Future LLM proposal flow remains sandbox-only and requires human approval before any patch apply.")
    return warnings


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Behavioral Remediation Strategy",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Decision: {payload.get('decision', '')}",
        f"- Blocker Category: {payload.get('current_blocker_category', '')}",
        f"- Repeated Same Blocker: {str(payload.get('repeated_same_blocker')).lower()}",
        f"- LLM Proposal Recommended: {str(payload.get('llm_proposal_recommended')).lower()}",
        f"- Human Approval Required: {str(payload.get('human_approval_required')).lower()}",
        "",
        "## Roles",
        "",
        f"- Model 1: {payload.get('model_1_role', '')}",
        f"- Model 2: {payload.get('model_2_role', '')}",
    ]
    actions = list(payload.get("recommended_next_actions") or [])
    if actions:
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in actions)
    return "\n".join(lines) + "\n"


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path) -> None:
    refs = {
        "behavioral_remediation_strategy": str(report_path),
        "behavioral_remediation_strategy_summary": str(summary_path),
    }
    for candidate in (
        run_root / "orchestration" / "orchestration_summary.json",
        run_root / "final" / "migration_report.json",
    ):
        payload = _read_optional_json(candidate)
        if not isinstance(payload, dict):
            continue
        artifact_refs = dict(payload.get("artifact_refs", {}) or {})
        payload["artifact_refs"] = {**artifact_refs, **refs}
        candidate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    final_summary = run_root / "final" / "migration_summary.md"
    if final_summary.is_file():
        text = final_summary.read_text(encoding="utf-8")
        line = f"- Behavioral Remediation Strategy: {report_path}"
        if line not in text:
            text = text.rstrip() + f"\n{line}\n"
            final_summary.write_text(text, encoding="utf-8")


def _read_optional_json(path_like: str | Path | None) -> dict[str, Any] | None:
    path = _resolve_path(path_like)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_path(path_like: Any) -> Path | None:
    if path_like is None:
        return None
    raw = str(path_like).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _surefire_text(run_root: Path, *, max_files: int = 12) -> str:
    reports_dir = run_root / "workspaces" / "sandbox" / "target" / "surefire-reports"
    if not reports_dir.is_dir():
        return ""
    chunks: list[str] = []
    for path in sorted(reports_dir.glob("*.xml"))[:max_files]:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)
