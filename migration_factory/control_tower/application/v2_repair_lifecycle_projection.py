from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary


_SECRET_VALUE_RE = re.compile(
    r'(?i)"[^"]*(password|secret|token|api[_-]?key)[^"]*"\s*:\s*"[^"]+"|'
    r"\b(?:password|secret|token|api[_-]?key|access[_-]?key|authorization)\s*[:=]\s*[^\s,;]+|"
    r"bearer\s+[A-Za-z0-9._\-]{8,}"
)
_REPAIR_STATUS_QUESTION_RE = re.compile(
    r"(?i)\b(what is the repair status|repair status|did you apply it|was it validated|did rollback happen|est-ce que la correction a été appliquée|rollback|validated)\b"
)


class V2RepairLifecycleProjectionService:
    @staticmethod
    def is_repair_status_question(text: str) -> bool:
        return bool(_REPAIR_STATUS_QUESTION_RE.search(str(text or "")))

    def list_projections(
        self,
        *,
        job_id: str,
        trace_root: Path | None,
    ) -> list[dict[str, Any]]:
        if trace_root is None:
            return []
        proposal_root = trace_root / "ai_supervision" / "repair_proposals"
        if not proposal_root.is_dir():
            return []
        projections: list[dict[str, Any]] = []
        for proposal_dir in sorted((path for path in proposal_root.iterdir() if path.is_dir()), key=lambda item: item.name):
            projection = self._build_projection(job_id=job_id, trace_root=trace_root, proposal_dir=proposal_dir)
            if projection:
                projections.append(projection)
        return projections

    def get_projection(
        self,
        *,
        job_id: str,
        trace_root: Path | None,
        proposal_id: str,
    ) -> dict[str, Any] | None:
        if trace_root is None:
            return None
        proposal_dir = trace_root / "ai_supervision" / "repair_proposals" / proposal_id
        if not proposal_dir.is_dir():
            return None
        return self._build_projection(job_id=job_id, trace_root=trace_root, proposal_dir=proposal_dir)

    def render_answer(
        self,
        *,
        question: str,
        projections: list[dict[str, Any]],
    ) -> str:
        if not projections:
            return self._bounded(
                (
                    f"Question: {self._bounded(question, 160)}\n"
                    "Repair lifecycle status: no governed repair proposal exists yet.\n"
                    "Next operator action: no action required.\n"
                    "Safety: Read-only status only. No patch applied. No validation run. No stage resumed."
                ),
                1800,
            )
        latest = projections[-1]
        artifact_refs = ", ".join(str(item) for item in latest.get("artifact_refs", {}).values()) or "none"
        answer = (
            f"Question: {self._bounded(question, 160)}\n"
            f"Repair proposal: {latest.get('proposal_id') or 'unknown'}\n"
            f"Current state: {latest.get('current_state') or 'unknown'}\n"
            f"Approval state: {latest.get('approval_state') or 'unknown'}\n"
            f"Sandbox apply state: {latest.get('sandbox_apply_state') or 'not_started'}\n"
            f"Sandbox validation state: {latest.get('sandbox_validation_state') or 'not_started'}\n"
            f"Rollback performed: {latest.get('rollback_performed')}\n"
            f"Model 2 verdict: {latest.get('model2_verdict') or 'unknown'}\n"
            f"Risk level: {latest.get('risk_level') or 'unknown'}\n"
            f"Next operator action: {latest.get('next_operator_action') or 'human review required'}\n"
            f"Artifacts: {self._bounded(artifact_refs, 320)}\n"
            "Safety: Read-only status only. No patch applied by this answer. No validation run. No stage resumed. No source or sandbox files modified."
        )
        return self._bounded(answer, 2200)

    def _build_projection(
        self,
        *,
        job_id: str,
        trace_root: Path,
        proposal_dir: Path,
    ) -> dict[str, Any]:
        proposal_payload = self._read_json_if_exists(proposal_dir / "repair_proposal.json")
        if proposal_payload is None:
            return {}
        verification_payload = self._read_json_if_exists(proposal_dir / "repair_verification.json") or {}
        approval_state = self._read_json_if_exists(proposal_dir / "approval_state.json") or {}
        execution_plan = self._read_json_if_exists(proposal_dir / "repair_execution_plan.json")
        patch_candidate = self._read_json_if_exists(proposal_dir / "repair_patch_candidate.json")
        apply_result = self._read_json_if_exists(proposal_dir / "sandbox_apply_result.json")
        validation_result = self._read_json_if_exists(proposal_dir / "sandbox_validation_result.json")
        model1 = proposal_payload.get("model1_result") if isinstance(proposal_payload.get("model1_result"), dict) else {}
        model2 = proposal_payload.get("model2_result") if isinstance(proposal_payload.get("model2_result"), dict) else {}
        if not model2 and isinstance(verification_payload.get("verification"), dict):
            model2 = verification_payload["verification"]
        current_state = self._current_state(
            approval_state=approval_state,
            execution_plan=execution_plan,
            patch_candidate=patch_candidate,
            apply_result=apply_result,
            validation_result=validation_result,
        )
        projection = {
            "job_id": job_id,
            "run_id": str(proposal_payload.get("run_id") or ""),
            "proposal_id": str(proposal_payload.get("proposal_id") or proposal_dir.name),
            "failure_type": str(proposal_payload.get("failure_type") or model1.get("failure_type") or ""),
            "root_cause": self._bounded(str(proposal_payload.get("root_cause") or model1.get("root_cause") or ""), 280),
            "current_state": current_state,
            "approval_state": str(approval_state.get("state") or "pending_approval"),
            "approval_checksum": str(approval_state.get("checksum") or ""),
            "has_execution_plan": execution_plan is not None,
            "has_patch_candidate": patch_candidate is not None,
            "sandbox_apply_state": self._sandbox_apply_state(apply_result=apply_result),
            "sandbox_validation_state": self._sandbox_validation_state(validation_result=validation_result),
            "rollback_performed": bool((validation_result or {}).get("rollback_performed")),
            "source_mutated": False,
            "sandbox_only": bool((apply_result or {}).get("sandbox_only", True)),
            "stage_resumed": False,
            "next_operator_action": self._next_operator_action(
                current_state=current_state,
                approval_state=str(approval_state.get("state") or "pending_approval"),
                model2_verdict=str(model2.get("verdict") or ""),
            ),
            "risk_level": str(model1.get("risk_level") or model2.get("risk_level") or "unknown"),
            "model2_verdict": str(model2.get("verdict") or "unknown"),
            "artifact_refs": self._artifact_refs(trace_root=trace_root, proposal_dir=proposal_dir),
            "read_only": True,
        }
        return projection

    def _current_state(
        self,
        *,
        approval_state: dict[str, Any],
        execution_plan: dict[str, Any] | None,
        patch_candidate: dict[str, Any] | None,
        apply_result: dict[str, Any] | None,
        validation_result: dict[str, Any] | None,
    ) -> str:
        approval = str(approval_state.get("state") or "pending_approval")
        if approval == "rejected":
            return "rejected"
        if validation_result is not None:
            status = str(validation_result.get("status") or "")
            if status == "passed":
                return "validation_passed"
            if status == "rolled_back":
                return "validation_failed_rolled_back"
            if status == "failed" and str(validation_result.get("rollback_error") or "").strip():
                return "validation_failed_rollback_error"
        if apply_result is not None and bool(apply_result.get("applied")):
            return "applied_to_sandbox"
        if patch_candidate is not None:
            return "patch_candidate_ready"
        if execution_plan is not None:
            return "execution_plan_ready"
        if approval == "approved":
            return "approved"
        if approval == "pending_approval":
            return "pending_approval"
        if approval_state:
            return "proposal_created"
        return "proposal_created"

    @staticmethod
    def _sandbox_apply_state(*, apply_result: dict[str, Any] | None) -> str:
        if apply_result is None:
            return "not_started"
        return "applied" if bool(apply_result.get("applied")) else "not_started"

    @staticmethod
    def _sandbox_validation_state(*, validation_result: dict[str, Any] | None) -> str:
        if validation_result is None:
            return "not_started"
        return str(validation_result.get("status") or "unknown")

    def _next_operator_action(
        self,
        *,
        current_state: str,
        approval_state: str,
        model2_verdict: str,
    ) -> str:
        if approval_state == "rejected":
            return "human review required"
        if model2_verdict in {"rejected", "needs_human_review"} and current_state in {"proposal_created", "pending_approval"}:
            return "human review required"
        mapping = {
            "proposal_created": "approve repair proposal",
            "pending_approval": "approve repair proposal",
            "approved": "materialize execution plan",
            "execution_plan_ready": "materialize patch candidate",
            "patch_candidate_ready": "apply patch to sandbox",
            "applied_to_sandbox": "validate sandbox repair",
            "validation_passed": "no action required",
            "validation_failed_rolled_back": "inspect rollback",
            "validation_failed_rollback_error": "inspect rollback",
            "rejected": "human review required",
            "unknown": "human review required",
        }
        return mapping.get(current_state, "human review required")

    def _artifact_refs(self, *, trace_root: Path, proposal_dir: Path) -> dict[str, str]:
        refs: dict[str, str] = {}
        for name in (
            "repair_proposal.json",
            "repair_verification.json",
            "approval_state.json",
            "repair_execution_plan.json",
            "repair_patch_candidate.json",
            "sandbox_apply_result.json",
            "sandbox_validation_result.json",
            "repair_proposal.md",
            "backups/pom.xml.before-repair",
        ):
            path = proposal_dir / Path(name)
            if path.is_file():
                refs[name.replace("/", "_").replace(".", "_")] = self._relative_path(path, trace_root)
        return refs

    @staticmethod
    def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _relative_path(path: Path, trace_root: Path) -> str:
        try:
            return str(path.resolve().relative_to(trace_root.resolve())).replace("\\", "/")
        except ValueError:
            return path.name

    def _bounded(self, text: str, limit: int) -> str:
        clean = _SECRET_VALUE_RE.sub("[REDACTED]", str(text or ""))
        clean = redact_model_summary(clean).strip()
        if len(clean) <= limit:
            return clean
        return clean[:limit] + "...[truncated]"
