from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_model_schemas import validate_model_output
from migration_factory.control_tower.application.v2_prompt_router import ModelCallRequest
from migration_factory.control_tower.domain.checksums import utc_now_text


MODEL_1_ROLE = "model_1_migration_engineer"
MODEL_2_ROLE = "model_2_safety_reviewer"
_ALLOWED_ROLES = {MODEL_1_ROLE, MODEL_2_ROLE}
_FORBIDDEN_RECOMMENDATION_RE = re.compile(
    r"(?i)\b(execute|run command|apply repair|approve|resume stage|write file|modify files?)\b"
)


@dataclass(frozen=True)
class ModelRuntimeStatus:
    provider: str
    model1_ready: bool
    model2_ready: bool
    fallback_available: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelInvocationRequest:
    role: str
    objective: str
    evidence_bundle: dict[str, Any]
    source_input: str = ""
    model1_output: dict[str, Any] | None = None
    correlation_id: str | None = None
    supervision_context: str = ""
    trace_root: str = ""

    def __post_init__(self) -> None:
        if self.role not in _ALLOWED_ROLES:
            raise ValueError(f"Unknown model role: {self.role!r}")


@dataclass(frozen=True)
class Model1ReviewResult:
    summary: str
    root_cause: str
    confidence: str
    evidence_refs: tuple[str, ...]
    recommended_action: str
    risk_level: str
    proposed_next_steps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate_model_output("Model1ReviewResult", data)
        return data


@dataclass(frozen=True)
class Model2VerificationResult:
    verdict: str
    evidence_alignment: str
    hallucination_check: str
    policy_check: str
    risk_level: str
    issues_found: tuple[str, ...]
    human_approval_required: bool

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate_model_output("Model2VerificationResult", data)
        return data


@dataclass(frozen=True)
class ModelInvocationResult:
    role: str
    provider: str
    mode: str
    success: bool
    structured_output: dict[str, Any]
    invocation_id: str = ""
    created_at: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    trace_artifact_refs: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StructuredModelRuntimeClient(Protocol):
    def invoke(
        self,
        *,
        request: ModelCallRequest,
        schema_name: str,
    ) -> Any:
        ...


class ModelInvocationTraceStore(Protocol):
    def persist_trace(self, *, request: ModelInvocationRequest, result: ModelInvocationResult) -> dict[str, str]:
        ...


class V2DualModelRuntimeService:
    provider = "azure_openai"

    def __init__(
        self,
        *,
        model1_client: StructuredModelRuntimeClient | None = None,
        model2_client: StructuredModelRuntimeClient | None = None,
        trace_store: ModelInvocationTraceStore | None = None,
    ) -> None:
        self._model1_client = model1_client
        self._model2_client = model2_client
        self._trace_store = trace_store

    def get_status(self) -> ModelRuntimeStatus:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        model1_deployment = os.environ.get("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "").strip()
        model2_deployment = os.environ.get("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "").strip()
        errors: list[str] = []
        warnings: list[str] = []
        if not endpoint:
            errors.append("Azure OpenAI endpoint not configured.")
        if not api_key:
            errors.append("Azure OpenAI API key not configured.")
        if not model1_deployment:
            warnings.append("Model 1 deployment not configured; deterministic fallback will be used.")
        if not model2_deployment:
            warnings.append("Model 2 deployment not configured; deterministic fallback will be used.")
        return ModelRuntimeStatus(
            provider=self.provider,
            model1_ready=bool(endpoint and api_key and model1_deployment),
            model2_ready=bool(endpoint and api_key and model2_deployment),
            fallback_available=True,
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def invoke_model_1(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if request.role != MODEL_1_ROLE:
            raise ValueError("Model 1 invocation requires model_1_migration_engineer role.")
        status = self.get_status()
        invocation_id = uuid4().hex
        created_at = utc_now_text()
        if status.model1_ready and self._model1_client is not None:
            try:
                model_call_request = self._build_model_call_request(
                    request=request,
                    schema_name="Model1ReviewResult",
                )
                structured = validate_model_output(
                    "Model1ReviewResult",
                    self._normalize_structured_output(
                        self._invoke_structured_client(
                            self._model1_client,
                            request=model_call_request,
                            schema_name="Model1ReviewResult",
                        )
                    ),
                )
                result = ModelInvocationResult(
                    role=MODEL_1_ROLE,
                    provider=self.provider,
                    mode="live",
                    success=True,
                    structured_output=structured,
                    invocation_id=invocation_id,
                    created_at=created_at,
                    warnings=status.warnings,
                    errors=status.errors,
                )
                return self._persist_if_configured(request=request, result=result)
            except Exception as exc:
                fallback = self._deterministic_model1(request.evidence_bundle)
                result = ModelInvocationResult(
                    role=MODEL_1_ROLE,
                    provider=self.provider,
                    mode="fallback",
                    success=False,
                    structured_output=fallback.to_dict(),
                    invocation_id=invocation_id,
                    created_at=created_at,
                    warnings=(
                        status.warnings
                        + ("Model 1 invocation failed; deterministic fallback used.",)
                    ),
                    errors=(
                        status.errors
                        + (redact_model_summary(f"model_invocation_failed:{type(exc).__name__}"),)
                    ),
                )
                return self._persist_if_configured(request=request, result=result)
        deterministic = self._deterministic_model1(request.evidence_bundle)
        result = ModelInvocationResult(
            role=MODEL_1_ROLE,
            provider="deterministic",
            mode="fallback",
            success=True,
            structured_output=deterministic.to_dict(),
            invocation_id=invocation_id,
            created_at=created_at,
            warnings=status.warnings,
            errors=status.errors,
        )
        return self._persist_if_configured(request=request, result=result)

    def invoke_model_2(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if request.role != MODEL_2_ROLE:
            raise ValueError("Model 2 invocation requires model_2_safety_reviewer role.")
        status = self.get_status()
        invocation_id = uuid4().hex
        created_at = utc_now_text()
        if status.model2_ready and self._model2_client is not None:
            try:
                model_call_request = self._build_model_call_request(
                    request=request,
                    schema_name="Model2VerificationResult",
                )
                structured = validate_model_output(
                    "Model2VerificationResult",
                    self._normalize_structured_output(
                        self._invoke_structured_client(
                            self._model2_client,
                            request=model_call_request,
                            schema_name="Model2VerificationResult",
                        )
                    ),
                )
                result = ModelInvocationResult(
                    role=MODEL_2_ROLE,
                    provider=self.provider,
                    mode="live",
                    success=True,
                    structured_output=structured,
                    invocation_id=invocation_id,
                    created_at=created_at,
                    warnings=status.warnings,
                    errors=status.errors,
                )
                return self._persist_if_configured(request=request, result=result)
            except Exception as exc:
                fallback = self._deterministic_model2(
                    evidence_bundle=request.evidence_bundle,
                    model1_output=request.model1_output or {},
                )
                result = ModelInvocationResult(
                    role=MODEL_2_ROLE,
                    provider=self.provider,
                    mode="fallback",
                    success=False,
                    structured_output=fallback.to_dict(),
                    invocation_id=invocation_id,
                    created_at=created_at,
                    warnings=(
                        status.warnings
                        + ("Model 2 invocation failed; deterministic fallback used.",)
                    ),
                    errors=(
                        status.errors
                        + (redact_model_summary(f"model_invocation_failed:{type(exc).__name__}"),)
                    ),
                )
                return self._persist_if_configured(request=request, result=result)
        deterministic = self._deterministic_model2(
            evidence_bundle=request.evidence_bundle,
            model1_output=request.model1_output or {},
        )
        result = ModelInvocationResult(
            role=MODEL_2_ROLE,
            provider="deterministic",
            mode="fallback",
            success=True,
            structured_output=deterministic.to_dict(),
            invocation_id=invocation_id,
            created_at=created_at,
            warnings=status.warnings,
            errors=status.errors,
        )
        return self._persist_if_configured(request=request, result=result)

    def _invoke_structured_client(
        self,
        client: StructuredModelRuntimeClient,
        *,
        request: ModelCallRequest,
        schema_name: str,
    ) -> Any:
        try:
            return client.invoke(request=request, schema_name=schema_name)
        except TypeError:
            pass
        try:
            return client.invoke(request=request)  # type: ignore[misc]
        except TypeError:
            return client.invoke(request)  # type: ignore[misc]

    def _build_model_call_request(
        self,
        *,
        request: ModelInvocationRequest,
        schema_name: str,
    ) -> ModelCallRequest:
        request_id = request.correlation_id or uuid4().hex
        return ModelCallRequest(
            request_id=request_id,
            event_type=request.supervision_context or request.role,
            prompt_template_id=f"v2-dual-model-runtime:{request.role}:{schema_name}",
            output_schema_name=schema_name,
            prompt_text=self._build_prompt_text(request=request, schema_name=schema_name),
            token_budget_input=8000,
            token_budget_output=2000,
            context_pack_checksum=str(request.evidence_bundle.get("run_id") or request.correlation_id or request_id),
            created_at=utc_now_text(),
        )

    def _build_prompt_text(
        self,
        *,
        request: ModelInvocationRequest,
        schema_name: str,
    ) -> str:
        payload = {
            "role": request.role,
            "objective": request.objective,
            "supervision_context": request.supervision_context,
            "schema_name": schema_name,
            "source_input": request.source_input,
            "evidence_bundle": request.evidence_bundle,
            "model1_output": request.model1_output or {},
            "correlation_id": request.correlation_id,
        }
        return json.dumps(payload, sort_keys=True, default=str)

    def _normalize_structured_output(self, raw_result: Any) -> dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result
        validated_output = getattr(raw_result, "validated_output", None)
        if isinstance(validated_output, dict):
            return dict(validated_output)
        if hasattr(raw_result, "to_dict") and callable(getattr(raw_result, "to_dict")):
            candidate = raw_result.to_dict()
            if isinstance(candidate, dict):
                return candidate
        raise ValueError(f"Unsupported structured model result type: {type(raw_result).__name__}")

    def _persist_if_configured(
        self,
        *,
        request: ModelInvocationRequest,
        result: ModelInvocationResult,
    ) -> ModelInvocationResult:
        if self._trace_store is None or not str(request.trace_root or "").strip():
            return result
        try:
            refs = self._trace_store.persist_trace(request=request, result=result)
        except Exception as exc:
            return ModelInvocationResult(
                role=result.role,
                provider=result.provider,
                mode=result.mode,
                success=result.success,
                structured_output=result.structured_output,
                invocation_id=result.invocation_id,
                created_at=result.created_at,
                warnings=result.warnings + ("Invocation trace persistence failed; execution status unchanged.",),
                errors=result.errors + (redact_model_summary(f"trace_persist_failed:{type(exc).__name__}"),),
                trace_artifact_refs=result.trace_artifact_refs,
            )
        return ModelInvocationResult(
            role=result.role,
            provider=result.provider,
            mode=result.mode,
            success=result.success,
            structured_output=result.structured_output,
            invocation_id=result.invocation_id,
            created_at=result.created_at,
            warnings=result.warnings,
            errors=result.errors,
            trace_artifact_refs=refs,
        )

    def _deterministic_model1(self, evidence_bundle: dict[str, Any]) -> Model1ReviewResult:
        migration_status = str(evidence_bundle.get("migration_status") or "unknown")
        ai_status = str(evidence_bundle.get("ai_supervision_status") or "unknown")
        approval_state = str(evidence_bundle.get("approval_state") or "unknown")
        next_action = str(evidence_bundle.get("next_operator_action") or "inspect_evidence")
        failure_bundle = evidence_bundle.get("failure_bundle") or {}
        root_cause = str(
            failure_bundle.get("root_cause")
            or self._default_root_cause(
                migration_status=migration_status,
                ai_status=ai_status,
                approval_state=approval_state,
            )
        )
        evidence_refs = self._evidence_refs(evidence_bundle)
        summary = self._summary_for_bundle(
            migration_status=migration_status,
            ai_status=ai_status,
            approval_state=approval_state,
            root_cause=root_cause,
        )
        return Model1ReviewResult(
            summary=summary,
            root_cause=root_cause,
            confidence=self._confidence_for_bundle(evidence_bundle),
            evidence_refs=evidence_refs,
            recommended_action=next_action,
            risk_level=self._risk_for_bundle(migration_status=migration_status, approval_state=approval_state),
            proposed_next_steps=self._next_steps(
                next_action=next_action,
                migration_status=migration_status,
                approval_state=approval_state,
                ai_status=ai_status,
            ),
        )

    def _deterministic_model2(
        self,
        *,
        evidence_bundle: dict[str, Any],
        model1_output: dict[str, Any],
    ) -> Model2VerificationResult:
        issues: list[str] = []
        root_cause = str(model1_output.get("root_cause") or "")
        summary = str(model1_output.get("summary") or "")
        recommended_action = str(model1_output.get("recommended_action") or "")
        expected_root_cause = str((evidence_bundle.get("failure_bundle") or {}).get("root_cause") or "")
        migration_status = str(evidence_bundle.get("migration_status") or "")
        next_action = str(evidence_bundle.get("next_operator_action") or "")

        if expected_root_cause and root_cause and root_cause != expected_root_cause:
            issues.append("Model 1 root cause does not align with deterministic evidence bundle.")
        if migration_status and migration_status not in summary.lower() and migration_status not in root_cause.lower():
            issues.append("Model 1 summary does not clearly reflect bundle migration status.")
        if recommended_action and recommended_action != next_action:
            issues.append("Model 1 recommended action does not match evidence bundle next action.")
        if _FORBIDDEN_RECOMMENDATION_RE.search(recommended_action):
            issues.append("Model 1 recommended action violates read-only runtime policy.")
        if not model1_output.get("evidence_refs"):
            issues.append("Model 1 output omitted evidence references.")

        if issues:
            verdict = "needs_human_review" if "does not align" not in " ".join(issues) else "rejected"
            evidence_alignment = "mismatch"
            hallucination_check = "failed"
            policy_check = "failed" if any("policy" in issue.lower() for issue in issues) else "warning"
        else:
            verdict = "accepted"
            evidence_alignment = "aligned"
            hallucination_check = "passed"
            policy_check = "passed"

        return Model2VerificationResult(
            verdict=verdict,
            evidence_alignment=evidence_alignment,
            hallucination_check=hallucination_check,
            policy_check=policy_check,
            risk_level=self._risk_for_bundle(
                migration_status=migration_status,
                approval_state=str(evidence_bundle.get("approval_state") or ""),
            ),
            issues_found=tuple(issues),
            human_approval_required=(
                verdict != "accepted"
                or str(evidence_bundle.get("approval_state") or "") == "pending_human_approval"
            ),
        )

    def _summary_for_bundle(
        self,
        *,
        migration_status: str,
        ai_status: str,
        approval_state: str,
        root_cause: str,
    ) -> str:
        if migration_status == "failed":
            return redact_model_summary(f"Migration failed. Evidence points to: {root_cause}")
        if migration_status == "approval_required":
            return "Migration is blocked pending human approval."
        if migration_status.startswith("completed"):
            if ai_status == "unavailable_fallback":
                return "Migration completed, but AI supervision is unavailable and deterministic fallback is active."
            return "Migration completed according to deterministic evidence."
        return redact_model_summary(f"Migration status is {migration_status}. {root_cause}")

    def _default_root_cause(self, *, migration_status: str, ai_status: str, approval_state: str) -> str:
        if migration_status == "approval_required" or approval_state == "pending_human_approval":
            return "Human approval is required before backend execution may continue."
        if migration_status.startswith("completed") and ai_status == "unavailable_fallback":
            return "Migration completed; only AI/model supervision is unavailable."
        if migration_status.startswith("completed"):
            return "Migration completed with no deterministic failure evidence."
        return "Deterministic evidence bundle did not include a confirmed root cause."

    def _evidence_refs(self, evidence_bundle: dict[str, Any]) -> tuple[str, ...]:
        refs: list[str] = []
        for item in evidence_bundle.get("generated_artifact_refs") or []:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("path") or "").strip()
                if label:
                    refs.append(label)
        latest = evidence_bundle.get("latest_trustworthy_migration_event") or {}
        latest_type = str(latest.get("type") or "").strip()
        if latest_type:
            refs.append(f"event:{latest_type}")
        failure_bundle = evidence_bundle.get("failure_bundle") or {}
        for item in failure_bundle.get("affected_paths") or []:
            text = str(item or "").strip()
            if text:
                refs.append(text)
        deduped: list[str] = []
        for ref in refs:
            if ref not in deduped:
                deduped.append(ref)
        return tuple(deduped[:8])

    def _confidence_for_bundle(self, evidence_bundle: dict[str, Any]) -> str:
        failure_bundle = evidence_bundle.get("failure_bundle") or {}
        if failure_bundle.get("confidence"):
            return str(failure_bundle.get("confidence"))
        migration_status = str(evidence_bundle.get("migration_status") or "")
        if migration_status.startswith("completed") or migration_status == "approval_required":
            return "high"
        return "medium"

    def _risk_for_bundle(self, *, migration_status: str, approval_state: str) -> str:
        if migration_status == "failed":
            return "high"
        if migration_status == "approval_required" or approval_state == "pending_human_approval":
            return "medium"
        return "low"

    def _next_steps(
        self,
        *,
        next_action: str,
        migration_status: str,
        approval_state: str,
        ai_status: str,
    ) -> tuple[str, ...]:
        steps = [f"Follow deterministic next action: {next_action}."]
        if migration_status == "failed":
            steps.append("Review evidence bundle artifacts and failure excerpts before drafting changes.")
        if approval_state == "pending_human_approval":
            steps.append("Await human approval; do not resume stage automatically.")
        if ai_status == "unavailable_fallback":
            steps.append("Use deterministic fallback outputs until Azure/OpenAI readiness is restored.")
        return tuple(steps[:4])
