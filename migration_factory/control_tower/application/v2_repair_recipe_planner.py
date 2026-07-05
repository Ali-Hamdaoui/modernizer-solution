"""Governed repair recipe planning foundation for R11A.

The planner turns a backend-computed subfamily assessment into a non-authoritative
recipe plan. It does not execute patches, does not approve repairs, and does not
let RAG or LLM context override backend policy.
"""

from __future__ import annotations

import json
from typing import Any

from migration_factory.control_tower.application.v2_repair_recipe_registry import (
    RepairRecipePolicy,
    repair_recipe_policy,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


def plan_recipe(
    assessment: dict[str, Any],
    evidence: dict[str, Any],
    strategy_packet: dict[str, Any],
    rag_context: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Create a governed repair recipe plan.

    RAG context is allowed as advisory context only. It can appear in the plan,
    but it cannot change recipe status, risk, apply eligibility, or backend gates.
    """

    safe_assessment = assessment if isinstance(assessment, dict) else {}
    safe_evidence = evidence if isinstance(evidence, dict) else {}
    safe_strategy = strategy_packet if isinstance(strategy_packet, dict) else {}
    safe_rag_context = _safe_rag_context(rag_context)

    subfamily = _clean(
        safe_assessment.get("subfamily")
        or safe_strategy.get("subfamily")
        or safe_strategy.get("repair_subfamily")
        or "UNKNOWN_SUBFAMILY"
    )
    policy = repair_recipe_policy(subfamily)

    evidence_text = _evidence_text(safe_assessment, safe_evidence, safe_strategy)
    missing_evidence = _missing_evidence(policy, safe_evidence, evidence_text)
    forbidden_patterns = _forbidden_patterns(policy, evidence_text)
    target_files = _target_files(safe_assessment, safe_evidence, safe_strategy)

    policy_apply_allowed = (
        policy.recipe_status == "apply_enabled"
        and policy.backend_recipe_available
        and policy.apply_candidate_allowed
    )
    apply_allowed = policy_apply_allowed and not missing_evidence and not forbidden_patterns

    if policy.recipe_status == "apply_enabled":
        plan_status = "planned" if apply_allowed else "blocked"
    elif policy.recipe_status == "dry_run_only":
        plan_status = "dry_run" if not forbidden_patterns else "blocked"
    elif policy.recipe_status in {"strategy_only", "human_refactor_required"}:
        plan_status = "blocked"
    else:
        plan_status = "unsupported"

    plan = {
        "recipe_plan_id": _recipe_plan_id(policy, safe_assessment, safe_evidence, safe_strategy),
        "recipe_id": policy.recipe_id,
        "family": policy.family,
        "subfamily": policy.subfamily,
        "recipe_status": policy.recipe_status,
        "plan_status": plan_status,
        "risk_level": policy.risk_level,
        "target_files": target_files,
        "proposed_operations": _proposed_operations(policy, target_files, plan_status),
        "required_evidence": list(policy.required_evidence),
        "missing_evidence": missing_evidence,
        "forbidden_patterns_matched": forbidden_patterns,
        "verification_requirements": list(policy.verification_requirements),
        "rag_context_used": safe_rag_context,
        "rag_reuse_signature": _rag_reuse_signature(safe_rag_context),
        "apply_candidate_allowed": bool(apply_allowed),
        "human_gate_required": True,
        "backend_recipe_available": bool(policy.backend_recipe_available),
        "dry_run_available": bool(policy.dry_run_available),
        "rollback_required": bool(policy.rollback_required),
        "proof_required": bool(policy.proof_required),
        "backend_gate": _backend_gate(),
        "policy_notes": policy.promotion_notes,
    }
    plan["plan_checksum"] = f"sha256:{sha256_canonical_json(_checksum_body(plan))}"
    return plan


def _backend_gate() -> dict[str, bool]:
    return {
        "backend_authority": True,
        "llm_can_apply": False,
        "llm_can_approve": False,
        "rag_can_apply": False,
        "rag_can_approve": False,
        "downstream_start_allowed": False,
    }


def _recipe_plan_id(
    policy: RepairRecipePolicy,
    assessment: dict[str, Any],
    evidence: dict[str, Any],
    strategy_packet: dict[str, Any],
) -> str:
    payload = {
        "recipe_id": policy.recipe_id,
        "subfamily": policy.subfamily,
        "assessment_checksum": assessment.get("assessment_checksum"),
        "strategy_checksum": strategy_packet.get("strategy_checksum"),
        "evidence_pack_checksum": (
            evidence.get("evidence_pack_checksum")
            or strategy_packet.get("evidence_pack_checksum")
            or assessment.get("evidence_pack_checksum")
        ),
    }
    return f"recipe-plan-{sha256_canonical_json(payload)[:16]}"


def _checksum_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key not in {"plan_checksum"}
    }


def _safe_rag_context(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "retrieved_case_id": _clean(item.get("retrieved_case_id")),
                "reuse_signature": _clean(item.get("reuse_signature")),
                "family": _clean(item.get("family")),
                "subfamily": _clean(item.get("subfamily")),
                "similarity_reason": _clean(item.get("similarity_reason")),
                "resolution_summary": _clean(item.get("resolution_summary")),
                "recipe_status": _clean(item.get("recipe_status")),
                "risk_level": _clean(item.get("risk_level")),
                "non_authoritative": True,
            }
        )
    return result


def _rag_reuse_signature(rag_context: list[dict[str, Any]]) -> str:
    payload = [
        {
            "retrieved_case_id": item.get("retrieved_case_id"),
            "reuse_signature": item.get("reuse_signature"),
            "family": item.get("family"),
            "subfamily": item.get("subfamily"),
        }
        for item in rag_context
    ]
    return f"sha256:{sha256_canonical_json(payload)}"


def _missing_evidence(policy: RepairRecipePolicy, evidence: dict[str, Any], evidence_text: str) -> list[str]:
    available = _available_evidence(evidence, evidence_text)
    missing = [item for item in policy.required_evidence if item not in available]
    return missing[:12]


def _available_evidence(evidence: dict[str, Any], evidence_text: str) -> set[str]:
    available: set[str] = set()

    for key, value in evidence.items():
        if value:
            available.add(_normalize_evidence_key(key))

    artifact_refs = evidence.get("artifact_refs")
    if isinstance(artifact_refs, dict):
        for key, value in artifact_refs.items():
            if value:
                available.add(_normalize_evidence_key(key))

    usable_artifacts = evidence.get("usable_artifacts")
    if isinstance(usable_artifacts, (list, tuple)):
        for item in usable_artifacts:
            if isinstance(item, dict):
                kind = item.get("kind")
                if kind:
                    available.add(_normalize_evidence_key(kind))
            elif item:
                available.add(_normalize_evidence_key(str(item)))

    if "src/test" in evidence_text:
        available.add("test_source")
    if "pom.xml" in evidence_text or "<project" in evidence_text:
        available.add("pom_xml")
    if "build_error_contract" in evidence_text:
        available.add("build_error_contract")
    if "test_report" in evidence_text or "surefire" in evidence_text or "failsafe" in evidence_text:
        available.add("test_report")
    if "sandbox" in evidence_text:
        available.add("sandbox")

    return available


def _normalize_evidence_key(value: str) -> str:
    text = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "pom": "pom_xml",
        "pomxml": "pom_xml",
        "pom_file": "pom_xml",
        "source": "source_ref",
        "source_file": "source_ref",
        "test": "test_source",
        "test_file": "test_source",
        "build_error": "build_error_contract",
        "build_errors": "build_error_contract",
        "dependency_tree": "dependency_graph",
    }
    return aliases.get(text, text)


def _forbidden_patterns(policy: RepairRecipePolicy, evidence_text: str) -> list[str]:
    matched = [pattern for pattern in policy.forbidden_patterns if pattern.lower() in evidence_text]

    if policy.subfamily == "JAKARTA_IMPORT_ONLY":
        if "<dependency" in evidence_text or "<version>" in evidence_text:
            matched.append("dependency version change")
        if "securityfilterchain" in evidence_text or "websecurityconfigureradapter" in evidence_text:
            matched.append("security behavior change")
        if "assert" in evidence_text and "import javax." not in evidence_text:
            matched.append("test assertion change")

    return list(dict.fromkeys(matched))[:12]


def _target_files(
    assessment: dict[str, Any],
    evidence: dict[str, Any],
    strategy_packet: dict[str, Any],
) -> list[str]:
    candidates: list[Any] = []

    for source in (assessment, evidence, strategy_packet):
        for key in ("target_files", "affected_files"):
            value = source.get(key)
            if isinstance(value, (list, tuple)):
                candidates.extend(value)

    artifact_refs = evidence.get("artifact_refs")
    if isinstance(artifact_refs, dict):
        for key in ("test_source", "source_ref"):
            value = artifact_refs.get(key)
            if value:
                candidates.append(value)

    result: list[str] = []
    for item in candidates:
        text = _clean(item)
        if not text:
            continue
        if text not in result:
            result.append(text)
    return result[:12]


def _proposed_operations(policy: RepairRecipePolicy, target_files: list[str], plan_status: str) -> list[dict[str, str]]:
    if plan_status == "unsupported":
        return []

    if policy.subfamily == "INITMOCKS_DIRECT_REPLACEMENT":
        return [
            {
                "operation": "replace",
                "target": target_files[0] if target_files else "test_source",
                "from": "MockitoAnnotations.initMocks(this)",
                "to": "MockitoAnnotations.openMocks(this)",
                "authority": "backend_recipe_policy",
            }
        ]

    if policy.subfamily == "JAKARTA_IMPORT_ONLY":
        return [
            {
                "operation": "dry_run_namespace_rewrite",
                "target": ",".join(target_files) if target_files else "source_ref",
                "from": "javax.validation|javax.annotation|javax.servlet|javax.persistence",
                "to": "jakarta.validation|jakarta.annotation|jakarta.servlet|jakarta.persistence",
                "authority": "dry_run_only",
            }
        ]

    if policy.subfamily == "JACKSON_PROPERTY_BOM_ALIGNMENT":
        return [
            {
                "operation": "pom_dependency_alignment",
                "target": "pom.xml",
                "from": "mixed Jackson 2.9.6/2.10.0 with omitted 2.13.5",
                "to": "fasterxml-jackson.version 2.13.5 plus Jackson BOM/direct deps when evidence requires",
                "authority": "backend_recipe_policy",
            }
        ]

    if policy.recipe_status == "dry_run_only":
        return [
            {
                "operation": "dry_run_assessment",
                "target": ",".join(target_files) if target_files else "evidence",
                "from": policy.subfamily,
                "to": "review_required_before_apply_candidate",
                "authority": "dry_run_only",
            }
        ]

    if policy.recipe_status == "human_refactor_required":
        return [
            {
                "operation": "human_refactor_required",
                "target": ",".join(target_files) if target_files else "evidence",
                "from": policy.subfamily,
                "to": "engineer_refactor_plan",
                "authority": "human_review_only",
            }
        ]

    return []


def _evidence_text(*values: Any) -> str:
    try:
        return json.dumps(values, sort_keys=True, default=str).lower()
    except TypeError:
        return str(values).lower()


def _clean(value: Any) -> str:
    return str(value or "").strip()[:500]
