"""Role-based Azure/OpenAI routing for V2 model calls.

This module resolves per-role deployment env refs, applies safe fallback
selection, and optionally fail-closes on structured-output schema checks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from migration_factory.control_tower.application.v2_model_schemas import (
    describe_model_output_validation_failure,
    extract_json_object,
    normalize_schema_object,
    validate_model_output,
)
from migration_factory.control_tower.application.v2_settings import ControlTowerSettings
from migration_factory.control_tower.application.redaction import redact_model_summary


class V2ModelRole(str, Enum):
    ASSISTANT = "assistant"
    PROPOSER = "proposer"
    REVIEWER = "reviewer"
    FALLBACK = "fallback"


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
    deployment: str = ""
    endpoint_metadata: str = ""
    provider_failure_kind: str = ""
    provider_failure_stage: str = ""
    provider_retry_path: str = ""
    provider_http_status: str = ""
    provider_error_redacted_preview: str = ""
    exact_provider_content: str = ""


@dataclass(frozen=True)
class V2RoleModelRoute:
    request: V2RoleModelRequest
    primary_env_ref: str
    primary_deployment: str
    fallback_env_ref: str
    fallback_deployment: str
    fallback_enabled: bool


class V2ModelRoleRouter:
    """Resolve role-specific deployments and execute safe fallback selection."""

    def __init__(self, settings: ControlTowerSettings | None = None) -> None:
        self._settings = settings or ControlTowerSettings()

    def plan(self, request: V2RoleModelRequest, *, settings: ControlTowerSettings | None = None) -> V2RoleModelRoute:
        active_settings = settings or self._settings
        primary_env_ref = self._role_env_ref(request.role, active_settings)
        fallback_env_ref = active_settings.azure_foundry_fallback_deployment_env or ""
        return V2RoleModelRoute(
            request=request,
            primary_env_ref=primary_env_ref,
            primary_deployment=os.environ.get(primary_env_ref, "").strip(),
            fallback_env_ref=fallback_env_ref,
            fallback_deployment=os.environ.get(fallback_env_ref, "").strip(),
            fallback_enabled=bool(active_settings.azure_foundry_fallback_enabled),
        )

    def route(
        self,
        request: V2RoleModelRequest,
        *,
        invoke: Callable[[str], Any],
        settings: ControlTowerSettings | None = None,
    ) -> V2RoleModelResult:
        route = self.plan(request, settings=settings)
        primary_result, primary_failure = self._try_invoke(
            invoke,
            deployment=route.primary_deployment,
            request=request,
            role=request.role.value,
        )
        if primary_result is not None:
            result = self._coerce_primary_result(primary_result, request)
            validation_content = result.exact_provider_content or result.content
            if result.success and self._schema_ok(request, validation_content):
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
                    deployment=result.deployment,
                    endpoint_metadata=result.endpoint_metadata,
                    provider_failure_kind=result.provider_failure_kind,
                    provider_failure_stage=result.provider_failure_stage,
                    provider_retry_path=result.provider_retry_path,
                    provider_http_status=result.provider_http_status,
                    provider_error_redacted_preview=result.provider_error_redacted_preview,
                    exact_provider_content=result.exact_provider_content,
                )
            schema_failure = self._schema_failure_reason(request, validation_content) if request.require_schema else ""
            primary_failure = (
                result.primary_failure_reason
                or result.failure_reason
                or primary_failure
                or schema_failure
                or "primary_model_failed"
            )

        if route.fallback_enabled and route.fallback_deployment:
            fallback_result, fallback_failure = self._try_invoke(
                invoke,
                deployment=route.fallback_deployment,
                request=request,
                role=V2ModelRole.FALLBACK.value,
            )
            if fallback_result is not None:
                result = self._coerce_fallback_result(
                    fallback_result,
                    request,
                    primary_failure_reason=primary_failure,
                )
                validation_content = result.exact_provider_content or result.content
                if result.success and self._schema_ok(request, validation_content):
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
                        deployment=result.deployment,
                        endpoint_metadata=result.endpoint_metadata,
                        provider_failure_kind=result.provider_failure_kind,
                        provider_failure_stage=result.provider_failure_stage,
                        provider_retry_path=result.provider_retry_path,
                        provider_http_status=result.provider_http_status,
                        provider_error_redacted_preview=result.provider_error_redacted_preview,
                        exact_provider_content=result.exact_provider_content,
                    )
                fallback_failure = (
                    result.failure_reason
                    or fallback_failure
                    or self._schema_failure_reason(request, validation_content)
                    or "fallback_model_failed"
                )
            else:
                fallback_failure = fallback_failure or "fallback_model_failed"
        else:
            fallback_failure = ""

        return self._deterministic_result(
            request=request,
            primary_failure_reason=primary_failure or "primary_model_unavailable",
            fallback_failure_reason=fallback_failure,
        )

    def _try_invoke(
        self,
        invoke: Callable[[str], Any],
        *,
        deployment: str,
        request: V2RoleModelRequest,
        role: str,
    ) -> tuple[Any | None, str]:
        if not deployment:
            return None, f"missing_{role}_deployment"
        try:
            return invoke(deployment), ""
        except Exception as exc:
            return None, redact_model_summary(f"{type(exc).__name__}: {exc}")

    def _coerce_primary_result(self, result: Any, request: V2RoleModelRequest) -> V2RoleModelResult:
        return V2RoleModelResult(
            content=str(getattr(result, "content", "") or ""),
            role=request.role.value,
            provider=str(getattr(result, "provider", "") or "azure_openai"),
            source=str(getattr(result, "source", "") or "azure_openai"),
            model_status=str(getattr(result, "model_status", "") or "live_ok"),
            success=bool(getattr(result, "success", False)),
            failure_reason=str(getattr(result, "failure_reason", "") or ""),
            primary_failure_reason=str(getattr(result, "primary_failure_reason", "") or ""),
            fallback_used=bool(getattr(result, "fallback_used", False)),
            schema_validated=bool(getattr(result, "schema_validated", False)),
            deployment=str(getattr(result, "deployment", "") or ""),
            endpoint_metadata=str(getattr(result, "endpoint_metadata", "") or ""),
            provider_failure_kind=str(getattr(result, "provider_failure_kind", "") or ""),
            provider_failure_stage=str(getattr(result, "provider_failure_stage", "") or ""),
            provider_retry_path=str(getattr(result, "provider_retry_path", "") or ""),
            provider_http_status=str(getattr(result, "provider_http_status", "") or ""),
            provider_error_redacted_preview=str(getattr(result, "provider_error_redacted_preview", "") or ""),
            exact_provider_content=str(
                getattr(result, "exact_provider_content", "") or getattr(result, "content", "") or ""
            ),
        )

    def _coerce_fallback_result(
        self,
        result: Any,
        request: V2RoleModelRequest,
        *,
        primary_failure_reason: str,
    ) -> V2RoleModelResult:
        coerced = self._coerce_primary_result(result, request)
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
            deployment=coerced.deployment,
            endpoint_metadata=coerced.endpoint_metadata,
            provider_failure_kind=coerced.provider_failure_kind,
            provider_failure_stage=coerced.provider_failure_stage,
            provider_retry_path=coerced.provider_retry_path,
            provider_http_status=coerced.provider_http_status,
            provider_error_redacted_preview=coerced.provider_error_redacted_preview,
            exact_provider_content=coerced.exact_provider_content,
        )

    def _schema_ok(self, request: V2RoleModelRequest, content: str) -> bool:
        if not request.require_schema:
            return True
        if not request.output_schema_name:
            return False
        if _is_governed_repair_schema(request.output_schema_name):
            try:
                parsed = _strict_json_object(content)
                validate_model_output(request.output_schema_name, parsed)
            except Exception:
                return False
            return True
        parsed = extract_json_object(content)
        if parsed is None:
            return False
        parsed = normalize_schema_object(request.output_schema_name, parsed)
        try:
            validate_model_output(request.output_schema_name, parsed)
        except Exception:
            return False
        return True

    def _deterministic_result(
        self,
        *,
        request: V2RoleModelRequest,
        primary_failure_reason: str,
        fallback_failure_reason: str,
    ) -> V2RoleModelResult:
        content = self._deterministic_content(request, primary_failure_reason, fallback_failure_reason)
        schema_validated = self._schema_ok(request, content)
        return V2RoleModelResult(
            content=content,
            role=request.role.value,
            provider="deterministic",
            source="deterministic",
            model_status="fallback",
            success=False,
            failure_reason=fallback_failure_reason or primary_failure_reason or "deterministic_fallback",
            primary_failure_reason=primary_failure_reason,
            fallback_used=bool(fallback_failure_reason)
            or not str(primary_failure_reason or "").startswith("missing_"),
            schema_validated=schema_validated,
            deployment="",
            endpoint_metadata="",
            provider_failure_kind="deterministic_fallback_used",
            provider_failure_stage="router_deterministic_fallback",
            provider_retry_path="deterministic_fallback",
            provider_http_status="",
            provider_error_redacted_preview=redact_model_summary(
                fallback_failure_reason or primary_failure_reason or "model_unavailable"
            )[:500],
            exact_provider_content=content,
        )

    def _deterministic_content(
        self,
        request: V2RoleModelRequest,
        primary_failure_reason: str,
        fallback_failure_reason: str,
    ) -> str:
        safe_reason = redact_model_summary(
            fallback_failure_reason or primary_failure_reason or "model_unavailable"
        )
        if request.require_schema and request.output_schema_name in {
            "RepairProposerShadowOutput",
            "RepairReviewerShadowOutput",
            "RepairFallbackShadowOutput",
        }:
            return request.fallback
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
        if role == V2ModelRole.PROPOSER:
            return settings.azure_foundry_proposer_deployment_env
        if role == V2ModelRole.REVIEWER:
            return settings.azure_foundry_reviewer_deployment_env
        if role == V2ModelRole.FALLBACK:
            return settings.azure_foundry_fallback_deployment_env
        return settings.azure_foundry_assistant_deployment_env

    def _schema_failure_reason(self, request: V2RoleModelRequest, content: str) -> str:
        if not request.require_schema:
            return ""
        if request.output_schema_name:
            if _is_governed_repair_schema(request.output_schema_name):
                try:
                    parsed = _strict_json_object(content)
                    validate_model_output(request.output_schema_name, parsed)
                except Exception as exc:
                    return redact_model_summary(
                        f"schema_validation_failed:{request.output_schema_name} {exc}"
                    )
                return ""
            reason = describe_model_output_validation_failure(request.output_schema_name, content)
            return reason or f"schema_validation_failed:{request.output_schema_name}"
        return "schema_validation_failed"


def _is_governed_repair_schema(schema_name: str | None) -> bool:
    return str(schema_name or "") in {"RepairPrimaryOutput", "RepairReviewerOutput"}


def _strict_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        raise ValueError("output must be a JSON object string")
    text = content.strip()
    if not text:
        raise ValueError("output must not be empty")
    decoder = json.JSONDecoder()
    parsed, end = decoder.raw_decode(text)
    if text[end:].strip():
        raise ValueError("output must contain exactly one JSON object")
    if not isinstance(parsed, dict):
        raise ValueError("output root must be a JSON object")
    return parsed
