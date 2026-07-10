"""SQLite store for backend-owned repair apply candidates."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    _approval_checksum_payload,
    _candidate_reviewer_outcome,
    _required_approval_mode,
    _reviewed_llm_approval_checksum,
    public_repair_apply_candidate,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


class SqliteV2RepairCandidateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_candidate(self, candidate: dict[str, Any]) -> None:
        if str(candidate.get("candidate_kind") or "") != "llm_unknown_family":
            for key in ("_sandbox_root", "_target_path", "_after_text", "_patch_payload"):
                if not candidate.get(key):
                    raise ValueError("internal_repair_candidate_required")
        public = public_repair_apply_candidate(candidate) or {}
        if str(candidate.get("candidate_kind") or "") == "llm_unknown_family":
            candidate = _safe_llm_candidate_state(dict(candidate))
            public = _safe_llm_candidate_state(dict(public))
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
        if str(candidate.get("candidate_kind") or "") == "llm_unknown_family":
            candidate = _attach_llm_persistence_bindings(self._connection, candidate)
            candidate = _attach_terminal_operator_action(self._connection, candidate)
        if row["approval_json"]:
            candidate["approval"] = json.loads(str(row["approval_json"]))
        if row["execution_json"]:
            candidate["execution"] = json.loads(str(row["execution_json"]))
        candidate = _attach_current_attempt_state(self._connection, candidate)
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
                "next_repair_candidate_blocked_reason": execution.get("next_repair_candidate_blocked_reason", public.get("next_repair_candidate_blocked_reason", "")),
                "next_repair_candidate_blocked_gate": execution.get("next_repair_candidate_blocked_gate", public.get("next_repair_candidate_blocked_gate", "")),
                "next_repair_candidate_gate_trace": execution.get("next_repair_candidate_gate_trace", public.get("next_repair_candidate_gate_trace")),
                "downstream_start_allowed": bool(execution.get("downstream_start_allowed")),
                "downstream_resume_status": execution.get("downstream_resume_status", public.get("downstream_resume_status", "")),
                "downstream_command_id": execution.get("downstream_command_id", public.get("downstream_command_id", "")),
                "downstream_stage_index": execution.get("downstream_stage_index", public.get("downstream_stage_index", 0)),
                "apply_enabled": False,
                "approval_enabled": False,
            })
        public = _attach_terminal_operator_action(self._connection, public)
        public = _attach_current_attempt_state(self._connection, public)
        return _safe_llm_candidate_state(public) if public.get("candidate_kind") == "llm_unknown_family" else public

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
                "next_repair_candidate_blocked_reason": execution.get("next_repair_candidate_blocked_reason", public.get("next_repair_candidate_blocked_reason", "")),
                "next_repair_candidate_blocked_gate": execution.get("next_repair_candidate_blocked_gate", public.get("next_repair_candidate_blocked_gate", "")),
                "next_repair_candidate_gate_trace": execution.get("next_repair_candidate_gate_trace", public.get("next_repair_candidate_gate_trace")),
                "downstream_start_allowed": bool(execution.get("downstream_start_allowed")),
                "downstream_resume_status": execution.get("downstream_resume_status", public.get("downstream_resume_status", "")),
                "downstream_command_id": execution.get("downstream_command_id", public.get("downstream_command_id", "")),
                "downstream_stage_index": execution.get("downstream_stage_index", public.get("downstream_stage_index", 0)),
                "apply_enabled": False,
                "approval_enabled": False,
            })
        public = _attach_terminal_operator_action(self._connection, public)
        public = _attach_current_attempt_state(self._connection, public)
        return _safe_llm_candidate_state(public) if public.get("candidate_kind") == "llm_unknown_family" else public

    def save_approval(self, job_id: str, stage_index: int, repair_candidate_id: str, approval: dict[str, Any]) -> None:
        if _is_llm_unknown_family(self._connection, job_id, stage_index, repair_candidate_id):
            _validate_llm_approval(self._connection, job_id, stage_index, repair_candidate_id, approval)
        now = utc_now_text()
        self._connection.execute(
            """UPDATE v2_repair_apply_candidates
               SET status = 'approved', approval_json = ?, updated_at = ?
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (json.dumps(approval, sort_keys=True, separators=(",", ":")), now, job_id, stage_index, repair_candidate_id),
        )

    def save_execution(self, job_id: str, stage_index: int, repair_candidate_id: str, execution: dict[str, Any]) -> None:
        if _is_llm_unknown_family(self._connection, job_id, stage_index, repair_candidate_id):
            if _validate_llm_execution(self._connection, job_id, stage_index, repair_candidate_id, execution):
                return
        now = utc_now_text()
        self._connection.execute(
            """UPDATE v2_repair_apply_candidates
               SET status = ?, execution_json = ?, updated_at = ?
               WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
            (str(execution.get("status") or execution.get("execution_status") or "failed"), json.dumps(execution, sort_keys=True, separators=(",", ":")), now, job_id, stage_index, repair_candidate_id),
        )


def _attach_llm_persistence_bindings(connection: sqlite3.Connection, candidate: dict[str, Any]) -> dict[str, Any]:
    proposal_id = str(
        candidate.get("llm_candidate_proposal_id")
        or (candidate.get("_llm_candidate_metadata") or {}).get("llm_candidate_proposal_id")
        or ""
    )
    if proposal_id:
        row = connection.execute(
            "SELECT policy_validation_checksum FROM v2_repair_proposals WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is not None and "policy_validation_checksum" in row.keys():
            candidate["_persisted_proposal_policy_validation_checksum"] = str(row["policy_validation_checksum"] or "")
    rows = connection.execute(
        """SELECT payload_json FROM v2_job_events
           WHERE job_id = ? AND stage = ? AND type = ?
           ORDER BY sequence DESC""",
        (candidate.get("job_id"), int(candidate.get("stage_index") or 0), "llm_reviewed_patch_policy_evaluated"),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            continue
        if str(payload.get("review_chain_identity_checksum") or "") == str(candidate.get("review_chain_identity_checksum") or candidate.get("proposal_checksum") or ""):
            candidate["_persisted_policy_event_checksum"] = str(payload.get("policy_checksum") or "")
            break
    return candidate


def _terminal_operator_action(connection: sqlite3.Connection, repair_candidate_id: str) -> str:
    row = connection.execute(
        """SELECT action.action_type
           FROM v2_repair_operator_actions AS action
           JOIN v2_repair_attempts AS attempt ON attempt.attempt_id = action.attempt_id
           WHERE attempt.repair_candidate_id = ?
             AND action.action_type IN ('reject_current_attempt', 'mark_manual_remediation_required')
           ORDER BY action.created_at DESC, action.rowid DESC
           LIMIT 1""",
        (repair_candidate_id,),
    ).fetchone()
    return str(row["action_type"] or "") if row is not None else ""


def _attach_terminal_operator_action(
    connection: sqlite3.Connection,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if str(candidate.get("candidate_kind") or "") != "llm_unknown_family":
        return candidate
    action = _terminal_operator_action(connection, str(candidate.get("repair_candidate_id") or ""))
    if not action:
        return candidate
    candidate["status"] = (
        "rejected" if action == "reject_current_attempt" else "manual_remediation_required"
    )
    candidate["approval_enabled"] = False
    candidate["apply_enabled"] = False
    candidate["terminal_operator_action"] = action
    return candidate


def _attach_current_attempt_state(
    connection: sqlite3.Connection,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if str(candidate.get("candidate_kind") or "") != "llm_unknown_family":
        return candidate
    repair_candidate_id = str(candidate.get("repair_candidate_id") or "")
    attempt = connection.execute(
        "SELECT attempt_id FROM v2_repair_attempts WHERE repair_candidate_id = ? ORDER BY attempt_number DESC LIMIT 1",
        (repair_candidate_id,),
    ).fetchone()
    if attempt is None:
        return candidate
    latest = connection.execute(
        "SELECT attempt_id FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ? ORDER BY attempt_number DESC, created_at DESC LIMIT 1",
        (candidate.get("job_id"), int(candidate.get("stage_index") or 0)),
    ).fetchone()
    if latest is None or str(latest["attempt_id"]) == str(attempt["attempt_id"]):
        return candidate
    candidate["status"] = "superseded"
    candidate["approval_enabled"] = False
    candidate["apply_enabled"] = False
    candidate["superseded_by_attempt_id"] = str(latest["attempt_id"])
    return candidate


def _repair_candidate_is_current(connection: sqlite3.Connection, repair_candidate_id: str) -> bool:
    row = connection.execute(
        """SELECT job_id, stage_index, attempt_id
           FROM v2_repair_attempts
           WHERE repair_candidate_id = ?
           ORDER BY attempt_number DESC
           LIMIT 1""",
        (repair_candidate_id,),
    ).fetchone()
    if row is None:
        return True
    latest = connection.execute(
        "SELECT attempt_id FROM v2_repair_attempts WHERE job_id = ? AND stage_index = ? ORDER BY attempt_number DESC, created_at DESC LIMIT 1",
        (row["job_id"], int(row["stage_index"])),
    ).fetchone()
    return latest is not None and str(latest["attempt_id"]) == str(row["attempt_id"])


def _validate_llm_approval(
    connection: sqlite3.Connection,
    job_id: str,
    stage_index: int,
    repair_candidate_id: str,
    approval: dict[str, Any],
) -> None:
    row = connection.execute(
        """SELECT internal_json, approval_json, execution_json, status
           FROM v2_repair_apply_candidates
           WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
        (job_id, stage_index, repair_candidate_id),
    ).fetchone()
    if row is None:
        raise ValueError("llm_candidate_missing")
    candidate = _attach_llm_persistence_bindings(connection, json.loads(str(row["internal_json"])))
    if row["approval_json"]:
        existing = json.loads(str(row["approval_json"]))
        if existing == approval:
            return
        raise ValueError("llm_approval_conflict")
    status = str(row["status"] or candidate.get("status") or "")
    if status not in {"read_only", "pending_human_approval"}:
        raise ValueError("llm_candidate_not_approval_eligible")
    if row["execution_json"]:
        raise ValueError("llm_candidate_execution_exists")
    if not _repair_candidate_is_current(connection, repair_candidate_id):
        raise ValueError("llm_candidate_superseded")
    terminal_action = _terminal_operator_action(connection, repair_candidate_id)
    if terminal_action:
        raise ValueError(f"llm_candidate_{terminal_action}")
    if str(approval.get("approval_status") or "") != "approved":
        raise ValueError("llm_approval_not_approved")
    if str(approval.get("approval_scope") or "") != "sandbox_only":
        raise ValueError("llm_approval_scope_mismatch")
    reviewer_outcome = _candidate_reviewer_outcome(candidate)
    if str(approval.get("reviewer_outcome") or "") != reviewer_outcome:
        raise ValueError("llm_approval_reviewer_outcome_mismatch")
    if str(approval.get("reviewer_decision") or "") != str(candidate.get("reviewer_decision") or ""):
        raise ValueError("llm_approval_reviewer_decision_mismatch")
    if str(approval.get("approval_mode") or "") != _required_approval_mode(reviewer_outcome):
        raise ValueError("llm_approval_mode_mismatch")
    if str(approval.get("reviewer_output_checksum") or "") != str(candidate.get("reviewer_output_checksum") or candidate.get("review_checksum") or ""):
        raise ValueError("llm_approval_reviewer_checksum_mismatch")
    if str(approval.get("reviewer_invocation_id") or "") != str(candidate.get("reviewer_invocation_id") or ""):
        raise ValueError("llm_approval_reviewer_invocation_mismatch")
    if not str(candidate.get("reviewer_invocation_id") or ""):
        raise ValueError("llm_approval_reviewer_invocation_required")
    if reviewer_outcome != "unavailable" and not str(candidate.get("reviewer_output_checksum") or candidate.get("review_checksum") or ""):
        raise ValueError("llm_approval_reviewer_checksum_required")
    if _required_approval_mode(reviewer_outcome) != "normal_approval":
        if not str(approval.get("operator_justification") or "").strip():
            raise ValueError("llm_approval_operator_justification_required")
        if not tuple(approval.get("acknowledged_risk_codes") or ()):
            raise ValueError("llm_approval_acknowledged_risks_required")
    if not str(approval.get("backend_actor_id") or "").strip():
        raise ValueError("llm_approval_actor_required")
    if not str(approval.get("backend_actor_type") or "").strip():
        raise ValueError("llm_approval_actor_required")
    expected = {
        "repair_candidate_id": repair_candidate_id,
        "candidate_checksum": str(candidate.get("candidate_checksum") or ""),
        "reviewed_diff_checksum": str(candidate.get("patch_checksum") or ""),
        "policy_validation_checksum": str(candidate.get("policy_validation_checksum") or ""),
        "review_chain_identity_checksum": str(candidate.get("review_chain_identity_checksum") or candidate.get("proposal_checksum") or ""),
        "base_repository_state_checksum": str(candidate.get("base_repo_state_checksum") or ""),
    }
    for key, value in expected.items():
        if str(approval.get(key) or "") != value:
            raise ValueError(f"llm_approval_{key}_mismatch")
    _validate_mandatory_policy_bindings(candidate, approval_policy_checksum=expected["policy_validation_checksum"])
    if _reviewed_llm_approval_checksum(_approval_checksum_payload(approval)) != str(approval.get("approval_checksum") or ""):
        raise ValueError("llm_approval_checksum_mismatch")


def _validate_llm_execution(
    connection: sqlite3.Connection,
    job_id: str,
    stage_index: int,
    repair_candidate_id: str,
    execution: dict[str, Any],
) -> bool:
    row = connection.execute(
        """SELECT internal_json, approval_json, execution_json, status
           FROM v2_repair_apply_candidates
           WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
        (job_id, stage_index, repair_candidate_id),
    ).fetchone()
    if row is None:
        raise ValueError("llm_candidate_missing")
    candidate = _attach_llm_persistence_bindings(connection, json.loads(str(row["internal_json"])))
    if not row["approval_json"]:
        raise ValueError("llm_execution_approval_required")
    if not _repair_candidate_is_current(connection, repair_candidate_id):
        raise ValueError("llm_execution_candidate_superseded")
    terminal_action = _terminal_operator_action(connection, repair_candidate_id)
    if terminal_action:
        raise ValueError(f"llm_execution_{terminal_action}")
    approval = json.loads(str(row["approval_json"]))
    existing_json = str(row["execution_json"] or "")
    if existing_json:
        existing = json.loads(existing_json)
        if existing == execution:
            return True
        raise ValueError("llm_execution_conflict")
    status = str(execution.get("status") or execution.get("execution_status") or "")
    if status not in {"verified", "rolled_back", "failed"}:
        raise ValueError("llm_execution_status_invalid")
    reviewer_outcome = _candidate_reviewer_outcome(candidate)
    if str(approval.get("reviewer_outcome") or "") != reviewer_outcome:
        raise ValueError("llm_execution_reviewer_outcome_mismatch")
    if str(approval.get("approval_mode") or "") != _required_approval_mode(reviewer_outcome):
        raise ValueError("llm_execution_approval_mode_mismatch")
    if _reviewed_llm_approval_checksum(_approval_checksum_payload(approval)) != str(approval.get("approval_checksum") or ""):
        raise ValueError("llm_execution_approval_checksum_mismatch")
    if str(execution.get("repair_candidate_id") or "") != repair_candidate_id:
        raise ValueError("llm_execution_candidate_mismatch")
    if str(execution.get("approval_id") or "") != str(approval.get("approval_id") or ""):
        raise ValueError("llm_execution_approval_mismatch")
    if str(execution.get("candidate_checksum") or "") != str(candidate.get("candidate_checksum") or ""):
        raise ValueError("llm_execution_candidate_checksum_mismatch")
    if str(execution.get("reviewed_diff_checksum") or "") != str(candidate.get("patch_checksum") or ""):
        raise ValueError("llm_execution_reviewed_diff_checksum_mismatch")
    if str(execution.get("policy_validation_checksum") or "") != str(candidate.get("policy_validation_checksum") or ""):
        raise ValueError("llm_execution_policy_checksum_mismatch")
    _validate_mandatory_policy_bindings(candidate, approval_policy_checksum=str(approval.get("policy_validation_checksum") or ""))
    if status == "verified":
        if str(execution.get("verification_status") or "") != "passed" or not str(execution.get("proof_artifact") or ""):
            raise ValueError("llm_execution_verification_proof_required")
        _validate_execution_repair_proof(candidate, approval, execution, expected_status="verified")
        if not bool(execution.get("downstream_start_allowed")) and str(execution.get("downstream_resume_status") or "") == "queued":
            raise ValueError("llm_execution_downstream_start_mismatch")
    if status == "rolled_back":
        if str(execution.get("rollback_status") or "") != "succeeded" or not str(execution.get("proof_artifact") or ""):
            raise ValueError("llm_execution_rollback_proof_required")
        _validate_execution_repair_proof(candidate, approval, execution, expected_status="rolled_back")
    if status == "failed":
        if bool(execution.get("downstream_start_allowed")) or str(execution.get("downstream_resume_status") or "") == "queued":
            raise ValueError("llm_execution_downstream_without_verification")
        if str(execution.get("rollback_status") or "") == "succeeded":
            raise ValueError("llm_execution_failed_rollback_status_invalid")
        if str(execution.get("proof_artifact") or ""):
            _validate_execution_repair_proof(candidate, approval, execution, expected_status="failed")
    if bool(execution.get("downstream_start_allowed")) and str(execution.get("verification_status") or "") != "passed":
        raise ValueError("llm_execution_downstream_without_verification")
    if str(execution.get("downstream_resume_status") or "") == "queued":
        command_id = str(execution.get("downstream_command_id") or "")
        downstream_stage = int(execution.get("downstream_stage_index") or 0)
        if not command_id or downstream_stage <= 0:
            raise ValueError("llm_execution_fake_downstream_command")
        command = connection.execute(
            "SELECT command_id FROM v2_stage_commands WHERE command_id = ? AND job_id = ? AND stage_index = ?",
            (command_id, job_id, downstream_stage),
        ).fetchone()
        if command is None:
            raise ValueError("llm_execution_fake_downstream_command")
    return False


def _validate_mandatory_policy_bindings(candidate: dict[str, Any], *, approval_policy_checksum: str) -> None:
    metadata = candidate.get("_llm_candidate_metadata") if isinstance(candidate.get("_llm_candidate_metadata"), dict) else {}
    checksums = {
        "candidate": str(candidate.get("policy_validation_checksum") or ""),
        "approval": str(approval_policy_checksum or ""),
        "metadata": str(metadata.get("policy_validation_checksum") or ""),
        "persisted_proposal": str(candidate.get("_persisted_proposal_policy_validation_checksum") or ""),
        "persisted_policy_event": str(candidate.get("_persisted_policy_event_checksum") or ""),
    }
    if not checksums["persisted_proposal"]:
        raise ValueError("persisted_proposal_policy_checksum_missing")
    if not checksums["persisted_policy_event"]:
        raise ValueError("persisted_policy_event_checksum_missing")
    if not all(checksums.values()) or len(set(checksums.values())) != 1:
        raise ValueError("apply_time_policy_checksum_mismatch")


def _validate_execution_repair_proof(
    candidate: dict[str, Any],
    approval: dict[str, Any],
    execution: dict[str, Any],
    *,
    expected_status: str,
) -> None:
    repair_candidate_id = str(candidate.get("repair_candidate_id") or "")
    sandbox = Path(str(candidate.get("_sandbox_root") or "")).resolve()
    proof_path = (sandbox / ".migration" / "repair-proofs" / f"{repair_candidate_id}.json").resolve()
    try:
        proof_path.relative_to(sandbox)
    except ValueError as exc:
        raise ValueError("llm_execution_proof_outside_sandbox") from exc
    if not proof_path.is_file():
        raise ValueError("llm_execution_verification_proof_required")
    artifact_ref = str(execution.get("proof_artifact") or "").replace("\\", "/")
    redacted_ref = artifact_ref.startswith("[redacted-") and artifact_ref.endswith("-path]")
    if not redacted_ref and artifact_ref.rsplit("/", 1)[-1] != f"{repair_candidate_id}.json":
        raise ValueError("llm_execution_fake_proof_artifact")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("llm_execution_proof_malformed") from exc
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("llm_execution_proof_malformed") from exc
    if not isinstance(proof, dict):
        raise ValueError("llm_execution_proof_malformed")
    stored_checksum = str(proof.get("proof_checksum") or "")
    if not stored_checksum:
        raise ValueError("llm_execution_proof_checksum_missing")
    payload = dict(proof)
    payload.pop("proof_checksum", None)
    if f"sha256:{sha256_canonical_json(payload)}" != stored_checksum:
        raise ValueError("llm_execution_proof_checksum_mismatch")
    if str(execution.get("proof_checksum") or "") != stored_checksum:
        raise ValueError("llm_execution_proof_checksum_mismatch")
    if str(proof.get("status") or "") != expected_status:
        raise ValueError("llm_execution_proof_status_mismatch")
    if str(proof.get("post_repair_verification_proof_checksum") or "") != str(execution.get("post_repair_verification_proof_checksum") or ""):
        raise ValueError("llm_execution_post_repair_proof_checksum_mismatch")
    _validate_execution_post_repair_proof(candidate, approval, execution, expected_status=expected_status)


def _validate_execution_post_repair_proof(
    candidate: dict[str, Any],
    approval: dict[str, Any],
    execution: dict[str, Any],
    *,
    expected_status: str,
) -> None:
    expected_checksum = str(execution.get("post_repair_verification_proof_checksum") or "")
    if not expected_checksum:
        return
    repair_candidate_id = str(candidate.get("repair_candidate_id") or "")
    sandbox = Path(str(candidate.get("_sandbox_root") or "")).resolve()
    proof_path = (
        sandbox
        / ".migration"
        / "post-repair-verification"
        / repair_candidate_id
        / "post-repair-verification.json"
    ).resolve()
    try:
        proof_path.relative_to(sandbox)
    except ValueError as exc:
        raise ValueError("llm_execution_post_repair_proof_outside_sandbox") from exc
    artifact_ref = str(execution.get("post_repair_proof_artifact") or "").replace("\\", "/")
    redacted_ref = artifact_ref.startswith("[redacted-") and artifact_ref.endswith("-path]")
    if not artifact_ref or (not redacted_ref and not artifact_ref.endswith(f".migration/post-repair-verification/{repair_candidate_id}/post-repair-verification.json")):
        raise ValueError("llm_execution_fake_post_repair_proof_artifact")
    if not proof_path.is_file():
        raise ValueError("llm_execution_post_repair_proof_required")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("llm_execution_post_repair_proof_malformed") from exc
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("llm_execution_post_repair_proof_malformed") from exc
    if not isinstance(proof, dict):
        raise ValueError("llm_execution_post_repair_proof_malformed")
    stored_checksum = str(proof.get("proof_checksum") or "")
    if not stored_checksum:
        raise ValueError("llm_execution_post_repair_proof_checksum_missing")
    payload = dict(proof)
    payload.pop("proof_checksum", None)
    if f"sha256:{sha256_canonical_json(payload)}" != stored_checksum:
        raise ValueError("llm_execution_post_repair_proof_checksum_mismatch")
    if stored_checksum != expected_checksum:
        raise ValueError("llm_execution_post_repair_proof_checksum_mismatch")
    if str(proof.get("job_id") or "") != str(candidate.get("job_id") or ""):
        raise ValueError("llm_execution_post_repair_proof_job_mismatch")
    if int(proof.get("stage_index") or 0) != int(candidate.get("stage_index") or 0):
        raise ValueError("llm_execution_post_repair_proof_stage_mismatch")
    if str(proof.get("repair_candidate_id") or "") != repair_candidate_id:
        raise ValueError("llm_execution_post_repair_proof_candidate_mismatch")
    if str(proof.get("approval_id") or "") != str(approval.get("approval_id") or ""):
        raise ValueError("llm_execution_post_repair_proof_approval_mismatch")
    execution_post_status = str(execution.get("post_repair_verification_status") or "")
    if execution_post_status and str(proof.get("post_repair_verification_status") or "") != execution_post_status:
        raise ValueError("llm_execution_post_repair_proof_status_mismatch")
    if expected_status == "verified":
        if str(proof.get("post_repair_verification_status") or "") != "passed":
            raise ValueError("llm_execution_post_repair_proof_status_mismatch")
        if str(proof.get("stage_recovery_status") or "") != "recovered":
            raise ValueError("llm_execution_post_repair_proof_stage_recovery_mismatch")


def _is_llm_unknown_family(connection: sqlite3.Connection, job_id: str, stage_index: int, repair_candidate_id: str) -> bool:
    row = connection.execute(
        """SELECT internal_json, public_json
           FROM v2_repair_apply_candidates
           WHERE job_id = ? AND stage_index = ? AND repair_candidate_id = ?""",
        (job_id, stage_index, repair_candidate_id),
    ).fetchone()
    if row is None:
        return False
    for column in ("internal_json", "public_json"):
        try:
            payload = json.loads(str(row[column] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if payload.get("candidate_kind") == "llm_unknown_family":
            return True
    return False


def _safe_llm_candidate_state(value: dict[str, Any]) -> dict[str, Any]:
    status = str(value.get("status") or "read_only")
    has_approval = isinstance(value.get("approval"), dict)
    has_execution = bool(value.get("execution_status") or value.get("execution"))
    value["candidate_kind"] = "llm_unknown_family"
    value["family"] = "llm_unknown_family"
    value["patch_source"] = "llm_reviewed"
    value["status"] = status
    value["approval_enabled"] = status in {"read_only", "pending_human_approval"} and not has_approval and not has_execution
    value["apply_enabled"] = status == "approved" and has_approval and not has_execution
    value["repair_enabled"] = False
    value["sandbox_only"] = True
    value["legacy_mutation_allowed"] = False
    value["downstream_start_allowed"] = bool(value.get("downstream_start_allowed")) and status == "verified"
    value["downstream_resume_status"] = str(value.get("downstream_resume_status") or "")
    value["downstream_command_id"] = str(value.get("downstream_command_id") or "")
    value["downstream_stage_index"] = int(value.get("downstream_stage_index") or 0)
    value["llm_can_apply"] = False
    value["browser_can_supply_patch"] = False
    return value
