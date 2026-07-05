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

    compile_gate = _main_source_compile_failure(evidence_pack, text)
    if compile_gate is not None:
        return _envelope(
            evidence_pack=evidence_pack,
            status=compile_gate["status"],
            failure_type=compile_gate["failure_type"],
            repair_family_candidate=compile_gate.get("repair_family_candidate", ""),
            confidence=compile_gate["confidence"],
            confidence_reason=compile_gate["reason"],
            matched_signals=compile_gate["signals"],
            missing_required_evidence=_missing_required(compile_gate["required"], usable, missing),
            assistant_next_action=compile_gate["assistant_next_action"],
            repair_blocked_reason=compile_gate["repair_blocked_reason"],
            governance_gate_type=compile_gate["governance_gate_type"],
            stage_relevance=compile_gate["stage_relevance"],
            extra=compile_gate.get("extra", {}),
        )

    jackson_gate = _jackson_alignment_failure(evidence_pack, text)
    if jackson_gate is not None:
        return _envelope(
            evidence_pack=evidence_pack,
            status=jackson_gate["status"],
            failure_type=jackson_gate["failure_type"],
            repair_family_candidate=jackson_gate.get("repair_family_candidate", ""),
            confidence=jackson_gate["confidence"],
            confidence_reason=jackson_gate["reason"],
            matched_signals=jackson_gate["signals"],
            missing_required_evidence=_missing_required(jackson_gate["required"], usable, missing),
            assistant_next_action=jackson_gate["assistant_next_action"],
            repair_blocked_reason=jackson_gate["repair_blocked_reason"],
            governance_gate_type=jackson_gate["governance_gate_type"],
            stage_relevance=jackson_gate["stage_relevance"],
            extra=jackson_gate.get("extra", {}),
        )

    review_gate = _review_gate_signal(text, boot3_plus, missing)
    if review_gate is not None:
        return _envelope(
            evidence_pack=evidence_pack,
            status=review_gate["status"],
            failure_type=review_gate["failure_type"],
            repair_family_candidate=review_gate.get("repair_family_candidate", ""),
            confidence=review_gate["confidence"],
            confidence_reason=review_gate["reason"],
            matched_signals=review_gate["signals"],
            missing_required_evidence=_missing_required(review_gate["required"], usable, missing),
            assistant_next_action=review_gate["assistant_next_action"],
            repair_blocked_reason=review_gate["repair_blocked_reason"],
            governance_gate_type=review_gate["governance_gate_type"],
            stage_relevance=review_gate["stage_relevance"],
        )

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
            governance_gate_type="future_deterministic_candidate",
            stage_relevance=_stage_relevance(evidence_pack, "deterministic candidate is stage-sensitive and remains disabled in R7C.2"),
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
            governance_gate_type="unsupported_review_signal",
            stage_relevance=_stage_relevance(evidence_pack, "legacy dependency/test signal needs more taxonomy"),
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
            governance_gate_type="blocked_pending_evidence",
            stage_relevance=_stage_relevance(evidence_pack, "stage failure needs core build/test evidence"),
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
        governance_gate_type="unknown",
        stage_relevance=_stage_relevance(evidence_pack, "no stage-aware taxonomy signal matched"),
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
    governance_gate_type: str = "",
    stage_relevance: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = {
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
        "governance_gate_type": governance_gate_type,
        "stage_relevance": stage_relevance,
        "downstream_stage_state": evidence_pack.get("downstream_stage_state"),
        "evidence_pack_id": evidence_pack.get("evidence_pack_id"),
        "evidence_pack_checksum": evidence_pack.get("evidence_pack_checksum"),
    }
    if extra:
        envelope.update(extra)
    return envelope


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


def _review_gate(
    *,
    status: str,
    failure_type: str,
    confidence: str,
    reason: str,
    signals: list[str],
    required: list[str],
    assistant_next_action: str,
    repair_blocked_reason: str,
    governance_gate_type: str,
    stage_relevance: str,
    repair_family_candidate: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    gate = {
        "status": status,
        "failure_type": failure_type,
        "repair_family_candidate": repair_family_candidate,
        "confidence": confidence,
        "reason": reason,
        "signals": signals,
        "required": required,
        "assistant_next_action": assistant_next_action,
        "repair_blocked_reason": repair_blocked_reason,
        "governance_gate_type": governance_gate_type,
        "stage_relevance": stage_relevance,
    }
    if extra:
        gate["extra"] = extra
    return gate


def _review_gate_signal(text: str, boot3_plus: bool, missing: list[str]) -> dict[str, Any] | None:
    missing_core = [item for item in ("build_error_contract", "test_agent_log", "test_report") if item in missing]

    if "powermock" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
            confidence="medium" if missing_core else ("high" if boot3_plus else "medium"),
            reason="PowerMock legacy test strategy signal found; static/final/constructor mocking requires human review and no automatic repair.",
            signals=["review_gate:powermock_legacy_test_strategy"],
            required=missing_core or ["test_source", "test_report"],
            assistant_next_action="review_powermock_legacy_test_strategy",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Stage 2/3/4 high risk; Stage 1 advisory unless build/test evidence proves blocker.",
        )

    if "springfox" in text or "swagger2" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="LEGACY_API_DEPENDENCY_ALIGNMENT_REVIEW",
            confidence="medium",
            reason="Legacy API documentation dependency signal found; needs dependency/API review before any repair family can be selected.",
            signals=["review_gate:legacy_api_dependency_alignment"],
            required=missing_core or ["pom_xml", "dependency_graph", "build_error_contract"],
            assistant_next_action="review_legacy_api_dependency_alignment",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Stage 1 advisory when only dependency evidence exists; later stages may require replacement strategy.",
        )

    if "com.microsoft.azure" in text or "com.microsoft.windowsazure" in text or "com.microsoft.rest" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="AZURE_SDK_API_MIGRATION_REVIEW",
            confidence="medium",
            reason="Legacy Azure SDK coordinate/import signal found; API migration is human/LLM review only.",
            signals=["review_gate:azure_sdk_api_migration"],
            required=["pom_xml", "dependency_graph", "source_ref"],
            assistant_next_action="review_azure_sdk_api_migration",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="All stages; not deterministic because SDK APIs and behavior can change.",
        )

    if "io.jsonwebtoken" in text or "jjwt-api" in text or "jjwt-impl" in text or "jjwt-jackson" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="JJWT_VERSION_ALIGNMENT_REVIEW",
            confidence="medium" if boot3_plus else "low",
            reason="JJWT version/API signal found; version alignment needs stage and source-usage review.",
            signals=["review_gate:jjwt_version_alignment"],
            required=["pom_xml", "dependency_graph", "source_ref"],
            assistant_next_action="review_jjwt_version_alignment",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Mostly Boot 3/4 or Java 17/21 stages; advisory on Stage 1.",
        )

    if "org.apache.juneau" in text or "juneau-" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="JUNEAU_VERSION_ALIGNMENT_REVIEW",
            confidence="medium",
            reason="Apache Juneau dependency signal found; alignment or API review required.",
            signals=["review_gate:juneau_version_alignment"],
            required=["pom_xml", "dependency_graph", "source_ref"],
            assistant_next_action="review_juneau_version_alignment",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="All stages; review needed because dependency and API surface may move together.",
        )

    if "public_api_signature_change" in text or "public api signature" in text or "consumer compatibility" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="PUBLIC_API_SIGNATURE_CHANGE_REVIEW",
            confidence="medium",
            reason="Reference/runtime delta indicates public API signature drift; consumer compatibility review required.",
            signals=["review_gate:public_api_signature_change"],
            required=["reference_delta", "runtime_contract"],
            assistant_next_action="review_public_api_signature_change",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="All stages; public API compatibility cannot be auto-repaired.",
        )

    if "spring-security" in text or "spring security" in text or "websecurityconfigureradapter" in text:
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="SPRING_SECURITY_BEHAVIOR_REVIEW",
            confidence="medium" if boot3_plus else "low",
            reason="Spring Security dependency/config signal found; behavior review required before repair selection.",
            signals=["review_gate:spring_security_behavior"],
            required=["pom_xml", "runtime_contract", "test_report"],
            assistant_next_action="review_spring_security_behavior",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Mostly Boot 3/4 behavior risk; advisory on Stage 1 unless tests prove blocker.",
        )

    if "mockitoannotations.initmocks" in text or "initmocks(" in text:
        return _review_gate(
            status="known_family_candidate",
            failure_type="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
            repair_family_candidate="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
            confidence="medium",
            reason="Mockito initMocks source signal found; future deterministic test modernization candidate only.",
            signals=["candidate:initmocks_to_openmocks"],
            required=["test_source"],
            assistant_next_action="prepare_evidence_bound_proposal_in_R7D",
            repair_blocked_reason=REPAIR_DISABLED_REASON,
            governance_gate_type="future_deterministic_candidate",
            stage_relevance="All stages when Mockito source evidence exists; repair remains disabled in R7C.2.",
        )

    if "mockbean" in text or "mockitobean" in text:
        if boot3_plus:
            return _review_gate(
                status="known_family_candidate",
                failure_type="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
                repair_family_candidate="MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
                confidence="medium",
                reason="MockBean/MockitoBean test modernization signal found for Boot 3/4 target; future candidate only.",
                signals=["candidate:mockbean_to_mockitobean"],
                required=["test_source", "test_report"],
                assistant_next_action="prepare_evidence_bound_proposal_in_R7D",
                repair_blocked_reason=REPAIR_DISABLED_REASON,
                governance_gate_type="future_deterministic_candidate",
                stage_relevance="Relevant to later Boot 3.4/4 test modernization; repair remains disabled.",
            )
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="LEGACY_TEST_FRAMEWORK_MIGRATION",
            confidence="low" if missing_core else "medium",
            reason="MockBean-style legacy test framework signal found on Boot 2.x target; advisory review only.",
            signals=["review_gate:legacy_test_framework_migration"],
            required=missing_core or ["test_source", "test_report"],
            assistant_next_action="review_legacy_test_framework_migration",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Stage 1 Boot 2.7 must not become MockBean-to-MockitoBean repair candidate.",
        )

    if "mockito" in text and ("initmocks" not in text and "openmocks" not in text):
        return _review_gate(
            status="blocked_pending_evidence",
            failure_type="blocked_pending_evidence",
            confidence="low",
            reason="Mockito dependency signal found, but test source evidence is required before selecting a test modernization subtype.",
            signals=["blocked:mockito_dependency_without_test_source"],
            required=["test_source"],
            assistant_next_action="collect_missing_stage_evidence",
            repair_blocked_reason="missing_required_failure_evidence",
            governance_gate_type="blocked_pending_evidence",
            stage_relevance="All stages; source evidence required.",
        )

    if _has_mixed_jakarta_javax(text):
        return _review_gate(
            status="unsupported_known_failure",
            failure_type="JAKARTA_HYBRID_STRATEGY_REVIEW",
            confidence="medium" if boot3_plus else "low",
            reason="Mixed javax/jakarta namespace state found; stage-specific hybrid strategy review required.",
            signals=["review_gate:jakarta_hybrid_strategy"],
            required=["pom_xml", "dependency_graph", "source_ref"],
            assistant_next_action="review_jakarta_hybrid_strategy",
            repair_blocked_reason="human_review_gate_no_auto_repair",
            governance_gate_type="human_review_gate",
            stage_relevance="Boot 2.7 may retain javax; Boot 3/4 generally expects jakarta.",
        )

    behavioral = _behavioral_test_failure(text, missing)
    if behavioral is not None:
        return behavioral

    return None


def _jackson_alignment_failure(evidence_pack: dict[str, Any], text: str) -> dict[str, Any] | None:
    missing_class = "tostringserializerbase" in text
    has_runtime_missing = missing_class and (
        "noclassdeffound" in text
        or "classnotfound" in text
        or "could not initialize class" in text
        or "failed to instantiate" in text
    )
    has_object_mapper_signal = (
        "messageutils.createobjectmapper" in text
        or "messageutilstest" in text
        or "messageutils" in text
        or "objectmapper" in text
        or "javatimemodule" in text
    )
    has_conflict = "jackson-" in text and "2.13.5" in text and _has_legacy_jackson_version(text)
    has_mixed_versions = _has_mixed_jackson_versions(text)
    if not (has_runtime_missing and has_object_mapper_signal and (has_conflict or has_mixed_versions)):
        return None
    advisory = ["reference:msa_utils_migrated_reference_confirms_alignment_trajectory"]
    advisory.extend(_dependency_review_advisory_signals(text))
    return _review_gate(
        status="known_family_candidate",
        failure_type="JACKSON_VERSION_ALIGNMENT_DRIFT",
        repair_family_candidate="JACKSON_VERSION_ALIGNMENT_DRIFT",
        confidence="high",
        reason="Jackson runtime class missing in MessageUtilsTest with mixed Jackson dependency versions on Boot 2.7.x; backend can prepare a checksum-bound POM-only alignment candidate.",
        signals=[
            "runtime:jackson_tostringserializerbase_missing",
            "test:messageutils_createobjectmapper_failure",
            "dependency:jackson_mixed_versions",
            "stage:boot_2_7_jackson_2_13_5_alignment",
        ],
        required=["test_report", "dependency_graph", "pom_xml"],
        assistant_next_action="prepare_jackson_alignment_apply_candidate",
        repair_blocked_reason="human_approval_required_before_sandbox_apply",
        governance_gate_type="backend_deterministic_candidate",
        stage_relevance=_stage_relevance(evidence_pack, "Stage 1 Boot 2.7 / Java 11; align Jackson around 2.13.5, not Boot 3.5 reference 2.20.0."),
        extra={
            "primary_failure": "Jackson version alignment drift",
            "jackson_alignment_target_version": "2.13.5",
            "advisory_signals": advisory[:8],
        },
    )


def _has_mixed_jackson_versions(text: str) -> bool:
    versions = set(re.findall(r"jackson-[a-z0-9-]+[^\n\r]{0,160}?(2\.\d+\.\d+)", text))
    if not versions:
        versions = set(re.findall(r"selected jackson-[a-z0-9-]+ is (2\.\d+\.\d+)", text))
        if "2.13.5" in text and "jackson-" in text:
            versions.add("2.13.5")
    return "2.13.5" in versions and any(version in versions for version in {"2.9.6", "2.10.0", "2.8.11"})


def _has_legacy_jackson_version(text: str) -> bool:
    legacy_pairs = (
        ("jackson-databind", "2.9.6"),
        ("jackson-core", "2.10.0"),
        ("jackson-annotations", "2.10.0"),
        ("jackson-dataformat-csv", "2.10.0"),
        ("jackson-dataformat-xml", "2.8.11"),
    )
    return any(artifact in text and version in text for artifact, version in legacy_pairs)


def _dependency_review_advisory_signals(text: str) -> list[str]:
    signals: list[str] = []
    if "com.microsoft.azure" in text or "com.microsoft.windowsazure" in text or "com.microsoft.rest" in text:
        signals.append("advisory:azure_sdk_api_migration_review_not_primary")
    if "io.jsonwebtoken" in text or "jjwt-api" in text or "jjwt-impl" in text or "jjwt-jackson" in text:
        signals.append("advisory:jjwt_version_alignment_review_not_primary")
    if "org.apache.juneau" in text or "juneau-" in text:
        signals.append("advisory:juneau_version_alignment_review_not_primary")
    if "spring-security" in text or "spring security" in text or "websecurityconfigureradapter" in text:
        signals.append("advisory:spring_security_behavior_review_not_primary")
    return signals


def _main_source_compile_failure(evidence_pack: dict[str, Any], text: str) -> dict[str, Any] | None:
    build_status = str(evidence_pack.get("build_status") or "").lower()
    usable = {
        str(item.get("kind") or "")
        for item in evidence_pack.get("usable_artifacts", [])
        if isinstance(item, dict)
    }
    if "build_failed_in_sandbox" not in build_status and "build_error_contract" not in usable:
        return None
    if not _looks_like_java_compile_failure(text):
        return None
    blockers = _main_source_compile_blockers(evidence_pack)
    if not blockers:
        return None
    advisory = []
    if "powermock" in text or "powermockito" in text or "preparefortest" in text:
        advisory.append("advisory:powermock_signal_not_primary_without_build_or_test_failure")
    sort_targets = _sort_api_drift_targets(evidence_pack, blockers)
    if sort_targets:
        return _review_gate(
            status="known_family_candidate",
            failure_type="SPRING_DATA_SORT_API_DRIFT",
            repair_family_candidate="SPRING_DATA_SORT_API_DRIFT",
            confidence="high",
            reason="Spring Data Sort constructor compile failure found in main source. Reference CLI migration used Sort.by(...) for same msa-utils drift; backend treats reference as advisory evidence only.",
            signals=["compiler:spring_data_sort_constructor_removed", "golden_reference:msa_utils_cli_sort_by"],
            required=["build_error_contract", "pom_xml", "source_ref"],
            assistant_next_action="prepare_sort_by_apply_candidate",
            repair_blocked_reason="human_approval_required_before_sandbox_apply",
            governance_gate_type="backend_deterministic_candidate",
            stage_relevance=_stage_relevance(evidence_pack, "Sort.by recipe is sandbox-only and requires checksum-bound human approval."),
            extra={
                "primary_failure": "Spring Data Sort API drift",
                "compile_blockers": blockers[:12],
                "sort_api_drift_targets": sort_targets[:12],
                "advisory_signals": advisory[:8],
            },
        )
    return _review_gate(
        status="unsupported_known_failure",
        failure_type="JAVA_MAIN_SOURCE_COMPILE_FAILURE",
        confidence="high",
        reason="Build error contract contains Java compilation errors in src/main/java; build evidence has priority over unrelated readonly test signals.",
        signals=["compiler:main_source_compile_failure"],
        required=["build_error_contract", "pom_xml"],
        assistant_next_action="review_main_source_compile_failure",
        repair_blocked_reason="compile_failure_no_auto_repair",
        governance_gate_type="human_review_gate",
        stage_relevance=_stage_relevance(evidence_pack, "build contract is primary source for BUILD_FAILED_IN_SANDBOX; downstream remains blocked."),
        extra={
            "primary_failure": "Java compilation/build failure",
            "compile_blockers": blockers[:12],
            "advisory_signals": advisory[:8],
        },
    )


def _looks_like_java_compile_failure(text: str) -> bool:
    markers = (
        "compilation error",
        "compilation failure",
        "maven-compiler-plugin",
        "incompatible types",
        "cannot find symbol",
        "package ",
        "does not exist",
    )
    return any(marker in text for marker in markers)


def _main_source_compile_blockers(evidence_pack: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<path>(?:[a-z]:)?[^\"'\n\r]*src[\\/]+main[\\/]+java[^:\]\n\r]*\.java)"
        r"(?::?\[(?P<bracket_line>\d+),(?P<bracket_column>\d+)\]|[:\[](?P<line>\d+)(?:,(?P<column>\d+))?)?"
        r".{0,220}?(?P<message>incompatible types|cannot find symbol|package [^\"'\n\r]+ does not exist|compilation failure)",
        re.IGNORECASE,
    )
    for artifact in evidence_pack.get("usable_artifacts", []):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("kind") != "build_error_contract":
            continue
        for error in artifact.get("compile_errors", []):
            if isinstance(error, dict) and str(error.get("path") or "").startswith("src/main/java"):
                blockers.append({
                    "path": str(error.get("path") or ""),
                    "line": str(error.get("line") or ""),
                    "column": str(error.get("column") or ""),
                    "message": str(error.get("message") or ""),
                })
        haystack = " ".join(str(artifact.get(key) or "") for key in ("excerpt", "ref"))
        for match in pattern.finditer(haystack):
            blockers.append({
                "path": _normalize_source_path(match.group("path")),
                "line": match.group("bracket_line") or match.group("line") or "",
                "column": match.group("bracket_column") or match.group("column") or "",
                "message": match.group("message"),
            })
    return blockers[:12]


def _sort_api_drift_targets(evidence_pack: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocker_paths = {str(item.get("path") or "").replace("\\", "/") for item in blockers}
    result: list[dict[str, str]] = []
    for artifact in evidence_pack.get("usable_artifacts", []):
        if not isinstance(artifact, dict) or artifact.get("kind") != "source_ref":
            continue
        excerpt = str(artifact.get("excerpt") or "")
        ref = str(artifact.get("internal_ref") or artifact.get("ref") or "").replace("\\", "/")
        if not _has_sort_constructor(excerpt):
            continue
        matched_path = next((path for path in blocker_paths if path and (path in ref or ref.endswith(path))), "")
        if not matched_path and "src/main/java" in ref:
            matched_path = ref[ref.index("src/main/java"):]
        if matched_path:
            result.append({
                "path": matched_path,
                "recipe": "SPRING_DATA_SORT_BY",
                "reference": "msa-utils migrated/reference",
            })
    return result[:12]


def _has_sort_constructor(text: str) -> bool:
    return bool(re.search(r"\bnew\s+Sort\s*\(", text))


def _normalize_source_path(path: str) -> str:
    marker = "src/main/java"
    normalized = path.replace("\\", "/")
    idx = normalized.lower().find(marker)
    if idx >= 0:
        return normalized[idx:]
    return normalized[-220:]


def _behavioral_test_failure(text: str, missing: list[str]) -> dict[str, Any] | None:
    has_test_evidence = "test_report" not in missing and ("test" in text or "surefire" in text or "assertion" in text)
    if not has_test_evidence:
        return None
    mappings = [
        (
            "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION",
            ("cannot mock final class", "cannot mock/spy class", "final class"),
            "behavioral:mockito_final_class",
            "Review Mockito final-class mocking strategy or inline mocking support.",
        ),
        (
            "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
            ("responseentityexceptionhandler", "exceptiontranslator", "request processing failed"),
            "behavioral:spring_mvc_exception_handler_drift",
            "Review Spring MVC exception handler behavior drift.",
        ),
        (
            "JAKARTA_VALIDATION_HANDLER_MISMATCH",
            ("jakarta.validation.constraintviolationexception", "javax.validation.constraintviolationexception"),
            "behavioral:jakarta_validation_handler_mismatch",
            "Review validation exception handler namespace mismatch.",
        ),
        (
            "HTTP_STATUS_CONTRACT_DRIFT",
            ("expected:<", "but was:<", "status code"),
            "behavioral:http_status_contract_drift",
            "Review HTTP status contract drift.",
        ),
        (
            "APPLICATION_BEHAVIOR_REGRESSION",
            ("assertionerror", "comparisonfailure", "nosuchelementexception", "jwtexception"),
            "behavioral:application_behavior_regression",
            "Review application behavior regression.",
        ),
    ]
    for failure_type, markers, signal, reason in mappings:
        if any(marker in text for marker in markers):
            return _review_gate(
                status="unsupported_known_failure",
                failure_type=failure_type,
                confidence="medium",
                reason=reason,
                signals=[signal],
                required=["test_report", "test_agent_log"],
                assistant_next_action=f"review_{failure_type.lower()}",
                repair_blocked_reason="human_review_gate_no_auto_repair",
                governance_gate_type="llm_rag_candidate",
                stage_relevance="Behavioral test failure; needs reviewer/human and possible LLM proposal later.",
            )
    return None


def _has_mixed_jakarta_javax(text: str) -> bool:
    has_javax = "javax.servlet" in text or "javax.validation" in text or "javax.annotation" in text
    has_jakarta = "jakarta.servlet" in text or "jakarta.validation" in text or "jakarta.annotation" in text
    return has_javax and has_jakarta


def _stage_relevance(evidence_pack: dict[str, Any], note: str) -> str:
    stage = evidence_pack.get("stage_index")
    source_boot = str(evidence_pack.get("source_boot_version") or "unknown")
    target_boot = str(evidence_pack.get("target_boot_version") or "unknown")
    source_java = str(evidence_pack.get("source_java_version") or "unknown")
    target_java = str(evidence_pack.get("target_java_version") or "unknown")
    return f"Stage {stage or '?'} {source_boot}/Java {source_java} -> {target_boot}/Java {target_java}: {note}"


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
