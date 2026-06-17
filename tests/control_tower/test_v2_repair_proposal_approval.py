from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from migration_factory.control_tower.application.v2_assistant_failure_answers import (
    V2AssistantFailureAnswerService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    RepairProposal,
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_repair_proposal_approval import (
    V2RepairProposalApprovalService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)


class _FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str):
        self.calls.append({"prompt": prompt, "fallback": fallback})
        raise AssertionError("Approval flow must not call model client")


def _headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _connection(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        tmp_path / "repair_proposal_approval.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _client(tmp_path: Path, fake_model_client: _FakeModelClient) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = _connection(tmp_path)
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake_model_client)
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _services(conn: sqlite3.Connection) -> tuple[V2RepairFlowService, V2ReviewerService, V2RepairProposalApprovalService]:
    uow = SqliteUnitOfWork(conn)
    reviewer_service = V2ReviewerService(reviewer_repo=uow.v2_reviewer)
    repair_flow = V2RepairFlowService(
        repair_repo=uow.v2_repairs,
        reviewer_service=reviewer_service,
    )
    approval_service = V2RepairProposalApprovalService(
        repair_repo=uow.v2_repairs,
        repair_flow=repair_flow,
        reviewer_service=reviewer_service,
    )
    return repair_flow, reviewer_service, approval_service


def _proposal(
    repair_flow: V2RepairFlowService,
    *,
    context_pack_checksum: str = "cp-1",
) -> RepairProposal:
    return repair_flow.create_proposal(
        command_id="cmd-approve-1",
        failure_summary="invalid_maven_wildcard_version: wildcard version in pom",
        hypothesis="Pin exact version",
        patch_summary="Change wildcard version to exact version in pom.xml",
        affected_paths=("pom.xml",),
        validation_plan="Run mvn test",
        diagnosis_id="diag-1",
        diagnosis_checksum="diag-checksum-1",
        evidence_pack_checksum="evidence-checksum-1",
        context_pack_checksum=context_pack_checksum,
    )


def test_reviewer_accepted_proposal_can_be_human_approved_with_matching_checksum(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Proposal is bounded and safe.",
    )

    result = approval_service.decide(
        proposal_id=proposal.proposal_id,
        operator_decision="approve",
        approval_checksum=proposal.proposal_checksum,
        operator_note="human approved",
        correlation_id="corr-1",
    )

    assert result.proposal.status == "approved"
    assert result.reviewer_gate_status == "accepted"
    assert result.applied is False
    assert result.approval_result == "approved"
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_proposal(proposal.proposal_id)
        assert stored is not None
        assert stored.status == "approved"
        assert uow.v2_repairs.list_actions_by_proposal(proposal.proposal_id) == ()
        decisions = uow.v2_repairs.list_approval_decisions_by_proposal(proposal.proposal_id)
        assert len(decisions) == 1
        assert decisions[0].operator_decision == "approve"


def test_approval_fails_if_no_reviewer_accepted_critique_exists(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)

    with pytest.raises(ValueError, match="no reviewer accepted critique matches current checksums"):
        approval_service.decide(
            proposal_id=proposal.proposal_id,
            operator_decision="approve",
            approval_checksum=proposal.proposal_checksum,
        )


@pytest.mark.parametrize("reviewer_decision", ["revise", "reject"])
def test_approval_fails_if_latest_reviewer_decision_is_revise_or_reject(
    tmp_path: Path,
    reviewer_decision: str,
) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Older accept.",
    )
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision=reviewer_decision,
        reasoning=f"Latest decision is {reviewer_decision}.",
    )

    with pytest.raises(ValueError, match=f"latest reviewer decision is {reviewer_decision}"):
        approval_service.decide(
            proposal_id=proposal.proposal_id,
            operator_decision="approve",
            approval_checksum=proposal.proposal_checksum,
        )


def test_approval_fails_on_proposal_checksum_mismatch(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Looks safe.",
    )

    with pytest.raises(ValueError, match="Approval checksum mismatch"):
        approval_service.decide(
            proposal_id=proposal.proposal_id,
            operator_decision="approve",
            approval_checksum="stale-checksum",
        )


def test_approval_fails_on_stale_context_checksum(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow, context_pack_checksum="cp-current")
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum="cp-stale",
        decision="accept",
        reasoning="Accepted for stale context only.",
    )

    with pytest.raises(ValueError, match="no reviewer accepted critique matches current checksums"):
        approval_service.decide(
            proposal_id=proposal.proposal_id,
            operator_decision="approve",
            approval_checksum=proposal.proposal_checksum,
        )


def test_rejection_records_and_marks_proposal_rejected_without_applying(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    sandbox_file = tmp_path / "sandbox" / "pom.xml"
    legacy_file = tmp_path / "legacy" / "App.java"
    sandbox_file.parent.mkdir(parents=True)
    legacy_file.parent.mkdir(parents=True)
    sandbox_file.write_text("<project />\n", encoding="utf-8")
    legacy_file.write_text("class App {}\n", encoding="utf-8")
    sandbox_before = sandbox_file.read_text(encoding="utf-8")
    legacy_before = legacy_file.read_text(encoding="utf-8")

    result = approval_service.decide(
        proposal_id=proposal.proposal_id,
        operator_decision="reject",
        approval_checksum=proposal.proposal_checksum,
        operator_note="human rejected",
    )

    assert result.proposal.status == "rejected"
    assert result.applied is False
    assert sandbox_file.read_text(encoding="utf-8") == sandbox_before
    assert legacy_file.read_text(encoding="utf-8") == legacy_before
    with SqliteUnitOfWork(conn) as uow:
        assert uow.v2_repairs.list_actions_by_proposal(proposal.proposal_id) == ()
        decisions = uow.v2_repairs.list_approval_decisions_by_proposal(proposal.proposal_id)
        assert len(decisions) == 1
        assert decisions[0].operator_decision == "reject"


def test_endpoint_rejects_patch_content_and_skips_model_calls(tmp_path: Path) -> None:
    fake_model_client = _FakeModelClient()
    client, conn = _client(tmp_path, fake_model_client)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Safe.",
    )

    response = client.post(
        f"/v1/v2/repair-proposals/{proposal.proposal_id}/approval",
        json={
            "decision": "approve",
            "approval_checksum": proposal.proposal_checksum,
            "note": "human approve",
            "patch_content": "diff --git a/pom.xml b/pom.xml",
        },
        headers=_headers(),
    )

    assert response.status_code == 422, response.text
    assert fake_model_client.calls == []
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_proposal(proposal.proposal_id)
        assert stored is not None
        assert stored.status == "draft"


def test_endpoint_approves_reviewed_proposal_and_returns_applied_false(tmp_path: Path) -> None:
    fake_model_client = _FakeModelClient()
    client, conn = _client(tmp_path, fake_model_client)
    repair_flow, reviewer_service, approval_service = _services(conn)
    proposal = _proposal(repair_flow)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Safe.",
    )

    response = client.post(
        f"/v1/v2/repair-proposals/{proposal.proposal_id}/approval",
        json={
            "decision": "approve",
            "approval_checksum": proposal.proposal_checksum,
            "note": "human approve",
        },
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal_status"] == "approved"
    assert body["reviewer_gate_status"] == "accepted"
    assert body["approval_result"] == "approved"
    assert body["applied"] is False
    assert fake_model_client.calls == []


def test_assistant_can_mention_approved_but_not_applied_state() -> None:
    answer = V2AssistantFailureAnswerService().answer_failure_question(
        job_id="job-1",
        latest_diagnosis_data={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "POM wildcard version.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
            "recommended_next_step": "Wait for later apply phase.",
            "evidence": [{"source": "pom.xml", "label": "pom.xml", "text": "<version>3.0.x</version>"}],
            "missing_artifacts": [],
        },
        latest_proposal_data={
            "proposal_id": "prop-1",
            "status": "approved",
            "proposal_checksum": "pc-1",
        },
        latest_reviewer_data={
            "decision": "accept",
        },
        existing_message_text="what should I fix?",
    )

    lowered = answer.answer.lower()
    assert "approved but patch candidate has not been prepared" in lowered
    assert "no patch was applied" in lowered
