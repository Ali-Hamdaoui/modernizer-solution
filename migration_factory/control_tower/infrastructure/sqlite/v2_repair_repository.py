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
    proposal_checksum: str | None = None
    source_proposal_id: str | None = None
    revision_of: str | None = None
    revision_number: int | None = None
    context_pack_checksum: str | None = None
    allowed_scope: str | None = None
    # PR-B: reviewed-diff and job-scoped fields (all nullable)
    job_id: str | None = None
    route_step_index: int | None = None
    attempt_number: int | None = None
    failure_evidence_ref: str | None = None
    repair_context_ref: str | None = None
    diagnosis_ref: str | None = None
    repair_plan_ref: str | None = None
    diff_ref: str | None = None
    diff_checksum: str | None = None
    safe_diff_preview_ref: str | None = None
    reviewer_verdict_id: str | None = None
    reviewer_verdict_ref: str | None = None
    reviewer_output_checksum: str | None = None
    policy_validation_checksum: str | None = None
    gate_id: str | None = None
    status_reason: str | None = None
    # PR-F: retry/attempt history fields (all nullable)
    apply_status: str | None = None
    rerun_status: str | None = None
    rollback_status: str | None = None
    validation_result_ref: str | None = None
    next_gate_id: str | None = None
    next_gate_status: str | None = None
    remaining_attempts: int | None = None
    completed_at: str | None = None
    reviewer_decision: str | None = None


@dataclass(frozen=True)
class V2SandboxActionRecord:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str
    result_summary: str
    created_at: str


class SqliteV2RepairRepository:
    """Repository for V2 repair proposals and sandbox actions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_proposal(self, record: V2RepairProposalRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_repair_proposals (
                proposal_id, command_id, failure_summary, hypothesis,
                patch_summary, affected_paths_json, status,
                approval_checksum, created_at, proposal_checksum, source_proposal_id,
                revision_of, revision_number, context_pack_checksum,
                allowed_scope,
                job_id, route_step_index, attempt_number,
                failure_evidence_ref, repair_context_ref, diagnosis_ref,
                repair_plan_ref, diff_ref, diff_checksum,
                safe_diff_preview_ref, reviewer_verdict_id,
                reviewer_verdict_ref, reviewer_output_checksum,
                policy_validation_checksum, gate_id, status_reason,
                apply_status, rerun_status, rollback_status,
                validation_result_ref, next_gate_id, next_gate_status,
                remaining_attempts, completed_at, reviewer_decision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                record.proposal_checksum,
                record.source_proposal_id,
                record.revision_of,
                record.revision_number,
                record.context_pack_checksum,
                record.allowed_scope,
                record.job_id,
                record.route_step_index,
                record.attempt_number,
                record.failure_evidence_ref,
                record.repair_context_ref,
                record.diagnosis_ref,
                record.repair_plan_ref,
                record.diff_ref,
                record.diff_checksum,
                record.safe_diff_preview_ref,
                record.reviewer_verdict_id,
                record.reviewer_verdict_ref,
                record.reviewer_output_checksum,
                record.policy_validation_checksum,
                record.gate_id,
                record.status_reason,
                record.apply_status,
                record.rerun_status,
                record.rollback_status,
                record.validation_result_ref,
                record.next_gate_id,
                record.next_gate_status,
                record.remaining_attempts,
                record.completed_at,
                record.reviewer_decision,
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

    def update_proposal_status_with_reason(self, proposal_id: str, status: str, status_reason: str) -> None:
        """Update proposal status and reason."""
        self._connection.execute(
            "UPDATE v2_repair_proposals SET status = ?, status_reason = ? WHERE proposal_id = ?",
            (status, status_reason, proposal_id),
        )

    def update_proposal_prf_fields(self, proposal_id: str, **fields) -> None:
        """Update PR-F retry/attempt history fields for a proposal.

        Accepts keyword args matching column names:
        apply_status, rerun_status, rollback_status, validation_result_ref,
        next_gate_id, next_gate_status, remaining_attempts, completed_at,
        reviewer_decision, status, status_reason
        """
        allowed = frozenset({
            "apply_status", "rerun_status", "rollback_status",
            "validation_result_ref", "next_gate_id", "next_gate_status",
            "remaining_attempts", "completed_at", "reviewer_decision",
            "status", "status_reason",
        })
        bad = [k for k in fields if k not in allowed]
        if bad:
            raise ValueError(f"Unknown PR-F fields: {bad}")
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = tuple(fields[k] for k in fields) + (proposal_id,)
        self._connection.execute(
            f"UPDATE v2_repair_proposals SET {set_clause} WHERE proposal_id = ?",
            values,
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

    def list_proposals_by_job(self, job_id: str) -> tuple[V2RepairProposalRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE job_id = ?
               ORDER BY created_at DESC""",
            (job_id,),
        ).fetchall()
        return tuple(self._row_to_proposal(row) for row in rows)

    def get_proposal_for_job(self, job_id: str, proposal_id: str) -> V2RepairProposalRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE proposal_id = ? AND job_id = ?""",
            (proposal_id, job_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def get_current_proposal_for_job(self, job_id: str) -> V2RepairProposalRecord | None:
        # First, try to find an actionable proposal
        row = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE job_id = ?
                 AND (status = 'user_review_required'
                      OR (gate_id IS NOT NULL AND status IN ('user_review_required', 'reviewer_accepted', 'diff_materialized')))
               ORDER BY created_at DESC
               LIMIT 1""",
            (job_id,),
        ).fetchone()
        if row is not None:
            return self._row_to_proposal(row)
        # Fallback: return the latest approve_failed proposal for the job
        row = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE job_id = ? AND status = 'approve_failed'
               ORDER BY created_at DESC
               LIMIT 1""",
            (job_id,),
        ).fetchone()
        if row is not None:
            return self._row_to_proposal(row)
        return None

    def list_attempts_by_job(self, job_id: str) -> tuple[V2RepairProposalRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_repair_proposals
               WHERE job_id = ?
                 AND attempt_number IS NOT NULL
               ORDER BY attempt_number DESC, created_at DESC""",
            (job_id,),
        ).fetchall()
        return tuple(self._row_to_proposal(row) for row in rows)

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

    def _row_to_proposal(self, row: sqlite3.Row) -> V2RepairProposalRecord:
        keys = row.keys()
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
            proposal_checksum=str(row["proposal_checksum"]) if "proposal_checksum" in keys and row["proposal_checksum"] else None,
            source_proposal_id=str(row["source_proposal_id"]) if "source_proposal_id" in keys and row["source_proposal_id"] else None,
            revision_of=str(row["revision_of"]) if "revision_of" in keys and row["revision_of"] else None,
            revision_number=int(row["revision_number"]) if "revision_number" in keys and row["revision_number"] is not None else None,
            context_pack_checksum=str(row["context_pack_checksum"]) if "context_pack_checksum" in keys and row["context_pack_checksum"] else None,
            allowed_scope=str(row["allowed_scope"]) if "allowed_scope" in keys and row["allowed_scope"] else None,
            job_id=str(row["job_id"]) if "job_id" in keys and row["job_id"] else None,
            route_step_index=int(row["route_step_index"]) if "route_step_index" in keys and row["route_step_index"] is not None else None,
            attempt_number=int(row["attempt_number"]) if "attempt_number" in keys and row["attempt_number"] is not None else None,
            failure_evidence_ref=str(row["failure_evidence_ref"]) if "failure_evidence_ref" in keys and row["failure_evidence_ref"] else None,
            repair_context_ref=str(row["repair_context_ref"]) if "repair_context_ref" in keys and row["repair_context_ref"] else None,
            diagnosis_ref=str(row["diagnosis_ref"]) if "diagnosis_ref" in keys and row["diagnosis_ref"] else None,
            repair_plan_ref=str(row["repair_plan_ref"]) if "repair_plan_ref" in keys and row["repair_plan_ref"] else None,
            diff_ref=str(row["diff_ref"]) if "diff_ref" in keys and row["diff_ref"] else None,
            diff_checksum=str(row["diff_checksum"]) if "diff_checksum" in keys and row["diff_checksum"] else None,
            safe_diff_preview_ref=str(row["safe_diff_preview_ref"]) if "safe_diff_preview_ref" in keys and row["safe_diff_preview_ref"] else None,
            reviewer_verdict_id=str(row["reviewer_verdict_id"]) if "reviewer_verdict_id" in keys and row["reviewer_verdict_id"] else None,
            reviewer_verdict_ref=str(row["reviewer_verdict_ref"]) if "reviewer_verdict_ref" in keys and row["reviewer_verdict_ref"] else None,
            reviewer_output_checksum=str(row["reviewer_output_checksum"]) if "reviewer_output_checksum" in keys and row["reviewer_output_checksum"] else None,
            policy_validation_checksum=str(row["policy_validation_checksum"]) if "policy_validation_checksum" in keys and row["policy_validation_checksum"] else None,
            gate_id=str(row["gate_id"]) if "gate_id" in keys and row["gate_id"] else None,
            status_reason=str(row["status_reason"]) if "status_reason" in keys and row["status_reason"] else None,
            apply_status=str(row["apply_status"]) if "apply_status" in keys and row["apply_status"] else None,
            rerun_status=str(row["rerun_status"]) if "rerun_status" in keys and row["rerun_status"] else None,
            rollback_status=str(row["rollback_status"]) if "rollback_status" in keys and row["rollback_status"] else None,
            validation_result_ref=str(row["validation_result_ref"]) if "validation_result_ref" in keys and row["validation_result_ref"] else None,
            next_gate_id=str(row["next_gate_id"]) if "next_gate_id" in keys and row["next_gate_id"] else None,
            next_gate_status=str(row["next_gate_status"]) if "next_gate_status" in keys and row["next_gate_status"] else None,
            remaining_attempts=int(row["remaining_attempts"]) if "remaining_attempts" in keys and row["remaining_attempts"] is not None else None,
            completed_at=str(row["completed_at"]) if "completed_at" in keys and row["completed_at"] else None,
            reviewer_decision=str(row["reviewer_decision"]) if "reviewer_decision" in keys and row["reviewer_decision"] else None,
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
