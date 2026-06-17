"""SQLite repository for V2 repair proposals and sandbox actions."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class V2RepairProposalRecord:
    proposal_id: str
    command_id: str
    failure_summary: str
    hypothesis: str
    patch_summary: str
    affected_paths_json: str
    status: str
    approval_checksum: str | None
    created_at: str
    diagnosis_id: str = ""
    diagnosis_checksum: str = ""
    evidence_pack_checksum: str = ""
    context_pack_checksum: str = ""
    proposal_checksum: str = ""
    validation_plan_text: str = ""
    proposer_model_invocation_id: str = ""
    proposer_model_role: str = ""
    proposer_model_provider: str = ""
    proposer_deployment_label: str = ""


@dataclass(frozen=True)
class V2SandboxActionRecord:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str
    result_summary: str
    created_at: str


@dataclass(frozen=True)
class V2RepairProposalApprovalDecisionRecord:
    decision_id: str
    proposal_id: str
    operator_decision: str
    approval_checksum: str
    proposal_checksum: str
    context_pack_checksum: str
    reviewer_gate_status: str
    reviewer_critique_id: str | None
    operator_note: str
    created_at: str
    correlation_id: str | None = None


@dataclass(frozen=True)
class V2PatchCandidateRecord:
    patch_candidate_id: str
    proposal_id: str
    proposal_checksum: str
    diagnosis_id: str
    diagnosis_checksum: str
    evidence_pack_checksum: str
    context_pack_checksum: str
    unified_diff: str
    patch_candidate_checksum: str
    materialization_strategy: str
    status: str
    gate_status: str
    gate_reason: str
    touched_paths_json: str
    created_at: str
    result_summary: str = ""
    validation_status: str = ""
    rollback_status: str = ""
    artifact_refs_json: str = "{}"
    applied_action_id: str = ""
    operator_note: str = ""


class SqliteV2RepairRepository:
    """Repository for V2 repair proposals and sandbox actions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_proposal(self, record: V2RepairProposalRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_repair_proposals (
                proposal_id, command_id, failure_summary, hypothesis,
                patch_summary, affected_paths_json, status,
                approval_checksum, created_at, diagnosis_id,
                diagnosis_checksum, evidence_pack_checksum,
                context_pack_checksum, proposal_checksum,
                validation_plan_text, proposer_model_invocation_id,
                proposer_model_role, proposer_model_provider,
                proposer_deployment_label
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.proposal_id,
                record.command_id,
                record.failure_summary,
                record.hypothesis,
                record.patch_summary,
                record.affected_paths_json,
                record.status,
                record.approval_checksum,
                record.created_at,
                record.diagnosis_id,
                record.diagnosis_checksum,
                record.evidence_pack_checksum,
                record.context_pack_checksum,
                record.proposal_checksum,
                record.validation_plan_text,
                record.proposer_model_invocation_id,
                record.proposer_model_role,
                record.proposer_model_provider,
                record.proposer_deployment_label,
            ),
        )

    def update_proposal_status(self, proposal_id: str, status: str, approval_checksum: str | None = None) -> None:
        """Update proposal status and optional approval checksum."""
        if approval_checksum is not None:
            self._connection.execute(
                "UPDATE v2_repair_proposals SET status = ?, approval_checksum = ? WHERE proposal_id = ?",
                (status, approval_checksum, proposal_id),
            )
        else:
            self._connection.execute(
                "UPDATE v2_repair_proposals SET status = ? WHERE proposal_id = ?",
                (status, proposal_id),
            )

    def get_proposal(self, proposal_id: str) -> V2RepairProposalRecord | None:
        row = self._connection.execute(
            "SELECT * FROM v2_repair_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def list_proposals_by_command(self, command_id: str) -> tuple[V2RepairProposalRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM v2_repair_proposals WHERE command_id = ? ORDER BY created_at DESC",
            (command_id,),
        ).fetchall()
        return tuple(self._row_to_proposal(row) for row in rows)

    def list_proposals_by_diagnosis(self, diagnosis_id: str) -> tuple[V2RepairProposalRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM v2_repair_proposals WHERE diagnosis_id = ? ORDER BY created_at DESC",
            (diagnosis_id,),
        ).fetchall()
        return tuple(self._row_to_proposal(row) for row in rows)

    def get_latest_by_command(self, command_id: str) -> V2RepairProposalRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE command_id = ?
               ORDER BY created_at DESC, proposal_id DESC
               LIMIT 1""",
            (command_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def save_action(self, record: V2SandboxActionRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_sandbox_actions (
                action_id, proposal_id, target_path, patch_content,
                status, result_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                record.action_id,
                record.proposal_id,
                record.target_path,
                record.patch_content,
                record.status,
                record.result_summary,
                record.created_at,
            ),
        )

    def get_action(self, action_id: str) -> V2SandboxActionRecord | None:
        row = self._connection.execute(
            "SELECT * FROM v2_sandbox_actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_action(row)

    def list_actions_by_proposal(self, proposal_id: str) -> tuple[V2SandboxActionRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM v2_sandbox_actions WHERE proposal_id = ? ORDER BY created_at DESC",
            (proposal_id,),
        ).fetchall()
        return tuple(self._row_to_action(row) for row in rows)

    def save_approval_decision(self, record: V2RepairProposalApprovalDecisionRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_repair_proposal_approval_decisions (
                decision_id, proposal_id, operator_decision,
                approval_checksum, proposal_checksum, context_pack_checksum,
                reviewer_gate_status, reviewer_critique_id, operator_note,
                created_at, correlation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.decision_id,
                record.proposal_id,
                record.operator_decision,
                record.approval_checksum,
                record.proposal_checksum,
                record.context_pack_checksum,
                record.reviewer_gate_status,
                record.reviewer_critique_id,
                record.operator_note,
                record.created_at,
                record.correlation_id,
            ),
        )

    def list_approval_decisions_by_proposal(
        self,
        proposal_id: str,
    ) -> tuple[V2RepairProposalApprovalDecisionRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_repair_proposal_approval_decisions
               WHERE proposal_id = ?
               ORDER BY created_at DESC, decision_id DESC""",
            (proposal_id,),
        ).fetchall()
        return tuple(self._row_to_approval_decision(row) for row in rows)

    def get_latest_approval_decision(
        self,
        proposal_id: str,
    ) -> V2RepairProposalApprovalDecisionRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_repair_proposal_approval_decisions
               WHERE proposal_id = ?
               ORDER BY created_at DESC, decision_id DESC
               LIMIT 1""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_approval_decision(row)

    def save_patch_candidate(self, record: V2PatchCandidateRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_patch_candidates (
                patch_candidate_id, proposal_id, proposal_checksum,
                diagnosis_id, diagnosis_checksum, evidence_pack_checksum,
                context_pack_checksum, unified_diff, patch_candidate_checksum,
                materialization_strategy, status, gate_status, gate_reason,
                touched_paths_json, created_at, result_summary,
                validation_status, rollback_status, artifact_refs_json,
                applied_action_id, operator_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.patch_candidate_id,
                record.proposal_id,
                record.proposal_checksum,
                record.diagnosis_id,
                record.diagnosis_checksum,
                record.evidence_pack_checksum,
                record.context_pack_checksum,
                record.unified_diff,
                record.patch_candidate_checksum,
                record.materialization_strategy,
                record.status,
                record.gate_status,
                record.gate_reason,
                record.touched_paths_json,
                record.created_at,
                record.result_summary,
                record.validation_status,
                record.rollback_status,
                record.artifact_refs_json,
                record.applied_action_id,
                record.operator_note,
            ),
        )

    def get_patch_candidate(self, patch_candidate_id: str) -> V2PatchCandidateRecord | None:
        row = self._connection.execute(
            "SELECT * FROM v2_patch_candidates WHERE patch_candidate_id = ?",
            (patch_candidate_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_patch_candidate(row)

    def list_patch_candidates_by_proposal(
        self,
        proposal_id: str,
    ) -> tuple[V2PatchCandidateRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_patch_candidates
               WHERE proposal_id = ?
               ORDER BY created_at DESC, patch_candidate_id DESC""",
            (proposal_id,),
        ).fetchall()
        return tuple(self._row_to_patch_candidate(row) for row in rows)

    def get_latest_patch_candidate(
        self,
        proposal_id: str,
    ) -> V2PatchCandidateRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_patch_candidates
               WHERE proposal_id = ?
               ORDER BY created_at DESC, patch_candidate_id DESC
               LIMIT 1""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_patch_candidate(row)

    def update_patch_candidate_apply_result(
        self,
        *,
        patch_candidate_id: str,
        status: str,
        gate_status: str,
        gate_reason: str,
        result_summary: str,
        validation_status: str,
        rollback_status: str,
        artifact_refs_json: str,
        applied_action_id: str,
        operator_note: str,
    ) -> None:
        self._connection.execute(
            """UPDATE v2_patch_candidates
               SET status = ?, gate_status = ?, gate_reason = ?,
                   result_summary = ?, validation_status = ?,
                   rollback_status = ?, artifact_refs_json = ?,
                   applied_action_id = ?, operator_note = ?
               WHERE patch_candidate_id = ?""",
            (
                status,
                gate_status,
                gate_reason,
                result_summary,
                validation_status,
                rollback_status,
                artifact_refs_json,
                applied_action_id,
                operator_note,
                patch_candidate_id,
            ),
        )

    def _row_to_proposal(self, row: sqlite3.Row) -> V2RepairProposalRecord:
        return V2RepairProposalRecord(
            proposal_id=str(row["proposal_id"]),
            command_id=str(row["command_id"]),
            failure_summary=str(row["failure_summary"]),
            hypothesis=str(row["hypothesis"]),
            patch_summary=str(row["patch_summary"]),
            affected_paths_json=str(row["affected_paths_json"]),
            status=str(row["status"]),
            approval_checksum=str(row["approval_checksum"]) if row["approval_checksum"] else None,
            created_at=str(row["created_at"]),
            diagnosis_id=str(row["diagnosis_id"]) if "diagnosis_id" in row.keys() else "",
            diagnosis_checksum=str(row["diagnosis_checksum"]) if "diagnosis_checksum" in row.keys() else "",
            evidence_pack_checksum=str(row["evidence_pack_checksum"]) if "evidence_pack_checksum" in row.keys() else "",
            context_pack_checksum=str(row["context_pack_checksum"]) if "context_pack_checksum" in row.keys() else "",
            proposal_checksum=str(row["proposal_checksum"]) if "proposal_checksum" in row.keys() else "",
            validation_plan_text=str(row["validation_plan_text"]) if "validation_plan_text" in row.keys() else "",
            proposer_model_invocation_id=str(row["proposer_model_invocation_id"]) if "proposer_model_invocation_id" in row.keys() else "",
            proposer_model_role=str(row["proposer_model_role"]) if "proposer_model_role" in row.keys() else "",
            proposer_model_provider=str(row["proposer_model_provider"]) if "proposer_model_provider" in row.keys() else "",
            proposer_deployment_label=str(row["proposer_deployment_label"]) if "proposer_deployment_label" in row.keys() else "",
        )

    def _row_to_action(self, row: sqlite3.Row) -> V2SandboxActionRecord:
        return V2SandboxActionRecord(
            action_id=str(row["action_id"]),
            proposal_id=str(row["proposal_id"]),
            target_path=str(row["target_path"]),
            patch_content=str(row["patch_content"]),
            status=str(row["status"]),
            result_summary=str(row["result_summary"]),
            created_at=str(row["created_at"]),
        )

    def _row_to_approval_decision(
        self,
        row: sqlite3.Row,
    ) -> V2RepairProposalApprovalDecisionRecord:
        return V2RepairProposalApprovalDecisionRecord(
            decision_id=str(row["decision_id"]),
            proposal_id=str(row["proposal_id"]),
            operator_decision=str(row["operator_decision"]),
            approval_checksum=str(row["approval_checksum"]),
            proposal_checksum=str(row["proposal_checksum"]),
            context_pack_checksum=str(row["context_pack_checksum"]),
            reviewer_gate_status=str(row["reviewer_gate_status"]),
            reviewer_critique_id=str(row["reviewer_critique_id"]) if row["reviewer_critique_id"] else None,
            operator_note=str(row["operator_note"]),
            created_at=str(row["created_at"]),
            correlation_id=str(row["correlation_id"]) if row["correlation_id"] else None,
        )

    def _row_to_patch_candidate(
        self,
        row: sqlite3.Row,
    ) -> V2PatchCandidateRecord:
        return V2PatchCandidateRecord(
            patch_candidate_id=str(row["patch_candidate_id"]),
            proposal_id=str(row["proposal_id"]),
            proposal_checksum=str(row["proposal_checksum"]),
            diagnosis_id=str(row["diagnosis_id"]),
            diagnosis_checksum=str(row["diagnosis_checksum"]),
            evidence_pack_checksum=str(row["evidence_pack_checksum"]),
            context_pack_checksum=str(row["context_pack_checksum"]),
            unified_diff=str(row["unified_diff"]),
            patch_candidate_checksum=str(row["patch_candidate_checksum"]),
            materialization_strategy=str(row["materialization_strategy"]),
            status=str(row["status"]),
            gate_status=str(row["gate_status"]),
            gate_reason=str(row["gate_reason"]),
            touched_paths_json=str(row["touched_paths_json"]),
            created_at=str(row["created_at"]),
            result_summary=str(row["result_summary"]) if "result_summary" in row.keys() else "",
            validation_status=str(row["validation_status"]) if "validation_status" in row.keys() else "",
            rollback_status=str(row["rollback_status"]) if "rollback_status" in row.keys() else "",
            artifact_refs_json=str(row["artifact_refs_json"]) if "artifact_refs_json" in row.keys() else "{}",
            applied_action_id=str(row["applied_action_id"]) if "applied_action_id" in row.keys() else "",
            operator_note=str(row["operator_note"]) if "operator_note" in row.keys() else "",
        )
