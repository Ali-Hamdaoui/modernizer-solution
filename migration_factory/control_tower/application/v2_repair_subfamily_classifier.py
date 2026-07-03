"""Deterministic backend repair subfamily classifier for R10."""

from __future__ import annotations

import json
from typing import Any

from migration_factory.control_tower.application.redaction import redact_public_value
from migration_factory.control_tower.application.v2_repair_family_registry import RepairFamilyPolicy, repair_family_policy
from migration_factory.control_tower.application.v2_repair_subfamily_registry import (
    RepairSubfamilyPolicy,
    repair_subfamily_policy,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


def classify_repair_subfamily(
    *,
    family_policy: RepairFamilyPolicy | None = None,
    repair_strategy_packet: dict[str, Any] | None = None,
    stage_evidence: dict[str, Any] | None = None,
    classification: dict[str, Any] | None = None,
    migration_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    strategy = repair_strategy_packet if isinstance(repair_strategy_packet, dict) else {}
    evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
    classification = classification if isinstance(classification, dict) else {}
    memory = migration_memory if isinstance(migration_memory, dict) else {}
    policy = family_policy or repair_family_policy(
        strategy.get("family")
        or classification.get("repair_family_candidate")
        or classification.get("failure_type")
    )
    text = _evidence_text(strategy, evidence, classification, memory)
    subfamily = _select_subfamily(policy.family, text)
    sub_policy = repair_subfamily_policy(subfamily)
    matched = _matched_patterns(sub_policy, text)
    forbidden = _forbidden_patterns(sub_policy, text)
    missing = _missing_evidence(sub_policy, evidence, text)
    assessment = {
        "assessment_id": "",
        "job_id": str(strategy.get("job_id") or evidence.get("job_id") or classification.get("job_id") or ""),
        "stage_index": strategy.get("stage_index") if strategy.get("stage_index") is not None else evidence.get("stage_index") or classification.get("stage_index"),
        "family": sub_policy.family if subfamily != "UNKNOWN_SUBFAMILY" else policy.family,
        "subfamily": sub_policy.subfamily,
        "risk_level": sub_policy.risk_level,
        "promotion_status": sub_policy.promotion_status,
        "backend_recipe_available": bool(sub_policy.backend_recipe_available),
        "apply_candidate_allowed": bool(sub_policy.apply_candidate_allowed),
        "human_gate_required": True,
        "matched_patterns": matched,
        "forbidden_patterns_matched": forbidden,
        "missing_evidence": missing,
        "verification_requirements": list(sub_policy.verification_requirements),
        "recommended_engineer_action": sub_policy.recommended_engineer_action,
        "rollback_required": True,
        "proof_required": True,
        "backend_gate": _backend_gate(),
    }
    checksum = repair_subfamily_assessment_checksum(assessment)
    assessment["assessment_id"] = f"repair-subfamily-{checksum.removeprefix('sha256:')[:12]}"
    assessment["assessment_checksum"] = checksum
    return assessment


def repair_subfamily_assessment_checksum(assessment: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in assessment.items()
        if key not in {"assessment_id", "assessment_checksum"}
    }
    return f"sha256:{sha256_canonical_json(body)}"


def _select_subfamily(family: str, text: str) -> str:
    if "powermockito.whennew" in text or "whennew" in text:
        return "POWERMOCK_CONSTRUCTOR_MOCKING"
    if any(pattern in text for pattern in ("whitebox", "private method", "private method mocking", "final class", "final-class", "final class mocking")):
        return "POWERMOCK_PRIVATE_OR_FINAL_MOCKING"
    if "mockitoannotations.initmocks" in text:
        return "INITMOCKS_DIRECT_REPLACEMENT"
    if "@mockbean" in text or "mockbean" in text:
        return "MOCKBEAN_DIRECT_REPLACEMENT"
    if family == "POWERMOCK_LEGACY_TEST_STRATEGY" and any(pattern in text for pattern in ("powermockito.mockstatic", "mockstatic")):
        return "POWERMOCK_STATIC_MOCK_SIMPLE"
    if "@rule" in text or "externalresource" in text:
        return "JUNIT4_RULE_COMPLEX"
    if "@runwith" in text:
        return "JUNIT4_RUNNER_SIMPLE"
    if family == "SPRING_SECURITY_API_DRIFT" or any(pattern in text for pattern in ("securityfilterchain", "websecurityconfigureradapter", "authorizehttprequests")):
        return "SPRING_SECURITY_BEHAVIORAL_CHANGE"
    if family == "JAKARTA_NAMESPACE_MISMATCH" and "javax." in text and "dependency" not in text:
        return "JAKARTA_IMPORT_ONLY"
    if family == "JAKARTA_NAMESPACE_MISMATCH" and "dependency" in text:
        return "JAKARTA_DEPENDENCY_ALIGNMENT"
    if family == "DEPENDENCY_VERSION_ALIGNMENT" and "version" in text:
        return "DEPENDENCY_VERSION_BUMP_ONLY"
    return "UNKNOWN_SUBFAMILY"


def _matched_patterns(policy: RepairSubfamilyPolicy, text: str) -> list[str]:
    return [pattern for pattern in policy.detected_patterns if pattern.lower() in text][:12]


def _forbidden_patterns(policy: RepairSubfamilyPolicy, text: str) -> list[str]:
    result = [pattern for pattern in policy.forbidden_patterns if pattern.lower() in text]
    if policy.subfamily == "POWERMOCK_CONSTRUCTOR_MOCKING" and result and "constructor mocking" not in result:
        result.append("constructor mocking")
    return result[:12]


def _missing_evidence(policy: RepairSubfamilyPolicy, evidence: dict[str, Any], text: str) -> list[str]:
    usable = {
        str(item.get("kind") or "")
        for item in evidence.get("usable_artifacts", [])
        if isinstance(item, dict)
    }
    missing: list[str] = []
    for required in policy.required_evidence:
        if required == "test_source" and ("test_source" in usable or "src/test" in text):
            continue
        if required in usable:
            continue
        missing.append(required)
    return missing[:8]


def _backend_gate() -> dict[str, bool]:
    return {
        "backend_authority": True,
        "llm_can_apply": False,
        "llm_can_approve": False,
        "downstream_start_allowed": False,
    }


def _evidence_text(*values: Any) -> str:
    return json.dumps(redact_public_value(values), sort_keys=True).lower()
