"""SQLite store for backend-owned repair apply candidates."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from migration_factory.control_tower.application.v2_repair_apply_candidate import public_repair_apply_candidate
from migration_factory.control_tower.domain.checksums import utc_now_text


class SqliteV2RepairCandidateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_candidate(self, candidate: dict[str, Any]) -> None:
        for key in ("_sandbox_root", "_target_path", "_after_text", "_patch_payload"):
            if not candidate.get(key):
                raise ValueError("internal_repair_candidate_required")
        public = public_repair_apply_candidate(candidate) or {}
        now = str(candidate.get("created_at") or utc_now_text())
        self._connection.execute(
            """INSERT OR IGNORE INTO v2_repair_apply_candidates (
                repair_candidate_id, job_id, stage_index, status, public_json,
                internal_json, approval_json, execution_json, patch_checksum,
                target_file_checksum, review_checksum, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)""",
            (
                candidate["repair_candidate_id"],
                candidate["job_id"],
                int(candidate["stage_index"]),
                candidate["status"],
                json.dumps(public, sort_keys=True, separators=(",", ":")),
                json.dumps(candidate, sort_keys=True, separators=(",", ":")),
                candidate["patch_checksum"],
                candidate["target_file_checksum"],
                candidate["review_checksum"],
                now,
                now,
            ),
        )

    def get_internal(self, job_id: str, stage_index: int, repair_candidate_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """SELECT internal_json, approval_json, execution_json, status
               FROM v2_repair_apply_candidates
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (job_id, stage_index, repair_candidate_id),
        ).fetchone()
        if row is None:
            return None
        candidate = json.loads(str(row["internal_json"]))
        candidate["status"] = str(row["status"])
        if row["approval_json"]:
            candidate["approval"] = json.loads(str(row["approval_json"]))
        if row["execution_json"]:
            candidate["execution"] = json.loads(str(row["execution_json"]))
        return candidate

    def get_public(self, job_id: str, stage_index: int, repair_candidate_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """SELECT public_json, approval_json, execution_json, status
               FROM v2_repair_apply_candidates
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (job_id, stage_index, repair_candidate_id),
        ).fetchone()
        if row is None:
            return None
        public = json.loads(str(row["public_json"]))
        public["status"] = str(row["status"])
        if row["approval_json"]:
            public["approval"] = json.loads(str(row["approval_json"]))
            public["apply_enabled"] = public["status"] == "approved"
            public["approval_enabled"] = False
        if row["execution_json"]:
            execution = json.loads(str(row["execution_json"]))
            public.update({
                "status": execution.get("status", public["status"]),
                "execution_status": execution.get("execution_status", ""),
                "verification_status": execution.get("verification_status", public.get("verification_status", "")),
                "rollback_status": execution.get("rollback_status", public.get("rollback_status", "")),
                "proof_artifact": execution.get("proof_artifact", public.get("proof_artifact", "")),
                "post_repair_verification_status": execution.get("post_repair_verification_status", public.get("post_repair_verification_status", "")),
                "stage_recovery_status": execution.get("stage_recovery_status", public.get("stage_recovery_status", "")),
                "post_repair_verification": execution.get("post_repair_verification", public.get("post_repair_verification")),
                "next_repair_candidate": execution.get("next_repair_candidate", public.get("next_repair_candidate")),
                "apply_enabled": False,
                "approval_enabled": False,
            })
        return public

    def latest_public_for_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            """SELECT public_json, approval_json, execution_json, status
               FROM v2_repair_apply_candidates
               WHERE job_id = ?
               ORDER BY created_at DESC, repair_candidate_id DESC
               LIMIT 1""",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        public = json.loads(str(row["public_json"]))
        public["status"] = str(row["status"])
        if row["approval_json"]:
            public["approval"] = json.loads(str(row["approval_json"]))
            public["apply_enabled"] = public["status"] == "approved"
            public["approval_enabled"] = False
        if row["execution_json"]:
            execution = json.loads(str(row["execution_json"]))
            public.update({
                "status": execution.get("status", public["status"]),
                "execution_status": execution.get("execution_status", ""),
                "verification_status": execution.get("verification_status", public.get("verification_status", "")),
                "rollback_status": execution.get("rollback_status", public.get("rollback_status", "")),
                "proof_artifact": execution.get("proof_artifact", public.get("proof_artifact", "")),
                "post_repair_verification_status": execution.get("post_repair_verification_status", public.get("post_repair_verification_status", "")),
                "stage_recovery_status": execution.get("stage_recovery_status", public.get("stage_recovery_status", "")),
                "post_repair_verification": execution.get("post_repair_verification", public.get("post_repair_verification")),
                "next_repair_candidate": execution.get("next_repair_candidate", public.get("next_repair_candidate")),
                "apply_enabled": False,
                "approval_enabled": False,
            })
        return public

    def save_approval(self, job_id: str, stage_index: int, repair_candidate_id: str, approval: dict[str, Any]) -> None:
        now = utc_now_text()
        self._connection.execute(
            """UPDATE v2_repair_apply_candidates
               SET status = 'approved', approval_json = ?, updated_at = ?
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (json.dumps(approval, sort_keys=True, separators=(",", ":")), now, job_id, stage_index, repair_candidate_id),
        )

    def save_execution(self, job_id: str, stage_index: int, repair_candidate_id: str, execution: dict[str, Any]) -> None:
        now = utc_now_text()
        self._connection.execute(
            """UPDATE v2_repair_apply_candidates
               SET status = ?, execution_json = ?, updated_at = ?
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (str(execution.get("status") or execution.get("execution_status") or "failed"), json.dumps(execution, sort_keys=True, separators=(",", ":")), now, job_id, stage_index, repair_candidate_id),
        )
