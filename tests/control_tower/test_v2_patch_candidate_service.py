from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import migration_factory.control_tower.application.v2_patch_candidate_service as patch_candidate_module
from migration_factory.control_tower.application.v2_assistant_failure_answers import (
    V2AssistantFailureAnswerService,
)
from migration_factory.control_tower.application.v2_patch_candidate_service import (
    V2PatchCandidateService,
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
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    V2RepairProposalApprovalDecisionRecord,
)
from migration_factory.repair_loop.patch_gate import PatchGateResult


class _FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str):
        self.calls.append({"prompt": prompt, "fallback": fallback})
        raise AssertionError("Patch candidate flow must not call model client")


def _headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _connection(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        tmp_path / "patch_candidate.sqlite3",
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


def _seed_job_and_command(conn: sqlite3.Connection, sandbox_path: Path) -> None:
    now = utc_now_text()
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_jobs.save(
            V2MigrationJobRecord(
                job_id="job-1",
                setup_id="setup-1",
                setup_checksum="setup-checksum-1",
                pipeline_id="springboot-216-to-356-java21-three-stage",
                stage_chain_json="[]",
                status="running",
                created_at=now,
                updated_at=now,
                correlation_id=None,
            )
        )
        uow.v2_commands.save(
            V2StageCommandRecord(
                command_id="cmd-1",
                job_id="job-1",
                stage_index=2,
                manifest_checksum="manifest-checksum-1",
                argv_json='["mvn","test"]',
                env_json="{}",
                status="failed",
                created_at=now,
                updated_at=now,
                result_json=json.dumps({"sandbox_path": str(sandbox_path)}),
            )
        )


def _services(conn: sqlite3.Connection) -> tuple[V2RepairFlowService, V2ReviewerService, V2RepairProposalApprovalService, V2PatchCandidateService]:
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
    patch_candidate_service = V2PatchCandidateService(
        repair_repo=uow.v2_repairs,
        reviewer_service=reviewer_service,
        command_repo=uow.v2_commands,
    )
    return repair_flow, reviewer_service, approval_service, patch_candidate_service


def _proposal(repair_flow: V2RepairFlowService, *, failure_summary: str = "invalid_maven_wildcard_version: wildcard pom version") -> RepairProposal:
    return repair_flow.create_proposal(
        command_id="cmd-1",
        failure_summary=failure_summary,
        hypothesis="Pin exact version",
        patch_summary="Replace wildcard version with exact managed version",
        affected_paths=("pom.xml",),
        validation_plan="Run mvn test",
        diagnosis_id="diag-1",
        diagnosis_checksum="diag-checksum-1",
        evidence_pack_checksum="evidence-checksum-1",
        context_pack_checksum="context-checksum-1",
    )


def _approve(
    proposal: RepairProposal,
    reviewer_service: V2ReviewerService,
    approval_service: V2RepairProposalApprovalService,
) -> None:
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="accept",
        reasoning="Bounded and safe.",
    )
    approval_service.decide(
        proposal_id=proposal.proposal_id,
        operator_decision="approve",
        approval_checksum=proposal.proposal_checksum,
    )


def _sandbox(tmp_path: Path, pom_text: str) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / "pom.xml").write_text(pom_text, encoding="utf-8")
    return sandbox


def test_approved_proposal_can_produce_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)
    original_pom = (sandbox / "pom.xml").read_text(encoding="utf-8")

    candidate = patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)

    assert candidate.status == "gate_allowed"
    assert candidate.gate_status == "ALLOWED"
    assert candidate.touched_paths == ("pom.xml",)
    assert "diff --git a/pom.xml b/pom.xml" in candidate.unified_diff
    assert (sandbox / "pom.xml").read_text(encoding="utf-8") == original_pom
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_latest_patch_candidate(proposal.proposal_id)
        assert stored is not None
        assert stored.status == "gate_allowed"
        assert stored.gate_status == "ALLOWED"
        assert uow.v2_repairs.list_actions_by_proposal(proposal.proposal_id) == ()


def test_unapproved_proposal_cannot_produce_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)

    with pytest.raises(ValueError, match="must be approved"):
        patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)


def test_reviewer_stale_proposal_cannot_produce_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="reject",
        reasoning="Later critique blocks apply path.",
    )

    with pytest.raises(ValueError, match="reviewer binding is stale: latest decision is reject"):
        patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)


def test_approval_stale_checksum_cannot_produce_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repairs.save_approval_decision(
            V2RepairProposalApprovalDecisionRecord(
                decision_id="stale-approval",
                proposal_id=proposal.proposal_id,
                operator_decision="approve",
                approval_checksum="stale-checksum",
                proposal_checksum=proposal.proposal_checksum,
                context_pack_checksum=proposal.context_pack_checksum or "",
                reviewer_gate_status="accepted",
                reviewer_critique_id=None,
                operator_note="stale",
                created_at=utc_now_text(),
                correlation_id=None,
            )
        )

    with pytest.raises(ValueError, match="stale human approval checksum"):
        patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)


def test_frontend_patch_content_rejected_by_api_model(tmp_path: Path) -> None:
    fake_model_client = _FakeModelClient()
    client, conn = _client(tmp_path, fake_model_client)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)

    response = client.post(
        f"/v1/v2/repair-proposals/{proposal.proposal_id}/patch-candidate",
        json={
            "materialization_mode": "deterministic_only",
            "patch_content": "diff --git a/pom.xml b/pom.xml",
        },
        headers=_headers(),
    )

    assert response.status_code == 422, response.text
    assert fake_model_client.calls == []


def test_unsupported_materialization_is_explicit_and_does_not_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>1.0.0</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow, failure_summary="compiler_source_target_issue: source/target invalid")
    _approve(proposal, reviewer_service, approval_service)
    original_pom = (sandbox / "pom.xml").read_text(encoding="utf-8")

    candidate = patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)

    assert candidate.status == "unsupported_materialization"
    assert candidate.gate_status == "NOT_RUN"
    assert "No deterministic materializer exists" in candidate.gate_reason
    assert candidate.unified_diff == ""
    assert (sandbox / "pom.xml").read_text(encoding="utf-8") == original_pom
    with SqliteUnitOfWork(conn) as uow:
        assert uow.v2_repairs.list_actions_by_proposal(proposal.proposal_id) == ()


def test_invalid_maven_wildcard_materialization_produces_bounded_pom_only_diff(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project>\n  <version>5.0.x</version>\n</project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)

    candidate = patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)
    preview = patch_service.preview_unified_diff(candidate, limit=200)

    assert candidate.touched_paths == ("pom.xml",)
    assert "<version>5.0.0</version>" in candidate.unified_diff
    assert len(preview) <= 214
    assert "pom.xml" in preview


def test_patch_gate_preview_is_called_and_blocked_result_is_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    sandbox = _sandbox(tmp_path, "<project><version>3.0.x</version></project>\n")
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, patch_service = _services(conn)
    proposal = _proposal(repair_flow)
    _approve(proposal, reviewer_service, approval_service)
    calls: list[dict[str, object]] = []

    def fake_gate(**kwargs):
        calls.append(kwargs)
        return PatchGateResult(
            status="HUMAN_REVIEW_REQUIRED",
            reason="needs extra operator review",
            rule_id="POM_VERSION_PIN_EXACT",
            risk="LOW",
            touched_paths=("pom.xml",),
            human_review_required=True,
        )

    monkeypatch.setattr(patch_candidate_module, "evaluate_patch_proposal", fake_gate)
    original_pom = (sandbox / "pom.xml").read_text(encoding="utf-8")

    candidate = patch_service.create_patch_candidate(proposal_id=proposal.proposal_id)

    assert calls
    assert candidate.status == "gate_blocked"
    assert candidate.gate_status == "HUMAN_REVIEW_REQUIRED"
    assert candidate.gate_reason == "needs extra operator review"
    assert (sandbox / "pom.xml").read_text(encoding="utf-8") == original_pom
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_latest_patch_candidate(proposal.proposal_id)
        assert stored is not None
        assert stored.status == "gate_blocked"
        assert stored.gate_status == "HUMAN_REVIEW_REQUIRED"
        assert uow.v2_repairs.list_actions_by_proposal(proposal.proposal_id) == ()


def test_assistant_says_patch_candidate_exists_but_not_applied() -> None:
    answer = V2AssistantFailureAnswerService().answer_failure_question(
        job_id="job-1",
        latest_diagnosis_data={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "POM wildcard version.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
            "recommended_next_step": "Review patch candidate.",
            "evidence": [{"source": "pom.xml", "label": "pom.xml", "text": "<version>3.0.x</version>"}],
            "missing_artifacts": [],
        },
        latest_proposal_data={
            "proposal_id": "prop-1",
            "status": "approved",
            "proposal_checksum": "pc-1",
            "patch_candidate_status": "gate_allowed",
            "patch_candidate_gate_status": "ALLOWED",
        },
        latest_reviewer_data={"decision": "accept"},
        existing_message_text="what should I fix?",
    )

    lowered = answer.answer.lower()
    assert "patch candidate is prepared" in lowered
    assert "gate status is allowed" in lowered
    assert "patch was not applied" in lowered
