"""Governed human approval for reviewed repair proposals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.v2_repair_flow import (
    RepairProposal,
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    ReviewerCritique,
    V2ReviewerService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalApprovalDecisionRecord,
)


@dataclass(frozen=True)
class RepairProposalApprovalDecision:
    decision_id: str
    proposal_id: str
    operator_decision: str
    approval_checksum: str
    proposal_checksum: str
    context_pack_checksum: str
    reviewer_gate_status: str
    reviewer_critique_id: str | None
    operator_note: str
    created_at: str
    correlation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepairProposalApprovalResult:
    proposal: RepairProposal
    approval_decision: RepairProposalApprovalDecision
    reviewer_gate_status: str
    approval_result: str
    latest_reviewer_decision: str | None
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal": V2RepairFlowService().proposal_to_dict(self.proposal),
            "approval_decision": self.approval_decision.to_dict(),
            "reviewer_gate_status": self.reviewer_gate_status,
            "approval_result": self.approval_result,
            "latest_reviewer_decision": self.latest_reviewer_decision,
            "applied": False,
        }


class V2RepairProposalApprovalService:
    def __init__(
        self,
        *,
        repair_repo: SqliteV2RepairRepository,
        repair_flow: V2RepairFlowService | None = None,
        reviewer_service: V2ReviewerService | None = None,
    ) -> None:
        self._repair_repo = repair_repo
        self._reviewer = reviewer_service or V2ReviewerService()
        self._repair_flow = repair_flow or V2RepairFlowService(
            repair_repo=repair_repo,
            reviewer_service=self._reviewer,
        )

    def decide(
        self,
        *,
        proposal_id: str,
        operator_decision: str,
        approval_checksum: str,
        operator_note: str = "",
        correlation_id: str | None = None,
    ) -> RepairProposalApprovalResult:
        proposal = self._load_proposal(proposal_id)
        self._require_non_applied_status(proposal)
        self._require_bindings(proposal)

        latest_matching = self._latest_matching_reviewer(proposal)
        gate_status = self._gate_status(proposal, latest_matching)

        if operator_decision == "approve":
            if approval_checksum != proposal.proposal_checksum:
                raise ValueError(
                    f"Approval checksum mismatch for proposal {proposal_id!r}: stale proposal checksum"
                )
            if latest_matching is None:
                raise ValueError(
                    f"Proposal {proposal_id!r} cannot be approved: no reviewer accepted critique matches current checksums"
                )
            if latest_matching.decision != "accept":
                raise ValueError(
                    f"Proposal {proposal_id!r} cannot be approved: latest reviewer decision is {latest_matching.decision}"
                )
            updated = self._repair_flow.approve_proposal(
                proposal_id=proposal_id,
                approval_checksum=approval_checksum,
                proposal_checksum=proposal.proposal_checksum,
                context_pack_checksum=proposal.context_pack_checksum or "",
            )
            approval_result = "approved"
            reviewer_critique_id = latest_matching.critique_id
        elif operator_decision == "reject":
            updated = self._repair_flow.reject_proposal(proposal_id)
            approval_result = "rejected"
            reviewer_critique_id = latest_matching.critique_id if latest_matching is not None else None
        else:
            raise ValueError(f"Unsupported operator decision {operator_decision!r}")

        decision = RepairProposalApprovalDecision(
            decision_id=uuid4().hex,
            proposal_id=proposal_id,
            operator_decision=operator_decision,
            approval_checksum=approval_checksum,
            proposal_checksum=proposal.proposal_checksum,
            context_pack_checksum=proposal.context_pack_checksum or "",
            reviewer_gate_status=gate_status,
            reviewer_critique_id=reviewer_critique_id,
            operator_note=operator_note,
            created_at=utc_now_text(),
            correlation_id=correlation_id,
        )
        self._repair_repo.save_approval_decision(
            V2RepairProposalApprovalDecisionRecord(
                decision_id=decision.decision_id,
                proposal_id=decision.proposal_id,
                operator_decision=decision.operator_decision,
                approval_checksum=decision.approval_checksum,
                proposal_checksum=decision.proposal_checksum,
                context_pack_checksum=decision.context_pack_checksum,
                reviewer_gate_status=decision.reviewer_gate_status,
                reviewer_critique_id=decision.reviewer_critique_id,
                operator_note=decision.operator_note,
                created_at=decision.created_at,
                correlation_id=decision.correlation_id,
            )
        )
        return RepairProposalApprovalResult(
            proposal=updated,
            approval_decision=decision,
            reviewer_gate_status=gate_status,
            approval_result=approval_result,
            latest_reviewer_decision=latest_matching.decision if latest_matching is not None else None,
            applied=False,
        )

    def _load_proposal(self, proposal_id: str) -> RepairProposal:
        record = self._repair_repo.get_proposal(proposal_id)
        if record is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        return V2RepairFlowService.record_to_proposal(record)

    @staticmethod
    def _require_non_applied_status(proposal: RepairProposal) -> None:
        if proposal.status == "applied":
            raise ValueError(f"Proposal {proposal.proposal_id!r} is already applied")
        if proposal.status == "rejected":
            raise ValueError(f"Proposal {proposal.proposal_id!r} is already rejected")
        if proposal.status == "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} is already approved")
        if proposal.status != "draft":
            raise ValueError(f"Proposal {proposal.proposal_id!r} cannot be decided from status {proposal.status}")

    @staticmethod
    def _require_bindings(proposal: RepairProposal) -> None:
        if not proposal.proposal_checksum:
            raise ValueError("Proposal is missing required checksum binding: proposal_checksum")
        if not (proposal.context_pack_checksum or "").strip():
            raise ValueError("Proposal is missing required checksum binding: context_pack_checksum")
        if proposal.diagnosis_id:
            if not proposal.diagnosis_checksum:
                raise ValueError("Proposal is missing required checksum binding: diagnosis_checksum")
            if not proposal.evidence_pack_checksum:
                raise ValueError("Proposal is missing required checksum binding: evidence_pack_checksum")

    def _latest_matching_reviewer(
        self,
        proposal: RepairProposal,
    ) -> ReviewerCritique | None:
        critiques = self._reviewer.list_critiques(proposal.proposal_id)
        for critique in critiques:
            if (
                critique.proposal_checksum == proposal.proposal_checksum
                and critique.context_pack_checksum == (proposal.context_pack_checksum or "")
            ):
                return critique
        return None

    @staticmethod
    def _gate_status(
        proposal: RepairProposal,
        latest_matching: ReviewerCritique | None,
    ) -> str:
        if latest_matching is None:
            return "missing_or_stale"
        if latest_matching.decision == "accept":
            return "accepted"
        return latest_matching.decision
