from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_failure_diagnosis_repository import (
    SqliteV2FailureDiagnosisRepository,
    V2FailureDiagnosisPersistedRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2PatchCandidateRecord,
    V2RepairProposalApprovalDecisionRecord,
    V2RepairProposalRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
    SqliteV2ReviewerRepository,
    V2ReviewerCritiqueRecord,
)


_MAX_DIFF_PREVIEW_CHARS = 900
_SECRET_VALUE_RE = re.compile(
    r'(?i)"[^"]*(password|secret|token|api[_-]?key)[^"]*"\s*:\s*"[^"]+"|'
    r"\b(?:password|secret|token|api[_-]?key|access[_-]?key|authorization)\s*[:=]\s*[^\s,;]+|"
    r"bearer\s+[A-Za-z0-9._\-]{8,}"
)
_WINDOWS_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
_POSIX_ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.-])/(?:[^/\s\"']+/)*[^/\s\"']+")


class V2GovernedRepairStatusService:
    def __init__(
        self,
        *,
        diagnosis_repo: SqliteV2FailureDiagnosisRepository,
        repair_repo: SqliteV2RepairRepository,
        reviewer_repo: SqliteV2ReviewerRepository,
        command_repo: SqliteV2CommandRepository,
    ) -> None:
        self._diagnosis_repo = diagnosis_repo
        self._repair_repo = repair_repo
        self._reviewer_repo = reviewer_repo
        self._command_repo = command_repo

    def get_status(
        self,
        *,
        job_id: str,
        stage_index: int | None = None,
        diagnosis_id: str | None = None,
        proposal_id: str | None = None,
        patch_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        diagnosis, proposal, review, approval, patch_candidate, command = self._resolve_workflow_records(
            job_id=job_id,
            stage_index=stage_index,
            diagnosis_id=diagnosis_id,
            proposal_id=proposal_id,
            patch_candidate_id=patch_candidate_id,
        )
        resolved_stage = (
            stage_index
            if stage_index is not None
            else (diagnosis.stage_index if diagnosis is not None else (command.stage_index if command is not None else None))
        )
        approval_status = self._approval_status(approval=approval, proposal=proposal)
        projection = {
            "job_id": job_id,
            "stage_index": resolved_stage,
            "diagnosis": self._diagnosis_projection(diagnosis),
            "proposal": self._proposal_projection(proposal),
            "review": self._review_projection(review),
            "approval": self._approval_projection(approval, proposal=proposal, status=approval_status),
            "patch_candidate": self._patch_candidate_projection(patch_candidate),
            "apply": self._apply_projection(patch_candidate),
            "next_action": self._infer_next_action(
                diagnosis=diagnosis,
                proposal=proposal,
                review=review,
                approval_status=approval_status,
                patch_candidate=patch_candidate,
            ),
            "safety": {
                "legacy_mutated": False,
                "sandbox_only": bool(patch_candidate is not None or proposal is not None),
                "frontend_patch_content_allowed": False,
                "commands_from_frontend_allowed": False,
            },
        }
        return projection

    def _resolve_workflow_records(
        self,
        *,
        job_id: str,
        stage_index: int | None,
        diagnosis_id: str | None,
        proposal_id: str | None,
        patch_candidate_id: str | None,
    ) -> tuple[
        V2FailureDiagnosisPersistedRecord | None,
        V2RepairProposalRecord | None,
        V2ReviewerCritiqueRecord | None,
        V2RepairProposalApprovalDecisionRecord | None,
        V2PatchCandidateRecord | None,
        V2StageCommandRecord | None,
    ]:
        patch_candidate = self._repair_repo.get_patch_candidate(patch_candidate_id) if patch_candidate_id else None
        proposal = None
        if patch_candidate is not None:
            proposal = self._repair_repo.get_proposal(patch_candidate.proposal_id)
        if proposal is None and proposal_id:
            proposal = self._repair_repo.get_proposal(proposal_id)
        diagnosis = None
        if diagnosis_id:
            diagnosis = self._diagnosis_repo.get_by_id(diagnosis_id)
        if diagnosis is None and patch_candidate is not None and patch_candidate.diagnosis_id:
            diagnosis = self._diagnosis_repo.get_by_id(patch_candidate.diagnosis_id)
        if diagnosis is None and proposal is not None and proposal.diagnosis_id:
            diagnosis = self._diagnosis_repo.get_by_id(proposal.diagnosis_id)
        command = None
        if proposal is not None:
            command = self._command_repo.get(proposal.command_id)
        elif diagnosis is not None:
            command = self._command_repo.get(diagnosis.command_id)

        if diagnosis is None and job_id:
            diagnosis = self._diagnosis_repo.get_latest_for_job(job_id, stage_index=stage_index)
        if proposal is None and diagnosis is not None:
            proposals = self._repair_repo.list_proposals_by_diagnosis(diagnosis.diagnosis_id)
            proposal = proposals[0] if proposals else None
        if proposal is not None and command is None:
            command = self._command_repo.get(proposal.command_id)
        if patch_candidate is None and proposal is not None:
            patch_candidate = self._repair_repo.get_latest_patch_candidate(proposal.proposal_id)

        review = (
            self._reviewer_repo.list_critiques_by_proposal(proposal.proposal_id)[0]
            if proposal is not None and self._reviewer_repo.list_critiques_by_proposal(proposal.proposal_id)
            else None
        )
        approval = (
            self._repair_repo.get_latest_approval_decision(proposal.proposal_id)
            if proposal is not None
            else None
        )

        self._validate_job_binding(
            job_id=job_id,
            diagnosis=diagnosis,
            command=command,
        )
        return diagnosis, proposal, review, approval, patch_candidate, command

    @staticmethod
    def _validate_job_binding(
        *,
        job_id: str,
        diagnosis: V2FailureDiagnosisPersistedRecord | None,
        command: V2StageCommandRecord | None,
    ) -> None:
        if diagnosis is not None and diagnosis.job_id != job_id:
            raise ValueError(f"Diagnosis {diagnosis.diagnosis_id!r} does not belong to job {job_id!r}")
        if command is not None and command.job_id != job_id:
            raise ValueError(f"Command {command.command_id!r} does not belong to job {job_id!r}")

    def _diagnosis_projection(self, diagnosis: V2FailureDiagnosisPersistedRecord | None) -> dict[str, Any]:
        if diagnosis is None:
            return {}
        return {
            "diagnosis_id": diagnosis.diagnosis_id,
            "failure_type": diagnosis.failure_type,
            "likely_root_cause": self._bounded_text(diagnosis.likely_root_cause, 280),
            "confidence": diagnosis.confidence,
            "diagnosis_checksum": diagnosis.diagnosis_checksum,
            "evidence_pack_checksum": diagnosis.evidence_pack_checksum,
            "created_at": diagnosis.created_at,
        }

    def _proposal_projection(self, proposal: V2RepairProposalRecord | None) -> dict[str, Any]:
        if proposal is None:
            return {}
        return {
            "proposal_id": proposal.proposal_id,
            "status": proposal.status,
            "proposal_checksum": proposal.proposal_checksum,
            "affected_paths": self._safe_json_list(proposal.affected_paths_json),
            "patch_summary": self._bounded_text(proposal.patch_summary, 240),
        }

    def _review_projection(self, review: V2ReviewerCritiqueRecord | None) -> dict[str, Any]:
        if review is None:
            return {}
        return {
            "critique_id": review.critique_id,
            "decision": review.decision,
            "reasoning": self._bounded_text(review.reasoning, 240),
            "model_role": review.model_role,
            "created_at": review.created_at,
        }

    def _approval_projection(
        self,
        approval: V2RepairProposalApprovalDecisionRecord | None,
        *,
        proposal: V2RepairProposalRecord | None,
        status: str,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "decision_id": approval.decision_id if approval is not None else None,
            "approval_checksum": approval.approval_checksum if approval is not None else None,
            "created_at": approval.created_at if approval is not None else None,
        }

    def _patch_candidate_projection(self, candidate: V2PatchCandidateRecord | None) -> dict[str, Any]:
        if candidate is None:
            return {}
        return {
            "patch_candidate_id": candidate.patch_candidate_id,
            "status": candidate.status,
            "gate_status": candidate.gate_status,
            "gate_reason": self._bounded_text(candidate.gate_reason, 220),
            "patch_candidate_checksum": candidate.patch_candidate_checksum,
            "touched_paths": [self._safe_path_name(item) for item in self._safe_json_list(candidate.touched_paths_json)],
            "unified_diff_preview": self._bounded_diff_preview(candidate.unified_diff),
        }

    def _apply_projection(self, candidate: V2PatchCandidateRecord | None) -> dict[str, Any]:
        if candidate is None:
            return {
                "status": "not_started",
                "validation_status": "not_started",
                "rollback_status": "not_started",
                "artifact_refs": {},
                "applied": False,
                "rolled_back": False,
            }
        status = "not_started"
        if candidate.status == "applied":
            status = "applied"
        elif candidate.status == "rolled_back":
            status = "rolled_back"
        elif candidate.status == "apply_failed":
            status = "apply_failed"
        elif candidate.status == "gate_blocked_at_apply":
            status = "blocked"
        return {
            "status": status,
            "validation_status": candidate.validation_status or ("not_started" if status == "not_started" else "unknown"),
            "rollback_status": candidate.rollback_status or ("not_started" if status == "not_started" else "unknown"),
            "artifact_refs": self._safe_artifact_refs(candidate.artifact_refs_json),
            "applied": candidate.status == "applied",
            "rolled_back": candidate.status == "rolled_back",
        }

    def _approval_status(
        self,
        *,
        approval: V2RepairProposalApprovalDecisionRecord | None,
        proposal: V2RepairProposalRecord | None,
    ) -> str:
        if approval is None:
            return "none"
        if proposal is not None:
            if (
                approval.approval_checksum != proposal.proposal_checksum
                or approval.proposal_checksum != proposal.proposal_checksum
                or approval.context_pack_checksum != (proposal.context_pack_checksum or "")
            ):
                return "stale"
        if approval.operator_decision == "approve":
            return "approved"
        if approval.operator_decision == "reject":
            return "rejected"
        return "none"

    def _infer_next_action(
        self,
        *,
        diagnosis: V2FailureDiagnosisPersistedRecord | None,
        proposal: V2RepairProposalRecord | None,
        review: V2ReviewerCritiqueRecord | None,
        approval_status: str,
        patch_candidate: V2PatchCandidateRecord | None,
    ) -> str:
        if diagnosis is None:
            return "run_diagnosis"
        if proposal is None:
            return "create_proposal"
        if review is None:
            return "review_proposal"
        if review.decision in {"revise", "reject"}:
            return "blocked"
        if approval_status in {"rejected", "stale"}:
            return "blocked"
        if approval_status != "approved":
            return "human_approval_required"
        if patch_candidate is None:
            return "create_patch_candidate"
        if patch_candidate.status == "gate_allowed":
            return "apply_patch_candidate"
        if patch_candidate.status == "applied":
            return "resolved"
        if patch_candidate.status in {"rolled_back", "apply_failed"}:
            return "inspect_validation_result"
        if patch_candidate.status in {"gate_blocked", "gate_blocked_at_apply", "unsupported_materialization"}:
            return "blocked"
        return "blocked"

    def _safe_artifact_refs(self, raw_json: str) -> dict[str, str]:
        try:
            payload = json.loads(raw_json or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): self._safe_path_name(str(value))
            for key, value in payload.items()
            if str(value or "").strip()
        }

    def _safe_json_list(self, raw_json: str) -> list[str]:
        try:
            payload = json.loads(raw_json or "[]")
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(payload, list):
            return []
        return [str(item) for item in payload if str(item or "").strip()]

    def _bounded_diff_preview(self, text: str) -> str:
        return self._bounded_text(text, _MAX_DIFF_PREVIEW_CHARS)

    def _bounded_text(self, text: str, limit: int) -> str:
        sanitized = self._sanitize_text(text)
        if len(sanitized) <= limit:
            return sanitized
        return sanitized[:limit] + "...[truncated]"

    def _sanitize_text(self, text: str) -> str:
        value = _SECRET_VALUE_RE.sub("[REDACTED]", str(text or ""))
        value = _WINDOWS_ABS_PATH_RE.sub(lambda m: self._safe_path_name(m.group(0)), value)
        value = _POSIX_ABS_PATH_RE.sub(lambda m: self._safe_path_name(m.group(0)), value)
        return redact_model_summary(value).strip()

    def _safe_path_name(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace("\\", "/").rstrip("/")
        return Path(normalized).name or normalized
