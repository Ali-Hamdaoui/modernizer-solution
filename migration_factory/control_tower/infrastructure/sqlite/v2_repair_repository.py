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
                approval_checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
