"""Repair learning case foundation for R11A.

A learning case is advisory memory material. It can be converted to a RAG
knowledge document later, but it cannot approve, apply, execute, or start
downstream stages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json


_ALLOWED_CASE_STATUSES = frozenset({
    "observed",
    "strategy_created",
    "dry_run_created",
    "human_refactor_required",
    "successful_repair",
    "candidate_recipe_proposed",
    "promoted",
    "rejected",
})


def build_repair_learning_case(
    *,
    job_id: str,
    stage_index: int,
    microservice: str,
    family: str,
    subfamily: str,
    recipe_id: str | None = None,
    case_status: str = "observed",
    evidence: dict[str, Any] | None = None,
    strategy_packet: dict[str, Any] | None = None,
    recipe_plan: dict[str, Any] | None = None,
    llm_proposed_resolution: dict[str, Any] | None = None,
    llm_review: dict[str, Any] | None = None,
    root_cause: str | None = None,
    matched_patterns: list[str] | tuple[str, ...] | None = None,
    missing_evidence: list[str] | tuple[str, ...] | None = None,
    recommended_engineer_action: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build an advisory repair learning case.

    The returned structure is deterministic except for created_at when omitted.
    It is safe to expose in failure summaries after redaction/sanitization by the
    caller, because it does not include executable authority.
    """

    safe_evidence = evidence if isinstance(evidence, dict) else {}
    safe_strategy = strategy_packet if isinstance(strategy_packet, dict) else {}
    safe_plan = recipe_plan if isinstance(recipe_plan, dict) else {}

    normalized_status = _safe_case_status(case_status, safe_plan, subfamily)
    normalized_recipe_id = _clean(recipe_id or safe_plan.get("recipe_id") or "")
    normalized_missing = _clean_list(missing_evidence if missing_evidence is not None else safe_plan.get("missing_evidence"))
    normalized_patterns = _clean_list(matched_patterns if matched_patterns is not None else _patterns_from_sources(safe_strategy, safe_plan))

    evidence_pack_checksum = _clean(
        safe_evidence.get("evidence_pack_checksum")
        or safe_strategy.get("evidence_pack_checksum")
        or safe_plan.get("evidence_pack_checksum")
        or "sha256:null"
    )
    strategy_checksum = _clean(safe_strategy.get("strategy_checksum") or "sha256:null")
    recipe_plan_checksum = _clean(safe_plan.get("plan_checksum") or "sha256:null")
    normalized_root_cause = _clean(root_cause or _root_cause_from_sources(safe_strategy, safe_plan, family, subfamily))
    normalized_action = _clean(recommended_engineer_action or _recommended_action(normalized_status, safe_plan, subfamily))
    timestamp = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    reuse_signature = compute_learning_reuse_signature(
        microservice=microservice,
        family=family,
        subfamily=subfamily,
        recipe_id=normalized_recipe_id,
        root_cause=normalized_root_cause,
        matched_patterns=normalized_patterns,
    )

    case_base = {
        "job_id": _clean(job_id),
        "stage_index": int(stage_index or 0),
        "microservice": _clean(microservice or "unknown"),
        "family": _clean(family or "UNKNOWN_FAILURE"),
        "subfamily": _clean(subfamily or "UNKNOWN_SUBFAMILY"),
        "recipe_id": normalized_recipe_id or None,
        "case_status": normalized_status,
        "evidence_pack_checksum": evidence_pack_checksum,
        "strategy_checksum": strategy_checksum,
        "recipe_plan_checksum": recipe_plan_checksum,
        "root_cause": normalized_root_cause,
        "matched_patterns": normalized_patterns,
        "missing_evidence": normalized_missing,
        "llm_proposed_resolution": _safe_model_map(llm_proposed_resolution),
        "llm_review": _safe_model_map(llm_review),
        "recommended_engineer_action": normalized_action,
        "reuse_signature": reuse_signature,
        "created_at": timestamp,
    }
    case_id = _learning_case_id(case_base)
    rag_document = build_rag_document_from_learning_case_data(case_base | {"learning_case_id": case_id})

    return {
        "learning_case_id": case_id,
        **case_base,
        "rag_document": rag_document,
        "backend_gate": _backend_gate(),
    }


def compute_learning_reuse_signature(
    *,
    microservice: str,
    family: str,
    subfamily: str,
    recipe_id: str | None,
    root_cause: str,
    matched_patterns: list[str] | tuple[str, ...],
) -> str:
    payload = {
        "microservice": _clean(microservice or "unknown"),
        "family": _clean(family or "UNKNOWN_FAILURE"),
        "subfamily": _clean(subfamily or "UNKNOWN_SUBFAMILY"),
        "recipe_id": _clean(recipe_id or ""),
        "root_cause": _clean(root_cause),
        "matched_patterns": sorted(_clean_list(matched_patterns)),
    }
    return f"sha256:{sha256_canonical_json(payload)}"


def build_rag_document_from_learning_case_data(case: dict[str, Any]) -> dict[str, Any]:
    """Convert a learning case to an advisory RAG document payload."""

    family = _clean(case.get("family") or "UNKNOWN_FAILURE")
    subfamily = _clean(case.get("subfamily") or "UNKNOWN_SUBFAMILY")
    recipe_id = _clean(case.get("recipe_id") or "")
    case_status = _clean(case.get("case_status") or "observed")
    risk_level = _risk_from_subfamily(subfamily)
    recipe_status = _recipe_status_from_case(case_status)

    title = f"{subfamily} repair learning case"
    summary = _summary_for_case(case_status, family, subfamily, recipe_id)

    return {
        "title": title,
        "summary": summary,
        "problem_signature": _clean(case.get("reuse_signature")),
        "resolution_summary": _resolution_summary(case_status, recipe_id, subfamily),
        "risk_level": risk_level,
        "recipe_status": recipe_status,
        "evidence_requirements": list(_clean_list(case.get("missing_evidence"))),
        "do_not_apply_when": _do_not_apply_when(subfamily, case_status),
        "verification_notes": _verification_notes(case_status, subfamily),
        "non_authoritative": True,
        "rag_can_apply": False,
        "rag_can_approve": False,
        "rag_can_start_downstream": False,
    }


def _learning_case_id(case_base: dict[str, Any]) -> str:
    payload = {
        "job_id": case_base.get("job_id"),
        "stage_index": case_base.get("stage_index"),
        "microservice": case_base.get("microservice"),
        "family": case_base.get("family"),
        "subfamily": case_base.get("subfamily"),
        "recipe_id": case_base.get("recipe_id"),
        "case_status": case_base.get("case_status"),
        "evidence_pack_checksum": case_base.get("evidence_pack_checksum"),
        "strategy_checksum": case_base.get("strategy_checksum"),
        "recipe_plan_checksum": case_base.get("recipe_plan_checksum"),
        "reuse_signature": case_base.get("reuse_signature"),
    }
    return f"repair-learning-{sha256_canonical_json(payload)[:16]}"


def _backend_gate() -> dict[str, bool]:
    return {
        "backend_authority": True,
        "llm_can_apply": False,
        "llm_can_approve": False,
        "rag_can_apply": False,
        "rag_can_approve": False,
        "downstream_start_allowed": False,
    }


def _safe_case_status(case_status: str, recipe_plan: dict[str, Any], subfamily: str) -> str:
    text = _clean(case_status)
    if text in _ALLOWED_CASE_STATUSES:
        return text

    plan_status = _clean(recipe_plan.get("plan_status"))
    recipe_status = _clean(recipe_plan.get("recipe_status"))

    if recipe_status == "human_refactor_required":
        return "human_refactor_required"
    if plan_status == "dry_run":
        return "dry_run_created"
    if plan_status == "planned":
        return "candidate_recipe_proposed"
    if subfamily == "UNKNOWN_SUBFAMILY":
        return "observed"
    return "strategy_created"


def _patterns_from_sources(strategy_packet: dict[str, Any], recipe_plan: dict[str, Any]) -> list[str]:
    patterns: list[str] = []
    for key in ("matched_patterns", "detected_patterns", "forbidden_patterns_matched"):
        value = strategy_packet.get(key)
        if isinstance(value, (list, tuple)):
            patterns.extend(str(item) for item in value)
        value = recipe_plan.get(key)
        if isinstance(value, (list, tuple)):
            patterns.extend(str(item) for item in value)
    return _clean_list(patterns)


def _root_cause_from_sources(
    strategy_packet: dict[str, Any],
    recipe_plan: dict[str, Any],
    family: str,
    subfamily: str,
) -> str:
    for key in ("root_cause", "failure_summary", "reason"):
        value = strategy_packet.get(key) or recipe_plan.get(key)
        if value:
            return str(value)
    return f"{family or 'UNKNOWN_FAILURE'} / {subfamily or 'UNKNOWN_SUBFAMILY'} requires governed repair handling."


def _recommended_action(case_status: str, recipe_plan: dict[str, Any], subfamily: str) -> str:
    if case_status == "successful_repair":
        return "Reuse as advisory migration memory for similar future failures."
    if case_status == "dry_run_created":
        return "Review dry-run recipe plan and promote only after evidence gates and tests."
    if case_status == "human_refactor_required":
        return "Prepare an engineer refactor plan; do not create an automatic apply candidate."
    if subfamily == "UNKNOWN_SUBFAMILY":
        return "Collect missing evidence and improve classifier coverage before proposing a recipe."
    if recipe_plan.get("apply_candidate_allowed") is True:
        return "Proceed through backend candidate creation and human approval gates."
    return "Use this case as advisory context; backend policy still controls apply eligibility."


def _safe_model_map(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed_keys = (
        "model",
        "role",
        "schema_validation_status",
        "verdict",
        "summary",
        "failure_reason",
        "fallback_used",
    )
    return {key: _clean(value.get(key)) for key in allowed_keys if value.get(key) is not None}


def _risk_from_subfamily(subfamily: str) -> str:
    if subfamily in {"INITMOCKS_DIRECT_REPLACEMENT"}:
        return "low"
    if subfamily in {
        "JAKARTA_IMPORT_ONLY",
        "MOCKBEAN_DIRECT_REPLACEMENT",
        "DEPENDENCY_VERSION_BUMP_ONLY",
        "POWERMOCK_STATIC_MOCK_SIMPLE",
    }:
        return "medium"
    if subfamily in {
        "POWERMOCK_CONSTRUCTOR_MOCKING",
        "POWERMOCK_PRIVATE_OR_FINAL_MOCKING",
        "SPRING_SECURITY_BEHAVIORAL_CHANGE",
        "JUNIT4_RULE_COMPLEX",
    }:
        return "high"
    return "unknown"


def _recipe_status_from_case(case_status: str) -> str:
    if case_status == "successful_repair":
        return "governed_success"
    if case_status == "dry_run_created":
        return "dry_run_only"
    if case_status == "human_refactor_required":
        return "human_refactor_required"
    if case_status == "candidate_recipe_proposed":
        return "candidate_recipe_proposed"
    return "advisory_only"


def _summary_for_case(case_status: str, family: str, subfamily: str, recipe_id: str) -> str:
    if case_status == "successful_repair":
        return f"Successful governed repair for {subfamily} using {recipe_id or 'backend recipe'}."
    if case_status == "dry_run_created":
        return f"Dry-run repair plan for {subfamily}; no apply authority granted."
    if case_status == "human_refactor_required":
        return f"{subfamily} is high-risk and requires engineer refactor."
    return f"Observed repair learning case for {family} / {subfamily}."


def _resolution_summary(case_status: str, recipe_id: str, subfamily: str) -> str:
    if case_status == "successful_repair":
        return f"Verified repair may inform future {subfamily} cases, but remains advisory."
    if case_status == "dry_run_created":
        return "Dry-run plan available; promotion requires governed tests and evidence gates."
    if case_status == "human_refactor_required":
        return "Engineer refactor required; do not auto-apply."
    if recipe_id:
        return f"Recipe {recipe_id} considered, but backend gates still control apply."
    return "No executable recipe available."


def _do_not_apply_when(subfamily: str, case_status: str) -> list[str]:
    rules = [
        "evidence is missing",
        "checksums are not verified",
        "human approval is absent",
        "target is not sandbox",
    ]
    if case_status != "successful_repair":
        rules.append("case is advisory and not promoted")
    if subfamily.startswith("POWERMOCK"):
        rules.append("PowerMock migration may alter test behavior")
    return rules


def _verification_notes(case_status: str, subfamily: str) -> list[str]:
    notes = ["RAG memory is advisory only.", "Backend gates own apply eligibility."]
    if case_status == "successful_repair":
        notes.append("Reuse only with matching evidence and verification proof.")
    if subfamily == "JAKARTA_IMPORT_ONLY":
        notes.append("Verify namespace-only diff and compile/test proof.")
    if subfamily.startswith("POWERMOCK"):
        notes.append("Require engineer behavior review for PowerMock migration.")
    return notes


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        text = _clean(item)
        if text and text not in result:
            result.append(text)
    return result[:24]


def _clean(value: Any) -> str:
    return str(value or "").strip()[:500]