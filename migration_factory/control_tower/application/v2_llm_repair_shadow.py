"""LLM repair proposer/reviewer/fallback shadow trace for R7E.3.

Shadow traces are advisory only. They never apply, approve, or override the
deterministic repair draft reviewer.
"""

from __future__ import annotations

import json
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary, redact_public_value
from migration_factory.control_tower.application.v2_model_schemas import (
    SchemaValidationError,
    extract_json_object,
    normalize_schema_object,
    validate_model_output,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.domain.checksums import sha256_canonical_json


TRACE_ORIGIN = "backend_llm_shadow"
PROPOSER_ROLE = "repair_proposer"
REVIEWER_ROLE = "repair_reviewer"
FALLBACK_ROLE = "repair_fallback"
ALLOWED_CONFIDENCE = {"low", "medium", "high"}
ALLOWED_REVIEWER_VERDICTS = {"advisory_accept", "advisory_reject", "advisory_needs_changes"}
EXPECTED_MODEL_BY_ROLE = {
    V2ModelRole.PROPOSER: "gpt5-mini",
    V2ModelRole.REVIEWER: "Llama-3.3-70B-Instruct",
    V2ModelRole.FALLBACK: "Mistral-Large-3",
}
SCHEMA_BY_OUTPUT_KIND = {
    "proposer": "RepairProposerShadowOutput",
    "reviewer": "RepairReviewerShadowOutput",
    "fallback": "RepairFallbackShadowOutput",
}
PROPOSER_JSON_SHAPE = {
    "status": "available",
    "role": "repair_proposer",
    "summary": "string",
    "root_cause": "string",
    "repair_intent": "string",
    "expected_change": "string",
    "affected_files": [],
    "risk_notes": [],
    "missing_evidence": [],
    "confidence": "low",
}
REVIEWER_JSON_SHAPE = {
    "status": "available",
    "role": "repair_reviewer",
    "verdict": "advisory_needs_changes",
    "critique": "string",
    "risks": [],
    "missing_evidence": [],
    "unsafe_assumptions": [],
    "recommended_next_action": "use_deterministic_backend_gate",
    "confidence": "low",
}
FALLBACK_JSON_SHAPE = {
    "status": "available",
    "role": "repair_fallback",
    "verdict": "advisory_needs_changes",
    "critique": "string",
    "risks": [],
    "missing_evidence": [],
    "unsafe_assumptions": [],
    "recommended_next_action": "use_deterministic_backend_gate",
    "confidence": "low",
}


def run_llm_repair_shadow_trace(
    *,
    job_id: str,
    stage_index: int | None,
    classification: dict[str, Any],
    stage_evidence: dict[str, Any] | None,
    migration_memory: dict[str, Any] | None,
    repair_proposal_draft: dict[str, Any] | None,
    repair_draft_review: dict[str, Any] | None,
    llm_client: object | None = None,
    llm_shadow_enabled: bool = False,
) -> dict[str, Any]:
    """Build visible, non-actionable LLM proposer/reviewer shadow trace."""

    classification = classification if isinstance(classification, dict) else {}
    stage_evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
    migration_memory = migration_memory if isinstance(migration_memory, dict) else {}
    draft = repair_proposal_draft if isinstance(repair_proposal_draft, dict) else {}
    review = repair_draft_review if isinstance(repair_draft_review, dict) else {}
    runtime_mode = (
        "configured_llm_shadow_mode"
        if llm_client is not None and llm_shadow_enabled
        else "fallback_only_mode"
    )

    proposer_input = _proposer_input(
        job_id=job_id,
        stage_index=stage_index,
        classification=classification,
        stage_evidence=stage_evidence,
        migration_memory=migration_memory,
        draft=draft,
        review=review,
    )
    proposer_trace = _run_role_trace(
        role=PROPOSER_ROLE,
        model_role=V2ModelRole.PROPOSER,
        runtime_mode=runtime_mode,
        llm_client=llm_client if runtime_mode == "configured_llm_shadow_mode" else None,
        prompt=_prompt("repair proposer", proposer_input, _proposer_instructions()),
        structured_input=proposer_input,
        fallback_output=_fallback_proposer_output(classification, draft),
        output_kind="proposer",
    )

    reviewer_input = _reviewer_input(
        proposer_input=proposer_input,
        proposer_output=proposer_trace["output"],
        classification=classification,
        stage_evidence=stage_evidence,
        migration_memory=migration_memory,
        draft=draft,
        review=review,
    )
    reviewer_trace = _run_role_trace(
        role=REVIEWER_ROLE,
        model_role=V2ModelRole.REVIEWER,
        runtime_mode=runtime_mode,
        llm_client=llm_client if runtime_mode == "configured_llm_shadow_mode" else None,
        prompt=_prompt("repair reviewer", reviewer_input, _reviewer_instructions()),
        structured_input=reviewer_input,
        fallback_output=_fallback_reviewer_output(review),
        output_kind="reviewer",
    )
    llm_fallback_input = _llm_fallback_input(
        failed_role=_fallback_failed_role(proposer_trace, reviewer_trace),
        failure_reason=_fallback_failure_reason(proposer_trace, reviewer_trace),
        proposer_input=proposer_input,
        proposer_output=proposer_trace["output"],
        reviewer_input=reviewer_input,
        reviewer_output=reviewer_trace["output"],
        draft=draft,
        review=review,
    )
    llm_fallback_trace = _run_llm_fallback_trace(
        runtime_mode=runtime_mode,
        llm_client=llm_client if runtime_mode == "configured_llm_shadow_mode" else None,
        structured_input=llm_fallback_input,
        should_invoke=_should_invoke_llm_fallback(proposer_trace, reviewer_trace),
    )

    fallback_trace = _fallback_trace(review)
    trace = _clamp_trace({
        "trace_origin": TRACE_ORIGIN,
        "trace_status": "available" if runtime_mode == "configured_llm_shadow_mode" else "fallback_used",
        "runtime_mode": runtime_mode,
        "proposer_trace": proposer_trace,
        "reviewer_trace": reviewer_trace,
        "llm_fallback_trace": llm_fallback_trace,
        "fallback_trace": fallback_trace,
        "combined_llm_shadow_trace_checksum": "",
        "llm_can_apply": False,
        "llm_can_approve": False,
        "llm_can_start_downstream": False,
        "llm_can_override_backend_gate": False,
        "deterministic_gate_authority": True,
    })
    trace["combined_llm_shadow_trace_checksum"] = f"sha256:{sha256_canonical_json({k: v for k, v in trace.items() if k != 'combined_llm_shadow_trace_checksum'})}"
    return trace


def _proposer_input(
    *,
    job_id: str,
    stage_index: int | None,
    classification: dict[str, Any],
    stage_evidence: dict[str, Any],
    migration_memory: dict[str, Any],
    draft: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    top = migration_memory.get("top_match") if isinstance(migration_memory.get("top_match"), dict) else {}
    return _redact_obj({
        "job_id": job_id,
        "stage_index": stage_index,
        "failure_type": classification.get("failure_type", ""),
        "classification_status": classification.get("classification_status", ""),
        "governance_gate_type": classification.get("governance_gate_type", ""),
        "evidence_pack_id": stage_evidence.get("evidence_pack_id") or classification.get("evidence_pack_id", ""),
        "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum") or classification.get("evidence_pack_checksum", ""),
        "usable_artifacts": _artifact_summaries(stage_evidence),
        "missing_evidence": classification.get("missing_required_evidence", []),
        "memory_query_signature": migration_memory.get("query_signature", ""),
        "memory_matches": migration_memory.get("retrieved_case_ids", []),
        "top_memory_match": {
            "memory_case_id": top.get("memory_case_id", ""),
            "title": top.get("title", ""),
            "authority_level": "advisory_only",
        },
        "repair_draft": _draft_summary(draft),
        "checksum_verification": _review_checksum_summary(review),
        "non_authority_instructions": _proposer_instructions(),
    })


def _reviewer_input(
    *,
    proposer_input: dict[str, Any],
    proposer_output: dict[str, Any],
    classification: dict[str, Any],
    stage_evidence: dict[str, Any],
    migration_memory: dict[str, Any],
    draft: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    return _redact_obj({
        "proposer_output": proposer_output,
        "proposer_input_checksum": f"sha256:{sha256_canonical_json(proposer_input)}",
        "classification": {
            "failure_type": classification.get("failure_type", ""),
            "classification_status": classification.get("classification_status", ""),
            "governance_gate_type": classification.get("governance_gate_type", ""),
        },
        "stage_evidence": {
            "evidence_pack_id": stage_evidence.get("evidence_pack_id", ""),
            "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        },
        "migration_memory": {
            "query_signature": migration_memory.get("query_signature", ""),
            "authority_level": "advisory_only",
            "retrieved_case_ids": migration_memory.get("retrieved_case_ids", []),
        },
        "repair_draft": _draft_summary(draft),
        "deterministic_reviewer": _review_checksum_summary(review),
        "non_authority_instructions": _reviewer_instructions(),
    })


def _llm_fallback_input(
    *,
    failed_role: str,
    failure_reason: str,
    proposer_input: dict[str, Any],
    proposer_output: dict[str, Any],
    reviewer_input: dict[str, Any],
    reviewer_output: dict[str, Any],
    draft: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    return _redact_obj({
        "failed_role": failed_role,
        "failure_reason": failure_reason,
        "original_role_metadata": {
            "proposer_input_checksum": f"sha256:{sha256_canonical_json(proposer_input)}",
            "reviewer_input_checksum": f"sha256:{sha256_canonical_json(reviewer_input)}",
        },
        "proposer_input_preview": _bounded_json(proposer_input, limit=1200),
        "proposer_output": proposer_output,
        "reviewer_input_preview": _bounded_json(reviewer_input, limit=1200),
        "reviewer_output": reviewer_output,
        "repair_draft": _draft_summary(draft),
        "deterministic_reviewer": _review_checksum_summary(review),
        "non_authority_instructions": _fallback_instructions(),
    })


def _run_role_trace(
    *,
    role: str,
    model_role: V2ModelRole,
    runtime_mode: str,
    llm_client: object | None,
    prompt: str,
    structured_input: dict[str, Any],
    fallback_output: dict[str, Any],
    output_kind: str,
) -> dict[str, Any]:
    input_preview = _bounded_json(structured_input)
    input_checksum = f"sha256:{sha256_canonical_json(structured_input)}"
    model_metadata = _model_metadata(llm_client, model_role, runtime_mode)
    if llm_client is None:
        output = _clamp_output(fallback_output, output_kind)
        return _trace(role, model_metadata, "fallback_used", False, True, "llm_shadow_disabled_or_unconfigured", input_preview, input_checksum, output, "fallback_validated")

    try:
        raw = _invoke_client(llm_client, model_role, prompt, fallback_output, output_kind)
        content = str(getattr(raw, "content", raw) or "")
        output, schema_status, failure_reason, parse_error_kind, model_output_was_json = _parse_and_clamp(content, fallback_output, output_kind)
        status = "available" if schema_status == "validated" else "failed"
        return _trace(
            role,
            _model_metadata(raw, model_role, runtime_mode),
            status,
            True,
            bool(getattr(raw, "fallback_used", False)),
            str(getattr(raw, "failure_reason", "") or failure_reason),
            input_preview,
            input_checksum,
            output,
            schema_status,
            raw_output_redacted_preview=_safe_text(content, limit=1200),
            json_parse_error_kind=parse_error_kind,
            model_output_was_json=model_output_was_json,
        )
    except Exception as exc:
        output = _clamp_output(fallback_output, output_kind)
        return _trace(
            role,
            model_metadata,
            "failed",
            False,
            True,
            redact_model_summary(f"{type(exc).__name__}: {exc}"),
            input_preview,
            input_checksum,
            output,
            "fallback_validated",
            raw_output_redacted_preview="",
            json_parse_error_kind="client_exception",
            model_output_was_json=False,
        )


def _run_llm_fallback_trace(
    *,
    runtime_mode: str,
    llm_client: object | None,
    structured_input: dict[str, Any],
    should_invoke: bool,
) -> dict[str, Any]:
    fallback_output = _fallback_model_output(structured_input)
    if not should_invoke:
        input_preview = _bounded_json(structured_input)
        input_checksum = f"sha256:{sha256_canonical_json(structured_input)}"
        output = _clamp_output(fallback_output, "fallback")
        return _trace(
            FALLBACK_ROLE,
            _model_metadata(None, V2ModelRole.FALLBACK, runtime_mode),
            "unavailable",
            False,
            False,
            "fallback_model_not_needed",
            input_preview,
            input_checksum,
            output,
            "not_applicable",
        )
    return _run_role_trace(
        role=FALLBACK_ROLE,
        model_role=V2ModelRole.FALLBACK,
        runtime_mode=runtime_mode,
        llm_client=llm_client,
        prompt=_prompt("repair fallback reviewer", structured_input, _fallback_instructions()),
        structured_input=structured_input,
        fallback_output=fallback_output,
        output_kind="fallback",
    )


def _invoke_client(llm_client: object, model_role: V2ModelRole, prompt: str, fallback_output: dict[str, Any], output_kind: str) -> Any:
    fallback = json.dumps(fallback_output, separators=(",", ":"), sort_keys=True)
    schema_name = SCHEMA_BY_OUTPUT_KIND.get(output_kind)
    if hasattr(llm_client, "answer_with_role"):
        return llm_client.answer_with_role(
            role=model_role,
            prompt=prompt,
            fallback=fallback,
            output_schema_name=schema_name,
            require_schema=bool(schema_name),
        )
    if hasattr(llm_client, "answer"):
        return llm_client.answer(prompt=prompt, fallback=fallback)
    if hasattr(llm_client, "complete_shadow"):
        return llm_client.complete_shadow(role=model_role.value, prompt=prompt, fallback=fallback, output_kind=output_kind)
    raise TypeError("llm_shadow_client_missing_supported_method")


def _trace(
    role: str,
    model_metadata: dict[str, Any],
    status: str,
    llm_invoked: bool,
    fallback_used: bool,
    failure_reason: str,
    input_preview: str,
    input_checksum: str,
    output: dict[str, Any],
    schema_status: str,
    raw_output_redacted_preview: str = "",
    json_parse_error_kind: str = "",
    model_output_was_json: bool = False,
) -> dict[str, Any]:
    return {
        "role": role,
        "model_metadata": model_metadata,
        "status": status,
        "llm_invoked": bool(llm_invoked),
        "fallback_used": bool(fallback_used),
        "failure_reason": redact_model_summary(failure_reason),
        "input_preview": redact_model_summary(input_preview)[:4000],
        "input_checksum": input_checksum,
        "output": output,
        "output_checksum": f"sha256:{sha256_canonical_json(output)}",
        "schema_validation_status": schema_status,
        "raw_output_redacted_preview": redact_model_summary(raw_output_redacted_preview)[:1200],
        "json_parse_error_kind": redact_model_summary(json_parse_error_kind)[:160],
        "model_output_was_json": bool(model_output_was_json),
        "non_actionable": True,
        "apply_allowed": False,
        "approval_allowed": False,
        "downstream_start_allowed": False,
    }


def _parse_and_clamp(content: str, fallback_output: dict[str, Any], output_kind: str) -> tuple[dict[str, Any], str, str, str, bool]:
    parsed = extract_json_object(content)
    if not isinstance(parsed, dict):
        return (
            _clamp_output(fallback_output, output_kind),
            "fallback_validated",
            "invalid_json_model_output",
            "invalid_json",
            False,
        )
    schema_name = SCHEMA_BY_OUTPUT_KIND.get(output_kind, "")
    try:
        normalized = normalize_schema_object(schema_name, parsed)
        validate_model_output(schema_name, normalized)
    except (SchemaValidationError, ValueError) as exc:
        output = _clamp_output(parsed, output_kind)
        missing = _missing_output_fields(output, output_kind)
        reason = f"schema_missing:{','.join(missing)}" if missing else f"schema_invalid:{redact_model_summary(str(exc))}"
        fallback = _clamp_output({**fallback_output, **output}, output_kind)
        return fallback, "fallback_validated", reason, "schema_invalid", True
    output = _clamp_output(normalized, output_kind)
    return output, "validated", "", "", True


def _clamp_output(value: dict[str, Any], output_kind: str) -> dict[str, Any]:
    if output_kind in {"reviewer", "fallback"}:
        verdict = str(value.get("verdict") or "advisory_needs_changes")
        if verdict not in ALLOWED_REVIEWER_VERDICTS:
            verdict = "advisory_needs_changes"
        return {
            "status": _status(value.get("status")),
            "role": FALLBACK_ROLE if output_kind == "fallback" else REVIEWER_ROLE,
            "verdict": verdict,
            "critique": _safe_text(value.get("critique")),
            "risks": _safe_list(value.get("risks")),
            "missing_evidence": _safe_list(value.get("missing_evidence")),
            "unsafe_assumptions": _safe_list(value.get("unsafe_assumptions")),
            "recommended_next_action": _safe_text(value.get("recommended_next_action")),
            "confidence": _confidence(value.get("confidence")),
            "non_actionable": True,
            "apply_allowed": False,
            "approval_allowed": False,
            "downstream_start_allowed": False,
        }
    return {
        "status": _status(value.get("status")),
        "role": PROPOSER_ROLE,
        "summary": _safe_text(value.get("summary")),
        "root_cause": _safe_text(value.get("root_cause")),
        "repair_intent": _safe_text(value.get("repair_intent")),
        "expected_change": _safe_text(value.get("expected_change")),
        "affected_files": _safe_relative_list(value.get("affected_files")),
        "risk_notes": _safe_list(value.get("risk_notes")),
        "missing_evidence": _safe_list(value.get("missing_evidence")),
        "confidence": _confidence(value.get("confidence")),
        "non_actionable": True,
        "apply_allowed": False,
        "approval_allowed": False,
        "downstream_start_allowed": False,
    }


def _missing_output_fields(output: dict[str, Any], output_kind: str) -> list[str]:
    required = (
        ("status", "role", "verdict", "critique", "risks", "missing_evidence", "unsafe_assumptions", "recommended_next_action", "confidence")
        if output_kind in {"reviewer", "fallback"}
        else ("status", "role", "summary", "root_cause", "repair_intent", "expected_change", "affected_files", "risk_notes", "missing_evidence", "confidence")
    )
    return [field for field in required if field not in output or output.get(field) in (None, "")]


def _fallback_proposer_output(classification: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "fallback_used",
        "role": PROPOSER_ROLE,
        "summary": "LLM proposer unavailable; deterministic evidence-bound draft remains visible.",
        "root_cause": str(classification.get("failure_type") or "unknown"),
        "repair_intent": str(draft.get("supported_family") or "none"),
        "expected_change": "No LLM-authored change is actionable in R7E.2.",
        "affected_files": draft.get("target_files", []),
        "risk_notes": ["LLM shadow proposer unavailable or disabled."],
        "missing_evidence": classification.get("missing_required_evidence", []),
        "confidence": "low",
    }


def _fallback_reviewer_output(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "fallback_used",
        "role": REVIEWER_ROLE,
        "verdict": "advisory_needs_changes",
        "critique": "LLM reviewer unavailable; deterministic reviewer remains authoritative.",
        "risks": ["No independent LLM reviewer critique was completed."],
        "missing_evidence": review.get("reasons", []),
        "unsafe_assumptions": ["LLM output cannot approve, apply, or override backend gate."],
        "recommended_next_action": "use_deterministic_backend_gate",
        "confidence": "low",
    }


def _fallback_model_output(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "fallback_used",
        "role": FALLBACK_ROLE,
        "verdict": "advisory_needs_changes",
        "critique": "LLM fallback model used because primary shadow role was unavailable or invalid.",
        "risks": ["Fallback output remains advisory and cannot override deterministic backend gate."],
        "missing_evidence": [],
        "unsafe_assumptions": [str(context.get("failure_reason") or "primary_shadow_failure")],
        "recommended_next_action": "use_deterministic_backend_gate",
        "confidence": "low",
    }


def _fallback_trace(review: dict[str, Any]) -> dict[str, Any]:
    return _clamp_authority({
        "fallback_kind": "deterministic_repair_draft_reviewer",
        "deterministic_reviewer_verdict": str(review.get("verdict") or ""),
        "checksum_verification_status": str(review.get("checksum_verification_status") or ""),
        "deterministic_gate_authority": True,
        "llm_can_apply": False,
        "llm_can_approve": False,
        "llm_can_start_downstream": False,
        "llm_can_override_backend_gate": False,
        "apply_enabled": False,
        "approval_enabled": False,
        "repair_enabled": False,
        "downstream_start_allowed": False,
        "memory_authority": "advisory_only",
    })


def _model_metadata(source: object | None, role: V2ModelRole, runtime_mode: str) -> dict[str, Any]:
    provider = str(getattr(source, "provider", "") or ("azure_openai" if runtime_mode == "configured_llm_shadow_mode" else "deterministic"))
    deployment = str(getattr(source, "deployment", "") or getattr(source, "deployment_label", "") or "")
    endpoint = str(getattr(source, "endpoint_metadata", "") or getattr(source, "endpoint_host", "") or "")
    expected = EXPECTED_MODEL_BY_ROLE.get(role, role.value)
    return {
        "role": _public_role_name(role),
        "provider": redact_model_summary(provider),
        "deployment": redact_model_summary(deployment)[:120],
        "expected_model": expected,
        "configuration_source": "existing_v2_model_role_router",
        "endpoint_metadata": redact_model_summary(endpoint)[:160],
        "status": str(getattr(source, "model_status", "") or ("configured" if runtime_mode == "configured_llm_shadow_mode" else "fallback")),
    }


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_status": draft.get("proposal_status", ""),
        "supported_family": draft.get("supported_family", ""),
        "target_files": _safe_relative_list(draft.get("target_files")),
        "proposed_diff_preview": _safe_text(draft.get("proposed_diff_preview"), limit=2000),
        "proposed_diff_checksum": draft.get("proposed_diff_checksum", ""),
        "proposal_checksum": draft.get("proposal_checksum", ""),
    }


def _review_checksum_summary(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": review.get("verdict", ""),
        "checksum_verification_status": review.get("checksum_verification_status", ""),
        "declared_diff_checksum": review.get("declared_diff_checksum", ""),
        "recomputed_diff_checksum": review.get("recomputed_diff_checksum", ""),
        "diff_checksum_match": bool(review.get("diff_checksum_match")),
        "declared_proposal_checksum": review.get("declared_proposal_checksum", ""),
        "recomputed_proposal_checksum": review.get("recomputed_proposal_checksum", ""),
        "proposal_checksum_match": bool(review.get("proposal_checksum_match")),
        "review_checksum": review.get("review_checksum", ""),
    }


def _artifact_summaries(stage_evidence: dict[str, Any]) -> list[dict[str, str]]:
    summaries = []
    for item in list(stage_evidence.get("usable_artifacts") or [])[:8]:
        if isinstance(item, dict):
            summaries.append({
                "kind": _safe_text(item.get("kind"), limit=80),
                "ref": _safe_text(item.get("ref"), limit=160),
                "checksum": _safe_text(item.get("checksum"), limit=120),
            })
    return summaries


def _proposer_instructions() -> str:
    return _json_only_instructions(
        role="repair proposer",
        shape=PROPOSER_JSON_SHAPE,
        extra=(
            "Explain root cause and repair intent using only supplied evidence. "
            "affected_files must contain safe relative paths only."
        ),
    )


def _reviewer_instructions() -> str:
    return _json_only_instructions(
        role="repair reviewer",
        shape=REVIEWER_JSON_SHAPE,
        extra="Review proposer output and backend-owned draft. List risks, missing evidence, and unsafe assumptions.",
    )


def _fallback_instructions() -> str:
    return _json_only_instructions(
        role="repair fallback reviewer",
        shape=FALLBACK_JSON_SHAPE,
        extra="Explain why primary LLM shadow role failed and give advisory fallback critique.",
    )


def _json_only_instructions(*, role: str, shape: dict[str, Any], extra: str) -> str:
    return (
        f"You are a {role}. {extra}\n"
        "Return only one valid JSON object.\n"
        "Do not use markdown.\n"
        "Do not use code fences.\n"
        "Do not include explanations outside JSON.\n"
        "Do not include comments.\n"
        "Do not include trailing commas.\n"
        "Use double quotes only.\n"
        "All required fields must be present.\n"
        "Allowed status values: available, unavailable, failed, fallback_used.\n"
        "Allowed confidence values: low, medium, high.\n"
        "Reviewer/fallback verdict values: advisory_accept, advisory_reject, advisory_needs_changes.\n"
        "Output is advisory only.\n"
        "Do not claim authority.\n"
        "Do not approve apply.\n"
        "Do not start downstream.\n"
        "Do not output secrets.\n"
        f"Exact JSON shape:\n{json.dumps(shape, indent=2, sort_keys=True)}"
    )


def _should_invoke_llm_fallback(proposer_trace: dict[str, Any], reviewer_trace: dict[str, Any]) -> bool:
    return _trace_needs_fallback(proposer_trace) or _trace_needs_fallback(reviewer_trace)


def _trace_needs_fallback(trace: dict[str, Any]) -> bool:
    return (
        str(trace.get("status") or "") in {"failed", "unavailable"}
        or bool(trace.get("fallback_used"))
        or str(trace.get("schema_validation_status") or "") not in {"validated", "not_applicable"}
    )


def _fallback_failed_role(proposer_trace: dict[str, Any], reviewer_trace: dict[str, Any]) -> str:
    if _trace_needs_fallback(proposer_trace):
        return str(proposer_trace.get("role") or PROPOSER_ROLE)
    if _trace_needs_fallback(reviewer_trace):
        return str(reviewer_trace.get("role") or REVIEWER_ROLE)
    return ""


def _fallback_failure_reason(proposer_trace: dict[str, Any], reviewer_trace: dict[str, Any]) -> str:
    for trace in (proposer_trace, reviewer_trace):
        if _trace_needs_fallback(trace):
            return str(trace.get("failure_reason") or trace.get("schema_validation_status") or "shadow_role_failed")
    return ""


def _public_role_name(role: V2ModelRole) -> str:
    if role == V2ModelRole.PROPOSER:
        return "repair_proposer_model"
    if role == V2ModelRole.REVIEWER:
        return "repair_reviewer_model"
    if role == V2ModelRole.FALLBACK:
        return "repair_fallback_model"
    return role.value


def _prompt(title: str, payload: dict[str, Any], instructions: str) -> str:
    return redact_model_summary(f"{title}\n{instructions}\n\n{_bounded_json(payload, limit=6000)}")


def _bounded_json(value: Any, limit: int = 3000) -> str:
    return redact_model_summary(json.dumps(_redact_obj(value), sort_keys=True, separators=(",", ":"))[:limit])


def _redact_obj(value: Any) -> Any:
    return redact_public_value(value)


def _safe_text(value: Any, limit: int = 1200) -> str:
    return redact_model_summary(str(value or ""))[:limit]


def _safe_list(value: Any, limit: int = 8) -> list[str]:
    return [_safe_text(item, limit=300) for item in list(value or [])[:limit] if _safe_text(item, limit=300)]


def _safe_relative_list(value: Any, limit: int = 8) -> list[str]:
    result = []
    for item in list(value or [])[:limit]:
        text = str(item).replace("\\", "/").strip()
        if text and not text.startswith("/") and ":" not in text and ".." not in text.split("/"):
            result.append(redact_model_summary(text)[:300])
    return result


def _status(value: Any) -> str:
    text = str(value or "fallback_used")
    return text if text in {"available", "unavailable", "failed", "fallback_used"} else "fallback_used"


def _confidence(value: Any) -> str:
    text = str(value or "low")
    return text if text in ALLOWED_CONFIDENCE else "low"


def _clamp_trace(trace: dict[str, Any]) -> dict[str, Any]:
    return _clamp_authority(trace)


def _clamp_authority(value: dict[str, Any]) -> dict[str, Any]:
    value["llm_can_apply"] = False
    value["llm_can_approve"] = False
    value["llm_can_start_downstream"] = False
    value["llm_can_override_backend_gate"] = False
    value["apply_enabled"] = False
    value["approval_enabled"] = False
    value["repair_enabled"] = False
    value["downstream_start_allowed"] = False
    value["memory_authority"] = "advisory_only"
    return value
