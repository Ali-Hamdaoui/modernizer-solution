"""Privileged action persistence service for V1-17A.

Persists pending privileged action requests with typed action
metadata, checksums, actor attribution, status tracking, and
audit trails.

Only typed Maven and write actions are allowed. Shell actions
are rejected at the service layer.

Approval logic belongs to V1-17C. Execution belongs to V1-17D.
Policy/checksum validation beyond basic storage belongs to V1-17B.
"""

from __future__ import annotations

import json
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import V1PrivilegedActionRecord
from migration_factory.control_tower.domain.errors import ControlTowerError


# ── Domain errors ──────────────────────────────────────────────────


class PrivilegedActionError(ControlTowerError):
    """Base error for privileged action failures."""


class InvalidActionTypeError(PrivilegedActionError):
    """Raised when an unsupported action type is requested."""

    def __init__(self, action_type: str) -> None:
        self.action_type = action_type
        super().__init__(
            f"Unsupported privileged action type: {action_type!r}. "
            f"Only 'maven' and 'write' are allowed."
        )


class ActionNotFoundError(PrivilegedActionError):
    """Raised when a privileged action is not found."""

    def __init__(self, action_id: str) -> None:
        self.action_id = action_id
        super().__init__(f"Privileged action not found: {action_id!r}")


# ── Allowed action types ──────────────────────────────────────────

ALLOWED_ACTION_TYPES: tuple[str, ...] = ("maven", "write")

# Action parameters are validated structurally but not deeply
# (policy/checksum validation belongs to V1-17B)


# ── PrivilegedActionService ────────────────────────────────────────


class PrivilegedActionService:
    """Service for persisting and querying pending privileged actions.

    This service stores requested actions only. It does not:
    - Approve or reject actions (V1-17C)
    - Execute actions (V1-17D)
    - Validate action policy/checksums beyond basic type checks (V1-17B)
    """

    def __init__(self, unit_of_work_factory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def request_action(
        self,
        *,
        job_id: str,
        action_type: str,
        parameters: dict[str, object],
        requested_by: str = "system",
        policy_json: str | None = None,
        policy_version: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> V1PrivilegedActionRecord:
        """Persist a pending privileged action request.

        Validates:
        - Action type is 'maven' or 'write' (shell is rejected).
        - Parameters are not empty.

        Computes:
        - A unique action_id.
        - A checksum over the parameters.
        - Attribution and timestamps.

        Args:
            job_id: The migration job requesting the action.
            action_type: 'maven' or 'write'.
            parameters: Structured parameters for the action.
            requested_by: Actor requesting the action.
            policy_json: Optional policy reference JSON.
            policy_version: Optional policy version.
            correlation_id: Optional correlation ID.
            causation_id: Optional causation ID.

        Returns:
            The persisted V1PrivilegedActionRecord.

        Raises:
            InvalidActionTypeError: If action_type is not 'maven' or 'write'.
        """
        start = self._validate_request(action_type, parameters)

        action_id = f"pa-{uuid4().hex}"
        now = utc_now_text()
        parameters_json = json.dumps(parameters, separators=(",", ":"), sort_keys=True)
        parameters_checksum = sha256_canonical_json(parameters)

        record = V1PrivilegedActionRecord(
            action_id=action_id,
            job_id=job_id,
            action_type=action_type,
            action_version="1.0",
            parameters_json=parameters_json,
            parameters_checksum=parameters_checksum,
            policy_json=policy_json,
            policy_version=policy_version,
            status="pending",
            requested_by=requested_by,
            requested_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        with self._unit_of_work_factory() as uow:
            uow.v1_privileged_actions.insert(record)

            # Record audit event
            import json as _json

            audit_payload = {
                "action": "privileged_action_requested",
                "action_id": action_id,
                "job_id": job_id,
                "action_type": action_type,
                "parameters_checksum": parameters_checksum,
            }
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type="system",
                actor_id=requested_by,
                action="privileged_action_requested",
                payload_json=_json.dumps(audit_payload, separators=(",", ":"), sort_keys=True),
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )

        return record

    def get_action(self, action_id: str) -> V1PrivilegedActionRecord | None:
        """Get a single privileged action by ID."""
        with self._unit_of_work_factory() as uow:
            return uow.v1_privileged_actions.get(action_id)

    def list_actions(self) -> tuple[V1PrivilegedActionRecord, ...]:
        """List all privileged actions."""
        with self._unit_of_work_factory() as uow:
            return uow.v1_privileged_actions.list()

    def list_actions_for_job(self, job_id: str) -> tuple[V1PrivilegedActionRecord, ...]:
        """List privileged actions for a specific job."""
        with self._unit_of_work_factory() as uow:
            return uow.v1_privileged_actions.list_for_job(job_id)

    def list_pending_actions(self) -> tuple[V1PrivilegedActionRecord, ...]:
        """List all pending privileged actions."""
        with self._unit_of_work_factory() as uow:
            return uow.v1_privileged_actions.list_by_status("pending")

    def list_actions_by_status(self, status: str) -> tuple[V1PrivilegedActionRecord, ...]:
        """List privileged actions by status."""
        with self._unit_of_work_factory() as uow:
            return uow.v1_privileged_actions.list_by_status(status)

    def to_dto(self, record: V1PrivilegedActionRecord) -> dict[str, object]:
        """Convert a domain record to a public DTO.

        Only non-sensitive fields are exposed. Parameters JSON
        is included in its structured form (already safe by
        construction since raw paths/secrets are not stored).
        """
        return {
            "action_id": record.action_id,
            "job_id": record.job_id,
            "action_type": record.action_type,
            "action_version": record.action_version,
            "parameters": json.loads(record.parameters_json) if record.parameters_json else {},
            "parameters_checksum": record.parameters_checksum,
            "status": record.status,
            "requested_by": record.requested_by,
            "requested_at": record.requested_at,
            "approved_by": record.approved_by,
            "approved_at": record.approved_at,
            "rejected_by": record.rejected_by,
            "rejected_reason": record.rejected_reason,
            "executed_at": record.executed_at,
            "failure_reason": record.failure_reason,
        }

    def _validate_request(
        self,
        action_type: str,
        parameters: dict[str, object],
    ) -> None:
        """Validate a privileged action request before persistence."""
        if action_type not in ALLOWED_ACTION_TYPES:
            raise InvalidActionTypeError(action_type)

        if not parameters:
            raise ValueError("Privileged action parameters must not be empty")
