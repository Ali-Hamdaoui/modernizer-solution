"""Tests for V2 repair/proposal flow."""

import pytest

from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)


def test_create_proposal() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Compilation failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency to pom.xml",
        affected_paths=("pom.xml",),
    )
    assert proposal.status == "draft"
    assert proposal.command_id == "cmd-1"


def test_approve_proposal() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Compilation failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency",
        affected_paths=("pom.xml",),
    )
    approved = service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="abc123",
    )
    assert approved.status == "approved"
    assert approved.approval_checksum == "abc123"


def test_apply_patch_requires_approval() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Test failed",
        hypothesis="Missing config",
        patch_summary="Add config",
        affected_paths=("config.xml",),
    )
    with pytest.raises(ValueError, match="must be approved"):
        service.apply_patch(
            proposal_id=proposal.proposal_id,
            target_path="config.xml",
            patch_content="new config",
        )


def test_apply_patch_after_approval() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Test failed",
        hypothesis="Missing config",
        patch_summary="Add config",
        affected_paths=("config.xml",),
    )
    service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="abc123",
    )
    action = service.apply_patch(
        proposal_id=proposal.proposal_id,
        target_path="sandbox/config.xml",
        patch_content="<updated />",
    )
    assert action.status == "applied"
    assert "sandbox/config.xml" in action.target_path


def test_cannot_approve_twice() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Error",
        hypothesis="Bug",
        patch_summary="Fix",
        affected_paths=("file.java",),
    )
    service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="abc123",
    )
    with pytest.raises(ValueError, match="already approved"):
        service.approve_proposal(
            proposal_id=proposal.proposal_id,
            approval_checksum="abc123",
        )


def test_unknown_proposal() -> None:
    service = V2RepairFlowService()
    with pytest.raises(ValueError, match="not found"):
        service.approve_proposal(
            proposal_id="nonexistent",
            approval_checksum="abc",
        )
