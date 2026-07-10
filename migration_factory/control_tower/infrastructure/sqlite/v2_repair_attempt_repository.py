"""Append-only persistence for governed repair attempts and operator authority."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


class SqliteV2RepairAttemptRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def next_attempt_number(self, job_id: str, stage_index: int) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(attempt_number), 0) AS value FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ?",
            (job_id, stage_index),
        ).fetchone()
        return int(row["value"] if row is not None else 0) + 1

    def save_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        public = dict(attempt.get("projection") or {})
        internal = dict(attempt.get("internal") or {})
        stable = {
            "attempt_id": str(attempt["attempt_id"]),
            "job_id": str(attempt["job_id"]),
            "stage_index": int(attempt["stage_index"]),
            "command_id": str(attempt.get("command_id") or ""),
            "attempt_number": int(attempt["attempt_number"]),
            "attempt_source": str(attempt.get("attempt_source") or "llm"),
            "previous_attempt_id": str(attempt.get("previous_attempt_id") or ""),
            "repair_candidate_id": str(attempt.get("repair_candidate_id") or ""),
            "applicability_status": str(attempt["applicability_status"]),
            "workflow_state": str(attempt["workflow_state"]),
            "projection": public,
            "internal": internal,
        }
        checksum = "sha256:" + sha256_canonical_json(stable)
        created_at = str(attempt.get("created_at") or utc_now_text())
        existing = self._connection.execute(
            "SELECT attempt_checksum FROM v2_repair_attempts WHERE attempt_id = ?",
            (stable["attempt_id"],),
        ).fetchone()
        if existing is not None:
            if str(existing["attempt_checksum"]) != checksum:
                raise ValueError("repair_attempt_checksum_collision")
            loaded = self.get_internal(stable["job_id"], stable["stage_index"], stable["attempt_id"])
            return loaded or {}
        self._connection.execute(
            """INSERT INTO v2_repair_attempts (
                attempt_id, job_id, stage_index, command_id, attempt_number,
                attempt_source, previous_attempt_id, repair_candidate_id,
                applicability_status, workflow_state, projection_json,
                internal_json, attempt_checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULLIF(?, ''), NULLIF(?, ''), ?, ?, ?, ?, ?, ?)""",
            (
                stable["attempt_id"], stable["job_id"], stable["stage_index"],
                stable["command_id"], stable["attempt_number"], stable["attempt_source"],
                stable["previous_attempt_id"], stable["repair_candidate_id"],
                stable["applicability_status"], stable["workflow_state"],
                json.dumps(public, sort_keys=True, separators=(",", ":")),
                json.dumps(internal, sort_keys=True, separators=(",", ":")),
                checksum, created_at,
            ),
        )
        return {**stable, "attempt_checksum": checksum, "created_at": created_at}

    def get_internal(self, job_id: str, stage_index: int, attempt_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ? AND attempt_id = ?",
            (job_id, stage_index, attempt_id),
        ).fetchone()
        return self._with_candidate_state(_attempt_row(row, include_internal=True))

    def get_public(self, job_id: str, stage_index: int, attempt_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ? AND attempt_id = ?",
            (job_id, stage_index, attempt_id),
        ).fetchone()
        return self._with_candidate_state(_attempt_row(row, include_internal=False))

    def latest_internal(self, job_id: str, stage_index: int | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM v2_repair_attempts WHERE job_id = ?"
        values: list[Any] = [job_id]
        if stage_index is not None:
            query += " AND stage_index = ?"
            values.append(stage_index)
        query += " ORDER BY attempt_number DESC, created_at DESC LIMIT 1"
        return self._with_candidate_state(_attempt_row(self._connection.execute(query, tuple(values)).fetchone(), include_internal=True))

    def for_candidate(self, job_id: str, stage_index: int, repair_candidate_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ? ORDER BY attempt_number DESC LIMIT 1",
            (job_id, stage_index, repair_candidate_id),
        ).fetchone()
        return self._with_candidate_state(_attempt_row(row, include_internal=True))

    def list_public(self, job_id: str, stage_index: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM v2_repair_attempts WHERE job_id = ?"
        values: list[Any] = [job_id]
        if stage_index is not None:
            query += " AND stage_index = ?"
            values.append(stage_index)
        query += " ORDER BY stage_index, attempt_number, created_at"
        attempts: list[dict[str, Any]] = []
        for row in self._connection.execute(query, tuple(values)).fetchall():
            value = self._with_candidate_state(_attempt_row(row, include_internal=False))
            if value is not None:
                attempts.append(value)
        return attempts

    def _with_candidate_state(self, attempt: dict[str, Any] | None) -> dict[str, Any] | None:
        if attempt is None:
            return attempt
        if not str(attempt.get("repair_candidate_id") or ""):
            return self._with_action_state(attempt)
        row = self._connection.execute(
            "SELECT status, approval_json, execution_json FROM v2_repair_apply_candidates WHERE repair_candidate_id = ? AND job_id = ? AND stage_index = ?",
            (attempt["repair_candidate_id"], attempt["job_id"], attempt["stage_index"]),
        ).fetchone()
        if row is not None:
            status = str(row["status"] or "")
            attempt["candidate_status"] = status
            if row["approval_json"]:
                approval = json.loads(str(row["approval_json"]))
                attempt["operator_decision"] = {
                    key: approval.get(key)
                    for key in ("approval_id", "approval_mode", "operator_justification", "acknowledged_risk_codes", "reviewer_outcome", "approval_checksum", "created_at")
                }
                attempt["apply_enabled"] = status == "approved"
                attempt["repair_workflow_state"] = {
                    "normal_approval": "repair_approved",
                    "acknowledged_risk_approval": "repair_approved_with_risks",
                    "reviewer_override_approval": "repair_reviewer_override_approved",
                }.get(str(approval.get("approval_mode") or ""), attempt.get("repair_workflow_state"))
            if row["execution_json"]:
                execution = json.loads(str(row["execution_json"]))
                downstream_status = str(execution.get("downstream_resume_status") or "blocked")
                attempt["apply_result"] = {key: execution.get(key) for key in ("status", "apply_status", "rollback_status", "created_at")}
                attempt["verification_result"] = {key: execution.get(key) for key in ("verification_status", "post_repair_verification_status", "stage_recovery_status")}
                attempt["proof"] = {key: execution.get(key) for key in ("proof_artifact", "proof_checksum", "post_repair_verification_proof_checksum")}
                attempt["route_continuation"] = {key: execution.get(key) for key in ("downstream_resume_status", "downstream_command_id", "downstream_stage_index")}
                attempt["apply_enabled"] = False
                attempt["resume_enabled"] = (
                    str(execution.get("status") or "") == "verified"
                    and downstream_status not in {"queued", "route_complete"}
                )
                attempt["repair_workflow_state"] = "repair_verified" if execution.get("status") == "verified" else "repair_rolled_back" if execution.get("status") == "rolled_back" else "operator_action_required"
        return self._with_action_state(attempt)

    def _with_action_state(self, attempt: dict[str, Any]) -> dict[str, Any]:
        action = self._connection.execute(
            "SELECT action_type, payload_json, created_at FROM v2_repair_operator_actions WHERE attempt_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (attempt["attempt_id"],),
        ).fetchone()
        if action is None:
            return attempt
        action_type = str(action["action_type"] or "")
        attempt["latest_operator_action"] = action_type
        attempt["latest_operator_action_at"] = str(action["created_at"] or "")
        action_states = {
            "request_corrected_proposal": "repair_revision_requested",
            "provide_operator_guidance": "repair_revision_requested",
            "request_additional_context": "additional_context_requested",
            "submit_manual_diff": "manual_patch_submitted",
            "reject_current_attempt": "repair_rejected",
            "mark_manual_remediation_required": "manual_remediation_required",
            "resume_from_repair_checkpoint": "route_resuming",
        }
        attempt["repair_workflow_state"] = action_states.get(action_type, attempt.get("repair_workflow_state"))
        if action_type == "resume_from_repair_checkpoint":
            try:
                payload = json.loads(str(action["payload_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            resume_result = payload.get("resume_result") if isinstance(payload.get("resume_result"), dict) else {}
            resume_status = str(resume_result.get("downstream_resume_status") or "")
            if resume_status in {"queued", "route_complete"}:
                attempt["route_continuation"] = {
                    key: resume_result.get(key)
                    for key in ("downstream_resume_status", "downstream_command_id", "downstream_stage_index")
                }
                attempt["resume_enabled"] = False
                attempt["repair_workflow_state"] = "route_complete" if resume_status == "route_complete" else "route_resuming"
            else:
                attempt["resume_enabled"] = True
                attempt["repair_workflow_state"] = "operator_action_required"
        return attempt

    def save_action(self, action: dict[str, Any]) -> dict[str, Any]:
        payload = dict(action.get("payload") or {})
        checksum = "sha256:" + sha256_canonical_json(payload)
        created_at = str(action.get("created_at") or utc_now_text())
        self._connection.execute(
            """INSERT INTO v2_repair_operator_actions (
                action_id, attempt_id, job_id, stage_index, action_type,
                payload_json, payload_checksum, actor_type, actor_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                action["action_id"], action["attempt_id"], action["job_id"],
                int(action["stage_index"]), action["action_type"],
                json.dumps(payload, sort_keys=True, separators=(",", ":")), checksum,
                action["actor_type"], action["actor_id"], created_at,
            ),
        )
        return {**action, "payload": payload, "payload_checksum": checksum, "created_at": created_at}

    def save_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        payload = dict(decision)
        payload.pop("decision_checksum", None)
        payload.pop("created_at", None)
        checksum = "sha256:" + sha256_canonical_json(payload)
        created_at = str(decision.get("created_at") or utc_now_text())
        existing = self._connection.execute(
            "SELECT decision_checksum FROM v2_repair_operator_decisions WHERE repair_candidate_id = ?",
            (decision["repair_candidate_id"],),
        ).fetchone()
        if existing is not None:
            if str(existing["decision_checksum"]) != checksum:
                raise ValueError("repair_operator_decision_conflict")
            return {**decision, "decision_checksum": checksum, "created_at": created_at}
        risks = tuple(str(code) for code in decision.get("acknowledged_risk_codes") or ())
        self._connection.execute(
            """INSERT INTO v2_repair_operator_decisions (
                decision_id, attempt_id, repair_candidate_id, job_id, stage_index,
                approval_mode, decision_status, operator_justification,
                acknowledged_risk_codes_json, reviewer_outcome,
                reviewer_output_checksum, reviewer_invocation_id,
                candidate_checksum, decision_checksum, actor_type, actor_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision["decision_id"], decision["attempt_id"], decision["repair_candidate_id"],
                decision["job_id"], int(decision["stage_index"]), decision["approval_mode"],
                decision["decision_status"], decision.get("operator_justification", ""),
                json.dumps(risks, separators=(",", ":")), decision["reviewer_outcome"],
                decision.get("reviewer_output_checksum", ""), decision.get("reviewer_invocation_id", ""),
                decision["candidate_checksum"], checksum, decision["actor_type"],
                decision["actor_id"], created_at,
            ),
        )
        return {**decision, "acknowledged_risk_codes": risks, "decision_checksum": checksum, "created_at": created_at}


def _attempt_row(row: sqlite3.Row | None, *, include_internal: bool) -> dict[str, Any] | None:
    if row is None:
        return None
    projection = json.loads(str(row["projection_json"] or "{}"))
    value = {
        **projection,
        "attempt_id": str(row["attempt_id"]),
        "job_id": str(row["job_id"]),
        "stage_index": int(row["stage_index"]),
        "command_id": str(row["command_id"]),
        "attempt_number": int(row["attempt_number"]),
        "attempt_source": str(row["attempt_source"]),
        "previous_attempt_id": str(row["previous_attempt_id"] or ""),
        "repair_candidate_id": str(row["repair_candidate_id"] or ""),
        "applicability_status": str(row["applicability_status"]),
        "workflow_state": str(row["workflow_state"]),
        "attempt_checksum": str(row["attempt_checksum"]),
        "created_at": str(row["created_at"]),
    }
    if include_internal:
        value["internal"] = json.loads(str(row["internal_json"] or "{}"))
    return value
