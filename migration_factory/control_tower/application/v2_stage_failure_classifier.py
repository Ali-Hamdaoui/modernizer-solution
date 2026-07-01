"""Stage-aware deterministic failure classification for R7C.

Classification is advisory only. It never enables real repair apply.
"""

from __future__ import annotations

import json
import re
from typing import Any


REPAIR_DISABLED_REASON = "R7C_classification_only_no_real_repair_apply"


def classify_stage_failure(evidence_pack: dict[str, Any]) -> dict[str, Any]:
    """Classify a stage failure into a candidate or blocked state.

    The classifier consumes the R7B stage evidence pack. It only returns
    backend-owned classification metadata; repair remains disabled.
    """

    text = _evidence_text(evidence_pack)
    target_boot = str(evidence_pack.get("target_boot_version") or "")
    target_java = str(evidence_pack.get("target_java_version") or "")
    boot3_plus = _version_at_least(target_boot, 3)
    java17_plus = _version_at_least(target_java, 17)
    java21_plus = _version_at_least(target_java, 21)
    missing = [str(item) for item in evidence_pack.get("missing_artifacts", []) if str(item)]
    usable = [
        str(item.get("kind") or "")
        for item in evidence_pack.get("usable_artifacts", [])
        if isinstance(item, dict) and item.get("kind")
    ]

    candidates = [
        _jakarta_import_source(text, boot3_plus),
        _javax_servlet_dependency(text, boot3_plus),
        _javax_validation_dependency(text, boot3_plus),
        _validation_starter(text),
        _tomcat9_override(text, boot3_plus),
        _zalando_problem(text, boot3_plus),
        _maven_compiler_mismatch(text, java17_plus, java21_plus),
        _java_language_level(text, java17_plus, java21_plus),
        _spring_boot_plugin_mismatch(text, target_boot),
        _test_api_breakage(text, usable),
        _h2_smoke_config(text),
    ]
    known = [item for item in candidates if item is not None]
    if known:
        best = max(known, key=lambda item: item["score"])
        return _envelope(
            evidence_pack=evidence_pack,
            status="known_family_candidate",
            failure_type=best["family"],
            repair_family_candidate=best["family"],
            confidence=best["confidence"],
            confidence_reason=best["reason"],
            matched_signals=best["signals"],
            missing_required_evidence=_missing_required(best["required"], usable, missing),
            assistant_next_action="prepare_evidence_bound_proposal_in_R7D",
            repair_blocked_reason=REPAIR_DISABLED_REASON,
        )

    unsupported = _unsupported_known_failure(text)
    if unsupported is not None:
        return _envelope(
            evidence_pack=evidence_pack,
            status="unsupported_known_failure",
            failure_type=unsupported["failure_type"],
            confidence=unsupported["confidence"],
            confidence_reason=unsupported["reason"],
            matched_signals=unsupported["signals"],
            missing_required_evidence=[],
            assistant_next_action="record_unsupported_failure_and_plan_taxonomy_expansion",
            repair_blocked_reason="unsupported_known_failure_no_repair_family",
        )

    if _needs_more_evidence(missing, usable, text):
        needed = [item for item in ("build_error_contract", "test_agent_log", "test_report") if item in missing]
        return _envelope(
            evidence_pack=evidence_pack,
            status="blocked_pending_evidence",
            failure_type="blocked_pending_evidence",
            confidence="low",
            confidence_reason="Core build/test failure artifacts missing; taxonomy cannot select a repair family.",
            matched_signals=[],
            missing_required_evidence=needed or missing[:6],
            assistant_next_action="collect_missing_stage_evidence",
            repair_blocked_reason="missing_required_failure_evidence",
        )

    return _envelope(
        evidence_pack=evidence_pack,
        status="unknown",
        failure_type="unknown",
        confidence="low",
        confidence_reason="Evidence reviewed, but no supported taxonomy signal matched.",
        matched_signals=[],
        missing_required_evidence=[],
        assistant_next_action="escalate_unknown_stage_failure",
        repair_blocked_reason="no_known_family_match",
    )


def _envelope(
    *,
    evidence_pack: dict[str, Any],
    status: str,
    failure_type: str,
    confidence: str,
    confidence_reason: str,
    matched_signals: list[str],
    missing_required_evidence: list[str],
    assistant_next_action: str,
    repair_blocked_reason: str,
    repair_family_candidate: str = "",
) -> dict[str, Any]:
    return {
        "stage_index": evidence_pack.get("stage_index"),
        "stage_name": evidence_pack.get("stage_name", ""),
        "source_boot_version": evidence_pack.get("source_boot_version", ""),
        "target_boot_version": evidence_pack.get("target_boot_version", ""),
        "source_java_version": evidence_pack.get("source_java_version", ""),
        "target_java_version": evidence_pack.get("target_java_version", ""),
        "classification_status": status,
        "failure_type": failure_type,
        "repair_family_candidate": repair_family_candidate,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "matched_signals": matched_signals[:8],
        "missing_required_evidence": missing_required_evidence[:8],
        "usable_artifacts": [
            str(item.get("kind") or "")
            for item in evidence_pack.get("usable_artifacts", [])
            if isinstance(item, dict) and item.get("kind")
        ][:12],
        "repair_enabled": False,
        "repair_blocked_reason": repair_blocked_reason,
        "reason": repair_blocked_reason,
        "assistant_next_action": assistant_next_action,
        "downstream_stage_state": evidence_pack.get("downstream_stage_state"),
        "evidence_pack_id": evidence_pack.get("evidence_pack_id"),
        "evidence_pack_checksum": evidence_pack.get("evidence_pack_checksum"),
    }


def _evidence_text(evidence_pack: dict[str, Any]) -> str:
    return json.dumps(evidence_pack, sort_keys=True).lower()


def _version_at_least(value: str, major: int) -> bool:
    match = re.search(r"\d+", value)
    return bool(match and int(match.group(0)) >= major)


def _candidate(family: str, confidence: str, reason: str, signals: list[str], required: list[str]) -> dict[str, Any]:
    score = {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)
    return {
        "family": family,
        "confidence": confidence,
        "score": score,
        "reason": reason,
        "signals": signals,
        "required": required,
    }


def _jakarta_import_source(text: str, boot3_plus: bool) -> dict[str, Any] | None:
    if "package jakarta.servlet" in text and "does not exist" in text:
        reason = "Jakarta servlet package missing while target Boot version implies javax namespace may still be expected." if not boot3_plus else "Jakarta servlet compile error found; source import/dependency alignment needs bounded proposal."
        return _candidate("JAKARTA_IMPORT_MECHANICAL_SOURCE", "medium", reason, ["compiler:package_jakarta_servlet_missing"], ["build_error_contract", "rewrite_patch"])
    if "package javax.servlet" in text and "does not exist" in text:
        reason = "javax servlet package missing; target Boot namespace decides whether source import migration is needed."
        return _candidate("JAKARTA_IMPORT_MECHANICAL_SOURCE", "medium", reason, ["compiler:package_javax_servlet_missing"], ["build_error_contract", "rewrite_patch"])
    if ("import jakarta.servlet" in text or "import javax.servlet" in text) and "namespace mismatch" in text:
        return _candidate("JAKARTA_IMPORT_MECHANICAL_SOURCE", "medium", "Import namespace mismatch signal found.", ["source:servlet_namespace_mismatch"], ["rewrite_patch"])
    return None


def _javax_servlet_dependency(text: str, boot3_plus: bool) -> dict[str, Any] | None:
    if boot3_plus and ("javax.servlet-api" in text or "javax.servlet</groupid>" in text or "javax.servlet:" in text):
        return _candidate(
            "DEPENDENCY_REPLACE_JAVAX_SERVLET_API_WITH_JAKARTA",
            "high",
            "Boot 3/4 target with javax servlet dependency signal.",
            ["dependency:javax_servlet_api_on_boot3_plus"],
            ["pom_xml", "dependency_graph"],
        )
    return None


def _javax_validation_dependency(text: str, boot3_plus: bool) -> dict[str, Any] | None:
    if boot3_plus and ("javax.validation" in text or "validation-api" in text and "javax" in text):
        return _candidate(
            "DEPENDENCY_REPLACE_JAVAX_VALIDATION_WITH_JAKARTA",
            "high",
            "Boot 3/4 target with javax validation signal.",
            ["dependency:javax_validation_on_boot3_plus"],
            ["pom_xml", "dependency_graph"],
        )
    return None


def _validation_starter(text: str) -> dict[str, Any] | None:
    markers = ("no validator could be found", "hibernate validator", "validator bean", "jakarta.validation.validationexception")
    if any(marker in text for marker in markers) and "spring-boot-starter-validation" not in text:
        return _candidate(
            "DEPENDENCY_ADD_VALIDATION_STARTER",
            "medium",
            "Validation API/runtime signal found without starter evidence.",
            ["dependency:validation_runtime_missing"],
            ["build_error_contract", "pom_xml", "dependency_graph"],
        )
    return None


def _tomcat9_override(text: str, boot3_plus: bool) -> dict[str, Any] | None:
    if boot3_plus and ("tomcat" in text and ("9." in text or "tomcat-embed-core:9" in text)):
        return _candidate(
            "DEPENDENCY_REMOVE_TOMCAT9_OVERRIDE_BOOT3",
            "high",
            "Boot 3/4 target with Tomcat 9 override signal.",
            ["dependency:tomcat9_override_on_boot3_plus"],
            ["pom_xml", "dependency_graph"],
        )
    return None


def _zalando_problem(text: str, boot3_plus: bool) -> dict[str, Any] | None:
    if boot3_plus and "problem-spring-web" in text and ("0.27" in text or "0.28" in text or "0.29.0" in text):
        return _candidate(
            "DEPENDENCY_UPGRADE_ZALANDO_PROBLEM_SPRING_WEB_0291",
            "high",
            "Old Zalando problem-spring-web version under Boot 3/4 target.",
            ["dependency:old_zalando_problem_spring_web"],
            ["pom_xml", "dependency_graph"],
        )
    return None


def _maven_compiler_mismatch(text: str, java17_plus: bool, java21_plus: bool) -> dict[str, Any] | None:
    if "invalid target release" in text or "release version" in text or "source option" in text:
        confidence = "high" if (java17_plus or java21_plus) else "medium"
        return _candidate(
            "MAVEN_COMPILER_PLUGIN_SOURCE_TARGET_MISMATCH",
            confidence,
            "Maven compiler release/source/target mismatch signal found.",
            ["maven:compiler_release_mismatch"],
            ["build_error_contract", "pom_xml"],
        )
    return None


def _java_language_level(text: str, java17_plus: bool, java21_plus: bool) -> dict[str, Any] | None:
    if "unsupportedclassversionerror" in text or "class file has wrong version" in text:
        confidence = "high" if (java17_plus or java21_plus) else "medium"
        return _candidate(
            "JAVA_VERSION_LANGUAGE_LEVEL_FAILURE",
            confidence,
            "Java class/runtime language level mismatch signal found.",
            ["java:language_level_mismatch"],
            ["build_error_contract", "pom_xml"],
        )
    return None


def _spring_boot_plugin_mismatch(text: str, target_boot: str) -> dict[str, Any] | None:
    if "spring-boot-maven-plugin" in text and ("version mismatch" in text or "plugin" in text and target_boot and target_boot not in text):
        return _candidate(
            "SPRING_BOOT_PLUGIN_VERSION_MISMATCH",
            "medium",
            "Spring Boot Maven plugin/target version mismatch signal found.",
            ["maven:spring_boot_plugin_mismatch"],
            ["pom_xml", "build_error_contract"],
        )
    return None


def _test_api_breakage(text: str, usable: list[str]) -> dict[str, Any] | None:
    if ("test_report" in usable or "test_agent_log" in usable) and ("nosuchmethoderror" in text or "assertionerror" in text or "test failed" in text):
        return _candidate(
            "TEST_API_BREAKAGE",
            "medium",
            "Test failure artifact includes API/test framework breakage signal.",
            ["test:api_breakage"],
            ["test_report", "test_agent_log"],
        )
    return None


def _h2_smoke_config(text: str) -> dict[str, Any] | None:
    if "h2_required" in text and ("missing h2" in text or "h2 smoke" in text or "jdbc:h2" in text):
        return _candidate(
            "H2_SMOKE_CONFIG_ONLY",
            "medium",
            "H2 smoke-only configuration signal found.",
            ["smoke:h2_config_only"],
            ["test_report", "runtime_contract"],
        )
    return None


def _unsupported_known_failure(text: str) -> dict[str, Any] | None:
    if "springfox" in text or "powermock" in text:
        return {
            "failure_type": "unsupported_legacy_test_or_api_dependency",
            "confidence": "medium",
            "reason": "Known legacy dependency/API signal found, but no R7C supported repair family exists.",
            "signals": ["unsupported:legacy_dependency_or_test_framework"],
        }
    return None


def _missing_required(required: list[str], usable: list[str], missing: list[str]) -> list[str]:
    result = [item for item in required if item not in usable]
    result.extend(item for item in missing if item in required and item not in result)
    return result[:8]


def _needs_more_evidence(missing: list[str], usable: list[str], text: str) -> bool:
    core_missing = {"build_error_contract", "test_agent_log", "test_report"}.intersection(missing)
    has_failure_text = any(marker in text for marker in ("[error]", "exception", "does not exist", "invalid target release", "release version"))
    return bool(core_missing and not has_failure_text)
