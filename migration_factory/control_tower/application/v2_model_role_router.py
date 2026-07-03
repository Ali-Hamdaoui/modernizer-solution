"""Role-based Azure/OpenAI routing for V2 model calls.

This module resolves per-role deployment env refs, applies safe fallback
selection, and optionally fail-closes on structured-output schema checks.
Uses ModelRoleConfigLoader for primary config with backward compat for
legacy AZURE_OPENAI_* env vars.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from migration_factory.control_tower.application.v2_model_role_config import (
    ModelRoleConfigLoader,
    ModelRoleConfigMissingError,
)
from migration_factory.control_tower.application.v2_model_schemas import validate_model_output
from migration_factory.control_tower.application.v2_settings import ControlTowerSettings
from migration_factory.control_tower.application.redaction import redact_model_summary

# Public build marker: branch + version constant (no secrets, no paths).
CODE_BRANCH = "amf-237-reviewed-repair-gate"
CODE_VERSION = "amf-237-diagnostics-2026.07.02"

class V2ModelRole(str, Enum):
    ASSISTANT = "assistant"
    PROPOSER = "proposer"
    REVIEWER = "reviewer"
    FALLBACK = "fallback"


# ── Role mapping helpers ──────────────────────────────────────────────

_OLD_ROLE_ENV: dict[V2ModelRole, str] = {
    V2ModelRole.PROPOSER: "AZURE_OPENAI_PROPOSER_DEPLOYMENT",
    V2ModelRole.REVIEWER: "AZURE_OPENAI_REVIEWER_DEPLOYMENT",
    V2ModelRole.ASSISTANT: "AZURE_OPENAI_ASSISTANT_DEPLOYMENT",
    V2ModelRole.FALLBACK: "AZURE_OPENAI_FALLBACK_DEPLOYMENT",
}


def _role_to_env_key(role: V2ModelRole) -> str:
    """Map a V2ModelRole to the AI_MIGRATION_* role key (MAIN, REVIEWER, FALLBACK)."""
    if role in (V2ModelRole.PROPOSER, V2ModelRole.ASSISTANT):
        return "MAIN"
    if role == V2ModelRole.REVIEWER:
        return "REVIEWER"
    if role == V2ModelRole.FALLBACK:
        return "FALLBACK"
    return "MAIN"


def _role_to_config_role(role: V2ModelRole) -> str:
    """Map a V2ModelRole to the config role name (main, reviewer, fallback)."""
    if role in (V2ModelRole.PROPOSER, V2ModelRole.ASSISTANT):
        return "main"
    if role == V2ModelRole.REVIEWER:
        return "reviewer"
    if role == V2ModelRole.FALLBACK:
        return "fallback"
    return "main"


def _resolve_deployment_for_role(role: V2ModelRole) -> str:
    """Resolve deployment ID for a role via ModelRoleConfigLoader, with backward compat."""
    config_role = _role_to_config_role(role)
    config = ModelRoleConfigLoader.try_load_role(config_role)
    if config is not None:
        return config.deployment_or_model_id
    old_env = _OLD_ROLE_ENV.get(role)
    if old_env and os.environ.get(old_env, "").strip():
        return os.environ[old_env].strip()
    return ""


def _resolve_deployment_for_fallback() -> str:
    """Resolve fallback deployment via ModelRoleConfigLoader, with backward compat."""
    config = ModelRoleConfigLoader.try_load_role("fallback")
    if config is not None:
        return config.deployment_or_model_id
    return os.environ.get("AZURE_OPENAI_FALLBACK_DEPLOYMENT", "").strip()


@dataclass(frozen=True)
class V2RoleModelRequest:
    role: V2ModelRole
    prompt: str
    fallback: str
    output_schema_name: str | None = None
    require_schema: bool = False
    conversation_history: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class V2RoleModelResult:
    content: str
    role: str
    provider: str
    source: str
    model_status: str
    success: bool
    failure_reason: str
    primary_failure_reason: str = ""
    fallback_used: bool = False
    schema_validated: bool = False
    redacted_summary: str = ""
    schema_diagnostics: dict[str, Any] | None = None
    response_format_requested: bool = False
    response_format_used: bool | None = None
    deployment_alias_hash: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class V2RoleModelRoute:
    request: V2RoleModelRequest
    primary_env_ref: str
    primary_deployment: str
    fallback_env_ref: str
    fallback_deployment: str
    fallback_enabled: bool
    provider: str = "azure_openai"


class V2ModelRoleRouter:
    """Resolve role-specific deployments and execute safe fallback selection."""

    def __init__(self, settings: ControlTowerSettings | None = None) -> None:
        self._settings = settings or ControlTowerSettings()

    def plan(self, request: V2RoleModelRequest, *, settings: ControlTowerSettings | None = None) -> V2RoleModelRoute:
        active_settings = settings or self._settings
        primary_env_ref = self._role_env_ref(request.role, active_settings)
        fallback_env_ref = active_settings.azure_foundry_fallback_deployment_env or ""

        role_config = ModelRoleConfigLoader.try_load_role(request.role.value)
        provider_alias = (role_config.provider_alias if role_config else "azure_openai")

        if provider_alias == "mistral":
            model_env = f"AI_MIGRATION_{request.role.value.upper()}_MODEL"
            primary_env_ref = model_env

        return V2RoleModelRoute(
            request=request,
            primary_env_ref=primary_env_ref,
            primary_deployment=_resolve_deployment_for_role(request.role),
            fallback_env_ref=fallback_env_ref,
            fallback_deployment=_resolve_deployment_for_fallback(),
            fallback_enabled=bool(active_settings.azure_foundry_fallback_enabled),
            provider=provider_alias,
        )

    def route(
        self,
        request: V2RoleModelRequest,
        *,
        invoke: Callable[[str, str], Any],
        settings: ControlTowerSettings | None = None,
    ) -> V2RoleModelResult:
        route = self.plan(request, settings=settings)
        primary_result, primary_failure = self._try_invoke(
            invoke,
            deployment=route.primary_deployment,
            provider=route.provider,
            request=request,
            role=request.role.value,
        )
        schema_diag: dict[str, Any] = {}
        schema_summary: str = ""
        if primary_result is not None:
            result = self._coerce_primary_result(primary_result, request)
            schema_failure = self._schema_failure_reason(request, result.content)
            if schema_failure:
                schema_diag = self._schema_diagnostics(
                    request, result.content, deployment=route.primary_deployment,
                )
                schema_summary = _build_schema_failure_summary(request, result.content)
            if result.success and not schema_failure:
                return V2RoleModelResult(
                    content=result.content,
                    role=result.role,
                    provider=result.provider,
                    source=result.source,
                    model_status=result.model_status,
                    success=True,
                    failure_reason="",
                    primary_failure_reason="",
                    fallback_used=False,
                    schema_validated=True,
                    redacted_summary=schema_summary,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    reasoning_tokens=result.reasoning_tokens,
                    latency_ms=result.latency_ms,
                )
            primary_failure = (
                result.failure_reason
                or schema_failure
                or primary_failure
                or f"{request.role.value}_model_failed"
            )
            if request.role == V2ModelRole.REVIEWER and primary_failure:
                _reviewer_codes = {"reviewer_model_unavailable", "reviewer_schema_invalid", "reviewer_model_failed"}
                if primary_failure not in _reviewer_codes:
                    primary_failure = "reviewer_model_failed"

        if request.role != V2ModelRole.REVIEWER and route.fallback_enabled and route.fallback_deployment:
            fallback_result, fallback_failure = self._try_invoke(
                invoke,
                deployment=route.fallback_deployment,
                provider=route.provider,
                request=request,
                role=V2ModelRole.FALLBACK.value,
            )
            if fallback_result is not None:
                result = self._coerce_fallback_result(
                    fallback_result,
                    request,
                    primary_failure_reason=primary_failure,
                )
                schema_failure = self._schema_failure_reason(request, result.content)
                if result.success and not schema_failure:
                    redacted = self._build_schema_redacted_summary(primary_failure)
                    return V2RoleModelResult(
                        content=result.content,
                        role=result.role,
                        provider=result.provider,
                        source=result.source,
                        model_status=result.model_status,
                        success=True,
                        failure_reason="",
                        primary_failure_reason=primary_failure,
                        fallback_used=True,
                        schema_validated=True,
                        redacted_summary=redacted or result.redacted_summary,
                        schema_diagnostics=schema_diag or None,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                        total_tokens=result.total_tokens,
                        reasoning_tokens=result.reasoning_tokens,
                        latency_ms=result.latency_ms,
                    )
                fallback_failure = result.failure_reason or schema_failure or fallback_failure or "fallback_model_failed"
            else:
                fallback_failure = fallback_failure or "fallback_model_failed"
        else:
            fallback_failure = ""

        return self._deterministic_result(
            request=request,
            primary_failure_reason=primary_failure or f"{request.role.value}_model_unavailable",
            fallback_failure_reason=fallback_failure,
            schema_diagnostics=schema_diag or None,
        )

    def _try_invoke(
        self,
        invoke: Callable[[str, str], Any],
        *,
        deployment: str,
        provider: str = "azure_openai",
        request: V2RoleModelRequest,
        role: str,
    ) -> tuple[Any | None, str]:
        if not deployment:
            if role == V2ModelRole.REVIEWER.value:
                return None, "reviewer_model_unavailable"
            return None, f"missing_{role}_deployment"
        try:
            return invoke(deployment, provider), ""
        except Exception:
            if role == V2ModelRole.REVIEWER.value:
                return None, "reviewer_model_failed"
            return None, f"{role}_model_failed"

    def _coerce_primary_result(self, result: Any, request: V2RoleModelRequest) -> V2RoleModelResult:
        return V2RoleModelResult(
            content=str(getattr(result, "content", "") or ""),
            role=request.role.value,
            provider=str(getattr(result, "provider", "") or "azure_openai"),
            source=str(getattr(result, "source", "") or "azure_openai"),
            model_status=str(getattr(result, "model_status", "") or "live_ok"),
            success=bool(getattr(result, "success", False)),
            failure_reason=str(getattr(result, "failure_reason", "") or ""),
            redacted_summary=str(getattr(result, "redacted_summary", "") or ""),
            response_format_requested=bool(getattr(result, "response_format_requested", request.require_schema)),
            response_format_used=getattr(result, "response_format_used", None),
            deployment_alias_hash=str(getattr(result, "deployment_alias_hash", "") or ""),
            prompt_tokens=getattr(result, "prompt_tokens", None),
            completion_tokens=getattr(result, "completion_tokens", None),
            total_tokens=getattr(result, "total_tokens", None),
            reasoning_tokens=getattr(result, "reasoning_tokens", None),
            latency_ms=getattr(result, "latency_ms", None),
        )

    def _coerce_fallback_result(
        self,
        result: Any,
        request: V2RoleModelRequest,
        *,
        primary_failure_reason: str,
    ) -> V2RoleModelResult:
        coerced = self._coerce_primary_result(result, request)
        redacted = self._build_schema_redacted_summary(primary_failure_reason)
        return V2RoleModelResult(
            content=coerced.content,
            role=request.role.value,
            provider=coerced.provider,
            source=coerced.source,
            model_status=coerced.model_status,
            success=coerced.success,
            failure_reason=coerced.failure_reason,
            primary_failure_reason=primary_failure_reason,
            fallback_used=True,
            schema_validated=coerced.schema_validated,
            redacted_summary=redacted,
            prompt_tokens=coerced.prompt_tokens,
            completion_tokens=coerced.completion_tokens,
            total_tokens=coerced.total_tokens,
            reasoning_tokens=coerced.reasoning_tokens,
            latency_ms=coerced.latency_ms,
        )

    def _schema_ok(self, request: V2RoleModelRequest, content: str) -> bool:
        return self._schema_failure_reason(request, content) == ""

    def _schema_failure_reason(self, request: V2RoleModelRequest, content: str) -> str:
        if not request.require_schema:
            return ""
        if not request.output_schema_name:
            return f"{request.role.value}_schema_invalid"
        parsed, category = _parse_model_json_safe(content)
        if parsed is None:
            if category == "empty_output":
                return "main_empty_response"
            if request.role == V2ModelRole.PROPOSER:
                return "main_schema_invalid"
            return f"{request.role.value}_schema_invalid"
        try:
            validate_model_output(request.output_schema_name, parsed)
        except Exception:
            if request.role == V2ModelRole.PROPOSER:
                return "main_schema_invalid"
            return f"{request.role.value}_schema_invalid"
        return ""

    def _schema_diagnostics(
        self,
        request: V2RoleModelRequest,
        content: str,
        *,
        deployment: str = "",
    ) -> dict[str, Any]:
        """Return safe schema diagnostics without leaking raw content."""
        if not request.require_schema or not request.output_schema_name:
            return {"schema_validated": False}
        output_checksum = ""
        if content.strip():
            output_checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        parsed, category = _parse_model_json_safe(content)
        base: dict[str, Any] = {
            "schema_name": request.output_schema_name,
            "role": request.role.value,
            "stage": "reviewer" if request.role == V2ModelRole.REVIEWER else "main",
            "output_checksum": output_checksum if content.strip() else "",
            "response_format_requested": True,
            "response_format_used": True,
            "deployment_alias_hash": _deployment_alias_hash(deployment),
        }
        if parsed is None:
            base.update({
                "schema_validated": False,
                "parse_failure_category": category or "unknown",
                "reason_code": f"{request.role.value}_schema_invalid",
            })
            return base
        try:
            validate_model_output(request.output_schema_name, parsed)
            return {"schema_validated": True, **base}
        except Exception as exc:
            missing, wrong_types, wrong_names = _categorize_schema_error(
                request.output_schema_name, parsed, str(exc)
            )
            result: dict[str, Any] = {
                "schema_validated": False,
                "parse_failure_category": category,
                "reason_code": f"{request.role.value}_schema_invalid",
                **base,
            }
            if missing:
                result["missing_fields"] = missing
            if wrong_types:
                result["wrong_field_types"] = wrong_types
                result["invalid_fields"] = wrong_types
            if wrong_names:
                result["wrong_field_names"] = wrong_names
                result["extra_fields"] = wrong_names

            # Check diff-specific failures for RepairPrimaryOutput
            if request.output_schema_name == "RepairPrimaryOutput":
                has_proposed_diff = isinstance(parsed.get("proposed_diff"), str) and bool(str(parsed.get("proposed_diff")).strip())
                result["has_proposed_diff"] = has_proposed_diff
                result["proposed_diff_parse_status"] = "missing"
                if "proposed_diff" in parsed:
                    if not isinstance(parsed.get("proposed_diff"), str):
                        result["proposed_diff_parse_status"] = "invalid_type"
                    else:
                        diff = str(parsed["proposed_diff"])
                        if not diff.strip():
                            result["proposed_diff_parse_status"] = "empty"
                        else:
                            diff_failure = _classify_diff_failure(diff)
                            result["proposed_diff_parse_status"] = diff_failure or "valid_shape"
                            if diff_failure:
                                result["parse_failure_category"] = diff_failure
            return result

    def _deterministic_result(
        self,
        *,
        request: V2RoleModelRequest,
        primary_failure_reason: str,
        fallback_failure_reason: str,
        schema_diagnostics: dict[str, Any] | None = None,
    ) -> V2RoleModelResult:
        content = self._deterministic_content(request, primary_failure_reason, fallback_failure_reason)
        schema_validated = self._schema_ok(request, content)
        redacted = self._build_schema_redacted_summary(primary_failure_reason, schema_diagnostics)
        return V2RoleModelResult(
            content=content,
            role=request.role.value,
            provider="deterministic",
            source="deterministic",
            model_status="fallback",
            success=False,
            failure_reason=fallback_failure_reason or primary_failure_reason or "deterministic_fallback",
            primary_failure_reason=primary_failure_reason,
            fallback_used=bool(fallback_failure_reason),
            schema_validated=schema_validated,
            redacted_summary=redacted,
            schema_diagnostics=schema_diagnostics,
        )

    def _build_schema_redacted_summary(
        self,
        primary_failure_reason: str,
        schema_diagnostics: dict[str, Any] | None = None,
    ) -> str:
        if schema_diagnostics:
            safe = _build_diagnostic_summary_from_diag(schema_diagnostics)
            if safe:
                return safe
        if "schema_invalid" in primary_failure_reason:
            return "Main model output failed schema validation, so Reviewer was not run and no reviewed diff was materialized."
        if "model_unavailable" in primary_failure_reason or "model_failed" in primary_failure_reason:
            return "Main model invocation failed; Reviewer was not run."
        return ""

    def _deterministic_content(
        self,
        request: V2RoleModelRequest,
        primary_failure_reason: str,
        fallback_failure_reason: str,
    ) -> str:
        safe_reason = redact_model_summary(
            fallback_failure_reason or primary_failure_reason or "model_unavailable"
        )
        if request.require_schema and request.output_schema_name == "ReviewerCritique":
            return json.dumps(
                {
                    "decision": "revise",
                    "reasoning": "Reviewer model unavailable; fail-closed review requires revision or manual evidence review.",
                    "missing_evidence": ["Reviewer model output unavailable"],
                    "unsafe_assumptions": ["No independent model critique was completed"],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        if request.require_schema and request.output_schema_name == "AssistantAnswer":
            return json.dumps(
                {"answer": request.fallback, "evidence_refs": []},
                separators=(",", ":"),
                sort_keys=True,
            )
        if request.role == V2ModelRole.REVIEWER:
            return json.dumps(
                {
                    "decision": "revise",
                    "reasoning": "Reviewer model unavailable; fail-closed review requires revision or manual evidence review.",
                    "missing_evidence": ["Reviewer model output unavailable"],
                    "unsafe_assumptions": ["No independent model critique was completed"],
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        return (
            f"{request.fallback}\n\nModel: fallback\nSource: deterministic\nReason: {safe_reason}"
        )

    def _role_env_ref(self, role: V2ModelRole, settings: ControlTowerSettings) -> str:
        new_env = f"AI_MIGRATION_{_role_to_env_key(role)}_MODEL"
        if os.environ.get(new_env, "").strip():
            return new_env
        old_env = _OLD_ROLE_ENV.get(role)
        if old_env and os.environ.get(old_env, "").strip():
            return old_env
        if role == V2ModelRole.PROPOSER:
            return settings.azure_foundry_proposer_deployment_env
        if role == V2ModelRole.REVIEWER:
            return settings.azure_foundry_reviewer_deployment_env
        if role == V2ModelRole.FALLBACK:
            return settings.azure_foundry_fallback_deployment_env
        return settings.azure_foundry_assistant_deployment_env


# ── Module-level helpers ────────────────────────────────────────────


def _deployment_alias_hash(deployment: str) -> str:
    """Hash a deployment name to a safe opaque identifier."""
    if not deployment:
        return ""
    return hashlib.sha256(deployment.encode("utf-8")).hexdigest()[:16]


def _build_diagnostic_summary_from_diag(diag: dict[str, Any]) -> str:
    """Build a specific redacted summary from schema diagnostics dict."""
    role = str(diag.get("role") or diag.get("stage") or "")
    subject = "Reviewer" if role == "reviewer" else "Main"
    if subject == "Reviewer" and str(diag.get("reason_code") or "") == "reviewer_schema_invalid":
        return "Reviewer model output failed schema validation."
    category = str(diag.get("parse_failure_category") or "")
    missing = diag.get("missing_fields")
    wrong_types = diag.get("wrong_field_types")
    wrong_names = diag.get("wrong_field_names")
    invalid_fields = diag.get("invalid_fields")
    extra_fields = diag.get("extra_fields")
    diff_status = str(diag.get("proposed_diff_parse_status") or "")
    rfu = diag.get("response_format_used")

    if rfu is False:
        return "Azure rejected response_format=json_object; model returned plain text."

    if category == "azure_response_format_rejected":
        return "Azure rejected response_format=json_object."

    if category == "truncated_output":
        return f"{subject} model response appears truncated."

    if category == "unsupported_response_format":
        return f"{subject} model returned unsupported response format."

    if category == "invalid_json":
        return f"{subject} model returned invalid JSON."

    if category == "markdown_wrapped_json":
        return f"{subject} model returned markdown-wrapped JSON that could not be parsed."

    if missing:
        return f"{subject} model returned JSON missing required fields: {', '.join(missing)}"

    if wrong_types:
        return f"{subject} model returned JSON with wrong field types: {'; '.join(wrong_types)}"

    if wrong_names:
        return f"{subject} model returned JSON with unexpected fields: {', '.join(wrong_names)}"

    if invalid_fields:
        return f"{subject} model returned JSON with invalid fields: {'; '.join(invalid_fields)}"

    if extra_fields:
        return f"{subject} model returned JSON with unexpected fields: {', '.join(extra_fields)}"

    if diff_status in {"missing", "empty", "invalid_type", "missing_diff_git_header", "missing_hunk", "invalid_diff"}:
        return f"{subject} model returned invalid proposed_diff: {diff_status}"

    return ""


def _build_schema_failure_summary(request: V2RoleModelRequest, content: str) -> str:
    """Build a safe human-readable summary for schema validation failures."""
    if not request.require_schema or not request.output_schema_name:
        return ""
    if request.role == V2ModelRole.REVIEWER:
        return "Reviewer model output failed schema validation."
    parsed, category = _parse_model_json_safe(content)
    if parsed is not None:
        missing, wrong_types, wrong_names = _categorize_schema_error(
            request.output_schema_name, parsed, ""
        )
        parts: list[str] = []
        if missing:
            parts.append(f"missing required fields: {missing}")
        if wrong_types:
            parts.append(f"wrong field types: {wrong_types}")
        if wrong_names:
            parts.append(f"unexpected fields: {wrong_names}")
        if parts:
            return f"Main model returned JSON with schema errors: {'; '.join(parts)}"

        diff = str(parsed.get("proposed_diff", ""))
        if diff.strip():
            if "diff --git " not in diff:
                return "Main model returned JSON with proposed_diff missing diff --git header"
            if "@@" not in diff:
                return "Main model returned JSON with proposed_diff missing @@ hunk"
        return "Main model output failed schema validation."
    if category == "markdown_wrapped_json":
        return "Main model returned markdown-wrapped JSON that could not be parsed."
    if category == "empty_output":
        return "Main model returned empty output."
    return "Main model returned non-JSON output that could not be parsed as structured repair data."


def _parse_model_json_safe(content: str) -> tuple[dict[str, Any] | None, str]:
    """Try to parse model output as JSON with resilient fallbacks.

    Returns (parsed_dict, category) where category describes the parse method used.
    """
    raw = str(content).strip()
    if not raw:
        return None, "empty_output"

    # Truncation detection: content that looks like it was cut off
    braces_unequal = raw.count("{") != raw.count("}")
    truncated_signals = (
        raw.endswith("..."),
        raw.endswith("```") and not raw.startswith("```"),
        raw.rstrip().endswith(","),
        raw.count("{") > raw.count("}"),
        raw.count("[") > raw.count("]"),
        # Object started but braces unbalanced — strong truncation signal
        braces_unequal and raw.lstrip().startswith("{"),
        # Odd number of double-quotes = unclosed string value
        (raw.count('"') % 2 == 1) if raw.count('"') > 0 else False,
    )
    likely_truncated = sum(truncated_signals) >= 1

    # Attempt 1: direct json.loads
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed, "direct_parse"
    except json.JSONDecodeError:
        pass

    # Attempt 2: strip markdown code fences
    cleaned = raw
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = cleaned.strip()
    if cleaned != raw:
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed, "markdown_wrapped_json"
        except json.JSONDecodeError:
            pass

    # Attempt 3: extract first complete JSON object
    extracted = _extract_first_json_object(raw)
    if extracted is not None:
        return extracted, "extracted_json_object"

    if likely_truncated:
        return None, "truncated_output"

    return None, "invalid_json"


def _extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Extract the first complete JSON object from arbitrary text."""
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        if text[idx] == "{":
            try:
                obj, end = decoder.raw_decode(text, idx)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                idx += 1
                continue
        idx += 1
    return None


def _categorize_schema_error(
    schema_name: str,
    data: dict[str, Any],
    error_text: str,
) -> tuple[list[str], list[str], list[str]]:
    """Categorize schema validation errors into missing fields, wrong types, wrong names.

    Returns (missing_fields, wrong_types, wrong_names).
    """
    from migration_factory.control_tower.application.v2_model_schemas import SCHEMA_REGISTRY

    schema = SCHEMA_REGISTRY.get(schema_name, {})
    missing: list[str] = []
    wrong_types: list[str] = []
    wrong_names: list[str] = []

    # Check missing required fields
    required = schema.get("required", [])
    for field in required:
        if field not in data:
            missing.append(field)

    # Check field types
    properties = schema.get("properties", {})
    for field, field_schema in properties.items():
        if field not in data:
            continue
        expected_type = field_schema.get("type")
        value = data[field]
        if expected_type == "string" and not isinstance(value, str):
            wrong_types.append(f"{field} (expected string, got {type(value).__name__})")
        elif expected_type == "array" and not isinstance(value, (list, tuple)):
            wrong_types.append(f"{field} (expected array, got {type(value).__name__})")
        elif expected_type == "number" and not isinstance(value, (int, float)):
            wrong_types.append(f"{field} (expected number, got {type(value).__name__})")
        elif expected_type in ("integer",) and not isinstance(value, int):
            wrong_types.append(f"{field} (expected integer, got {type(value).__name__})")

    # Check for unexpected field names (additionalProperties: false)
    allowed = set(properties.keys())
    for key in data:
        if key not in allowed:
            wrong_names.append(key)

    return missing, wrong_types, wrong_names


def _classify_diff_failure(diff: str) -> str:
    """Classify a proposed_diff string failure mode.

    Returns one of: missing_diff_git_header, missing_hunk, invalid_diff, or empty string.
    """
    text = diff.strip()
    if not text:
        return ""
    if "diff --git " not in text:
        return "missing_diff_git_header"
    if "@@" not in text:
        return "missing_hunk"
    if "--- " not in text or "+++ " not in text:
        return "invalid_diff"
    return ""
