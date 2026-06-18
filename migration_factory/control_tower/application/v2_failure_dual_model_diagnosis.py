from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    ModelInvocationResult,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import RunEvidenceBundle


_MAX_ANSWER = 2600
_MAX_EVIDENCE = 6
_MAX_ISSUES = 4
_MAVEN_COORD_RE = re.compile(r"\b[\w.\-]+:[\w.\-]+:(?:jar|pom):\d+\.\d+\.x\b")
_PROPERTY_RE = re.compile(r"\b(?:javax\.persistence\.version|javax\.servlet\.version)\b")


@dataclass(frozen=True)
class V2FailureDualModelDiagnosisAnswer:
    migration_status: str
    root_cause: str
    confidence: str
    model2_verdict: str
    evidence_refs: tuple[str, ...]
    next_operator_action: str
    answer: str
    model1: dict[str, Any]
    model2: dict[str, Any]
    trace_artifact_refs: dict[str, dict[str, str]]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2FailureDualModelDiagnosisService:
    def __init__(
        self,
        *,
        runtime_service: V2DualModelRuntimeService,
    ) -> None:
        self._runtime = runtime_service

    @staticmethod
    def should_run(bundle: RunEvidenceBundle) -> bool:
        return bool(
            bundle.migration_status == "failed"
            or bundle.failure_bundle is not None
            or bundle.deterministic_failure_classification is not None
        )

    def diagnose(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        setup: Any | None,
        trace_root: str | Path | None = None,
    ) -> V2FailureDualModelDiagnosisAnswer:
        resolved_trace_root = self._trace_root(bundle=bundle, setup=setup, trace_root=trace_root)
        source_input = self._source_input(question=question, bundle=bundle)
        model1 = self._runtime.invoke_model_1(
            ModelInvocationRequest(
                role=MODEL_1_ROLE,
                objective="Analyze deterministic migration failure evidence for assistant diagnosis.",
                evidence_bundle=bundle.to_dict(),
                source_input=source_input,
                correlation_id=f"{bundle.run_id}:failure:model1",
                supervision_context="failure_diagnosis",
                trace_root=str(resolved_trace_root) if resolved_trace_root is not None else "",
            )
        )
        model2 = self._runtime.invoke_model_2(
            ModelInvocationRequest(
                role=MODEL_2_ROLE,
                objective="Verify deterministic migration failure diagnosis for assistant answer.",
                evidence_bundle=bundle.to_dict(),
                source_input=source_input,
                model1_output=model1.structured_output,
                correlation_id=f"{bundle.run_id}:failure:model2",
                supervision_context="failure_diagnosis_verification",
                trace_root=str(resolved_trace_root) if resolved_trace_root is not None else "",
            )
        )
        answer = self._answer_text(question=question, bundle=bundle, model1=model1, model2=model2)
        return V2FailureDualModelDiagnosisAnswer(
            migration_status=bundle.migration_status,
            root_cause=self._root_cause(bundle=bundle, model1=model1, model2=model2),
            confidence=self._confidence(bundle=bundle, model1=model1, model2=model2),
            model2_verdict=str(model2.structured_output.get("verdict") or "unknown"),
            evidence_refs=self._evidence_refs(bundle=bundle, model1=model1),
            next_operator_action=str(bundle.next_operator_action or model1.structured_output.get("recommended_action") or "inspect_evidence"),
            answer=answer,
            model1=model1.to_dict(),
            model2=model2.to_dict(),
            trace_artifact_refs={
                "model1": dict(model1.trace_artifact_refs),
                "model2": dict(model2.trace_artifact_refs),
            },
            read_only=True,
        )

    def _trace_root(
        self,
        *,
        bundle: RunEvidenceBundle,
        setup: Any | None,
        trace_root: str | Path | None,
    ) -> Path | None:
        if trace_root not in (None, ""):
            return Path(str(trace_root)).resolve()
        output_parent = str(getattr(setup, "output_parent_path", "") or "").strip()
        run_id = str(bundle.run_id or "").strip()
        if output_parent and run_id:
            return (Path(output_parent) / ".migration" / "runs" / run_id).resolve()
        return None

    def _source_input(self, *, question: str, bundle: RunEvidenceBundle) -> str:
        payload = {
            "question": question,
            "supervision_purpose": "failure_diagnosis",
            "migration_status": bundle.migration_status,
            "ai_supervision_status": bundle.ai_supervision_status,
            "next_operator_action": bundle.next_operator_action,
            "deterministic_failure_classification": bundle.deterministic_failure_classification,
            "failure_bundle": asdict(bundle.failure_bundle) if bundle.failure_bundle is not None else None,
            "build_test_error_contracts": list(bundle.build_test_error_contracts[:_MAX_EVIDENCE]),
            "relevant_log_excerpts": list(bundle.relevant_log_excerpts[:_MAX_EVIDENCE]),
            "pom_excerpts": list(bundle.pom_excerpts[:_MAX_EVIDENCE]),
            "generated_artifact_refs": list(bundle.generated_artifact_refs[:_MAX_EVIDENCE]),
            "guardrails": {
                "evidence_grounded_only": True,
                "no_direct_repair_execution": True,
                "no_command_execution": True,
                "no_approval_mutation": True,
            },
        }
        return json.dumps(payload, sort_keys=True, default=str)

    def _answer_text(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        model1: ModelInvocationResult,
        model2: ModelInvocationResult,
    ) -> str:
        verdict = str(model2.structured_output.get("verdict") or "unknown")
        refs = ", ".join(self._evidence_refs(bundle=bundle, model1=model1)) or "none"
        evidence_details = self._evidence_details(bundle)
        issues = "; ".join(
            str(item)
            for item in (model2.structured_output.get("issues_found") or [])[:_MAX_ISSUES]
        ) or "none"
        lines = [
            f"Question: {self._bounded(question, 180)}",
            f"Migration status: {bundle.migration_status}",
        ]
        if bundle.ai_supervision_status == "unavailable_fallback" and bundle.migration_status.startswith("completed"):
            lines.append("Root cause: Migration completed. Only AI/model supervision is unavailable, so deterministic fallback is active.")
        elif verdict == "accepted":
            lines.append(f"Verified root cause: {self._root_cause(bundle=bundle, model1=model1, model2=model2)}")
        else:
            lines.append("Verified root cause: Diagnosis needs human review before it should be treated as final.")
            lines.append(
                f"Model 1 suggested root cause: {self._bounded(str(model1.structured_output.get('root_cause') or 'none'), 220)}"
            )
        lines.extend(
            [
                f"Confidence: {self._confidence(bundle=bundle, model1=model1, model2=model2)}",
                f"Model 2 verdict: {verdict}",
                f"Evidence refs: {refs}",
            ]
        )
        if evidence_details:
            lines.append(f"Evidence details: {evidence_details}")
        if verdict != "accepted":
            lines.append(f"Verifier issues: {self._bounded(issues, 320)}")
        lines.append(f"Next operator action: {bundle.next_operator_action}")
        lines.append(
            "Safety: Diagnosis only. Read-only evidence path. No commands executed, no approvals changed, no patch was applied, no repairs applied, no files modified."
        )
        return self._bounded("\n".join(lines), _MAX_ANSWER)

    def _evidence_details(self, bundle: RunEvidenceBundle) -> str:
        parts: list[str] = []
        classification = bundle.deterministic_failure_classification or {}
        for item in classification.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("source") or "evidence").strip()
            text = self._bounded(self._compressed_evidence_text(str(item.get("text") or "")), 180)
            if text:
                parts.append(f"{label}: {text}")
        for collection in (
            bundle.build_test_error_contracts,
            bundle.relevant_log_excerpts,
            bundle.pom_excerpts,
        ):
            for item in collection[:2]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("source") or "evidence").strip()
                text = self._compressed_evidence_text(str(item.get("text") or ""))
                text = self._bounded(text, 180)
                if text:
                    parts.append(f"{label}: {text}")
        deduped: list[str] = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        return self._bounded("; ".join(deduped[:6]), 520)

    def _compressed_evidence_text(self, text: str) -> str:
        coords = _MAVEN_COORD_RE.findall(text)
        props = _PROPERTY_RE.findall(text)
        fragments: list[str] = []
        for item in coords:
            if item not in fragments:
                fragments.append(item)
        for item in props:
            if item not in fragments:
                fragments.append(item)
        if "BUILD_FAILED_IN_SANDBOX" in text and "BUILD_FAILED_IN_SANDBOX" not in fragments:
            fragments.append("BUILD_FAILED_IN_SANDBOX")
        if fragments:
            return "; ".join(fragments[:6])
        return text

    def _root_cause(
        self,
        *,
        bundle: RunEvidenceBundle,
        model1: ModelInvocationResult,
        model2: ModelInvocationResult,
    ) -> str:
        if str(model2.structured_output.get("verdict") or "") == "accepted":
            text = str(model1.structured_output.get("root_cause") or "").strip()
            if text:
                return text
        if bundle.failure_bundle is not None and bundle.failure_bundle.root_cause:
            return bundle.failure_bundle.root_cause
        return str(model1.structured_output.get("root_cause") or "No verified root cause available.").strip()

    def _confidence(
        self,
        *,
        bundle: RunEvidenceBundle,
        model1: ModelInvocationResult,
        model2: ModelInvocationResult,
    ) -> str:
        if str(model2.structured_output.get("verdict") or "") == "accepted":
            value = str(model1.structured_output.get("confidence") or "").strip()
            if value:
                return value
        if bundle.failure_bundle is not None and bundle.failure_bundle.confidence:
            return bundle.failure_bundle.confidence
        return str(model1.structured_output.get("confidence") or "low").strip() or "low"

    def _evidence_refs(
        self,
        *,
        bundle: RunEvidenceBundle,
        model1: ModelInvocationResult,
    ) -> tuple[str, ...]:
        refs: list[str] = []
        for item in model1.structured_output.get("evidence_refs") or []:
            text = str(item or "").strip()
            if text:
                refs.append(text)
        if not refs:
            for item in bundle.generated_artifact_refs:
                if isinstance(item, dict):
                    text = str(item.get("label") or item.get("path") or "").strip()
                    if text:
                        refs.append(text)
        deduped: list[str] = []
        for ref in refs:
            if ref not in deduped:
                deduped.append(ref)
        return tuple(deduped[:_MAX_EVIDENCE])

    def _bounded(self, text: str, limit: int) -> str:
        redacted = redact_model_summary(str(text or "")).strip()
        if len(redacted) <= limit:
            return redacted
        return redacted[:limit] + "...[truncated]"
