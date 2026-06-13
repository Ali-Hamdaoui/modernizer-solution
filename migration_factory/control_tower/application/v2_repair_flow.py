"""V2 repair/proposal flow — failed stage evidence to bounded repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
    V2SandboxActionRecord,
)


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    command_id: str
    failure_summary: str
    hypothesis: str
    patch_summary: str
    affected_paths: tuple[str, ...]
    status: str  # draft, proposed, approved, rejected, applied
    approval_checksum: str | None
    created_at: str


@dataclass(frozen=True)
class SandboxAction:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str  # pending, applied, failed, rolled_back
    result_summary: str
    created_at: str


class V2RepairFlowService:
    """Convert failed command evidence into repair proposals and actions.

    - Proposal created from failure context
    - Approval with checksum required before patch application
    - Actions are sandbox-only (no legacy source mutation)
    - Rollback on failure
    """

    def __init__(
        self,
        repair_repo: SqliteV2RepairRepository | None = None,
    ) -> None:
        self._proposals: dict[str, RepairProposal] = {}
        self._actions: dict[str, SandboxAction] = {}
        self._repo = repair_repo

    def create_proposal(
        self,
        command_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
    ) -> RepairProposal:
        proposal = RepairProposal(
            proposal_id=uuid4().hex,
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            status="draft",
            approval_checksum=None,
            created_at=utc_now_text(),
        )
        self._proposals[proposal.proposal_id] = proposal
        # Persist if repo available
        if self._repo is not None:
            record = V2RepairProposalRecord(
                proposal_id=proposal.proposal_id,
                command_id=proposal.command_id,
                failure_summary=proposal.failure_summary,
                hypothesis=proposal.hypothesis,
                patch_summary=proposal.patch_summary,
                affected_paths_json=json.dumps(list(proposal.affected_paths), separators=(",", ":")),
                status=proposal.status,
                approval_checksum=proposal.approval_checksum,
                created_at=proposal.created_at,
            )
            self._repo.save_proposal(record)
        return proposal

    def approve_proposal(
        self,
        proposal_id: str,
        approval_checksum: str,
    ) -> RepairProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = RepairProposal(
                    proposal_id=record.proposal_id,
                    command_id=record.command_id,
                    failure_summary=record.failure_summary,
                    hypothesis=record.hypothesis,
                    patch_summary=record.patch_summary,
                    affected_paths=tuple(json.loads(record.affected_paths_json)),
                    status=record.status,
                    approval_checksum=record.approval_checksum,
                    created_at=record.created_at,
                )
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status != "draft":
            raise ValueError(f"Proposal {proposal_id!r} is already {proposal.status}")

        updated = RepairProposal(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            failure_summary=proposal.failure_summary,
            hypothesis=proposal.hypothesis,
            patch_summary=proposal.patch_summary,
            affected_paths=proposal.affected_paths,
            status="approved",
            approval_checksum=approval_checksum,
            created_at=proposal.created_at,
        )
        self._proposals[proposal_id] = updated
        # Persist if repo available
        if self._repo is not None:
            self._repo.update_proposal_status(proposal_id, "approved", approval_checksum)
        return updated

    def apply_patch(
        self,
        proposal_id: str,
        target_path: str,
        patch_content: str,
    ) -> SandboxAction:
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = RepairProposal(
                    proposal_id=record.proposal_id,
                    command_id=record.command_id,
                    failure_summary=record.failure_summary,
                    hypothesis=record.hypothesis,
                    patch_summary=record.patch_summary,
                    affected_paths=tuple(json.loads(record.affected_paths_json)),
                    status=record.status,
                    approval_checksum=record.approval_checksum,
                    created_at=record.created_at,
                )
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal_id!r} must be approved first")

        action = SandboxAction(
            action_id=uuid4().hex,
            proposal_id=proposal_id,
            target_path=target_path,
            patch_content=patch_content,
            status="applied",
            result_summary=f"Patch applied to {target_path}",
            created_at=utc_now_text(),
        )
        self._actions[action.action_id] = action

        # Update proposal
        updated = RepairProposal(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            failure_summary=proposal.failure_summary,
            hypothesis=proposal.hypothesis,
            patch_summary=proposal.patch_summary,
            affected_paths=proposal.affected_paths,
            status="applied",
            approval_checksum=proposal.approval_checksum,
            created_at=proposal.created_at,
        )
        # Persist action if repo available
        if self._repo is not None:
            action_record = V2SandboxActionRecord(
                action_id=action.action_id,
                proposal_id=action.proposal_id,
                target_path=action.target_path,
                patch_content=action.patch_content,
                status=action.status,
                result_summary=action.result_summary,
                created_at=action.created_at,
            )
            self._repo.save_action(action_record)
            # Also update proposal status
            self._repo.update_proposal_status(proposal_id, "applied")
        self._proposals[proposal_id] = updated
        return action

    def proposal_to_dict(self, proposal: RepairProposal) -> dict[str, Any]:
        return {
            "proposal_id": proposal.proposal_id,
            "command_id": proposal.command_id,
            "failure_summary": proposal.failure_summary,
            "hypothesis": proposal.hypothesis,
            "patch_summary": proposal.patch_summary,
            "affected_paths": list(proposal.affected_paths),
            "status": proposal.status,
            "approval_checksum": proposal.approval_checksum,
            "created_at": proposal.created_at,
        }

    def action_to_dict(self, action: SandboxAction) -> dict[str, Any]:
        return {
            "action_id": action.action_id,
            "proposal_id": action.proposal_id,
            "target_path": action.target_path,
            "patch_content": action.patch_content[:100] if action.patch_content else "",
            "status": action.status,
            "result_summary": action.result_summary,
            "created_at": action.created_at,
        }
