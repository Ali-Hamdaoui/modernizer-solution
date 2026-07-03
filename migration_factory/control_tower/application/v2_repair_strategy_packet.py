"""Generic advisory repair strategy packets for R9."""

from __future__ import annotations

import json
import re
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary, redact_public_value
from migration_factory.control_tower.application.v2_model_schemas import extract_json_object
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_repair_family_registry import (
    RepairFamilyPolicy,
    repair_family_policy,
)
from migration_factory.control_tower.application.v2_repair_subfamily_classifier import (
    classify_repair_subfamily,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


ALLOWED_STATUS = {"available", "blocked_missing_evidence", "unsupported", "unknown"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_VERDICT = {"advisory_accept", "advisory_reject", "advisory_needs_changes"}
POWERMOCK_PATTERNS = (
    ("PowerMockRunner", "JUnit 4 runner dependency"),
    ("PrepareForTest", "classloader preparation"),
    ("PowerMockito.mockStatic", "static mocking"),
    ("PowerMockito.whenNew", "constructor mocking"),
    ("mockStatic", "static mocking"),
    ("whenNew", "constructor mocking"),
    ("Whitebox", "private method mocking"),
    ("final class", "final class mocking"),
)


def create_repair_strategy_packet(
    *,
    job_id: str,
    stage_index: int | None,
    classification: dict[str, Any] | None,
    stage_evidence: dict[str, Any] | None,
    migration_memory: dict[str, Any] | None = None,
    llm_client: object | None = None,
    llm_enabled: bool = False,
) -> dict[str, Any]:
    classification = classification if isinstance(classification, dict) else {}
    stage_evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
    migration_memory = migration_memory if isinstance(migration_memory, dict) else {}
    family = _family(classification)
    policy = repair_family_policy(family)
    missing = _missing_evidence(policy, classification, stage_evidence)
    detected_patterns = _detected_patterns(policy.family, stage_evidence, classification)
    proposer = _run_proposer(
        policy=policy,
        classification=classification,
        stage_evidence=stage_evidence,
        migration_memory=migration_memory,
        detected_patterns=detected_patterns,
        missing_evidence=missing,
        llm_client=llm_client,
        llm_enabled=llm_enabled and policy.llm_proposer_enabled,
    )
    reviewer = _run_reviewer(
        policy=policy,
        proposer_output=proposer["output"],
        missing_evidence=missing,
        llm_client=llm_client,
        llm_enabled=llm_enabled and policy.llm_reviewer_required,
    )
    evidence_pack_checksum = str(stage_evidence.get("evidence_pack_checksum") or "")
    classification_status = str(classification.get("classification_status") or "")
    fallback = _fallback_trace(
        policy,
        proposer,
        reviewer,
        llm_client=llm_client,
        llm_enabled=llm_enabled,
    )
    status = _strategy_status(policy, missing)
    output = proposer["output"]
    packet_job_id = str(job_id or stage_evidence.get("job_id") or "")
    packet_stage_index = stage_index if stage_index is not None else stage_evidence.get("stage_index")
    subfamily_assessment = classify_repair_subfamily(
        family_policy=policy,
        repair_strategy_packet={
            "job_id": packet_job_id,
            "stage_index": packet_stage_index,
            "family": policy.family,
        },
        stage_evidence=stage_evidence,
        classification=classification,
        migration_memory=migration_memory,
    )
    base_hash = sha256_canonical_json({
        "job_id": packet_job_id,
        "stage_index": packet_stage_index,
        "family": policy.family,
        "evidence_pack_checksum": evidence_pack_checksum,
    })[:16]
    packet = {
        "strategy_id": f"repair-strategy-{base_hash}-v1",
        "strategy_base_id": f"repair-strategy-{base_hash}",
        "version": 1,
        "job_id": packet_job_id,
        "stage_index": packet_stage_index,
        "family": policy.family,
        "risk_level": policy.risk_level,
        "category": policy.category,
        "strategy_status": status,
        "evidence_pack_checksum": evidence_pack_checksum,
        "classification_status": classification_status,
        "apply_candidate_allowed": bool(policy.apply_candidate_allowed),
        "backend_recipe_available": bool(policy.backend_recipe_available),
        "human_gate_required": bool(policy.human_gate_required),
        "root_cause": output.get("root_cause") or _default_root_cause(policy, classification),
        "affected_files": output.get("affected_files") or _affected_files(stage_evidence),
        "detected_patterns": output.get("detected_patterns") or detected_patterns,
        "migration_options": output.get("migration_options") or _migration_options(policy),
        "recommended_strategy": output.get("recommended_strategy") or _recommended_strategy(policy),
        "risk_notes": output.get("risk_notes") or _risk_notes(policy),
        "missing_evidence": missing,
        "engineer_checklist": output.get("engineer_checklist") or _engineer_checklist(policy),
        "repair_subfamily_assessment": subfamily_assessment,
        "llm_proposer": proposer,
        "llm_reviewer": reviewer,
        "llm_fallback": fallback,
        "backend_gate": _backend_gate(),
    }
    packet["strategy_checksum"] = repair_strategy_packet_checksum(packet)
    return _clamp_packet(packet, policy)


def repair_strategy_packet_checksum(packet: dict[str, Any]) -> str:
    body = {
        key: value
        for key, value in packet.items()
        if key not in {"strategy_id", "strategy_base_id", "version", "strategy_checksum", "created_at", "updated_at", "history_count", "history"}
    }
    return f"sha256:{sha256_canonical_json(body)}"


def repair_strategy_narration(packet: dict[str, Any] | None, candidate: dict[str, Any] | None = None) -> str:
    if not isinstance(packet, dict):
        return "Repair strategy: unavailable. Backend has no strategy packet yet; downstream remains blocked."
    proposer = packet.get("llm_proposer") if isinstance(packet.get("llm_proposer"), dict) else {}
    reviewer = packet.get("llm_reviewer") if isinstance(packet.get("llm_reviewer"), dict) else {}
    fallback = packet.get("llm_fallback") if isinstance(packet.get("llm_fallback"), dict) else {}
    subfamily = packet.get("repair_subfamily_assessment") if isinstance(packet.get("repair_subfamily_assessment"), dict) else {}
    candidate_text = "exists" if candidate else "none"
    version = packet.get("version") or "unknown"
    history_count = int(packet.get("history_count") or 0)
    fallback_source = fallback.get("fallback_validated_output_source") or "none"
    changed_text = (
        f" Strategy history has {history_count} versions; latest differs from earlier packet checksums."
        if history_count > 1
        else " Strategy history has one version."
    )
    return (
        f"Repair strategy: id={packet.get('strategy_id')}, version={version}, "
        f"family={packet.get('family')}, risk={packet.get('risk_level')}, status={packet.get('strategy_status')}. "
        f"Checksum={packet.get('strategy_checksum')}; evidence={packet.get('evidence_pack_checksum')}. "
        f"Root cause: {packet.get('root_cause')}. "
        f"Subfamily: {subfamily.get('subfamily', 'unknown')}; promotion={subfamily.get('promotion_status', 'unknown')}; "
        f"subfamily reason: matched {', '.join(subfamily.get('matched_patterns') or []) or 'no specific pattern'}. "
        f"Proposer: {_trace_summary(proposer)} Reviewer: {_trace_summary(reviewer)} "
        f"Fallback: {_trace_summary(fallback)}; fallback model invoked={bool(fallback.get('fallback_model_invoked'))}; "
        f"fallback output source={fallback_source}. Missing evidence: {', '.join(packet.get('missing_evidence') or []) or 'none'}. "
        f"Engineer next: {subfamily.get('recommended_engineer_action') or '; '.join(packet.get('engineer_checklist') or []) or packet.get('recommended_strategy')}. "
        f"Apply candidate: {candidate_text}. Apply allowed: {bool(subfamily.get('apply_candidate_allowed')) and bool(subfamily.get('backend_recipe_available'))}. "
        + changed_text
        + " "
        "Assistant cannot approve, apply, execute, or start downstream; backend and human gates own state changes."
    )


def _family(classification: dict[str, Any]) -> str:
    return str(classification.get("repair_family_candidate") or classification.get("failure_type") or "UNKNOWN_FAILURE")


def _strategy_status(policy: RepairFamilyPolicy, missing: list[str]) -> str:
    if policy.family == "UNKNOWN_FAILURE":
        return "unknown"
    if missing:
        return "blocked_missing_evidence"
    return "available"


def _missing_evidence(policy: RepairFamilyPolicy, classification: dict[str, Any], stage_evidence: dict[str, Any]) -> list[str]:
    existing = [str(item) for item in classification.get("missing_required_evidence", []) if str(item)]
    usable = {
        str(item.get("kind") or "")
        for item in stage_evidence.get("usable_artifacts", [])
        if isinstance(item, dict)
    }
    text = _evidence_text(stage_evidence, classification)
    result = list(existing)
    for required in policy.evidence_required:
        if required == "test_source_markers":
            if not any(marker.lower() in text for marker, _ in POWERMOCK_PATTERNS):
                result.append(required)
        elif required not in usable:
            result.append(required)
    return list(dict.fromkeys(result))[:8]


def _detected_patterns(family: str, stage_evidence: dict[str, Any], classification: dict[str, Any]) -> list[str]:
    text = _evidence_text(stage_evidence, classification)
    patterns: list[str] = []
    if family == "POWERMOCK_LEGACY_TEST_STRATEGY":
        for marker, label in POWERMOCK_PATTERNS:
            if marker.lower() in text or label.lower() in text:
                patterns.append(label)
        if "powermock" in text:
            patterns.append("PowerMock legacy dependency")
        patterns.extend(["Mockito inline candidate", "refactor required"])
    else:
        patterns.extend(str(item) for item in classification.get("matched_signals", [])[:8])
    return list(dict.fromkeys(patterns))[:12]


def _run_proposer(
    *,
    policy: RepairFamilyPolicy,
    classification: dict[str, Any],
    stage_evidence: dict[str, Any],
    migration_memory: dict[str, Any],
    detected_patterns: list[str],
    missing_evidence: list[str],
    llm_client: object | None,
    llm_enabled: bool,
) -> dict[str, Any]:
    fallback = _default_proposer(policy, classification, stage_evidence, detected_patterns, missing_evidence)
    return _run_role(
        role="repair_strategy_proposer",
        model_role=V2ModelRole.PROPOSER,
        llm_client=llm_client,
        llm_enabled=llm_enabled,
        output_kind="proposer",
        fallback=fallback,
        prompt_payload={
            "policy": policy.to_dict(),
            "classification": classification,
            "stage_evidence": _public_evidence(stage_evidence),
            "migration_memory": migration_memory,
            "required_schema": "repair_strategy_proposer",
        },
    )


def _run_reviewer(
    *,
    policy: RepairFamilyPolicy,
    proposer_output: dict[str, Any],
    missing_evidence: list[str],
    llm_client: object | None,
    llm_enabled: bool,
) -> dict[str, Any]:
    fallback = {
        "status": "fallback_used",
        "role": "repair_strategy_reviewer",
        "verdict": "advisory_needs_changes" if missing_evidence else "advisory_accept",
        "critique": "Deterministic fallback reviewer: strategy remains advisory and requires human gate.",
        "risks": _risk_notes(policy),
        "missing_evidence": missing_evidence,
        "unsafe_assumptions": ["LLM output cannot approve, apply, or start downstream."],
        "recommended_next_action": _recommended_strategy(policy),
        "confidence": "low",
    }
    return _run_role(
        role="repair_strategy_reviewer",
        model_role=V2ModelRole.REVIEWER,
        llm_client=llm_client,
        llm_enabled=llm_enabled,
        output_kind="reviewer",
        fallback=fallback,
        prompt_payload={
            "policy": policy.to_dict(),
            "proposer_output": proposer_output,
            "missing_evidence": missing_evidence,
            "required_schema": "repair_strategy_reviewer",
        },
    )


def _run_role(
    *,
    role: str,
    model_role: V2ModelRole,
    llm_client: object | None,
    llm_enabled: bool,
    output_kind: str,
    fallback: dict[str, Any],
    prompt_payload: dict[str, Any],
) -> dict[str, Any]:
    input_checksum = f"sha256:{sha256_canonical_json(redact_public_value(prompt_payload))}"
    if not llm_client or not llm_enabled:
        output = _clamp_output(fallback, output_kind)
        return _trace(role, "fallback_used", False, True, "llm_strategy_disabled_or_unconfigured", input_checksum, output, "fallback_validated")
    try:
        prompt = redact_model_summary(json.dumps(redact_public_value(prompt_payload), sort_keys=True)[:6000])
        fallback_text = json.dumps(fallback, sort_keys=True, separators=(",", ":"))
        if hasattr(llm_client, "answer_with_role"):
            raw = llm_client.answer_with_role(role=model_role, prompt=prompt, fallback=fallback_text)
        elif hasattr(llm_client, "answer"):
            raw = llm_client.answer(prompt=prompt, fallback=fallback_text)
        else:
            raise TypeError("llm_strategy_client_missing_supported_method")
        parsed = extract_json_object(str(getattr(raw, "content", raw) or ""))
        if not isinstance(parsed, dict):
            output = _clamp_output(fallback, output_kind)
            return _trace(role, "fallback_used", True, True, "invalid_json_model_output", input_checksum, output, "fallback_validated")
        output = _clamp_output(parsed, output_kind)
        required_missing = _missing_output_fields(output, output_kind)
        if required_missing:
            output = _clamp_output({**fallback, **output}, output_kind)
            return _trace(role, "fallback_used", True, True, "schema_missing:" + ",".join(required_missing), input_checksum, output, "fallback_validated")
        return _trace(role, "available", True, False, "", input_checksum, output, "validated")
    except Exception as exc:
        output = _clamp_output(fallback, output_kind)
        return _trace(role, "fallback_used", False, True, redact_model_summary(str(exc)), input_checksum, output, "fallback_validated")


def _trace(role: str, status: str, llm_invoked: bool, fallback_used: bool, reason: str, input_checksum: str, output: dict[str, Any], schema_status: str) -> dict[str, Any]:
    return {
        "role": role,
        "status": status,
        "llm_invoked": bool(llm_invoked),
        "fallback_used": bool(fallback_used),
        "failure_reason": redact_model_summary(reason)[:300],
        "input_checksum": input_checksum,
        "output": output,
        "output_checksum": f"sha256:{sha256_canonical_json(output)}",
        "schema_validation_status": schema_status,
        "non_actionable": True,
        "apply_allowed": False,
        "approval_allowed": False,
        "downstream_start_allowed": False,
    }


def _fallback_trace(
    policy: RepairFamilyPolicy,
    proposer: dict[str, Any],
    reviewer: dict[str, Any],
    *,
    llm_client: object | None,
    llm_enabled: bool,
) -> dict[str, Any]:
    used = bool(proposer.get("fallback_used")) or bool(reviewer.get("fallback_used"))
    deterministic = {
        "status": "fallback_used" if used else "unavailable",
        "role": "repair_strategy_fallback",
        "verdict": "advisory_needs_changes" if used else "advisory_accept",
        "critique": "Fallback remains advisory only." if used else "Fallback not needed.",
        "risks": _risk_notes(policy) if used else [],
        "missing_evidence": [],
        "unsafe_assumptions": ["Fallback cannot approve or apply."] if used else [],
        "recommended_next_action": _recommended_strategy(policy),
        "confidence": "low",
    }
    if not used:
        trace = _trace("repair_strategy_fallback", deterministic["status"], False, False, "fallback_model_not_needed", "", deterministic, "not_applicable")
        trace.update({
            "fallback_model_invoked": False,
            "fallback_model_used": False,
            "fallback_failure_reason": "",
            "fallback_validated_output_source": "none",
        })
        return trace

    input_payload = {
        "policy": policy.to_dict(),
        "proposer_trace": proposer,
        "reviewer_trace": reviewer,
        "required_schema": "repair_strategy_fallback",
        "governance": _backend_gate(),
    }
    input_checksum = f"sha256:{sha256_canonical_json(redact_public_value(input_payload))}"
    if llm_client and llm_enabled:
        try:
            prompt = redact_model_summary(json.dumps(redact_public_value(input_payload), sort_keys=True)[:6000])
            fallback_text = json.dumps(deterministic, sort_keys=True, separators=(",", ":"))
            if hasattr(llm_client, "answer_with_role"):
                raw = llm_client.answer_with_role(role=V2ModelRole.FALLBACK, prompt=prompt, fallback=fallback_text)
            elif hasattr(llm_client, "answer"):
                raw = llm_client.answer(prompt=prompt, fallback=fallback_text)
            else:
                raise TypeError("llm_strategy_client_missing_supported_method")
            parsed = extract_json_object(str(getattr(raw, "content", raw) or ""))
            if not isinstance(parsed, dict):
                raise ValueError("invalid_json_fallback_model_output")
            output = _clamp_output(parsed, "fallback")
            missing = _missing_output_fields(output, "fallback")
            if missing:
                raise ValueError("schema_missing:" + ",".join(missing))
            trace = _trace("repair_strategy_fallback", "fallback_used", True, True, "", input_checksum, output, "validated")
            trace.update({
                "fallback_model_invoked": True,
                "fallback_model_used": True,
                "fallback_failure_reason": "",
                "fallback_validated_output_source": "fallback_model",
            })
            return trace
        except Exception as exc:
            reason = redact_model_summary(str(exc))[:300]
            trace = _trace("repair_strategy_fallback", "fallback_used", True, True, reason, input_checksum, _clamp_output(deterministic, "fallback"), "fallback_validated")
            trace.update({
                "fallback_model_invoked": True,
                "fallback_model_used": False,
                "fallback_failure_reason": reason,
                "fallback_validated_output_source": "deterministic_fallback",
            })
            return trace

    trace = _trace("repair_strategy_fallback", "fallback_used", False, True, "fallback_model_unconfigured", input_checksum, _clamp_output(deterministic, "fallback"), "fallback_validated")
    trace.update({
        "fallback_model_invoked": False,
        "fallback_model_used": False,
        "fallback_failure_reason": "fallback_model_unconfigured",
        "fallback_validated_output_source": "deterministic_fallback",
    })
    return trace


def _default_proposer(policy: RepairFamilyPolicy, classification: dict[str, Any], stage_evidence: dict[str, Any], patterns: list[str], missing: list[str]) -> dict[str, Any]:
    return {
        "status": "available" if policy.family != "UNKNOWN_FAILURE" else "unknown",
        "role": "repair_strategy_proposer",
        "family": policy.family,
        "root_cause": _default_root_cause(policy, classification),
        "affected_files": _affected_files(stage_evidence),
        "detected_patterns": patterns,
        "migration_options": _migration_options(policy),
        "recommended_strategy": _recommended_strategy(policy),
        "risk_notes": _risk_notes(policy),
        "missing_evidence": missing,
        "engineer_checklist": _engineer_checklist(policy),
        "confidence": "medium" if policy.family != "UNKNOWN_FAILURE" else "low",
    }


def _clamp_output(value: dict[str, Any], output_kind: str) -> dict[str, Any]:
    if output_kind == "proposer":
        return {
            "status": _status(value.get("status")),
            "role": "repair_strategy_proposer",
            "family": redact_model_summary(str(value.get("family") or ""))[:120],
            "root_cause": _text(value.get("root_cause")),
            "affected_files": _relative_list(value.get("affected_files")),
            "detected_patterns": _list(value.get("detected_patterns")),
            "migration_options": _list(value.get("migration_options")),
            "recommended_strategy": _text(value.get("recommended_strategy")),
            "risk_notes": _list(value.get("risk_notes")),
            "missing_evidence": _list(value.get("missing_evidence")),
            "engineer_checklist": _list(value.get("engineer_checklist")),
            "confidence": _confidence(value.get("confidence")),
            "non_actionable": True,
            "apply_allowed": False,
            "approval_allowed": False,
            "downstream_start_allowed": False,
        }
    verdict = str(value.get("verdict") or "advisory_needs_changes")
    if verdict not in ALLOWED_VERDICT:
        verdict = "advisory_needs_changes"
    return {
        "status": _status(value.get("status")),
        "role": "repair_strategy_reviewer" if output_kind == "reviewer" else "repair_strategy_fallback",
        "verdict": verdict,
        "critique": _text(value.get("critique")),
        "risks": _list(value.get("risks")),
        "missing_evidence": _list(value.get("missing_evidence")),
        "unsafe_assumptions": _list(value.get("unsafe_assumptions")),
        "recommended_next_action": _text(value.get("recommended_next_action")),
        "confidence": _confidence(value.get("confidence")),
        "non_actionable": True,
        "apply_allowed": False,
        "approval_allowed": False,
        "downstream_start_allowed": False,
    }


def _missing_output_fields(output: dict[str, Any], output_kind: str) -> list[str]:
    required = (
        ("root_cause", "recommended_strategy", "engineer_checklist")
        if output_kind == "proposer"
        else ("verdict", "critique", "recommended_next_action")
    )
    return [field for field in required if not output.get(field)]


def _clamp_packet(packet: dict[str, Any], policy: RepairFamilyPolicy) -> dict[str, Any]:
    packet["apply_candidate_allowed"] = bool(policy.apply_candidate_allowed)
    packet["backend_recipe_available"] = bool(policy.backend_recipe_available)
    packet["human_gate_required"] = True
    packet["backend_gate"] = _backend_gate()
    return packet


def _backend_gate() -> dict[str, bool]:
    return {
        "backend_authority": True,
        "llm_can_apply": False,
        "llm_can_approve": False,
        "downstream_start_allowed": False,
    }


def _default_root_cause(policy: RepairFamilyPolicy, classification: dict[str, Any]) -> str:
    if policy.family == "POWERMOCK_LEGACY_TEST_STRATEGY":
        return "PowerMock legacy test strategy requires human modernization review."
    return str(classification.get("confidence_reason") or classification.get("failure_type") or policy.family)


def _migration_options(policy: RepairFamilyPolicy) -> list[str]:
    if policy.family == "POWERMOCK_LEGACY_TEST_STRATEGY":
        return [
            "replace simple static mocking with Mockito inline",
            "migrate JUnit runner to extension where safe",
            "refactor constructor mocking by injecting dependency",
            "keep test human-gated if behavior risk is high",
            "temporarily quarantine only if explicitly approved by engineer and documented as technical debt",
        ]
    if policy.apply_candidate_allowed:
        return ["use backend deterministic recipe after checksum-bound human approval"]
    return ["review evidence, choose migration option, and return with a later governed recipe"]


def _recommended_strategy(policy: RepairFamilyPolicy) -> str:
    if policy.family == "POWERMOCK_LEGACY_TEST_STRATEGY":
        return "Create engineer-reviewed PowerMock modernization plan; do not auto-apply."
    if policy.apply_candidate_allowed:
        return "Use existing governed apply-candidate flow when backend deterministic recipe and checksums are present."
    return "Create strategy guidance only; no apply candidate for this family in R9."


def _risk_notes(policy: RepairFamilyPolicy) -> list[str]:
    notes = ["LLM, memory, and fallback outputs are advisory only.", "Downstream stages must remain blocked until backend proof exists."]
    if policy.risk_level == "high":
        notes.append("High-risk family can change test behavior and requires engineer review.")
    if not policy.apply_candidate_allowed:
        notes.append("No backend deterministic recipe is available for apply in this milestone.")
    return notes


def _engineer_checklist(policy: RepairFamilyPolicy) -> list[str]:
    if policy.family == "POWERMOCK_LEGACY_TEST_STRATEGY":
        return [
            "Identify PowerMockRunner, PrepareForTest, mockStatic, and whenNew usage.",
            "Separate simple static mocks from constructor/private/final-class mocking.",
            "Prefer Mockito inline only for behavior-equivalent simple cases.",
            "Refactor constructor mocking by injecting dependencies where possible.",
            "Document any quarantine as explicit technical debt with human approval.",
        ]
    return [
        "Review required evidence.",
        "Check proposer and reviewer guidance.",
        "Confirm backend recipe availability before any apply.",
        "Keep downstream blocked until proof is available.",
    ]


def _affected_files(stage_evidence: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for item in stage_evidence.get("usable_artifacts", []):
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "")
        safe = ref.replace("\\", "/")
        if "/src/" in safe:
            result.append(safe[safe.index("src/"):])
    return list(dict.fromkeys(result))[:8]


def _public_evidence(stage_evidence: dict[str, Any]) -> dict[str, Any]:
    clean = redact_public_value(stage_evidence)
    if isinstance(clean, dict):
        clean["usable_artifacts"] = [
            {k: v for k, v in item.items() if k != "internal_ref"} if isinstance(item, dict) else item
            for item in clean.get("usable_artifacts", [])
        ]
    return clean if isinstance(clean, dict) else {}


def _trace_summary(trace: dict[str, Any]) -> str:
    output = trace.get("output") if isinstance(trace.get("output"), dict) else {}
    return f"{trace.get('status', 'unknown')} ({output.get('confidence', 'low')})"


def _evidence_text(*values: Any) -> str:
    return json.dumps(redact_public_value(values), sort_keys=True).lower()


def _text(value: Any, limit: int = 1200) -> str:
    return redact_model_summary(str(value or ""))[:limit]


def _list(value: Any, limit: int = 10) -> list[str]:
    return [_text(item, 300) for item in list(value or [])[:limit] if _text(item, 300)]


def _relative_list(value: Any, limit: int = 10) -> list[str]:
    result = []
    for item in list(value or [])[:limit]:
        text = str(item).replace("\\", "/").strip()
        if text and not text.startswith("/") and ":" not in text and ".." not in text.split("/"):
            result.append(redact_model_summary(text)[:300])
    return result


def _status(value: Any) -> str:
    text = str(value or "fallback_used")
    return text if text in {"available", "unavailable", "failed", "fallback_used", "unknown"} else "fallback_used"


def _confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in ALLOWED_CONFIDENCE else "low"
