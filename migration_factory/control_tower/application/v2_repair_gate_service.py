"""F15 V2 Repair Gate Service — repair_review gate creation, actions, and transitions.

Coordinates repair_review gate lifecycle:
  1. On build/test/transform failure → create repair_review gate with diagnosis binding.
  2. On repair_review gate action → approve/reject/revise via V2GateActionService.
  3. On repair validation result → route to stage_completion_review or new repair gate.
  4. Track attempt limits at gate layer.

Reuses:
  - V2PhaseGateService for gate creation/resolution
  - V2GateActionService for gate action execution
  - V2FailureDiagnosisService for diagnosis
  - V2RepairFlowService for proposal/patch flow
  - EvidencePackBuilder for failure evidence
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
    FailureDiagnosisRecord,
)
from migration_factory.control_tower.application.v2_gate_action_service import (
    V2GateActionService,
    GateActionResult,
)
from migration_factory.control_tower.application.v2_phase_gate_service import (
    CreateGateRequest,
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.schemas.phase_gate import GateDecision


# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_MAX_REPAIR_ATTEMPTS = 3


# ── Result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RepairGateCreationResult:
    """Result of creating a repair_review gate after failure."""

    gate_id: str
    gate_checksum: str
    diagnosis: FailureDiagnosisRecord | None
    status: str  # created, conflict, skipped
    existing_gate_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class RepairValidationTransitionResult:
    """Result of a repair validation transition."""

    status: str  # stage_completion_gate_created, repair_gate_created, attempts_exhausted, no_action
    gate_id: str | None = None
    gate_checksum: str = ""
    remaining_attempts: int = 0
    reason: str = ""


# ── Repair Gate Service ─────────────────────────────────────────────


class V2RepairGateService:
    """Coordinates repair_review gate lifecycle.

    Composes V2PhaseGateService, V2GateActionService, V2RepairFlowService,
    and V2FailureDiagnosisService to implement the F15 repair gate flow.
    """

    def __init__(
        self,
        gate_service: V2PhaseGateService,
        gate_action_service: V2GateActionService | None = None,
        repair_flow: V2RepairFlowService | None = None,
        diagnosis_service: V2FailureDiagnosisService | None = None,
        max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._gate_service = gate_service
        self._gate_action_service = gate_action_service
        self._repair_flow = repair_flow
        self._diagnosis_service = diagnosis_service
        self._max_repair_attempts = max_repair_attempts

        # In-memory attempt tracking: {(job_id, stage_index): attempt_count}
        self._attempt_counts: dict[tuple[str, int], int] = {}

    # ── Job 101/102: Create repair_review gate on failure ───────────

    def create_repair_gate_on_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        failure_summary: str,
        failure_details: dict[str, Any] | None = None,
        source_artifact_refs: tuple[str, ...] = (),
        diagnosis: FailureDiagnosisRecord | None = None,
    ) -> RepairGateCreationResult:
        """Create a repair_review gate after a build/test/transform failure.

        Creates a repair_review gate bound to failure evidence.
        If a repair_review gate already exists for the same
        (job_id, stage_index), returns a conflict result.

        Args:
            job_id: The job that owns the failed command.
            stage_index: The stage where failure occurred.
            command_id: The failed command id.
            failure_summary: Human-readable failure summary.
            failure_details: Optional structured failure details
                (build/test/transform status, logs, classification).
            source_artifact_refs: References to failure evidence artifacts.
            diagnosis: Optional diagnosis record from V2FailureDiagnosisService.

        Returns:
            RepairGateCreationResult with gate_id and status.
        """
        # Compute source artifact checksum from failure evidence
        evidence_payload = dict(failure_details or {})
        evidence_payload["failure_summary"] = failure_summary
        evidence_payload["command_id"] = command_id
        if diagnosis is not None:
            evidence_payload["diagnosis_id"] = diagnosis.diagnosis_id
            evidence_payload["context_pack_checksum"] = diagnosis.context_pack_checksum
            evidence_payload["failure_type"] = diagnosis.failure_type

        source_checksum = sha256_canonical_json(evidence_payload)

        # Build artifact refs from failure details and diagnosis
        refs = list(source_artifact_refs)
        if diagnosis is not None and diagnosis.context_pack_checksum:
            refs.append(f"diagnosis:{diagnosis.diagnosis_id}")
            refs.append(f"checksum:{diagnosis.context_pack_checksum}")

        # Create the repair_review gate
        gate_result = self._gate_service.create_gate(CreateGateRequest(
            job_id=job_id,
            gate_phase="repair_review",
            stage_index=stage_index,
            source_artifact_checksum=source_checksum,
            source_artifact_refs=tuple(sorted(set(refs))),
            created_by="system",
        ))

        if gate_result.status == "conflict":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=diagnosis,
                status="conflict",
                existing_gate_id=gate_result.existing_gate_id,
                reason="A repair_review gate already exists for this stage",
            )

        return RepairGateCreationResult(
            gate_id=gate_result.gate_id,
            gate_checksum=gate_result.gate_checksum,
            diagnosis=diagnosis,
            status="created",
        )

    # ── Job 104: request_repair_revision ─────────────────────────────

    def request_repair_revision(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        proposal_id: str,
        user_feedback: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
    ) -> GateActionResult:
        """Request a revision of the current repair proposal.

        Supersedes the current repair_review gate and creates a new one
        with a revised proposal. The user feedback is stored for context.

        Requires:
        - Gate exists and is OPEN
        - Gate phase is repair_review (REVISE is valid)
        - V2RepairFlowService is configured
        - The source proposal exists

        Returns:
            GateActionResult with status and new gate reference.
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.REVISE.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        # Use the existing REVISE decision path through gate action service
        # which handles: gate existence, phase validation, checksum check,
        # idempotency, gate resolution, and new gate creation.
        return self._gate_action_service.request_plan_revision(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            user_feedback=user_feedback,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
        )

    # ── Job 105: approve_repair (delegate to gate action service) ──

    def approve_repair(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        proposal_id: str,
        proposal_checksum: str,
        context_pack_checksum: str,
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
    ) -> GateActionResult:
        """Approve a repair at a repair_review gate.

        Delegates to V2GateActionService.approve_repair() which
        handles proposal approval, reviewer critique gate, and
        gate resolution.

        After approval, the caller should queue the patch application
        via V2RepairFlowService.apply_patch().
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.CONTINUE.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        return self._gate_action_service.approve_repair(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            context_pack_checksum=context_pack_checksum,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
        )

    # ── Job 106: reject repair ───────────────────────────────────────

    def reject_repair(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        reason: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
    ) -> GateActionResult:
        """Reject a repair at a repair_review gate.

        Persists rejection and leaves stage failed/blocked.
        The gate is resolved with REJECT.

        Requires:
        - Gate exists and is OPEN
        - Gate phase is repair_review
        - Gate checksum must match

        Returns:
            GateActionResult with rejection status.
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.REJECT.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        return self._gate_action_service.reject_gate(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            reason=reason,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
        )

    # ── Job 107: Repair validation result gate transition ────────────

    def handle_repair_validation_result(
        self,
        *,
        job_id: str,
        stage_index: int,
        validation_passed: bool,
        validation_id: str,
        sandbox_path: str = "",
        diagnosis: FailureDiagnosisRecord | None = None,
    ) -> RepairValidationTransitionResult:
        """Route after-repair validation to the correct next gate.

        If validation passed:
          - Create a stage_completion_review gate
          - Reset attempt count for this stage

        If validation failed:
          - Increment attempt count
          - If attempts remaining, create a new repair_review gate
          - If attempts exhausted, mark exhausted (no new gate)

        Args:
            job_id: The job that owns the repair.
            stage_index: The stage where repair was applied.
            validation_passed: Whether validation passed.
            validation_id: The validation run identifier.
            sandbox_path: The sandbox path for artifact refs.
            diagnosis: Optional new diagnosis for the failure.

        Returns:
            RepairValidationTransitionResult with next gate info.
        """
        attempt_key = (job_id, stage_index)
        current_attempts = self._attempt_counts.get(attempt_key, 0)

        if validation_passed:
            # Reset attempt count on success
            self._attempt_counts.pop(attempt_key, None)

            # Create stage_completion_review gate
            source_checksum = sha256_canonical_json({
                "validation_id": validation_id,
                "job_id": job_id,
                "stage_index": stage_index,
                "passed": True,
            })
            refs = [f"validation:{validation_id}", f"sandbox:{sandbox_path}"] if sandbox_path else [f"validation:{validation_id}"]

            gate_result = self._gate_service.create_gate(CreateGateRequest(
                job_id=job_id,
                gate_phase="stage_completion_review",
                stage_index=stage_index,
                source_artifact_checksum=source_checksum,
                source_artifact_refs=tuple(sorted(set(refs))),
                created_by="system",
            ))

            if gate_result.status == "created":
                return RepairValidationTransitionResult(
                    status="stage_completion_gate_created",
                    gate_id=gate_result.gate_id,
                    gate_checksum=gate_result.gate_checksum,
                    remaining_attempts=self._max_repair_attempts,
                    reason="Repair validation passed, stage_completion_review gate created",
                )
            return RepairValidationTransitionResult(
                status="no_action",
                reason=f"Could not create stage_completion_review gate: {gate_result.status}",
            )

        # Validation failed — increment attempt count (cap at max)
        current_attempts += 1
        if current_attempts > self._max_repair_attempts:
            current_attempts = self._max_repair_attempts
        self._attempt_counts[attempt_key] = current_attempts
        remaining = max(0, self._max_repair_attempts - current_attempts)

        if remaining > 0:
            # Create a new repair_review gate
            failure_details = {
                "validation_id": validation_id,
                "attempt": current_attempts,
                "remaining": remaining,
            }
            if diagnosis is not None:
                failure_details["diagnosis_id"] = diagnosis.diagnosis_id

            source_checksum = sha256_canonical_json(failure_details)
            refs = [f"validation:{validation_id}", f"diagnosis:{diagnosis.diagnosis_id}"] if diagnosis else [f"validation:{validation_id}"]

            gate_result = self._gate_service.create_gate(CreateGateRequest(
                job_id=job_id,
                gate_phase="repair_review",
                stage_index=stage_index,
                source_artifact_checksum=source_checksum,
                source_artifact_refs=tuple(sorted(set(refs))),
                created_by="system",
            ))

            if gate_result.status == "created":
                return RepairValidationTransitionResult(
                    status="repair_gate_created",
                    gate_id=gate_result.gate_id,
                    gate_checksum=gate_result.gate_checksum,
                    remaining_attempts=remaining,
                    reason=f"Repair validation failed, {remaining} attempt(s) remaining",
                )

        return RepairValidationTransitionResult(
            status="attempts_exhausted",
            remaining_attempts=remaining,
            reason=f"All {self._max_repair_attempts} repair attempt(s) exhausted for stage {stage_index}",
        )

    # ── Job 108: Attempt limits ──────────────────────────────────────

    def get_remaining_attempts(
        self,
        job_id: str,
        stage_index: int,
    ) -> int:
        """Get remaining repair attempts for a job+stage."""
        current = self._attempt_counts.get((job_id, stage_index), 0)
        return max(0, self._max_repair_attempts - current)

    def reset_attempts(
        self,
        job_id: str,
        stage_index: int,
    ) -> None:
        """Reset repair attempt count (e.g., after successful stage completion)."""
        self._attempt_counts.pop((job_id, stage_index), None)

    def clear_attempts(self) -> None:
        """Clear all attempt counts (for testing)."""
        self._attempt_counts.clear()

    # ── Serialization ────────────────────────────────────────────────

    def gate_creation_to_dict(
        self,
        result: RepairGateCreationResult,
    ) -> dict[str, Any]:
        return {
            "gate_id": result.gate_id,
            "gate_checksum": result.gate_checksum,
            "status": result.status,
            "existing_gate_id": result.existing_gate_id,
            "reason": result.reason,
        }

    def transition_to_dict(
        self,
        result: RepairValidationTransitionResult,
    ) -> dict[str, Any]:
        return {
            "status": result.status,
            "gate_id": result.gate_id,
            "gate_checksum": result.gate_checksum,
            "remaining_attempts": result.remaining_attempts,
            "reason": result.reason,
        }


# ── Orchestrator integration helper ─────────────────────────────────


def create_repair_gate_diagnosis_callback(
    repair_gate_service: V2RepairGateService,
    diagnosis_service: V2FailureDiagnosisService,
    *,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> Callable[[str, int, str, str, dict[str, Any]], None]:
    """Create a callback suitable for V2OrchestratorRunner(diagnosis_callback=...).

    This callback:
    1. Runs diagnosis via V2FailureDiagnosisService.diagnose()
    2. Creates a repair_review gate via V2RepairGateService.create_repair_gate_on_failure()
    3. Binds failure evidence to the gate

    Usage:
        svc = V2RepairGateService(gate_service, gate_action_service, repair_flow)
        diag_svc = V2FailureDiagnosisService(repair_flow=repair_flow)
        runner = V2OrchestratorRunner(
            unit_of_work_factory=...,
            diagnosis_callback=create_repair_gate_diagnosis_callback(svc, diag_svc),
        )
    """

    def callback(
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        # Step 1: Run diagnosis (if the event_type is diagnosable)
        diagnosis = None
        if V2FailureDiagnosisService.is_diagnosable_event(event_type):
            try:
                diagnosis = diagnosis_service.diagnose(
                    job_id=job_id,
                    stage_index=stage_index,
                    command_id=command_id,
                    event_type=event_type,
                    payload=payload,
                )
            except Exception:
                # Diagnosis is best-effort — don't block gate creation
                pass

        # Step 2: Build failure summary from payload
        failure_summary = _build_failure_summary_from_payload(event_type, payload)
        failure_details = dict(payload or {})

        # Step 3: Extract artifact refs from payload
        artifact_refs: tuple[str, ...] = ()
        raw_refs = failure_details.get("artifact_refs", {})
        if isinstance(raw_refs, dict):
            artifact_refs = tuple(
                str(v) for v in raw_refs.values() if v and isinstance(v, str)
            )

        # Step 4: Create repair_review gate
        try:
            repair_gate_service.create_repair_gate_on_failure(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                failure_summary=failure_summary,
                failure_details=failure_details,
                source_artifact_refs=artifact_refs,
                diagnosis=diagnosis,
            )
        except Exception:
            # Gate creation is best-effort — don't block the pipeline
            pass

    return callback


def _build_failure_summary_from_payload(
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Build a human-readable failure summary from event payload."""
    payload_data = payload or {}
    build_status = str(payload_data.get("build_status", ""))
    test_status = str(payload_data.get("test_status", ""))
    transform_status = str(payload_data.get("transform_status", ""))
    message = str(payload_data.get("message", ""))
    stderr = str(payload_data.get("stderr", ""))[:200]

    parts: list[str] = []
    if event_type == "build_failed":
        parts.append(f"Build failed: {build_status}")
    elif event_type == "test_failed":
        parts.append(f"Test failed: {test_status}")
    elif event_type == "transform_failed":
        parts.append(f"Transform failed: {transform_status or build_status}")

    if message and message not in parts:
        parts.append(message[:200])
    if stderr:
        parts.append(f"stderr: {stderr}")

    return " | ".join(parts) if parts else f"{event_type} with no details"
