from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    ModelInvocationResult,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.application.v2_failure_evidence import infer_stage_run_root
from migration_factory.control_tower.application.v2_run_evidence_bundle import V2RunEvidenceBundleService


UnitOfWorkFactory = Callable[[], Any]
_MAX_SUMMARY = 320


@dataclass(frozen=True)
class PlanningDualModelReviewResult:
    model1_result: ModelInvocationResult
    model2_result: ModelInvocationResult
    approval_summary: str
    artifact_refs: dict[str, str]
    supervision_payload: dict[str, Any]
    read_only: bool = True


class V2PlanningDualModelReviewService:
    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        runtime_service: V2DualModelRuntimeService,
        evidence_bundle_service: V2RunEvidenceBundleService | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._runtime_service = runtime_service
        self._evidence_bundle_service = evidence_bundle_service or V2RunEvidenceBundleService()

    def review_planning_for_approval(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        result: dict[str, Any],
    ) -> PlanningDualModelReviewResult:
        with self._unit_of_work_factory() as uow:
            job = uow.v2_jobs.get(job_id)
            setup = uow.v2_setups.get(job.setup_id) if job is not None and job.setup_id else None
            events = uow.v2_events.list_by_job(job_id)
            approvals = uow.v2_approvals.list_cards_by_job(job_id)
            commands = uow.v2_commands.list_by_job(job_id)
        bundle = self._evidence_bundle_service.build_bundle(
            job_id=job_id,
            setup=setup,
            events=events,
            approvals=approvals,
            commands=commands,
        )
        trace_root = self._trace_root(setup=setup, bundle=bundle.to_dict(), result=result)
        source_input = self._planning_context(result=result, bundle=bundle.to_dict(), stage_index=stage_index)

        model1 = self._runtime_service.invoke_model_1(
            ModelInvocationRequest(
                role=MODEL_1_ROLE,
                objective="Review deterministic migration planning before human approval.",
                evidence_bundle=bundle.to_dict(),
                source_input=source_input,
                correlation_id=f"{command_id}:planning:model1",
                supervision_context="planning_review",
                trace_root=str(trace_root) if trace_root is not None else "",
            )
        )
        model2 = self._runtime_service.invoke_model_2(
            ModelInvocationRequest(
                role=MODEL_2_ROLE,
                objective="Verify deterministic migration planning review before human approval.",
                evidence_bundle=bundle.to_dict(),
                source_input=source_input,
                model1_output=model1.structured_output,
                correlation_id=f"{command_id}:planning:model2",
                supervision_context="planning_verification",
                trace_root=str(trace_root) if trace_root is not None else "",
            )
        )

        artifact_refs = self._artifact_refs(trace_root=trace_root, model1=model1, model2=model2)
        supervision_payload = {
            "purpose": "planning_review",
            "model1": model1.to_dict(),
            "model2": model2.to_dict(),
            "artifact_refs": artifact_refs,
            "read_only": True,
        }
        return PlanningDualModelReviewResult(
            model1_result=model1,
            model2_result=model2,
            approval_summary=self._approval_summary(model1=model1, model2=model2),
            artifact_refs=artifact_refs,
            supervision_payload=supervision_payload,
            read_only=True,
        )

    def _trace_root(
        self,
        *,
        setup: Any,
        bundle: dict[str, Any],
        result: dict[str, Any],
    ) -> Path | None:
        refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}
        candidates = [result.get("sandbox_path"), result.get("modernized_app_path"), *refs.values()]
        for raw in candidates:
            if not raw:
                continue
            inferred = infer_stage_run_root(raw)
            if inferred is not None:
                return inferred
        output_parent = str(getattr(setup, "output_parent_path", "") or "").strip()
        run_id = str(bundle.get("run_id") or result.get("run_id") or "").strip()
        if output_parent and run_id:
            return Path(output_parent) / ".migration" / "runs" / run_id
        return None

    def _planning_context(self, *, result: dict[str, Any], bundle: dict[str, Any], stage_index: int) -> str:
        refs = result.get("artifact_refs") if isinstance(result.get("artifact_refs"), dict) else {}
        context = {
            "supervision_purpose": "planning_review",
            "stage_index": stage_index,
            "migration_plan_summary": result.get("summary") or result.get("plan_summary") or result.get("message") or "",
            "planning_status": result.get("planning_status") or result.get("status") or "",
            "assessment_status": result.get("assessment_status") or "",
            "generated_migration_units": result.get("generated_migration_units") or result.get("migration_units") or result.get("units") or [],
            "decision_options": result.get("decision_options") or [],
            "artifact_refs": {str(k): Path(str(v)).name for k, v in refs.items()},
            "evidence_run_id": bundle.get("run_id") or "",
        }
        return json.dumps(context, sort_keys=True, default=str)

    def _artifact_refs(
        self,
        *,
        trace_root: Path | None,
        model1: ModelInvocationResult,
        model2: ModelInvocationResult,
    ) -> dict[str, str]:
        refs: dict[str, str] = {}
        if trace_root is None:
            return refs
        model1_result = model1.trace_artifact_refs.get("result")
        model2_result = model2.trace_artifact_refs.get("result")
        if model1_result:
            refs["planning_model1_review"] = str((trace_root / model1_result).resolve())
        if model2_result:
            refs["planning_model2_verification"] = str((trace_root / model2_result).resolve())
        return refs

    def _approval_summary(
        self,
        *,
        model1: ModelInvocationResult,
        model2: ModelInvocationResult,
    ) -> str:
        model1_out = model1.structured_output if isinstance(model1.structured_output, dict) else {}
        model2_out = model2.structured_output if isinstance(model2.structured_output, dict) else {}
        issues = model2_out.get("issues_found") or []
        issue_text = "; ".join(str(item) for item in issues[:3]) if issues else "none"
        lines = [
            "Human approval required before sandbox transform.",
            f"Planning review risk: {model1_out.get('risk_level') or model2_out.get('risk_level') or 'unknown'}.",
            f"Model 1 summary: {self._short(model1_out.get('summary') or model1_out.get('root_cause') or 'No summary.')}",
            f"Model 2 verdict: {model2_out.get('verdict') or 'unknown'}.",
            f"Issues found: {self._short(issue_text)}.",
            "Exact checksum approval still required.",
        ]
        return "\n".join(lines)

    def _short(self, value: Any) -> str:
        text = redact_model_summary(str(value or "")).strip()
        if len(text) <= _MAX_SUMMARY:
            return text
        return text[:_MAX_SUMMARY] + "...[truncated]"
