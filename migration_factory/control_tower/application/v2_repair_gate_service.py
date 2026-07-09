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
import threading
from dataclasses import dataclass
from pathlib import Path
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
    sha256_hex,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import ArtifactRevisionRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_artifact_revision_repository import (
    SqliteArtifactRevisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    V2RepairProposalRecord,
)
from migration_factory.control_tower.schemas.phase_gate import GateDecision
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal


# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_MAX_REPAIR_ATTEMPTS = 3

_REPAIR_ATTEMPT_DEDUPE_LOCK = threading.Lock()
_REPAIR_ATTEMPT_DEDUPE_KEYS: set[str] = set()


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
    revision_id: str = ""
    policy_validation_checksum: str = ""


@dataclass(frozen=True)
class RepairValidationTransitionResult:
    """Result of a repair validation transition."""

    status: str  # stage_completion_gate_created, repair_gate_created, attempts_exhausted, no_action
    gate_id: str | None = None
    gate_checksum: str = ""
    remaining_attempts: int = 0
    reason: str = ""


@dataclass(frozen=True)
class ReviewedRepairProposalCreationResult:
    status: str
    proposal_id: str = ""
    reason: str = ""
    event_id: str | None = None
    reviewer_decision: str | None = None
    diff_checksum: str | None = None
    attempt_number: int = 0
    remaining_attempts: int = 0


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
        revision_repo: SqliteArtifactRevisionRepository | None = None,
        max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._gate_service = gate_service
        self._gate_action_service = gate_action_service
        self._repair_flow = repair_flow
        self._diagnosis_service = diagnosis_service
        self._revision_repo = revision_repo
        self._max_repair_attempts = max_repair_attempts

        # In-memory attempt tracking: {(job_id, stage_index): attempt_count}
        self._attempt_counts: dict[tuple[str, int], int] = {}

    def create_repair_gate_from_reviewed_chain(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        review_chain_result: dict[str, Any],
        failure_evidence_checksum: str,
        context_pack_checksum: str,
        base_repo_state_checksum: str,
        sandbox_path: str,
        run_dir: str,
        legacy_path: str,
        deterministic_rule_id: str,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Open a repair_review gate only from an accepted reviewed repair chain."""
        chain = review_chain_result.get("review_chain")
        if not isinstance(chain, dict):
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="missing review_chain metadata",
            )
        if str(chain.get("reviewer_decision") or "") != "accept":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewer did not accept repair chain",
            )

        primary_ref = str(chain.get("primary_output_ref") or "")
        final_diff_ref = str(chain.get("final_diff_ref") or "")
        final_artifact_ref = str(chain.get("final_artifact_ref") or "")
        if not primary_ref or not final_diff_ref or not final_artifact_ref:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewed repair chain missing artifact refs",
            )

        primary = json.loads(open(primary_ref, encoding="utf-8").read())
        reviewed_diff = open(final_diff_ref, encoding="utf-8").read()
        policy_result = evaluate_patch_proposal(
            proposal={
                "deterministic_rule_id": deterministic_rule_id,
                "risk": str(primary.get("risk") or "LOW"),
                "requires_human_review": False,
                "unified_diff": reviewed_diff,
            },
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            h2_required=h2_required,
        )
        policy_payload = {
            "status": policy_result.status.lower(),
            "reason": policy_result.reason,
            "rule_id": policy_result.rule_id,
            "risk": policy_result.risk,
            "touched_paths": list(policy_result.touched_paths),
            "human_review_required": policy_result.human_review_required,
        }
        policy_checksum = sha256_canonical_json(policy_payload)
        policy_path = Path(run_dir) / "repairs" / "repair_policy_validation.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps({**policy_payload, "policy_validation_checksum": policy_checksum}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if policy_result.status != "ALLOWED":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"repair policy validation failed: {policy_result.status}",
                policy_validation_checksum=policy_checksum,
            )

        required_binding = {
            "failure_evidence_checksum": failure_evidence_checksum,
            "context_pack_checksum": context_pack_checksum,
            "primary_output_checksum": str(chain.get("primary_output_checksum") or ""),
            "reviewer_output_checksum": str(chain.get("reviewer_output_checksum") or ""),
            "final_reviewed_diff_checksum": str(chain.get("proposed_diff_checksum") or ""),
            "policy_validation_checksum": policy_checksum,
            "base_repo_state_checksum": base_repo_state_checksum,
            "final_artifact_checksum": str(chain.get("final_artifact_checksum") or ""),
        }
        if any(not value for value in required_binding.values()):
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewed repair gate missing required checksum binding",
                policy_validation_checksum=policy_checksum,
            )
        source_checksum = sha256_canonical_json(required_binding)
        refs = tuple(sorted({
            str(chain.get("deterministic_artifact_ref") or ""),
            primary_ref,
            str(chain.get("reviewer_output_ref") or ""),
            final_artifact_ref,
            final_diff_ref,
            str(chain.get("review_chain_metadata_ref") or ""),
            str(policy_path),
            *[f"{key}:{value}" for key, value in required_binding.items()],
        } - {""}))
        gate_result = self._gate_service.create_gate(CreateGateRequest(
            job_id=job_id,
            gate_phase="repair_review",
            stage_index=stage_index,
            source_artifact_checksum=source_checksum,
            source_artifact_refs=refs,
            created_by="system",
        ))
        if gate_result.status == "conflict":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="conflict",
                existing_gate_id=gate_result.existing_gate_id,
                reason="A repair_review gate already exists for this stage",
                policy_validation_checksum=policy_checksum,
            )

        revision_id = ""
        if self._revision_repo is not None:
            revision_id = uuid4().hex
            self._revision_repo.save(ArtifactRevisionRecord(
                revision_id=revision_id,
                job_id=job_id,
                stage_index=stage_index,
                revision_kind="repair",
                revision_status="draft",
                revision_order=0,
                evidence_checksum=source_checksum,
                prior_revision_checksum=None,
                artifact_refs_json=json.dumps(list(refs), separators=(",", ":")),
                prior_revision_id=None,
                superseded_by_revision_id=None,
                accepted_at_gate_id=None,
                created_at=utc_now_text(),
                created_by="system",
            ))
        return RepairGateCreationResult(
            gate_id=gate_result.gate_id,
            gate_checksum=gate_result.gate_checksum,
            diagnosis=None,
            status="created",
            revision_id=revision_id,
            policy_validation_checksum=policy_checksum,
        )

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

    # ── Option A: Create reviewed repair proposal directly (no gate) ──

    def create_reviewed_repair_proposal_on_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        failure_payload: dict[str, Any],
        model_client: Any | None = None,
        invocation_ledger: Any | None = None,
        uow: Any | None = None,
    ) -> ReviewedRepairProposalCreationResult:
        refs = _extract_repair_refs_from_payload(failure_payload)
        if not refs["failure_evidence_ref"] or not refs["repair_context_ref"]:
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason="missing repair evidence refs",
            )
        result = self._create_reviewed_repair_proposal_from_refs(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            failure_evidence_ref=refs["failure_evidence_ref"],
            repair_context_ref=refs["repair_context_ref"],
            run_dir=refs["run_dir"],
            sandbox_path=refs["sandbox_path"],
            legacy_path=str(failure_payload.get("legacy_path", "")),
            source_profile=str(failure_payload.get("source_profile", "")),
            target_profile=str(failure_payload.get("target_profile", "")),
            h2_required=bool(failure_payload.get("_repair_h2_required", False)),
            model_client=model_client,
            invocation_ledger=invocation_ledger,
            uow=uow,
        )
        if uow is not None:
            if result.status == "created":
                event = uow.v2_events.save(
                    job_id=job_id,
                    stage=stage_index,
                    event_type="repair_proposal_ready",
                    status="ready",
                    message=f"Reviewed repair proposal ready for command {command_id}",
                    payload={
                        "proposal_id": result.proposal_id,
                        "job_id": job_id,
                        "stage_index": stage_index,
                        "command_id": command_id,
                        "diff_checksum": result.diff_checksum,
                        "reviewer_decision": result.reviewer_decision,
                        "attempt_number": result.attempt_number,
                        "remaining_attempts": result.remaining_attempts,
                    },
                )
                result = ReviewedRepairProposalCreationResult(
                    status=result.status,
                    proposal_id=result.proposal_id,
                    reason=result.reason,
                    event_id=event.event_id,
                    reviewer_decision=result.reviewer_decision,
                    diff_checksum=result.diff_checksum,
                    attempt_number=result.attempt_number,
                    remaining_attempts=result.remaining_attempts,
                )
            else:
                unavailable_event_type = (
                    "repair_attempts_exhausted"
                    if result.status == "attempts_exhausted"
                    else "reviewed_repair_unavailable"
                )
                uow.v2_events.save(
                    job_id=job_id,
                    stage=stage_index,
                    event_type=unavailable_event_type,
                    status="failed" if result.status == "attempts_exhausted" else "skipped",
                    message=result.reason or "Reviewed repair proposal unavailable.",
                    payload={
                        "job_id": job_id,
                        "stage_index": stage_index,
                        "command_id": command_id,
                        "reviewer_decision": result.reviewer_decision,
                        "attempt_number": result.attempt_number,
                        "remaining_attempts": result.remaining_attempts,
                    },
                )
                uow.v2_events.save(
                    job_id=job_id,
                    stage=stage_index,
                    event_type="repair_completed",
                    status="blocked",
                    message=f"Repair {unavailable_event_type}: {result.reason or 'No proposal could be created.'}",
                    payload={
                        "command_id": command_id,
                        "unavailable_reason": unavailable_event_type,
                    },
                )
        return result

    def _create_reviewed_repair_proposal_from_refs(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        failure_evidence_ref: str,
        repair_context_ref: str,
        run_dir: str,
        sandbox_path: str,
        legacy_path: str = "",
        source_profile: str = "",
        target_profile: str = "",
        h2_required: bool = False,
        model_client: Any | None = None,
        invocation_ledger: Any | None = None,
        uow: Any | None = None,
    ) -> ReviewedRepairProposalCreationResult:
        """Create a reviewed repair proposal from failure artifacts (Option A direct path).

        Loads persisted failure evidence and context pack, runs the
        proposer/reviewer LLM chain, and persists exactly one proposal
        if reviewer accepts.
        Does NOT create a repair_review gate. The proposal is the
        authorization artifact.
        """
        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )
        from migration_factory.control_tower.application.safe_diff_preview import (
            build_safe_diff_preview,
        )

        # 1. Load failure evidence
        evidence_path = Path(failure_evidence_ref)
        if not evidence_path.is_file():
            return ReviewedRepairProposalCreationResult(
                status="skipped", reason="failure_evidence_ref file not found"
            )
        try:
            evidence_dict = json.loads(evidence_path.read_text(encoding="utf-8"))
            evidence = _failure_evidence_from_dict(evidence_dict)
        except Exception as exc:
            return ReviewedRepairProposalCreationResult(
                status="skipped", reason=f"failed to load failure evidence: {exc}"
            )

        # 2. Load context pack
        context_path = Path(repair_context_ref)
        if not context_path.is_file():
            return ReviewedRepairProposalCreationResult(
                status="skipped", reason="repair_context_ref file not found"
            )
        try:
            context_dict = json.loads(context_path.read_text(encoding="utf-8"))
            context_pack = _context_pack_from_dict(context_dict)
        except Exception as exc:
            return ReviewedRepairProposalCreationResult(
                status="skipped", reason=f"failed to load context pack: {exc}"
            )

        # 3. Determine attempt number
        persisted_attempts = self._get_persisted_attempt_count(job_id, stage_index)
        if uow is not None and hasattr(uow, "v2_repairs"):
            try:
                direct_attempts = [
                    int(getattr(record, "attempt_number", 0) or 0)
                    for record in uow.v2_repairs.list_proposals_by_job(job_id)
                    if int(getattr(record, "route_step_index", -1) or -1) == stage_index
                ]
                if direct_attempts:
                    persisted_attempts = max(persisted_attempts, max(direct_attempts))
            except Exception as exc:
                import logging
                logging.getLogger("v2_repair_gate_service").exception(
                    "AMF-252 attempt count lookup failed: %s", exc
                )
        attempt_number = persisted_attempts + 1
        if attempt_number > self._max_repair_attempts:
            return ReviewedRepairProposalCreationResult(
                status="attempts_exhausted",
                reason=f"All {self._max_repair_attempts} repair attempt(s) exhausted for stage {stage_index}",
                attempt_number=attempt_number,
                remaining_attempts=0,
            )
        remaining_attempts = max(0, self._max_repair_attempts - attempt_number)

        # 4. Run review chain
        output_dir = Path(run_dir) / "repair_chain"
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=source_profile or evidence.source_profile,
                target_profile=target_profile or evidence.target_profile,
                model_client=model_client,
                invocation_ledger=invocation_ledger,
            )
        except Exception as exc:
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason=f"review chain production failed: {exc}",
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        review_chain = chain_result.get("review_chain") or {}
        reviewer_decision = str(review_chain.get("reviewer_decision") or "")

        # 5. Only accept creates a proposal
        if reviewer_decision != "accept":
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason=f"reviewer decision was '{reviewer_decision}'",
                reviewer_decision=reviewer_decision,
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        # 6. Read final diff
        final_diff_ref = str(review_chain.get("final_diff_ref") or "")
        if not final_diff_ref:
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason="review chain missing final_diff_ref",
                reviewer_decision=reviewer_decision,
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        diff_path = Path(final_diff_ref)
        if not diff_path.is_file():
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason=f"final diff file not found: {final_diff_ref}",
                reviewer_decision=reviewer_decision,
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        try:
            diff_bytes = diff_path.read_bytes()
            if not diff_bytes:
                return ReviewedRepairProposalCreationResult(
                    status="skipped",
                    reason="final diff is empty",
                    reviewer_decision=reviewer_decision,
                    attempt_number=attempt_number,
                    remaining_attempts=remaining_attempts,
                )
        except OSError as exc:
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason=f"failed to read final diff: {exc}",
                reviewer_decision=reviewer_decision,
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        # 7. Compute raw-byte checksum
        diff_checksum = sha256_hex(diff_bytes)

        # 8. Build SafeDiffPreview to validate applyability
        try:
            preview = build_safe_diff_preview(
                proposal_id="",
                diff_ref=final_diff_ref,
                diff_text=diff_bytes.decode("utf-8", errors="replace"),
                stored_diff_checksum=diff_checksum,
            )
            if preview.checksum_mismatch or getattr(preview, "parse_status", "ok") != "ok":
                return ReviewedRepairProposalCreationResult(
                    status="skipped",
                    reason="safe diff preview is not applyable",
                    reviewer_decision=reviewer_decision,
                    attempt_number=attempt_number,
                    remaining_attempts=remaining_attempts,
                )
            if not preview.files:
                return ReviewedRepairProposalCreationResult(
                    status="skipped",
                    reason="safe diff preview parsed zero files (diff may be unparseable)",
                    reviewer_decision=reviewer_decision,
                    attempt_number=attempt_number,
                    remaining_attempts=remaining_attempts,
                )
        except (ValueError, OSError) as exc:
            return ReviewedRepairProposalCreationResult(
                status="skipped",
                reason=f"failed to build safe diff preview: {exc}",
                reviewer_decision=reviewer_decision,
                attempt_number=attempt_number,
                remaining_attempts=remaining_attempts,
            )

        # 9. Persist proposal (duplicate check for same command_id)
        if uow is not None:
            existing = list(uow.v2_repairs.list_proposals_by_command(command_id))
            for existing_record in existing:
                if (getattr(existing_record, "status", "") in
                    frozenset({"user_review_required", "approvable", "reviewer_accepted"})):
                    return ReviewedRepairProposalCreationResult(
                        status="conflict",
                        proposal_id=existing_record.proposal_id,
                        reason="active proposal already exists for this command",
                        reviewer_decision=reviewer_decision,
                        diff_checksum=diff_checksum,
                        attempt_number=getattr(existing_record, "attempt_number", None) or attempt_number,
                        remaining_attempts=remaining_attempts,
                    )

        proposal_id = uuid4().hex
        created_at = utc_now_text()

        record = V2RepairProposalRecord(
            proposal_id=proposal_id,
            command_id=command_id,
            job_id=job_id,
            route_step_index=stage_index,
            failure_summary=str(evidence.failure_summary),
            hypothesis=str(review_chain.get("root_cause", "")),
            patch_summary=str(review_chain.get("fix_strategy", "")),
            affected_paths_json=json.dumps(review_chain.get("changed_files", [])),
            status="user_review_required",
            approval_checksum=None,
            created_at=created_at,
            attempt_number=attempt_number,
            remaining_attempts=remaining_attempts,
            failure_evidence_ref=failure_evidence_ref,
            repair_context_ref=repair_context_ref,
            diff_ref=final_diff_ref,
            diff_checksum=diff_checksum,
            reviewer_output_checksum=str(review_chain.get("reviewer_output_checksum", "")),
            policy_validation_checksum=str(review_chain.get("policy_validation_checksum", "")),
            gate_id=None,
            reviewer_verdict_id=None,
            reviewer_decision=reviewer_decision,
        )

        if uow is not None:
            uow.v2_repairs.save_proposal(record)

        # Track attempt in memory
        self._attempt_counts[(job_id, stage_index)] = attempt_number

        return ReviewedRepairProposalCreationResult(
            status="created",
            proposal_id=proposal_id,
            reason="reviewer accepted repair chain",
            reviewer_decision=reviewer_decision,
            diff_checksum=diff_checksum,
            attempt_number=attempt_number,
            remaining_attempts=remaining_attempts,
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
        command_id: str = "",
        model_client: Any | None = None,
        prior_apply_rerun_info: dict[str, Any] | None = None,
        source_profile: str = "",
        target_profile: str = "",
        sandbox_path: str = "",
        run_dir: str | Path = "",
        legacy_path: str = "",
        deterministic_rule_id: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        cycle_number: int = 1,
        h2_required: bool = False,
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

        should_regenerate = bool(
            model_client is not None
            and command_id
            and sandbox_path
            and str(run_dir)
            and legacy_path
            and deterministic_rule_id
        )

        # Use the repair-specific revise path so the revision history
        # remains tagged as repair, not planning.
        base_result = self._gate_action_service.request_repair_revision(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            proposal_id=proposal_id,
            user_feedback=user_feedback,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            open_followup_gate=not should_regenerate,
        )

        if base_result.status not in ("executed", "idempotent") or not should_regenerate:
            return base_result

        gate = self._gate_service._gate_repo.get(gate_id) if self._gate_service is not None else None
        if gate is None:
            return base_result

        refs = _parse_gate_ref_checksums(gate.source_artifact_refs_json)
        previous_checksums = previous_repair_review_checksums or (
            gate.source_artifact_checksum,
        )
        reviewed_result = self.regenerate_reviewed_repair_chain_on_revision(
            job_id=job_id,
            stage_index=gate.stage_index,
            command_id=command_id,
            user_comments=user_feedback,
            prior_evidence_checksum=refs.get("failure_evidence_checksum", gate.source_artifact_checksum),
            prior_context_checksum=refs.get("context_pack_checksum", ""),
            prior_primary_output_checksum=refs.get("primary_output_checksum", ""),
            prior_reviewer_output_checksum=refs.get("reviewer_output_checksum", ""),
            prior_final_diff_checksum=refs.get("final_reviewed_diff_checksum", ""),
            prior_policy_validation_checksum=refs.get("policy_validation_checksum", ""),
            prior_base_repo_state_checksum=refs.get("base_repo_state_checksum", ""),
            prior_apply_rerun_info=prior_apply_rerun_info,
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            source_profile=source_profile,
            target_profile=target_profile,
            previous_repair_review_checksums=previous_checksums,
            cycle_number=cycle_number,
            model_client=model_client,
            h2_required=h2_required,
        )
        if reviewed_result.status == "created":
            return GateActionResult(
                action=base_result.action,
                gate_id=base_result.gate_id,
                decision_id=base_result.decision_id,
                status=base_result.status,
                result_gate_id=reviewed_result.gate_id,
                result_command_id=base_result.result_command_id,
                result_revision_id=reviewed_result.revision_id or base_result.result_revision_id,
                reason=base_result.reason or reviewed_result.reason,
            )

        return GateActionResult(
            action=base_result.action,
            gate_id=base_result.gate_id,
            decision_id=base_result.decision_id,
            status=reviewed_result.status,
            result_gate_id=reviewed_result.gate_id or base_result.result_gate_id,
            result_command_id=base_result.result_command_id,
            result_revision_id=reviewed_result.revision_id or base_result.result_revision_id,
            reason=reviewed_result.reason or base_result.reason,
        )

    # ── F5: Regenerate reviewed repair chain on revision ───────────────

    def regenerate_reviewed_repair_chain_on_revision(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        user_comments: str = "",
        prior_evidence_checksum: str,
        prior_context_checksum: str,
        prior_primary_output_checksum: str,
        prior_reviewer_output_checksum: str,
        prior_final_diff_checksum: str,
        prior_policy_validation_checksum: str,
        prior_base_repo_state_checksum: str,
        prior_apply_rerun_info: dict[str, Any] | None = None,
        sandbox_path: str,
        run_dir: str | Path,
        legacy_path: str,
        deterministic_rule_id: str,
        source_profile: str = "",
        target_profile: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        cycle_number: int = 1,
        model_client: Any | None = None,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Regenerate a full Azure repair review chain after user revision request.

        Builds a new RepairContextPack including prior cycle context and user
        comments, calls produce_repair_review_chain() with Azure
        proposer/reviewer routing, policy-validates the new final diff, and
        opens a new repair_review gate if accepted.

        No old artifact mutation. No patch apply on revision.
        """
        from pathlib import Path as _Path
        from migration_factory.repair_loop.failure_evidence import (
            FailureSource,
            build_failure_evidence,
        )
        from migration_factory.repair_loop.repair_context import (
            build_repair_context_pack,
        )
        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )

        evidence = build_failure_evidence(
            failure_source=FailureSource.BUILD,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            failure_summary=f"Repair revision requested by user: {user_comments[:200] if user_comments else 'no comments'}",
            source_profile=source_profile,
            target_profile=target_profile,
            accepted_artifact_checksums=previous_repair_review_checksums,
        )

        prior_apply = prior_apply_rerun_info or {}
        prior_reviewer_notes: tuple[str, ...] = ()
        if prior_apply.get("reviewer_notes"):
            prior_reviewer_notes = tuple(str(n) for n in prior_apply["reviewer_notes"] if n)

        context_pack = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            source_profile=source_profile or evidence.source_profile,
            target_profile=target_profile or evidence.target_profile,
            prior_proposal_checksums=previous_repair_review_checksums,
            prior_reviewer_notes=prior_reviewer_notes,
            user_comments=user_comments,
            cycle_number=cycle_number,
            max_cycles=self._max_repair_attempts,
        )

        output_dir = _Path(run_dir) / "repair_chain"
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=source_profile or evidence.source_profile,
                target_profile=target_profile or evidence.target_profile,
                model_client=model_client,
            )
        except Exception:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewer did not accept repair chain on revision",
            )

        return self.create_repair_gate_from_reviewed_chain(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            review_chain_result=chain_result,
            failure_evidence_checksum=evidence.content_checksum,
            context_pack_checksum=context_pack.context_pack_checksum,
            base_repo_state_checksum=context_pack.base_repo_state_checksum,
            sandbox_path=sandbox_path,
            run_dir=str(run_dir),
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            h2_required=h2_required,
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
        reviewer_output_checksum: str = "",
        final_reviewed_diff_checksum: str = "",
        policy_validation_checksum: str = "",
        base_repo_state_checksum: str = "",
        final_reviewed_artifact_checksum: str = "",
        repair_revision_id: str = "",
        repair_revision_checksum: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
        actor_type: str = "human",
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

        if actor_type != "human":
            return GateActionResult(
                action=GateDecision.CONTINUE.value,
                gate_id=gate_id,
                decision_id="",
                status="actor_not_authoritative",
                reason=(
                    "approve_repair requires a human actor; "
                    f"received actor_type='{actor_type}'"
                ),
            )

        return self._gate_action_service.approve_repair(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            context_pack_checksum=context_pack_checksum,
            reviewer_output_checksum=reviewer_output_checksum,
            final_reviewed_diff_checksum=final_reviewed_diff_checksum,
            policy_validation_checksum=policy_validation_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            final_reviewed_artifact_checksum=final_reviewed_artifact_checksum,
            repair_revision_id=repair_revision_id,
            repair_revision_checksum=repair_revision_checksum,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            actor_type=actor_type,
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
        actor_type: str = "human",
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

        if actor_type != "human":
            return GateActionResult(
                action=GateDecision.REJECT.value,
                gate_id=gate_id,
                decision_id="",
                status="actor_not_authoritative",
                reason=(
                    "reject_repair requires a human actor; "
                    f"received actor_type='{actor_type}'"
                ),
            )

        return self._gate_action_service.reject_gate(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            reason=reason,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            actor_type=actor_type,
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
        current_attempts = self._get_persisted_attempt_count(job_id, stage_index)

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

    # ── F5: Create next bounded repair cycle after rerun failure ──────

    def create_next_repair_cycle_from_rerun_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        prior_evidence_checksum: str,
        prior_context_checksum: str,
        prior_primary_output_checksum: str,
        prior_reviewer_output_checksum: str,
        prior_final_diff_checksum: str,
        prior_policy_validation_checksum: str,
        prior_base_repo_state_checksum: str,
        apply_result: dict[str, Any] | None = None,
        rerun_result: dict[str, Any] | None = None,
        rollback_result: dict[str, Any] | None = None,
        user_comments: str = "",
        sandbox_path: str,
        run_dir: str | Path,
        legacy_path: str,
        deterministic_rule_id: str,
        source_profile: str = "",
        target_profile: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        max_cycles: int | None = None,
        model_client: Any | None = None,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Create the next bounded repair cycle after rerun validation failure.

        On rerun failure, if attempts remain:
        1. Build new FailureEvidence from rerun failure data
        2. Build new RepairContextPack including full prior cycle context
        3. Call produce_repair_review_chain with Azure proposer/reviewer
        4. Policy-validate the new final diff
        5. Open next repair_review gate with chain info

        If attempts exhausted, create terminal failure artifact.
        """
        from pathlib import Path as _Path
        from migration_factory.repair_loop.failure_evidence import (
            FailureSource,
            build_failure_evidence,
        )
        from migration_factory.repair_loop.repair_context import (
            build_repair_context_pack,
        )
        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )
        from migration_factory.control_tower.domain.checksums import (
            sha256_canonical_json,
        )

        effective_max = max_cycles or self._max_repair_attempts
        current_cycle = len(previous_repair_review_checksums) + 1
        remaining = effective_max - current_cycle
        run_path = _Path(run_dir)
        repairs_dir = run_path / "repairs"
        repairs_dir.mkdir(parents=True, exist_ok=True)

        def _write_cycle_artifact(filename: str, payload: dict[str, Any]) -> tuple[Path, str]:
            checksum = sha256_canonical_json(payload)
            artifact_path = repairs_dir / filename
            artifact_path.write_text(
                json.dumps({**payload, "artifact_checksum": checksum}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return artifact_path, checksum

        if isinstance(rerun_result, dict) and rerun_result:
            rerun_path, rerun_checksum = _write_cycle_artifact(
                "repair_rerun_result.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "rerun_result": dict(rerun_result),
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            rerun_result = {**rerun_result, "artifact_ref": str(rerun_path), "artifact_checksum": rerun_checksum}
        if isinstance(rollback_result, dict) and rollback_result:
            rollback_path, rollback_checksum = _write_cycle_artifact(
                "repair_rollback_result.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "rollback_result": dict(rollback_result),
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            rollback_result = {**rollback_result, "artifact_ref": str(rollback_path), "artifact_checksum": rollback_checksum}

        if remaining < 1:
            _write_cycle_artifact(
                "repair_terminal_failure.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "status": "REPAIR_FAILED",
                    "reason": f"All {effective_max} repair attempt(s) exhausted",
                    "max_cycles": effective_max,
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="attempts_exhausted",
                reason=f"All {effective_max} repair attempt(s) exhausted",
            )

        rerun_payload = dict(rerun_result or {})
        rollback_payload = dict(rollback_result or {})
        apply_payload = dict(apply_result or {})

        failure_summary = f"Rerun validation failed (cycle {current_cycle}/{effective_max})"
        if rerun_payload.get("errors"):
            failure_summary += ": " + "; ".join(str(e) for e in rerun_payload["errors"])

        evidence = build_failure_evidence(
            failure_source=FailureSource.VALIDATION,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            failure_summary=failure_summary,
            source_profile=source_profile,
            target_profile=target_profile,
            accepted_artifact_checksums=previous_repair_review_checksums,
        )

        prior_reviewer_notes: tuple[str, ...] = ()
        if apply_payload.get("reviewer_notes"):
            prior_reviewer_notes = tuple(str(n) for n in apply_payload["reviewer_notes"] if n)

        context_pack = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            source_profile=source_profile or evidence.source_profile,
            target_profile=target_profile or evidence.target_profile,
            prior_proposal_checksums=previous_repair_review_checksums,
            prior_reviewer_notes=prior_reviewer_notes,
            user_comments=user_comments,
            cycle_number=current_cycle,
            max_cycles=effective_max,
        )

        output_dir = _Path(run_dir) / "repair_chain"
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=source_profile or evidence.source_profile,
                target_profile=target_profile or evidence.target_profile,
                model_client=model_client,
            )
        except Exception:
            _write_cycle_artifact(
                "repair_terminal_failure.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "status": "REPAIR_FAILED",
                    "reason": "Azure repair chain production failed on next cycle",
                    "max_cycles": effective_max,
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="attempts_exhausted",
                reason="Azure repair chain production failed on next cycle",
            )

        return self.create_repair_gate_from_reviewed_chain(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            review_chain_result=chain_result,
            failure_evidence_checksum=evidence.content_checksum,
            context_pack_checksum=context_pack.context_pack_checksum,
            base_repo_state_checksum=context_pack.base_repo_state_checksum,
            sandbox_path=sandbox_path,
            run_dir=str(run_dir),
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            h2_required=h2_required,
        )

    # ── Job 108: Attempt limits ──────────────────────────────────────

    def get_remaining_attempts(
        self,
        job_id: str,
        stage_index: int,
    ) -> int:
        """Get remaining repair attempts for a job+stage."""
        current = self._get_persisted_attempt_count(job_id, stage_index)
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

    def _get_persisted_attempt_count(self, job_id: str, stage_index: int) -> int:
        """Derive the attempt count from persisted gate history."""
        if self._gate_service is None or self._gate_service._gate_repo is None:
            return self._attempt_counts.get((job_id, stage_index), 0)

        gates = self._gate_service._gate_repo.list_by_job_and_stage(job_id, stage_index)
        if any(g.gate_phase == "stage_completion_review" for g in gates):
            return 0

        repair_gates = [g for g in gates if g.gate_phase == "repair_review"]
        if not repair_gates:
            return self._attempt_counts.get((job_id, stage_index), 0)

        persisted = max(0, len(repair_gates) - 1)
        return min(self._max_repair_attempts, max(persisted, self._attempt_counts.get((job_id, stage_index), 0)))

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
    uow: Any | None = None,
    model_client: Any | None = None,
    invocation_ledger: Any | None = None,
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
            except Exception as exc:
                import logging
                logging.getLogger("v2_repair_gate_service").exception(
                    "AMF-252 diagnosis callback failed: %s", exc
                )

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

        # AMF-252: Route to reviewed repair proposal creation when internal refs exist
        refs = _extract_repair_refs_from_payload(payload)
        if refs["failure_evidence_ref"] and refs["repair_context_ref"]:
            dedupe_key = _repair_dedupe_key(job_id, stage_index, payload)
            if _is_duplicate_repair_attempt(dedupe_key):
                import logging
                logging.getLogger("v2_repair_gate_service").info(
                    "Skipping duplicate AMF-252 repair attempt",
                    extra={
                        "job_id": job_id,
                        "stage_index": stage_index,
                        "command_id": command_id,
                    },
                )
                return
            try:
                repair_gate_service.create_reviewed_repair_proposal_on_failure(
                    job_id=job_id,
                    stage_index=stage_index,
                    command_id=command_id,
                    failure_payload=payload,
                    model_client=model_client,
                    invocation_ledger=invocation_ledger,
                    uow=uow,
                )
            except Exception as exc:
                import logging
                logging.getLogger("v2_repair_gate_service").exception(
                    "AMF-252 reviewed repair callback failed: %s", exc
                )
            return  # Do not also create a generic gate

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
        except Exception as exc:
            import logging
            logging.getLogger("v2_repair_gate_service").exception(
                "AMF-252 gate creation callback failed: %s", exc
            )

    return callback


def _repair_dedupe_key(job_id: str, stage: int | None, payload: dict[str, Any]) -> str:
    return "|".join([
        str(job_id),
        str(stage or ""),
        str(payload.get("command_id") or ""),
        str(payload.get("_repair_failure_evidence_checksum") or payload.get("failure_evidence_checksum") or ""),
    ])


def _is_duplicate_repair_attempt(key: str) -> bool:
    with _REPAIR_ATTEMPT_DEDUPE_LOCK:
        if key in _REPAIR_ATTEMPT_DEDUPE_KEYS:
            return True
        _REPAIR_ATTEMPT_DEDUPE_KEYS.add(key)
        return False


def _extract_repair_refs_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    failure_evidence_ref = str(payload.get("_repair_failure_evidence_ref") or payload.get("failure_evidence_ref") or "")
    repair_context_ref = str(payload.get("_repair_context_pack_ref") or payload.get("repair_context_ref") or "")
    run_dir = str(payload.get("_repair_run_dir") or payload.get("run_dir") or "")
    sandbox_path = str(payload.get("_repair_sandbox_path") or payload.get("sandbox_path") or "")
    return {
        "failure_evidence_ref": failure_evidence_ref,
        "repair_context_ref": repair_context_ref,
        "run_dir": run_dir,
        "sandbox_path": sandbox_path,
    }


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


def _parse_gate_ref_checksums(source_artifact_refs_json: str) -> dict[str, str]:
    try:
        parsed = json.loads(source_artifact_refs_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, list):
        return {}
    refs: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, str):
            continue
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        if key.endswith("_checksum") or key == "checksum":
            refs[key] = value
    return refs


# ── Deserialization helpers (Option A direct path) ──────────────────


def _failure_evidence_from_dict(data: dict[str, Any]) -> Any:
    """Deserialize FailureEvidence from its to_dict() output."""
    from migration_factory.repair_loop.failure_evidence import (
        FailureEvidence,
        FailureSource,
        NormalizedCompilerError,
        NormalizedTestFailure,
    )
    compiler_errors = tuple(
        NormalizedCompilerError(**e) if isinstance(e, dict) else e
        for e in data.get("compiler_errors", ())
    )
    test_failures = tuple(
        NormalizedTestFailure(**t) if isinstance(t, dict) else t
        for t in data.get("test_failures", ())
    )
    return FailureEvidence(
        failure_source=FailureSource(data.get("failure_source", "UNKNOWN")),
        stage_index=int(data.get("stage_index", 0)),
        job_id=str(data.get("job_id", "")),
        command_id=str(data.get("command_id", "")),
        failure_summary=str(data.get("failure_summary", "")),
        compiler_errors=compiler_errors,
        test_failures=test_failures,
        changed_files=tuple(data.get("changed_files", ())),
        source_profile=str(data.get("source_profile", "")),
        target_profile=str(data.get("target_profile", "")),
        accepted_artifact_checksums=tuple(data.get("accepted_artifact_checksums", ())),
        artifact_refs={str(k): str(v) for k, v in data.get("artifact_refs", {}).items()},
        stdout_tail=str(data.get("stdout_tail", "")),
        stderr_tail=str(data.get("stderr_tail", "")),
        safe_log_preview=str(data.get("safe_log_preview", "")),
        content_checksum=str(data.get("content_checksum", "")),
        artifact_checksum=str(data.get("artifact_checksum", "")),
        created_at=str(data.get("created_at", "")),
        schema_version=str(data.get("schema_version", "1.0.0")),
    )


def _context_pack_from_dict(data: dict[str, Any]) -> Any:
    """Deserialize RepairContextPack from its to_dict() output."""
    from migration_factory.repair_loop.repair_context import RepairContextPack
    return RepairContextPack(
        job_id=str(data.get("job_id", "")),
        stage_index=int(data.get("stage_index", 0)),
        command_id=str(data.get("command_id", "")),
        failure_source=str(data.get("failure_source", "")),
        failure_evidence_checksum=str(data.get("failure_evidence_checksum", "")),
        source_profile=str(data.get("source_profile", "")),
        target_profile=str(data.get("target_profile", "")),
        accepted_analysis_checksum=str(data.get("accepted_analysis_checksum", "")),
        accepted_planning_checksum=str(data.get("accepted_planning_checksum", "")),
        prior_proposal_checksums=tuple(data.get("prior_proposal_checksums", ())),
        prior_reviewer_notes=tuple(data.get("prior_reviewer_notes", ())),
        user_comments=str(data.get("user_comments", "")),
        changed_files=tuple(data.get("changed_files", ())),
        safe_log_preview=str(data.get("safe_log_preview", "")),
        base_repo_state_checksum=str(data.get("base_repo_state_checksum", "")),
        context_pack_checksum=str(data.get("context_pack_checksum", "")),
        prior_revision_ids=tuple(data.get("prior_revision_ids", ())),
        cycle_number=int(data.get("cycle_number", 0)),
        max_cycles=int(data.get("max_cycles", 3)),
        created_at=str(data.get("created_at", "")),
        schema_version=str(data.get("schema_version", "1.0.0")),
    )
