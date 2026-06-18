from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    ModelInvocationResult,
)


_TRACE_SUBDIR = "ai_supervision"
_REQUEST_FILENAMES = {
    MODEL_1_ROLE: "model1_invocation_request.json",
    MODEL_2_ROLE: "model2_invocation_request.json",
}
_RESULT_FILENAMES = {
    MODEL_1_ROLE: "model1_review_result.json",
    MODEL_2_ROLE: "model2_verification_result.json",
}


@dataclass(frozen=True)
class DualModelInvocationTraceRecord:
    run_id: str
    supervision_context: str
    model_role: str
    provider: str
    fallback_used: bool
    request_id: str
    invocation_id: str
    timestamp: str
    evidence_summary: dict[str, Any]
    purpose: str
    structured_output: dict[str, Any]
    validation_status: str
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    artifact_refs: dict[str, str]
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2DualModelInvocationAuditStore:
    def persist_trace(self, *, request: ModelInvocationRequest, result: ModelInvocationResult) -> dict[str, str]:
        trace_root = self._resolve_trace_root(request.trace_root)
        invocation_dir = trace_root / _TRACE_SUBDIR / result.invocation_id
        invocation_dir.mkdir(parents=True, exist_ok=True)

        request_path = invocation_dir / _REQUEST_FILENAMES[request.role]
        result_path = invocation_dir / _RESULT_FILENAMES[request.role]
        combined_path = invocation_dir / "dual_model_invocation_trace.json"

        request_payload = self._request_payload(request=request, result=result)
        trace = self._trace_record(request=request, result=result, invocation_dir=invocation_dir)
        result_payload = trace.to_dict()

        request_path.write_text(json.dumps(request_payload, indent=2, sort_keys=True), encoding="utf-8")
        result_path.write_text(json.dumps(result_payload, indent=2, sort_keys=True), encoding="utf-8")
        combined_path.write_text(json.dumps(result_payload, indent=2, sort_keys=True), encoding="utf-8")
        return trace.artifact_refs

    def list_traces(self, *, trace_root: str | Path) -> tuple[DualModelInvocationTraceRecord, ...]:
        base = self._resolve_trace_root(trace_root) / _TRACE_SUBDIR
        if not base.is_dir():
            return ()
        records: list[DualModelInvocationTraceRecord] = []
        for combined in sorted(base.glob("*/dual_model_invocation_trace.json")):
            try:
                payload = json.loads(combined.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            records.append(self._record_from_dict(payload))
        records.sort(key=lambda record: record.timestamp, reverse=True)
        return tuple(records)

    def latest_trace(self, *, trace_root: str | Path, model_role: str | None = None) -> DualModelInvocationTraceRecord | None:
        traces = self.list_traces(trace_root=trace_root)
        for trace in traces:
            if model_role is None or trace.model_role == model_role:
                return trace
        return None

    def _trace_record(
        self,
        *,
        request: ModelInvocationRequest,
        result: ModelInvocationResult,
        invocation_dir: Path,
    ) -> DualModelInvocationTraceRecord:
        run_id = str(request.evidence_bundle.get("run_id") or "unknown-run")
        artifact_refs = {
            "request": self._relative_path(invocation_dir / _REQUEST_FILENAMES[request.role], invocation_dir.parent.parent),
            "result": self._relative_path(invocation_dir / _RESULT_FILENAMES[request.role], invocation_dir.parent.parent),
            "combined": self._relative_path(invocation_dir / "dual_model_invocation_trace.json", invocation_dir.parent.parent),
        }
        return DualModelInvocationTraceRecord(
            run_id=run_id,
            supervision_context=request.supervision_context or request.objective,
            model_role=request.role,
            provider=result.provider,
            fallback_used=result.mode == "fallback",
            request_id=request.correlation_id or result.invocation_id,
            invocation_id=result.invocation_id,
            timestamp=result.created_at,
            evidence_summary=self._compact_evidence_summary(request.evidence_bundle),
            purpose=request.objective,
            structured_output=result.structured_output,
            validation_status="validated",
            errors=result.errors,
            warnings=result.warnings,
            artifact_refs=artifact_refs,
            read_only=True,
        )

    def _request_payload(self, *, request: ModelInvocationRequest, result: ModelInvocationResult) -> dict[str, Any]:
        return {
            "run_id": str(request.evidence_bundle.get("run_id") or "unknown-run"),
            "supervision_context": request.supervision_context or request.objective,
            "model_role": request.role,
            "provider": result.provider,
            "fallback_used": result.mode == "fallback",
            "request_id": request.correlation_id or result.invocation_id,
            "invocation_id": result.invocation_id,
            "timestamp": result.created_at,
            "purpose": request.objective,
            "source_input": redact_model_summary(request.source_input),
            "model1_output": request.model1_output or {},
            "evidence_summary": self._compact_evidence_summary(request.evidence_bundle),
            "read_only": True,
        }

    def _compact_evidence_summary(self, evidence_bundle: dict[str, Any]) -> dict[str, Any]:
        latest = evidence_bundle.get("latest_trustworthy_migration_event") or {}
        artifact_labels = []
        for item in evidence_bundle.get("generated_artifact_refs") or []:
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("path") or "").strip()
                if label:
                    artifact_labels.append(label)
        failure_bundle = evidence_bundle.get("failure_bundle") or {}
        return {
            "run_id": str(evidence_bundle.get("run_id") or ""),
            "migration_status": str(evidence_bundle.get("migration_status") or ""),
            "ai_supervision_status": str(evidence_bundle.get("ai_supervision_status") or ""),
            "approval_state": str(evidence_bundle.get("approval_state") or ""),
            "final_status": str(evidence_bundle.get("final_status") or ""),
            "build_status": str(evidence_bundle.get("build_status") or ""),
            "test_status": str(evidence_bundle.get("test_status") or ""),
            "final_proof_level": str(evidence_bundle.get("final_proof_level") or ""),
            "next_operator_action": str(evidence_bundle.get("next_operator_action") or ""),
            "latest_event_type": str(latest.get("type") or ""),
            "latest_event_status": str(latest.get("status") or ""),
            "failure_type": str(failure_bundle.get("failure_type") or ""),
            "root_cause": str(failure_bundle.get("root_cause") or ""),
            "artifact_labels": artifact_labels[:10],
        }

    def _record_from_dict(self, payload: dict[str, Any]) -> DualModelInvocationTraceRecord:
        return DualModelInvocationTraceRecord(
            run_id=str(payload.get("run_id") or ""),
            supervision_context=str(payload.get("supervision_context") or ""),
            model_role=str(payload.get("model_role") or ""),
            provider=str(payload.get("provider") or ""),
            fallback_used=bool(payload.get("fallback_used")),
            request_id=str(payload.get("request_id") or ""),
            invocation_id=str(payload.get("invocation_id") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            evidence_summary=payload.get("evidence_summary") if isinstance(payload.get("evidence_summary"), dict) else {},
            purpose=str(payload.get("purpose") or ""),
            structured_output=payload.get("structured_output") if isinstance(payload.get("structured_output"), dict) else {},
            validation_status=str(payload.get("validation_status") or ""),
            errors=tuple(str(item) for item in payload.get("errors") or []),
            warnings=tuple(str(item) for item in payload.get("warnings") or []),
            artifact_refs={str(key): str(value) for key, value in (payload.get("artifact_refs") or {}).items()},
            read_only=bool(payload.get("read_only", True)),
        )

    def _resolve_trace_root(self, raw_path: str | Path) -> Path:
        root = Path(str(raw_path or "").strip()).resolve()
        if not str(root):
            raise ValueError("trace_root is required for invocation audit persistence.")
        return root

    def _relative_path(self, path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.name
