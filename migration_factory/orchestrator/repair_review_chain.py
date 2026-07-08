"""F5: Repair review-chain producer — extends the F2 review-chain pattern for repair.

Deterministic repair artifact -> Primary Repair LLM (PROPOSER) -> Reviewer Repair LLM (REVIEWER)
-> Final reviewed repair diff artifact.

Core rule: A model reviews another model for repair. Reviewer is mandatory.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
)
from migration_factory.control_tower.application.v2_model_schemas import (
    REPAIR_PRIMARY_OUTPUT_SCHEMA,
    REPAIR_REVIEWER_OUTPUT_SCHEMA,
    SchemaValidationError,
    validate_model_output,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_review_chain_contracts import (
    _check_forbidden_fields,
    _check_execution_instruction,
)
from migration_factory.control_tower.domain.checksums import (
    SHA256_CANONICAL_JSON_V1,
    SHA256_UTF8_BYTES_V1,
    canonical_json_text,
    sha256_canonical_json,
    sha256_raw_model_response,
    sha256_unified_diff_text,
    utc_now_text,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureEvidence,
    FailureSource,
    failure_evidence_to_dict,
)
from migration_factory.repair_loop.repair_context import (
    RepairContextPack,
    compute_base_repo_state_checksum,
    compute_context_pack_checksum,
    context_pack_to_dict,
)


class RepairReviewChainProductionError(RuntimeError):
    def __init__(self, message: str, *, failure_code: str = "") -> None:
        super().__init__(message)
        self.failure_code = failure_code


_PRIMARY_CANONICAL_FIELDS = tuple(REPAIR_PRIMARY_OUTPUT_SCHEMA["properties"].keys())
_REVIEWER_CANONICAL_FIELDS = tuple(REPAIR_REVIEWER_OUTPUT_SCHEMA["properties"].keys())


# ── F5-T3: Deterministic repair artifact ─────────────────────────────


class RepairArtifactPhase:
    REPAIR = "repair"


def _build_deterministic_repair_payload(
    *,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    source_profile: str = "",
    target_profile: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "phase": RepairArtifactPhase.REPAIR,
        "job_id": context_pack.job_id,
        "stage_index": context_pack.stage_index,
        "failure_source": failure_evidence.failure_source.value,
        "failure_summary": failure_evidence.failure_summary,
        "normalized_compiler_errors": [
            e.message for e in failure_evidence.compiler_errors
        ],
        "normalized_test_failures": [
            t.message for t in failure_evidence.test_failures
        ],
        "changed_files": list(failure_evidence.changed_files),
        "source_profile": source_profile or failure_evidence.source_profile,
        "target_profile": target_profile or failure_evidence.target_profile,
        "context_pack_checksum": context_pack.context_pack_checksum,
        "failure_evidence_checksum": failure_evidence.content_checksum,
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "accepted_artifact_checksums": list(failure_evidence.accepted_artifact_checksums),
        "allowed_repair_mode_hints": ["source_patch", "dependency_patch", "config_patch"],
        "created_at": utc_now_text(),
    }


# ── F5-T4/T5: Primary/Reviewer repair contracts ─────────────────────


def _primary_repair_prompt(context_pack: RepairContextPack, deterministic_checksum: str) -> str:
    return (
        "You are a repair proposer. Analyze the build/test failure evidence below "
        "and propose an exact unified diff to fix the issue.\n\n"
        "Return JSON with these required keys:\n"
        "  schema_version ('1.0'), proposal_kind ('llm_repair_primary'), "
        "root_cause, fix_strategy, changed_files (list of file paths), "
        "proposed_diff (unified diff string), deterministic_rule_id (or 'no_safe_rule'), "
        "risk (LOW/MEDIUM/HIGH), confidence (0.0-1.0), rationale.\n"
        "If no safe fix is possible, set 'no_fix_reason' and make proposed_diff empty.\n\n"
        "CONSTRAINTS:\n"
        "- Do NOT include commands, paths to execute, provider data, endpoint data, "
        "env data, deployment data, or approvals.\n"
        "- Do NOT include absolute sandbox paths.\n"
        "- The proposed_diff must be a valid unified diff format.\n"
        "- Do not skip or disable tests as a fix.\n"
        "- The fix must stay within the sandbox scope and declared changed files.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n\n"
        f"Context:\n{json.dumps(context_pack_to_dict(context_pack), sort_keys=True)}"
    )


def _reviewer_repair_prompt(
    primary_output: dict[str, Any],
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
) -> str:
    return (
        "You are a repair reviewer. Validate the repair proposal below against the "
        "exact checksums, context, and policy constraints.\n\n"
        "Return JSON with keys:\n"
        "  schema_version ('1.0'), proposal_kind ('llm_repair_review'), "
        "decision (accept/revise/reject), notes (list), risks (list), "
        "confidence (0.0-1.0), policy_concerns (list), "
        "reviewed_context_checksum, reviewed_primary_output_checksum, "
        "reviewed_diff_checksum.\n\n"
        "CONSTRAINTS:\n"
        "- Accept only if the diff is valid unified diff format and addresses "
        "the exact failure evidence.\n"
        "- Reject any unsafe diff (absolute paths, security config changes, "
        "execution instructions, test disabling, deleted production code).\n"
        "- Reject if the diff scope exceeds the declared changed files.\n"
        "- Bind your decision to the exact checksums provided.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Context pack checksum: {context_checksum}\n"
        f"Primary output checksum: {primary_checksum}\n"
        f"Proposed diff checksum: {diff_checksum}\n"
        f"Primary output:\n{json.dumps(primary_output, sort_keys=True)}"
    )


def _parse_strict_json_object(content: str, *, label: str) -> dict[str, Any]:
    failure_code = _schema_failure_code_for_label(label)
    if not isinstance(content, str):
        raise RepairReviewChainProductionError(f"{label} output must be a JSON object string", failure_code=failure_code)
    text = content.strip()
    if not text:
        raise RepairReviewChainProductionError(f"{label} output must not be empty", failure_code=failure_code)
    decoder = json.JSONDecoder()
    try:
        parsed, end = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise RepairReviewChainProductionError(f"{label} output must be valid JSON", failure_code=failure_code) from exc
    if text[end:].strip():
        raise RepairReviewChainProductionError(f"{label} output must contain exactly one JSON object", failure_code=failure_code)
    if not isinstance(parsed, dict):
        raise RepairReviewChainProductionError(f"{label} output root must be a JSON object", failure_code=failure_code)
    return parsed


def _validate_primary_repair_contract(content: str) -> dict[str, Any]:
    parsed = _parse_strict_json_object(content, label="primary repair")
    try:
        validate_model_output("RepairPrimaryOutput", parsed)
    except (SchemaValidationError, ValueError) as exc:
        raise RepairReviewChainProductionError(
            f"primary repair output schema invalid: {exc}",
            failure_code="proposer_schema_invalid",
        ) from exc

    failures = _validate_primary_repair_output(parsed)
    if failures:
        raise RepairReviewChainProductionError(
            "invalid primary repair output: " + "; ".join(failures),
            failure_code="proposer_schema_invalid",
        )
    return parsed


def _coerce_primary_repair_output(content: str) -> dict[str, Any]:
    return _validate_primary_repair_contract(content)


def _fallback_primary_repair_output(content: str) -> dict[str, Any]:
    raise RepairReviewChainProductionError(
        "primary repair output must be valid JSON with all required fields"
    )


def _coerce_reviewer_repair_output(
    content: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
) -> dict[str, Any]:
    parsed = _parse_strict_json_object(content, label="reviewer repair")
    try:
        validate_model_output("RepairReviewerOutput", parsed)
    except (SchemaValidationError, ValueError) as exc:
        raise RepairReviewChainProductionError(
            f"reviewer repair output schema invalid: {exc}",
            failure_code="reviewer_schema_invalid",
        ) from exc

    if parsed["reviewed_context_checksum"] != context_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer context checksum mismatch: expected {context_checksum}, got {parsed['reviewed_context_checksum']}",
            failure_code="reviewer_schema_invalid",
        )
    if parsed["reviewed_primary_output_checksum"] != primary_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer primary checksum mismatch: expected {primary_checksum}, got {parsed['reviewed_primary_output_checksum']}",
            failure_code="reviewer_schema_invalid",
        )
    if parsed["reviewed_diff_checksum"] != diff_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer diff checksum mismatch: expected {diff_checksum}, got {parsed['reviewed_diff_checksum']}",
            failure_code="reviewer_schema_invalid",
        )
    return parsed


def _schema_failure_code_for_label(label: str) -> str:
    normalized = str(label or "").lower()
    if "reviewer" in normalized:
        return "reviewer_schema_invalid"
    return "proposer_schema_invalid"


def _model_failure_code(result: Any, *, role_prefix: str) -> str:
    markers = {
        str(getattr(result, "failure_reason", "") or ""),
        str(getattr(result, "primary_failure_reason", "") or ""),
        str(getattr(result, "provider_failure_kind", "") or ""),
    }
    if "output_truncated" in markers:
        return f"{role_prefix}_output_truncated"
    return f"{role_prefix}_provider_failed"


def _compute_primary_repair_checksum(output: dict[str, Any]) -> str:
    return sha256_canonical_json(canonical_primary_repair_output(output))


def _compute_reviewer_repair_checksum(output: dict[str, Any]) -> str:
    return sha256_canonical_json(canonical_reviewer_repair_output(output))


def canonical_primary_repair_output(output: dict[str, Any]) -> dict[str, Any]:
    return _canonical_schema_projection(output, _PRIMARY_CANONICAL_FIELDS)


def canonical_reviewer_repair_output(output: dict[str, Any]) -> dict[str, Any]:
    return _canonical_schema_projection(output, _REVIEWER_CANONICAL_FIELDS)


def _canonical_schema_projection(output: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    source = output.get("validated_output") if isinstance(output.get("validated_output"), dict) else output
    return {field: source[field] for field in fields if field in source}


def normalized_json_output(output: dict[str, Any]) -> str:
    return canonical_json_text(output)


def checksum_normalized_json_output(output: dict[str, Any]) -> str:
    return sha256_raw_model_response(normalized_json_output(output))


def _exact_provider_content(result: Any) -> str:
    exact = getattr(result, "exact_provider_content", None)
    if isinstance(exact, str) and exact:
        return exact
    return str(getattr(result, "content", "") or "")


def _is_deterministic_fallback(result: Any) -> bool:
    return (
        str(getattr(result, "source", "") or "") == "deterministic"
        or str(getattr(result, "provider", "") or "") == "deterministic"
        or str(getattr(result, "model_status", "") or "") == "fallback"
        and not bool(getattr(result, "success", False))
    )


def _safe_provider_source(result: Any) -> str:
    provider = str(getattr(result, "provider", "") or "")
    source = str(getattr(result, "source", "") or "")
    if provider and provider != "deterministic":
        return provider
    if source and source != "deterministic":
        return source
    return "deterministic"


def _validate_primary_repair_output(output: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    for key in ("root_cause", "fix_strategy", "rationale"):
        if not isinstance(output.get(key), str) or not output[key].strip():
            failures.append(f"empty or missing required field {key!r}")

    changed = output.get("changed_files")
    if not isinstance(changed, list):
        failures.append("changed_files must be a list of strings")
    else:
        seen: set[str] = set()
        for item in changed:
            if not isinstance(item, str) or not item.strip():
                failures.append("changed_files must contain non-empty strings")
                continue
            reason = _unsafe_relative_path_reason(item)
            if reason:
                failures.append(f"changed_files path {item!r} is invalid: {reason}")
            normalized = item.replace("\\", "/")
            if normalized in seen:
                failures.append(f"duplicate changed_files path {item!r}")
            seen.add(normalized)

    risk = str(output.get("risk", "")).upper()
    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        failures.append(f"risk must be LOW/MEDIUM/HIGH, got {risk!r}")

    confidence = output.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        failures.append("confidence must be a float between 0.0 and 1.0")

    diff = str(output.get("proposed_diff", ""))
    if not diff:
        no_fix_reason = output.get("no_fix_reason")
        if not isinstance(no_fix_reason, str) or not no_fix_reason.strip():
            failures.append("empty proposed_diff requires non-empty no_fix_reason")
    else:
        if not _is_unified_diff(diff):
            failures.append("proposed_diff does not appear to be a valid unified diff")

    forbidden_paths = _check_forbidden_paths_in_diff(diff)
    if forbidden_paths:
        failures.extend(forbidden_paths)

    forbidden_fields = _check_forbidden_keys(output)
    if forbidden_fields:
        failures.extend(forbidden_fields)

    return failures


def _unsafe_relative_path_reason(value: str) -> str:
    text = value.strip()
    if PureWindowsPath(text).is_absolute() or PurePosixPath(text).is_absolute():
        return "absolute path"
    if PureWindowsPath(text).drive:
        return "drive-qualified path"
    normalized = text.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return "empty path"
    if any(part == ".." for part in parts):
        return "path traversal"
    if any(part in {".", ""} for part in normalized.split("/")):
        return "ambiguous path segment"
    return ""


def _is_unified_diff(diff: str) -> bool:
    lines = diff.strip().splitlines()
    has_header = any(line.startswith("--- ") for line in lines)
    has_changes = any(line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@") for line in lines)
    has_diff = any(line.startswith("+") or line.startswith("-") for line in lines)
    return (has_header or has_changes) and has_diff


def _check_forbidden_paths_in_diff(diff: str) -> list[str]:
    failures: list[str] = []
    forbidden_patterns = [
        "sandbox_path",
        ".git",
        ".env",
        "Dockerfile",
        "docker-compose",
        ".github/workflows",
        "deploy/",
        "deployment/",
        "k8s/",
        "helm/",
        ".migration",
    ]
    for pattern in forbidden_patterns:
        if pattern in diff:
            failures.append(f"diff contains forbidden path pattern {pattern!r}")
    return failures


def _check_forbidden_keys(data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    forbidden = {
        "sandbox_path", "argv", "env", "raw_command", "filesystem_target",
        "provider", "endpoint", "deployment", "env_ref", "user_supplied_file_path",
        "approval", "approved", "approval_checksum", "command", "maven_command",
        "jdk_path", "java_home", "sandbox", "target_path",
    }

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                key_text = str(key)
                current = f"{path}.{key_text}" if path else key_text
                if key_text in forbidden and item:
                    failures.append(f"forbidden key {current!r} found in repair output")
                walk(item, current)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(data)
    return failures


# ── F5-T6: Final reviewed repair diff artifact ─────────────────────


def _build_final_reviewed_repair_artifact(
    *,
    job_id: str,
    stage_index: int,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    primary_checksum: str,
    reviewer_output: dict[str, Any],
    reviewer_checksum: str,
    deterministic_checksum: str,
) -> dict[str, Any]:
    proposed_diff = str(primary_output.get("proposed_diff", ""))
    diff_checksum = sha256_unified_diff_text(proposed_diff)

    return {
        "schema_version": "2.0.0",
        "proposal_id": "",
        "job_id": job_id,
        "stage_index": stage_index,
        "failure_source": failure_evidence.failure_source.value,
        "failure_summary": failure_evidence.failure_summary,
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_pack.context_pack_checksum,
        "primary_output_checksum": primary_checksum,
        "reviewer_output_checksum": reviewer_checksum,
        "proposed_diff_checksum": diff_checksum,
        "proposed_diff_checksum_algorithm": SHA256_UTF8_BYTES_V1,
        "changed_files": list(primary_output.get("changed_files", [])),
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "root_cause": str(primary_output.get("root_cause", "")),
        "fix_strategy": str(primary_output.get("fix_strategy", "")),
        "risk": str(primary_output.get("risk", "")),
        "confidence": float(primary_output.get("confidence", 0.0)),
        "reviewer_decision": str(reviewer_output.get("decision", "")),
        "reviewer_notes": list(reviewer_output.get("notes", [])),
        "policy_validation_checksum": "",
        "artifact_checksum": "",
        "created_at": utc_now_text(),
    }


def _compute_final_repair_artifact_checksum(payload: dict[str, Any]) -> str:
    stable = {
        k: v for k, v in payload.items()
        if k not in {"artifact_checksum", "created_at", "policy_validation_checksum"}
    }
    return sha256_canonical_json(stable)


class _LedgerInvocationLifecycle:
    def __init__(self, ledger: Any, invocation_id: str, *, label: str) -> None:
        self._ledger = ledger
        self._invocation_id = invocation_id
        self._label = label
        self.terminal = False

    def fail(
        self,
        *,
        reason: str,
        summary: str | None = None,
        fallback_used: bool = False,
        accepted_provider_source: str | None = None,
        deterministic_fallback_used: bool = False,
    ) -> None:
        if self.terminal:
            return
        try:
            self._ledger.fail_invocation(
                self._invocation_id,
                redacted_error=reason,
                redacted_summary=summary,
                fallback_used=fallback_used,
                accepted_provider_source=accepted_provider_source,
                deterministic_fallback_used=deterministic_fallback_used,
            )
        except Exception as exc:
            raise RepairReviewChainProductionError(
                f"mandatory {self._label} invocation ledger failure update failed"
            ) from exc
        self.terminal = True

    def complete(self, **kwargs: Any) -> None:
        if self.terminal:
            return
        try:
            self._ledger.complete_invocation(self._invocation_id, **kwargs)
        except Exception as exc:
            raise RepairReviewChainProductionError(
                f"mandatory {self._label} invocation ledger completion failed"
            ) from exc
        self.terminal = True


# ── F5: Main producer ─────────────────────────────────────────────


def produce_repair_review_chain(
    *,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    output_dir: Path,
    source_profile: str = "",
    target_profile: str = "",
    model_client: V2AssistantModelClient | None = None,
    invocation_ledger: Any = None,
    proposal_id: str | None = None,
    gate_id: str | None = None,
    attempt_number: int | None = None,
) -> dict[str, Any]:
    """Produce the F5 model-reviewed repair chain.

    Deterministic repair artifact -> Primary Repair LLM -> Reviewer LLM -> Final reviewed diff.

    Fails closed when any model call is unavailable, malformed, rejected, or misbound.

    Args:
        invocation_ledger: Required V2LLMInvocationLedger instance for capturing
            proposer/reviewer invocations to the governed ledger table.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    deterministic_payload = _build_deterministic_repair_payload(
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        source_profile=source_profile,
        target_profile=target_profile,
    )
    deterministic_checksum = sha256_canonical_json(deterministic_payload)
    deterministic_path = output_dir / "deterministic_repair_artifact.json"
    _write_json(deterministic_path, deterministic_payload)

    client = model_client or V2AssistantModelClient()

    if invocation_ledger is None:
        raise RepairReviewChainProductionError("mandatory invocation ledger unavailable")

    # ── PR-G: Capture proposer invocation ────────────────────────────
    proposer_invocation_id: str | None = None
    reviewer_invocation_id: str | None = None
    effective_attempt_number = attempt_number
    if effective_attempt_number is None:
        cycle_number = getattr(context_pack, "cycle_number", None)
        if cycle_number is not None:
            effective_attempt_number = int(cycle_number)
    proposer_lifecycle: _LedgerInvocationLifecycle | None = None
    reviewer_lifecycle: _LedgerInvocationLifecycle | None = None
    try:
        context_checksum_for_ledger = getattr(context_pack, "context_pack_checksum", "") or ""
        proposer_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="main",
            responsibility="repair_proposal",
            proposal_id=proposal_id,
            gate_id=gate_id,
            stage_index=context_pack.stage_index,
            attempt_number=effective_attempt_number,
            context_checksum=context_checksum_for_ledger,
            input_checksum=deterministic_checksum,
            schema_name="RepairPrimaryOutput",
        )
        proposer_lifecycle = _LedgerInvocationLifecycle(invocation_ledger, proposer_invocation_id, label="proposer")
    except Exception as exc:
        raise RepairReviewChainProductionError("mandatory proposer invocation ledger start failed") from exc

    try:
        # Primary Repair LLM (PROPOSER)
        primary_result = client.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt=_primary_repair_prompt(context_pack, deterministic_checksum),
            fallback="Primary repair model unavailable; reviewed repair cannot be produced.",
            output_schema_name="RepairPrimaryOutput",
            require_schema=True,
        )

        provider_fallback_used_primary = bool(getattr(primary_result, "fallback_used", False))
        deterministic_fallback_primary = _is_deterministic_fallback(primary_result)
        primary_provider_source = _safe_provider_source(primary_result)
        if not primary_result.success:
            failure_code = _model_failure_code(primary_result, role_prefix="proposer")
            proposer_lifecycle.fail(
                reason=str(getattr(primary_result, "failure_reason", "") or getattr(primary_result, "model_status", "") or "provider_failure"),
                summary=getattr(primary_result, "redacted_summary", None),
                fallback_used=provider_fallback_used_primary or deterministic_fallback_primary,
                accepted_provider_source=primary_provider_source,
                deterministic_fallback_used=deterministic_fallback_primary,
            )
            raise RepairReviewChainProductionError(
                f"primary repair model failed closed: {primary_result.failure_reason or primary_result.model_status}",
                failure_code=failure_code,
            )
        if deterministic_fallback_primary:
            proposer_lifecycle.fail(
                reason="deterministic_proposer_fallback",
                summary=getattr(primary_result, "redacted_summary", None),
                fallback_used=True,
                accepted_provider_source="deterministic",
                deterministic_fallback_used=True,
            )
            raise RepairReviewChainProductionError(
                "primary deterministic fallback blocked; no actionable repair produced",
                failure_code="proposer_provider_failed",
            )

        primary_raw_response = _exact_provider_content(primary_result)
        primary_raw_checksum = sha256_raw_model_response(primary_raw_response)
        primary_parsed_output = _parse_strict_json_object(primary_raw_response, label="primary repair")
        primary_normalized_text = normalized_json_output(primary_parsed_output)
        primary_normalized_checksum = sha256_raw_model_response(primary_normalized_text)
        validated_primary_output = _coerce_primary_repair_output(primary_raw_response)

        primary_checksum = _compute_primary_repair_checksum(validated_primary_output)
        primary_validated_text = normalized_json_output(canonical_primary_repair_output(validated_primary_output))
        primary_artifact_envelope = {
            **validated_primary_output,
            "output_checksum": primary_checksum,
            "raw_response_checksum": primary_raw_checksum,
            "normalized_output_checksum": primary_normalized_checksum,
            "validated_output_checksum": primary_checksum,
            "raw_response_checksum_algorithm": SHA256_UTF8_BYTES_V1,
            "normalized_output_checksum_algorithm": SHA256_UTF8_BYTES_V1,
            "structured_output_checksum_algorithm": SHA256_CANONICAL_JSON_V1,
        }
        primary_path = output_dir / "primary_repair_llm_output.json"
        primary_raw_path = output_dir / "primary_raw_response.txt"
        primary_normalized_path = output_dir / "primary_normalized_output.json"
        primary_validated_path = output_dir / "primary_validated_output.json"
        primary_raw_path.write_text(primary_raw_response, encoding="utf-8", newline="")
        primary_normalized_path.write_text(primary_normalized_text, encoding="utf-8", newline="")
        primary_validated_path.write_text(primary_validated_text, encoding="utf-8", newline="")
        _write_json(primary_path, primary_artifact_envelope)

        context_checksum = context_pack.context_pack_checksum
        proposed_diff = str(validated_primary_output.get("proposed_diff", ""))
        diff_checksum = sha256_unified_diff_text(proposed_diff)
        diff_bytes_checksum = diff_checksum

        proposer_lifecycle.complete(
            output_checksum=primary_checksum,
            redacted_summary=primary_result.redacted_summary,
            fallback_used=provider_fallback_used_primary,
            raw_response_checksum=primary_raw_checksum,
            normalized_output_checksum=primary_normalized_checksum,
            validated_output_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            raw_response_artifact_ref=str(primary_raw_path),
            normalized_output_artifact_ref=str(primary_normalized_path),
            validated_output_artifact_ref=str(primary_validated_path),
            diff_artifact_ref="",
            accepted_provider_source=primary_provider_source,
            deterministic_fallback_used=deterministic_fallback_primary,
        )
    except Exception as exc:
        if proposer_lifecycle is not None and not proposer_lifecycle.terminal:
            proposer_lifecycle.fail(reason=f"repair_proposal_failure: {exc}")
        if isinstance(exc, RepairReviewChainProductionError):
            raise
        raise RepairReviewChainProductionError(f"primary repair chain failed closed: {exc}") from exc

    # ── PR-G: Capture reviewer invocation ────────────────────────────
    try:
        reviewer_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="reviewer",
            responsibility="repair_review",
            proposal_id=proposal_id,
            gate_id=gate_id,
            stage_index=context_pack.stage_index,
            attempt_number=effective_attempt_number,
            context_checksum=context_checksum,
            input_checksum=primary_checksum,
            schema_name="RepairReviewerOutput",
        )
        reviewer_lifecycle = _LedgerInvocationLifecycle(invocation_ledger, reviewer_invocation_id, label="reviewer")
    except Exception as exc:
        raise RepairReviewChainProductionError("mandatory reviewer invocation ledger start failed") from exc

    try:
        # Reviewer Repair LLM (REVIEWER)
        reviewer_result = client.answer_with_role(
            role=V2ModelRole.REVIEWER,
            prompt=_reviewer_repair_prompt(
                validated_primary_output,
                deterministic_checksum,
                context_checksum,
                primary_checksum,
                diff_checksum,
            ),
            fallback="Reviewer repair model unavailable; reviewed repair cannot be produced.",
            output_schema_name="RepairReviewerOutput",
            require_schema=True,
        )

        provider_fallback_used_reviewer = bool(getattr(reviewer_result, "fallback_used", False))
        deterministic_fallback_reviewer = _is_deterministic_fallback(reviewer_result)
        reviewer_provider_source = _safe_provider_source(reviewer_result)
        if not reviewer_result.success:
            failure_code = _model_failure_code(reviewer_result, role_prefix="reviewer")
            reviewer_lifecycle.fail(
                reason=str(getattr(reviewer_result, "failure_reason", "") or getattr(reviewer_result, "model_status", "") or "provider_failure"),
                summary=getattr(reviewer_result, "redacted_summary", None),
                fallback_used=provider_fallback_used_reviewer or deterministic_fallback_reviewer,
                accepted_provider_source=reviewer_provider_source,
                deterministic_fallback_used=deterministic_fallback_reviewer,
            )
            raise RepairReviewChainProductionError(
                f"reviewer repair model failed closed: {reviewer_result.failure_reason or reviewer_result.model_status}",
                failure_code=failure_code,
            )
        if deterministic_fallback_reviewer:
            reviewer_lifecycle.fail(
                reason="deterministic_reviewer_fallback",
                summary=getattr(reviewer_result, "redacted_summary", None),
                fallback_used=True,
                accepted_provider_source="deterministic",
                deterministic_fallback_used=True,
            )
            raise RepairReviewChainProductionError(
                "reviewer deterministic fallback blocked; no actionable repair produced",
                failure_code="reviewer_provider_failed",
            )

        reviewer_raw_response = _exact_provider_content(reviewer_result)
        reviewer_raw_checksum = sha256_raw_model_response(reviewer_raw_response)
        reviewer_parsed_output = _parse_strict_json_object(reviewer_raw_response, label="reviewer repair")
        reviewer_normalized_text = normalized_json_output(reviewer_parsed_output)
        reviewer_normalized_checksum = sha256_raw_model_response(reviewer_normalized_text)
        validated_reviewer_output = _coerce_reviewer_repair_output(
            reviewer_raw_response,
            deterministic_checksum,
            context_checksum,
            primary_checksum,
            diff_checksum,
        )

        if validated_reviewer_output["reviewed_context_checksum"] != context_checksum:
            raise RepairReviewChainProductionError(
                f"reviewer context checksum mismatch: expected {context_checksum}, got {validated_reviewer_output['reviewed_context_checksum']}",
                failure_code="reviewer_schema_invalid",
            )
        if validated_reviewer_output["reviewed_primary_output_checksum"] != primary_checksum:
            raise RepairReviewChainProductionError(
                f"reviewer primary checksum mismatch: expected {primary_checksum}, got {validated_reviewer_output['reviewed_primary_output_checksum']}",
                failure_code="reviewer_schema_invalid",
            )
        if validated_reviewer_output["reviewed_diff_checksum"] != diff_checksum:
            raise RepairReviewChainProductionError(
                f"reviewer diff checksum mismatch: expected {diff_checksum}, got {validated_reviewer_output['reviewed_diff_checksum']}",
                failure_code="reviewer_schema_invalid",
            )

        if validated_reviewer_output["decision"] != "accept":
            reviewer_lifecycle.fail(
                reason=f"reviewer_{validated_reviewer_output['decision']}",
                summary="reviewer failed closed",
                accepted_provider_source=reviewer_provider_source,
            )
            raise RepairReviewChainProductionError(
                f"reviewer decision failed closed: {validated_reviewer_output['decision']}",
                failure_code="reviewer_provider_failed",
            )

        reviewer_checksum = _compute_reviewer_repair_checksum(validated_reviewer_output)
        reviewer_validated_text = normalized_json_output(canonical_reviewer_repair_output(validated_reviewer_output))
        reviewer_artifact_envelope = {
            **validated_reviewer_output,
            "output_checksum": reviewer_checksum,
            "raw_response_checksum": reviewer_raw_checksum,
            "normalized_output_checksum": reviewer_normalized_checksum,
            "validated_output_checksum": reviewer_checksum,
            "raw_response_checksum_algorithm": SHA256_UTF8_BYTES_V1,
            "normalized_output_checksum_algorithm": SHA256_UTF8_BYTES_V1,
            "structured_output_checksum_algorithm": SHA256_CANONICAL_JSON_V1,
        }
        reviewer_path = output_dir / "reviewer_repair_llm_output.json"
        reviewer_raw_path = output_dir / "reviewer_raw_response.txt"
        reviewer_normalized_path = output_dir / "reviewer_normalized_output.json"
        reviewer_validated_path = output_dir / "reviewer_validated_output.json"
        reviewer_raw_path.write_text(reviewer_raw_response, encoding="utf-8", newline="")
        reviewer_normalized_path.write_text(reviewer_normalized_text, encoding="utf-8", newline="")
        reviewer_validated_path.write_text(reviewer_validated_text, encoding="utf-8", newline="")
        _write_json(reviewer_path, reviewer_artifact_envelope)

        final_artifact = _build_final_reviewed_repair_artifact(
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            primary_output=validated_primary_output,
            primary_checksum=primary_checksum,
            reviewer_output=validated_reviewer_output,
            reviewer_checksum=reviewer_checksum,
            deterministic_checksum=deterministic_checksum,
        )
        final_artifact_checksum = _compute_final_repair_artifact_checksum(final_artifact)
        final_artifact["artifact_checksum"] = final_artifact_checksum
        final_artifact_path = output_dir / "final_reviewed_repair_artifact.json"
        _write_json(final_artifact_path, final_artifact)

        diff_path = output_dir / "final_reviewed_repair.diff"
        diff_path.write_bytes(proposed_diff.encode("utf-8"))

        review_chain: dict[str, Any] = {
            "deterministic_artifact_checksum": deterministic_checksum,
            "context_pack_checksum": context_checksum,
            "primary_output_checksum": primary_checksum,
            "primary_raw_response_checksum": primary_raw_checksum,
            "primary_normalized_output_checksum": primary_normalized_checksum,
            "primary_validated_output_checksum": primary_checksum,
            "reviewer_output_checksum": reviewer_checksum,
            "reviewer_raw_response_checksum": reviewer_raw_checksum,
            "reviewer_normalized_output_checksum": reviewer_normalized_checksum,
            "reviewer_validated_output_checksum": reviewer_checksum,
            "proposed_diff_checksum": diff_checksum,
            "raw_diff_bytes_checksum": diff_bytes_checksum,
            "final_reviewed_diff_checksum": diff_bytes_checksum,
            "proposed_diff_checksum_algorithm": SHA256_UTF8_BYTES_V1,
            "final_artifact_checksum": final_artifact_checksum,
            "reviewer_decision": validated_reviewer_output["decision"],
            "schema_version": "1.0",
            "proposal_kind": "llm_repair_review",
            "job_id": context_pack.job_id,
            "stage_index": context_pack.stage_index,
            "deterministic_artifact_ref": str(deterministic_path),
            "primary_output_ref": str(primary_path),
            "primary_raw_response_ref": str(primary_raw_path),
            "primary_normalized_output_ref": str(primary_normalized_path),
            "primary_validated_output_ref": str(primary_validated_path),
            "reviewer_output_ref": str(reviewer_path),
            "reviewer_raw_response_ref": str(reviewer_raw_path),
            "reviewer_normalized_output_ref": str(reviewer_normalized_path),
            "reviewer_validated_output_ref": str(reviewer_validated_path),
            "final_artifact_ref": str(final_artifact_path),
            "final_diff_ref": str(diff_path),
            "model_roles": {
                "proposer": _safe_model_role_status(primary_result),
                "reviewer": _safe_model_role_status(reviewer_result),
            },
            "checksum_algorithms": {
                "raw_model_response_checksum": SHA256_UTF8_BYTES_V1,
                "normalized_output_checksum": SHA256_UTF8_BYTES_V1,
                "validated_structured_output_checksum": SHA256_CANONICAL_JSON_V1,
                "unified_diff_checksum": SHA256_UTF8_BYTES_V1,
            },
            "artifact_refs": {
                "primary_raw_response": str(primary_raw_path),
                "primary_normalized_output": str(primary_normalized_path),
                "primary_validated_output": str(primary_validated_path),
                "reviewer_raw_response": str(reviewer_raw_path),
                "reviewer_normalized_output": str(reviewer_normalized_path),
                "reviewer_validated_output": str(reviewer_validated_path),
                "final_reviewed_diff": str(diff_path),
            },
            "primary_provider_source": _safe_provider_source(primary_result),
            "reviewer_provider_source": _safe_provider_source(reviewer_result),
            "primary_fallback_used": provider_fallback_used_primary,
            "reviewer_fallback_used": provider_fallback_used_reviewer,
            "primary_deterministic_fallback_used": deterministic_fallback_primary,
            "reviewer_deterministic_fallback_used": deterministic_fallback_reviewer,
        }
        if proposer_invocation_id is not None and reviewer_invocation_id is not None:
            review_chain["proposer_invocation_id"] = proposer_invocation_id
            review_chain["reviewer_invocation_id"] = reviewer_invocation_id
            assert proposer_invocation_id != reviewer_invocation_id, "proposer and reviewer invocation IDs must be distinct"
        review_chain_path = output_dir / "review_chain.json"
        _write_json(review_chain_path, review_chain)

        reviewer_lifecycle.complete(
            output_checksum=reviewer_checksum,
            redacted_summary=reviewer_result.redacted_summary,
            fallback_used=provider_fallback_used_reviewer,
            raw_response_checksum=reviewer_raw_checksum,
            normalized_output_checksum=reviewer_normalized_checksum,
            validated_output_checksum=reviewer_checksum,
            diff_checksum=diff_bytes_checksum,
            raw_response_artifact_ref=str(reviewer_raw_path),
            normalized_output_artifact_ref=str(reviewer_normalized_path),
            validated_output_artifact_ref=str(reviewer_validated_path),
            diff_artifact_ref=str(diff_path),
            accepted_provider_source=reviewer_provider_source,
            deterministic_fallback_used=deterministic_fallback_reviewer,
        )
    except Exception as exc:
        if reviewer_lifecycle is not None and not reviewer_lifecycle.terminal:
            reviewer_lifecycle.fail(reason=f"repair_review_failure: {exc}")
        if isinstance(exc, RepairReviewChainProductionError):
            raise
        raise RepairReviewChainProductionError(f"reviewer repair chain failed closed: {exc}") from exc

    produced_refs = {
        "deterministic_artifact": str(deterministic_path),
        "primary_llm_output": str(primary_path),
        "primary_raw_response": str(primary_raw_path),
        "primary_normalized_output": str(primary_normalized_path),
        "primary_validated_output": str(primary_validated_path),
        "reviewer_llm_output": str(reviewer_path),
        "reviewer_raw_response": str(reviewer_raw_path),
        "reviewer_normalized_output": str(reviewer_normalized_path),
        "reviewer_validated_output": str(reviewer_validated_path),
        "final_reviewed_artifact": str(final_artifact_path),
        "final_reviewed_diff": str(diff_path),
        "review_chain_metadata": str(review_chain_path),
    }

    return {"artifact_refs": produced_refs, "review_chain": review_chain}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_model_role_status(result: Any) -> dict[str, Any]:
    """Public-safe role metadata: no deployment, endpoint, provider, or env refs."""
    return {
        "role": str(getattr(result, "role", "") or ""),
        "available": bool(getattr(result, "success", False)),
        "status": "available" if bool(getattr(result, "success", False)) else "blocked",
        "fallback_used": bool(getattr(result, "fallback_used", False)),
    }
