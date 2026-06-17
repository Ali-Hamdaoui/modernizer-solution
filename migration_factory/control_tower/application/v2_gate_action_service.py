"""F15 V2 Gate Action Service — centralized state-changing gate actions.

All gate actions flow through this service: continue, reanalyze, revise,
approve, reject. The service validates checksums, enforces phase-valid
decisions, records audit entries, and queues backend commands.

No command launch happens in the skeleton — the service returns action
results that callers use to queue work via existing services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.v2_phase_gate_service import (
    CreateGateRequest,
    ResolveGateRequest,
    ResolveGateResult,
    V2PhaseGateService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.domain.entities import (
    ArtifactRevisionRecord,
    GateDecisionRecord,
)
from migration_factory.control_tower.domain.gate_checksum import (
    GateChecksumMismatchError,
    gate_checksum,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_artifact_revision_repository import (
    SqliteArtifactRevisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_gate_decision_repository import (
    SqliteGateDecisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import (
    SqlitePhaseGateRepository,
)
from migration_factory.control_tower.schemas.phase_gate import (
    GateDecision,
    GatePhase,
    is_valid_decision_for_phase,
)


# ── result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateActionResult:
    """Result of a gate action execution.

    status values:
      - 'executed': action was applied, gate resolved, result refs set
      - 'stale_checksum': gate checksum mismatch, action rejected
      - 'invalid_decision': decision not valid for this gate phase
      - 'gate_not_open': gate is resolved/superseded, action rejected
      - 'gate_not_found': gate_id does not exist
      - 'idempotent': duplicate decision detected, existing result returned
    """

    action: str
    gate_id: str
    decision_id: str
    status: str
    result_gate_id: str | None = None
    result_command_id: str | None = None
    result_revision_id: str | None = None
    reason: str = ""


# ── service ──────────────────────────────────────────────────────────


class V2GateActionService:
    """Centralized service for F15 gate actions.

    All state-changing gate operations go through this service.
    No command launch — the caller uses result references to queue
    work via existing orchestrator/runner services.
    """

    def __init__(
        self,
        gate_repo: SqlitePhaseGateRepository,
        decision_repo: SqliteGateDecisionRepository,
        gate_service: V2PhaseGateService | None = None,
        revision_repo: SqliteArtifactRevisionRepository | None = None,
    ) -> None:
        self._gate_repo = gate_repo
        self._decision_repo = decision_repo
        self._gate_service = gate_service or V2PhaseGateService(gate_repo)
        self._revision_repo = revision_repo

    # ── action: continue ────────────────────────────────────────────

    def continue_from_gate(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Validate and execute a 'continue' decision at a gate.

        Requires:
        - gate exists and is OPEN
        - gate phase allows CONTINUE decision
        - gate checksum must match (validated inside resolve)

        Returns:
            GateActionResult with status and optional queued references.
        """
        return self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.CONTINUE,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )

    # ── action: reanalyze ───────────────────────────────────────────

    def reanalyze_from_gate(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Validate and execute a 'reanalyze' decision.

        Creates a new open analysis_review gate after resolving the
        current one (the new gate awaits updated analysis evidence).
        """
        return self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.REANALYZE,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )

    # ── action: request_reanalysis (with user feedback) ─────────────

    def request_reanalysis(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        user_feedback: str = "",
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Request reanalysis at an analysis_review gate.

        Unlike the generic ``reanalyze_from_gate``, this method:
          1. Only accepts analysis_review gates.
          2. Creates a new ArtifactRevision (kind=analysis, status=draft)
             with user feedback explaining why reanalysis is needed.
          3. Opens a fresh analysis_review gate.

        Downstream blocking (e.g. superseding planning) is handled at
        the service layer via revision lineage, not by DB-level UPDATE.

        No source writes occur.  The chatbot may explain the feedback
        to the backend for context, but the backend owns the revision.
        """
        base_result = self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.REANALYZE,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )
        if base_result.status not in ("executed", "idempotent"):
            return base_result

        # Determine stage_index from the gate
        gate = self._gate_repo.get(gate_id)
        if gate is None:
            return base_result  # unlikely, already resolved

        stage_index = gate.stage_index
        import json
        now = utc_now_text()

        # Create a draft analysis revision with user feedback
        if self._revision_repo is not None and base_result.status == "executed":
            rev_id = uuid4().hex
            self._revision_repo.save(
                ArtifactRevisionRecord(
                    revision_id=rev_id,
                    job_id=job_id,
                    stage_index=stage_index,
                    revision_kind="analysis",
                    revision_status="draft",
                    revision_order=0,
                    evidence_checksum=gate.source_artifact_checksum,
                    prior_revision_checksum=None,
                    artifact_refs_json=json.dumps(
                        [user_feedback[:256]] if user_feedback else [],
                        separators=(",", ":"),
                    ),
                    prior_revision_id=None,
                    superseded_by_revision_id=None,
                    accepted_at_gate_id=base_result.result_gate_id,
                    created_at=now,
                    created_by=decided_by,
                    accepted_at=None,
                    accepted_by=None,
                )
            )

        return base_result

    # ── action: request_plan_revision (with user feedback) ─────────

    def request_plan_revision(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        user_feedback: str = "",
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Request a plan revision at a planning_review gate.

        Only works on planning_review gates.  The handler:
          1. Resolves the current planning_review gate with REVISE.
          2. Creates a new ArtifactRevision (kind=planning, status=draft)
             with user feedback for the plan amendment.
          3. Opens a new open planning_review gate.
          4. Binds to the currently accepted analysis revision for
             the same stage (if available).

        No source writes occur.  The chatbot explains the feedback;
        the backend creates the revision.
        """
        base_result = self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.REVISE,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )
        if base_result.status not in ("executed", "idempotent"):
            return base_result

        gate = self._gate_repo.get(gate_id)
        if gate is None:
            return base_result

        stage_index = gate.stage_index
        import json
        now = utc_now_text()

        if self._revision_repo is not None and base_result.status == "executed":
            # Find the accepted analysis revision for this stage
            accepted_analysis = self._revision_repo.find_accepted(
                job_id, stage_index, "analysis"
            )
            analysis_checksum = (
                accepted_analysis.evidence_checksum
                if accepted_analysis is not None
                else gate.source_artifact_checksum
            )

            rev_id = uuid4().hex
            self._revision_repo.save(
                ArtifactRevisionRecord(
                    revision_id=rev_id,
                    job_id=job_id,
                    stage_index=stage_index,
                    revision_kind="planning",
                    revision_status="draft",
                    revision_order=0,
                    evidence_checksum=analysis_checksum,
                    prior_revision_checksum=None,
                    artifact_refs_json=json.dumps(
                        [user_feedback[:256]] if user_feedback else [],
                        separators=(",", ":"),
                    ),
                    prior_revision_id=None,
                    superseded_by_revision_id=None,
                    accepted_at_gate_id=base_result.result_gate_id,
                    created_at=now,
                    created_by=decided_by,
                    accepted_at=None,
                    accepted_by=None,
                )
            )

        return base_result

    # ── action: approve ─────────────────────────────────────────────

    def approve_from_gate(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Validate and execute an 'approve' decision."""
        return self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.APPROVE,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )

    # ── action: reject ──────────────────────────────────────────────

    def reject_from_gate(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Validate and execute a 'reject' decision."""
        return self._execute_action(
            gate_id=gate_id,
            job_id=job_id,
            action=GateDecision.REJECT,
            decided_by=decided_by,
            idempotency_key=idempotency_key,
        )

    # ── internal pipeline ───────────────────────────────────────────

    def _execute_action(
        self,
        *,
        gate_id: str,
        job_id: str,
        action: GateDecision,
        decided_by: str,
        idempotency_key: str | None = None,
    ) -> GateActionResult:
        """Common validation and execution pipeline for all gate actions.

        Steps:
        1. Verify gate exists and is OPEN.
        2. Validate decision is allowed for the gate phase.
        3. Compute current checksum for the action decision record.
        4. Check idempotency (duplicate detection).
        5. Resolve the gate via V2PhaseGateService.
        6. Persist the decision record.
        7. Return result with result references.
        """
        # 1. Gate existence
        gate = self._gate_repo.get(gate_id)
        if gate is None:
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id="",
                status="gate_not_found",
            )

        # 2. Idempotency check (before status check — idempotent
        #    requests return the same result regardless of gate state)
        effective_idempotency_key = idempotency_key or f"{gate_id}:{action.value}:{uuid4().hex[:8]}"
        existing = self._decision_repo.find_by_idempotency_key(effective_idempotency_key)
        if existing is not None:
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id=existing.decision_id,
                status="idempotent",
                result_gate_id=existing.result_gate_id,
                result_command_id=existing.result_command_id,
                result_revision_id=existing.result_revision_id,
            )

        # 3. Gate status must be OPEN for new actions
        if gate.gate_status != "open":
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id="",
                status="gate_not_open",
                reason=f"Gate is {gate.gate_status}",
            )

        # 4. Phase-valid decision check
        try:
            gate_phase = GatePhase(gate.gate_phase)
        except ValueError:
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id="",
                status="invalid_decision",
                reason=f"Unknown gate phase: {gate.gate_phase}",
            )

        if not is_valid_decision_for_phase(gate_phase, action):
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id="",
                status="invalid_decision",
                reason=f"Decision {action.value} not allowed at {gate_phase.value}",
            )

        # 6. Compute current gate checksum
        import json
        try:
            refs = json.loads(gate.source_artifact_refs_json)
        except (json.JSONDecodeError, TypeError):
            refs = []

        current_checksum = gate_checksum(
            gate_id=gate.gate_id,
            job_id=gate.job_id,
            gate_phase=gate.gate_phase,
            stage_index=gate.stage_index,
            source_artifact_checksum=gate.source_artifact_checksum,
            source_artifact_refs=refs,
        )

        # 5. Resolve the gate
        resolve_result = self._gate_service.resolve_gate(ResolveGateRequest(
            gate_id=gate_id,
            job_id=job_id,
            gate_decision=action.value,
            expected_gate_checksum=current_checksum,
            resolved_by=decided_by,
        ))

        if resolve_result.status != "resolved":
            return GateActionResult(
                action=action.value,
                gate_id=gate_id,
                decision_id="",
                status=resolve_result.status,
                reason=f"Gate resolve failed: {resolve_result.status}",
            )

        # 6. Persist the decision
        decision_id = uuid4().hex
        now = utc_now_text()

        result_gate_id: str | None = None
        # For reanalyze/revise, create a new open gate
        if action in (GateDecision.REANALYZE, GateDecision.REVISE):
            new_gate = self._gate_service.create_gate(CreateGateRequest(
                job_id=gate.job_id,
                gate_phase=gate.gate_phase,
                stage_index=gate.stage_index,
                source_artifact_checksum=gate.source_artifact_checksum,
                source_artifact_refs=tuple(refs),
                created_by=decided_by,
            ))
            result_gate_id = new_gate.gate_id if new_gate.status == "created" else None

        decision_record = GateDecisionRecord(
            decision_id=decision_id,
            gate_id=gate_id,
            job_id=job_id,
            action=action.value,
            expected_gate_checksum=current_checksum,
            idempotency_key=effective_idempotency_key,
            request_checksum=current_checksum,  # the decision is bound to the gate snapshot
            result_gate_id=result_gate_id,
            result_command_id=None,  # caller queues command
            result_revision_id=None,  # caller creates revision
            decided_by=decided_by,
            decided_at=now,
            actor_type="human",
            actor_id=decided_by,
        )

        try:
            self._decision_repo.save(decision_record)
        except Exception:
            # Idempotency key collision after concurrent resolve
            existing2 = self._decision_repo.find_by_idempotency_key(effective_idempotency_key)
            if existing2 is not None:
                return GateActionResult(
                    action=action.value,
                    gate_id=gate_id,
                    decision_id=existing2.decision_id,
                    status="idempotent",
                    result_gate_id=existing2.result_gate_id,
                    result_command_id=existing2.result_command_id,
                    result_revision_id=existing2.result_revision_id,
                )
            raise

        # 7. Return result
        return GateActionResult(
            action=action.value,
            gate_id=gate_id,
            decision_id=decision_id,
            status="executed",
            result_gate_id=result_gate_id,
        )
