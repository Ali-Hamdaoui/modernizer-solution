from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import migration_factory.control_tower.application.v2_patch_candidate_apply_service as patch_apply_module
import migration_factory.control_tower.application.v2_repair_flow as repair_flow_module
from migration_factory.control_tower.application.v2_diagnosis_proposal_flow import (
    RoleAwareStructuredModelClient,
    V2DiagnosisProposalFlowService,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_patch_candidate_apply_service import (
    V2PatchCandidateApplyService,
)
from migration_factory.control_tower.application.v2_patch_candidate_service import (
    V2PatchCandidateService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
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
from migration_factory.repair_loop.patch_apply import PatchApplyResult
from migration_factory.repair_loop.patch_gate import PatchGateResult
from migration_factory.repair_loop.validation_runner import ValidationResult


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


@dataclass(frozen=True)
class _FakeModelResult:
    content: str
    source: str = "fake"
    model_status: str = "live_ok"
    provider: str = "fake"
    deployment_label: str = "fake-deployment"
    model_invocation_id: str = "fake-invocation"
    success: bool = True
    redacted_summary: str = "Fake model OK."
    failure_reason: str = ""


class _NoAssistantModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str):
        self.calls.append({"prompt": prompt, "fallback": fallback})
        raise AssertionError("Deterministic E2E path must not call assistant model")


class _SingleRoleFakeRawClient:
    def __init__(self, *, expected_role: str, responses: list[_FakeModelResult]) -> None:
        self.expected_role = expected_role
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def answer_for_role(self, *, prompt: str, fallback: str, role: str):
        self.calls.append({"role": role, "prompt": prompt, "fallback": fallback})
        assert role == self.expected_role
        if not self._responses:
            raise AssertionError(f"Unexpected extra {role} model call")
        return self._responses.pop(0)

    def answer(self, *, prompt: str, fallback: str):
        raise AssertionError(f"Role fake for {self.expected_role} should not use generic answer()")


def _connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _client(conn: sqlite3.Connection, fake_model_client: _NoAssistantModelClient) -> TestClient:
    from migration_factory.control_tower.adapters.fastapi import create_app

    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake_model_client)
    return TestClient(app, base_url="http://127.0.0.1:8000")


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


def _fixture_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy" / "LegacyApp.java"
    run_dir.mkdir(parents=True, exist_ok=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    (run_dir / "phase2_transform.log").write_text(
        "Build failed while resolving project model: <version>3.0.x</version>\n",
        encoding="utf-8",
    )
    (run_dir / "orchestration_summary.json").write_text(
        json.dumps({"status": "failed", "stage": 2}),
        encoding="utf-8",
    )
    (sandbox / "pom.xml").write_text(
        "<project>\n  <version>3.0.x</version>\n</project>\n",
        encoding="utf-8",
    )
    legacy.write_text("class LegacyApp {}\n", encoding="utf-8")
    return run_dir, sandbox, legacy


def _diagnose_invalid_wildcard(conn: sqlite3.Connection, run_dir: Path, sandbox: Path):
    repo = SqliteUnitOfWork(conn).v2_failure_diagnoses
    service = V2FailureDiagnosisService(
        diagnosis_repo=repo,
        run_dir_resolver=lambda command_id, event_type: str(run_dir),
    )
    return service.diagnose(
        job_id="job-1",
        stage_index=2,
        command_id="cmd-1",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED",
            "message": "Model build failed",
            "stderr": "Project model invalid because pom contains <version>3.0.x</version>",
            "sandbox_path": str(sandbox),
            "artifact_refs": {
                "orchestration_summary": str(run_dir / "orchestration_summary.json"),
            },
        },
    )


def _services(
    conn: sqlite3.Connection,
    proposer_raw: _SingleRoleFakeRawClient,
    reviewer_raw: _SingleRoleFakeRawClient,
):
    uow = SqliteUnitOfWork(conn)
    reviewer_service = V2ReviewerService(reviewer_repo=uow.v2_reviewer)
    repair_flow = V2RepairFlowService(
        repair_repo=uow.v2_repairs,
        reviewer_service=reviewer_service,
    )
    proposal_flow = V2DiagnosisProposalFlowService(
        diagnosis_repo=uow.v2_failure_diagnoses,
        repair_repo=uow.v2_repairs,
        repair_flow=repair_flow,
        reviewer_service=reviewer_service,
        proposer_client=RoleAwareStructuredModelClient(proposer_raw, role="proposer"),
        reviewer_client=RoleAwareStructuredModelClient(reviewer_raw, role="reviewer"),
    )
    approval_service = V2RepairProposalApprovalService(
        repair_repo=uow.v2_repairs,
        repair_flow=repair_flow,
        reviewer_service=reviewer_service,
    )
    candidate_service = V2PatchCandidateService(
        repair_repo=uow.v2_repairs,
        reviewer_service=reviewer_service,
        command_repo=uow.v2_commands,
    )
    apply_service = V2PatchCandidateApplyService(
        repair_repo=uow.v2_repairs,
        reviewer_service=reviewer_service,
        command_repo=uow.v2_commands,
        repair_flow=repair_flow,
    )
    return proposal_flow, reviewer_service, approval_service, candidate_service, apply_service


def _prepare_candidate(conn: sqlite3.Connection, tmp_path: Path):
    run_dir, sandbox, legacy = _fixture_dirs(tmp_path)
    _seed_job_and_command(conn, sandbox)
    diagnosis = _diagnose_invalid_wildcard(conn, run_dir, sandbox)
    proposer_raw = _SingleRoleFakeRawClient(
        expected_role="proposer",
        responses=[
            _FakeModelResult(
                content='{"failure_hypothesis":"Wildcard Maven version breaks dependency resolution","patch_summary":"Replace wildcard pom version with exact version","affected_paths":["pom.xml"],"validation_plan":"Run mvn test"}',
                model_invocation_id="proposer-1",
            )
        ],
    )
    reviewer_raw = _SingleRoleFakeRawClient(
        expected_role="reviewer",
        responses=[
            _FakeModelResult(
                content='{"decision":"accept","reasoning":"Proposal matches persisted diagnosis and stays inside pom.xml.","missing_evidence":[],"unsafe_assumptions":[]}',
                model_invocation_id="reviewer-1",
            )
        ],
    )
    proposal_flow, reviewer_service, approval_service, candidate_service, apply_service = _services(
        conn,
        proposer_raw,
        reviewer_raw,
    )
    proposal_result = proposal_flow.create_repair_proposal(diagnosis_id=diagnosis.diagnosis_id)
    review_result = proposal_flow.review_repair_proposal(proposal_result.proposal.proposal_id)
    approval_result = approval_service.decide(
        proposal_id=proposal_result.proposal.proposal_id,
        operator_decision="approve",
        approval_checksum=proposal_result.proposal.proposal_checksum,
    )
    candidate = candidate_service.create_patch_candidate(proposal_id=proposal_result.proposal.proposal_id)
    return {
        "run_dir": run_dir,
        "sandbox": sandbox,
        "legacy": legacy,
        "diagnosis": diagnosis,
        "proposal": proposal_result.proposal,
        "review": review_result,
        "approval": approval_result,
        "candidate": candidate,
        "proposal_flow": proposal_flow,
        "reviewer_service": reviewer_service,
        "approval_service": approval_service,
        "candidate_service": candidate_service,
        "apply_service": apply_service,
        "proposer_raw": proposer_raw,
        "reviewer_raw": reviewer_raw,
    }


def _validation_success(**kwargs) -> ValidationResult:
    return ValidationResult(
        passed=True,
        build_status="BUILD_PASSED_IN_SANDBOX",
        test_status="TEST_PASSED",
        h2_status="H2_STARTUP_SKIPPED",
        validation_commands=[["mvn", "test"]],
        artifact_refs={},
        warnings=[],
        errors=[],
    )


def _validation_failure(**kwargs) -> ValidationResult:
    return ValidationResult(
        passed=False,
        build_status="BUILD_FAILED_IN_SANDBOX",
        test_status="TEST_FAILED",
        h2_status="H2_STARTUP_SKIPPED",
        validation_commands=[["mvn", "test"]],
        artifact_refs={},
        warnings=[],
        errors=["validation failed"],
    )


def _fake_apply_success_factory(calls: list[dict[str, object]]):
    def _fake_apply(**kwargs):
        calls.append(kwargs)
        sandbox = Path(kwargs["sandbox_path"])
        run_dir = Path(kwargs["run_dir"])
        patch_path = run_dir / "repairs" / "patch_attempt_1.diff"
        snapshot_dir = run_dir / "repairs" / "snapshots" / "attempt_1"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        original = (sandbox / "pom.xml").read_text(encoding="utf-8")
        (snapshot_dir / "pom.xml").write_text(original, encoding="utf-8")
        patch_path.write_text(str(kwargs["unified_diff"]), encoding="utf-8")
        (sandbox / "pom.xml").write_text(
            "<project>\n  <version>3.0.0</version>\n</project>\n",
            encoding="utf-8",
        )
        return PatchApplyResult(
            status="APPLIED",
            reason="ok",
            patch_path=patch_path,
            touched_paths=list(kwargs["touched_paths"]),
            before_hashes={"pom.xml": "before"},
            after_hashes={"pom.xml": "after"},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=[],
        )

    return _fake_apply


def test_governed_repair_e2e_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path / "happy.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    workflow = _prepare_candidate(conn, tmp_path / "happy")

    ask_before = client.post(
        "/v1/v2/jobs/job-1/assistant/ask",
        json={"question": "why build failed?"},
        headers=_mutation_headers(),
    )

    assert ask_before.status_code == 200, ask_before.text
    before_body = ask_before.json()
    assert before_body["failure_answer"]["failure_type"] == "invalid_maven_wildcard_version"
    assert "wildcard" in before_body["failure_answer"]["root_cause"].lower()
    assert fake_assistant.calls == []

    apply_calls: list[dict[str, object]] = []
    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", _fake_apply_success_factory(apply_calls))

    result = workflow["apply_service"].apply_patch_candidate(
        patch_candidate_id=workflow["candidate"].patch_candidate_id,
        patch_candidate_checksum=workflow["candidate"].patch_candidate_checksum,
        validation_runner=_validation_success,
    )

    assert workflow["proposer_raw"].calls and workflow["proposer_raw"].calls[0]["role"] == "proposer"
    assert workflow["reviewer_raw"].calls and workflow["reviewer_raw"].calls[0]["role"] == "reviewer"
    assert workflow["candidate"].status == "gate_allowed"
    assert workflow["candidate"].gate_status == "ALLOWED"
    assert result.apply_status == "applied"
    assert result.candidate_status == "applied"
    assert result.applied is True
    assert apply_calls and str(apply_calls[0]["unified_diff"]) == workflow["candidate"].unified_diff
    assert "3.0.0" in (workflow["sandbox"] / "pom.xml").read_text(encoding="utf-8")
    assert workflow["legacy"].read_text(encoding="utf-8") == "class LegacyApp {}\n"

    ask_after = client.post(
        "/v1/v2/jobs/job-1/assistant/ask",
        json={"question": "what should I fix?"},
        headers=_mutation_headers(),
    )

    assert ask_after.status_code == 200, ask_after.text
    after_body = ask_after.json()
    assert "sandbox patch was applied" in after_body["failure_answer"]["answer"].lower()
    assert "legacy source was not modified" in after_body["failure_answer"]["answer"].lower()
    assert fake_assistant.calls == []


def test_governed_repair_e2e_rollback_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path / "rollback.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    workflow = _prepare_candidate(conn, tmp_path / "rollback")
    original_legacy = workflow["legacy"].read_text(encoding="utf-8")
    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", _fake_apply_success_factory([]))

    def fake_rollback(**kwargs):
        sandbox_path = Path(kwargs["sandbox_path"])
        snapshot_dir = Path(kwargs["snapshot_dir"])
        (sandbox_path / "pom.xml").write_text(
            (snapshot_dir / "pom.xml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return True, "rolled back"

    monkeypatch.setattr(repair_flow_module, "rollback_patch", fake_rollback)

    result = workflow["apply_service"].apply_patch_candidate(
        patch_candidate_id=workflow["candidate"].patch_candidate_id,
        patch_candidate_checksum=workflow["candidate"].patch_candidate_checksum,
        validation_runner=_validation_failure,
    )

    assert result.apply_status == "rolled_back"
    assert result.candidate_status == "rolled_back"
    assert result.rolled_back is True
    assert "3.0.x" in (workflow["sandbox"] / "pom.xml").read_text(encoding="utf-8")
    assert workflow["legacy"].read_text(encoding="utf-8") == original_legacy

    ask_after = client.post(
        "/v1/v2/jobs/job-1/assistant/ask",
        json={"question": "explain the failure"},
        headers=_mutation_headers(),
    )

    assert ask_after.status_code == 200, ask_after.text
    assert "rollback happened" in ask_after.json()["failure_answer"]["answer"].lower()
    assert fake_assistant.calls == []


def test_stale_approval_and_reviewer_bindings_block_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "stale-approval.sqlite3")
    workflow = _prepare_candidate(conn, tmp_path / "stale-approval")
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repairs.save_approval_decision(
            V2RepairProposalApprovalDecisionRecord(
                decision_id="stale-approval",
                proposal_id=workflow["proposal"].proposal_id,
                operator_decision="approve",
                approval_checksum="stale-checksum",
                proposal_checksum=workflow["proposal"].proposal_checksum,
                context_pack_checksum=workflow["proposal"].context_pack_checksum or "",
                reviewer_gate_status="accepted",
                reviewer_critique_id=None,
                operator_note="stale",
                created_at=utc_now_text(),
                correlation_id=None,
            )
        )
    with pytest.raises(ValueError, match="stale human approval checksum"):
        workflow["apply_service"].apply_patch_candidate(
            patch_candidate_id=workflow["candidate"].patch_candidate_id,
            patch_candidate_checksum=workflow["candidate"].patch_candidate_checksum,
            validation_runner=_validation_success,
        )

    conn = _connection(tmp_path / "stale-reviewer.sqlite3")
    workflow = _prepare_candidate(conn, tmp_path / "stale-reviewer")
    workflow["reviewer_service"].record_critique(
        proposal_id=workflow["proposal"].proposal_id,
        proposal_checksum=workflow["proposal"].proposal_checksum,
        context_pack_checksum=workflow["proposal"].context_pack_checksum or "",
        decision="reject",
        reasoning="Latest critique blocks apply.",
    )
    with pytest.raises(ValueError, match="reviewer binding is stale"):
        workflow["apply_service"].apply_patch_candidate(
            patch_candidate_id=workflow["candidate"].patch_candidate_id,
            patch_candidate_checksum=workflow["candidate"].patch_candidate_checksum,
            validation_runner=_validation_success,
        )


def test_gate_blocked_candidate_cannot_apply(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path / "gate-blocked.sqlite3")
    workflow = _prepare_candidate(conn, tmp_path / "gate-blocked")
    original_pom = (workflow["sandbox"] / "pom.xml").read_text(encoding="utf-8")

    def fake_gate(**kwargs):
        return PatchGateResult(
            status="HUMAN_REVIEW_REQUIRED",
            reason="blocked at apply",
            rule_id="POM_VERSION_PIN_EXACT",
            risk="LOW",
            touched_paths=("pom.xml",),
            human_review_required=True,
        )

    monkeypatch.setattr(patch_apply_module, "evaluate_patch_proposal", fake_gate)

    result = workflow["apply_service"].apply_patch_candidate(
        patch_candidate_id=workflow["candidate"].patch_candidate_id,
        patch_candidate_checksum=workflow["candidate"].patch_candidate_checksum,
        validation_runner=_validation_success,
    )

    assert result.apply_status == "gate_blocked_at_apply"
    assert result.applied is False
    assert (workflow["sandbox"] / "pom.xml").read_text(encoding="utf-8") == original_pom


def test_patch_candidate_endpoint_rejects_extra_raw_patch_field(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "api-candidate.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    workflow = _prepare_candidate(conn, tmp_path / "api-candidate")

    response = client.post(
        f"/v1/v2/repair-proposals/{workflow['proposal'].proposal_id}/patch-candidate",
        json={
            "materialization_mode": "deterministic_only",
            "patch_content": "diff --git a/pom.xml b/pom.xml",
        },
        headers=_mutation_headers(),
    )

    assert response.status_code == 422, response.text
    assert fake_assistant.calls == []


def test_apply_endpoint_rejects_extra_command_path_and_patch_fields(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "api-apply.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    workflow = _prepare_candidate(conn, tmp_path / "api-apply")

    response = client.post(
        f"/v1/v2/patch-candidates/{workflow['candidate'].patch_candidate_id}/apply",
        json={
            "patch_candidate_checksum": workflow["candidate"].patch_candidate_checksum,
            "operator_note": "apply",
            "patch_content": workflow["candidate"].unified_diff,
            "command": "mvn test",
            "path": "pom.xml",
        },
        headers=_mutation_headers(),
    )

    assert response.status_code == 422, response.text
    assert fake_assistant.calls == []
