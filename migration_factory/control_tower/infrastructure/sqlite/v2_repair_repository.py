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


@dataclass(frozen=True)
class V2SandboxActionRecord:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str
    result_summary: str
    created_at: str
    verification_status: str = "not_available"
    verification_build_status: str = ""
    verification_test_status: str = ""
    verification_h2_status: str = ""
    verification_artifact_refs_json: str = "{}"
    verification_failure_classification_ref: str = ""


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
                allowed_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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

    def save_action(self, record: V2SandboxActionRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_sandbox_actions (
                action_id, proposal_id, target_path, patch_content,
                status, result_summary, created_at,
                verification_status, verification_build_status,
                verification_test_status, verification_h2_status,
                verification_artifact_refs_json,
                verification_failure_classification_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.action_id,
                record.proposal_id,
                record.target_path,
                record.patch_content,
                record.status,
                record.result_summary,
                record.created_at,
                record.verification_status,
                record.verification_build_status,
                record.verification_test_status,
                record.verification_h2_status,
                record.verification_artifact_refs_json,
                record.verification_failure_classification_ref,
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
            proposal_checksum=str(row["proposal_checksum"]) if "proposal_checksum" in row.keys() and row["proposal_checksum"] else None,
            source_proposal_id=str(row["source_proposal_id"]) if "source_proposal_id" in row.keys() and row["source_proposal_id"] else None,
            revision_of=str(row["revision_of"]) if "revision_of" in row.keys() and row["revision_of"] else None,
            revision_number=int(row["revision_number"]) if "revision_number" in row.keys() and row["revision_number"] is not None else None,
            context_pack_checksum=str(row["context_pack_checksum"]) if "context_pack_checksum" in row.keys() and row["context_pack_checksum"] else None,
            allowed_scope=str(row["allowed_scope"]) if "allowed_scope" in row.keys() and row["allowed_scope"] else None,
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
            verification_status=str(row["verification_status"]) if "verification_status" in row.keys() and row["verification_status"] else "not_available",
            verification_build_status=str(row["verification_build_status"]) if "verification_build_status" in row.keys() and row["verification_build_status"] else "",
            verification_test_status=str(row["verification_test_status"]) if "verification_test_status" in row.keys() and row["verification_test_status"] else "",
            verification_h2_status=str(row["verification_h2_status"]) if "verification_h2_status" in row.keys() and row["verification_h2_status"] else "",
            verification_artifact_refs_json=str(row["verification_artifact_refs_json"]) if "verification_artifact_refs_json" in row.keys() and row["verification_artifact_refs_json"] else "{}",
            verification_failure_classification_ref=str(row["verification_failure_classification_ref"]) if "verification_failure_classification_ref" in row.keys() and row["verification_failure_classification_ref"] else "",
        )
