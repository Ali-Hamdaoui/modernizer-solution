from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_diagnosis_proposal_flow import (
    RoleAwareStructuredModelClient,
    V2DiagnosisProposalFlowService,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_governed_repair_status import (
    V2GovernedRepairStatusService,
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
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    V2MigrationSetupRecord,
)


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
        raise AssertionError("Read-only status path must not call assistant model")


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
        raise AssertionError("Role-aware fake should not use generic answer()")


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


def _fixture_dirs(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = tmp_path / "sandbox"
    run_dir.mkdir(parents=True, exist_ok=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    (run_dir / "phase2_transform.log").write_text(
        "Build failed: <version>3.0.x</version>\n",
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
    return run_dir, sandbox


def _diagnose(conn: sqlite3.Connection, run_dir: Path, sandbox: Path):
    service = V2FailureDiagnosisService(
        diagnosis_repo=SqliteUnitOfWork(conn).v2_failure_diagnoses,
        run_dir_resolver=lambda command_id, event_type: str(run_dir),
    )
    return service.diagnose(
        job_id="job-1",
        stage_index=2,
        command_id="cmd-1",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED",
            "stderr": "pom contains <version>3.0.x</version>",
            "sandbox_path": str(sandbox),
            "artifact_refs": {"orchestration_summary": str(run_dir / "orchestration_summary.json")},
        },
    )


def _services(
    conn: sqlite3.Connection,
    *,
    proposer_response: str = '{"failure_hypothesis":"Wildcard Maven version breaks dependency resolution","patch_summary":"Replace wildcard pom version with exact version","affected_paths":["pom.xml"],"validation_plan":"Run mvn test"}',
    reviewer_response: str = '{"decision":"accept","reasoning":"Bounded repair matches diagnosis.","missing_evidence":[],"unsafe_assumptions":[]}',
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
        proposer_client=RoleAwareStructuredModelClient(
            _SingleRoleFakeRawClient(
                expected_role="proposer",
                responses=[_FakeModelResult(content=proposer_response, model_invocation_id="proposer-1")],
            ),
            role="proposer",
        ),
        reviewer_client=RoleAwareStructuredModelClient(
            _SingleRoleFakeRawClient(
                expected_role="reviewer",
                responses=[_FakeModelResult(content=reviewer_response, model_invocation_id="reviewer-1")],
            ),
            role="reviewer",
        ),
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
    status_service = V2GovernedRepairStatusService(
        diagnosis_repo=uow.v2_failure_diagnoses,
        repair_repo=uow.v2_repairs,
        reviewer_repo=uow.v2_reviewer,
        command_repo=uow.v2_commands,
    )
    return proposal_flow, reviewer_service, approval_service, candidate_service, status_service


def _prepare_diagnosis(conn: sqlite3.Connection, tmp_path: Path):
    run_dir, sandbox = _fixture_dirs(tmp_path)
    _seed_job_and_command(conn, sandbox)
    diagnosis = _diagnose(conn, run_dir, sandbox)
    return diagnosis, sandbox


def _prepare_proposal(conn: sqlite3.Connection, tmp_path: Path):
    diagnosis, sandbox = _prepare_diagnosis(conn, tmp_path)
    proposal_flow, reviewer_service, approval_service, candidate_service, status_service = _services(conn)
    proposal_result = proposal_flow.create_repair_proposal(diagnosis_id=diagnosis.diagnosis_id)
    return diagnosis, proposal_result.proposal, reviewer_service, approval_service, candidate_service, status_service


def _prepare_reviewed(conn: sqlite3.Connection, tmp_path: Path, *, decision: str = "accept"):
    diagnosis, sandbox = _prepare_diagnosis(conn, tmp_path)
    reviewer_response = json.dumps({
        "decision": decision,
        "reasoning": f"{decision} decision",
        "missing_evidence": [],
        "unsafe_assumptions": [],
    })
    proposal_flow, reviewer_service, approval_service, candidate_service, status_service = _services(
        conn,
        reviewer_response=reviewer_response,
    )
    proposal_result = proposal_flow.create_repair_proposal(diagnosis_id=diagnosis.diagnosis_id)
    review_result = proposal_flow.review_repair_proposal(proposal_result.proposal.proposal_id)
    return diagnosis, proposal_result.proposal, review_result.critique, reviewer_service, approval_service, candidate_service, status_service


def _prepare_approved(conn: sqlite3.Connection, tmp_path: Path):
    diagnosis, proposal, critique, reviewer_service, approval_service, candidate_service, status_service = _prepare_reviewed(
        conn,
        tmp_path,
    )
    approval_service.decide(
        proposal_id=proposal.proposal_id,
        operator_decision="approve",
        approval_checksum=proposal.proposal_checksum,
    )
    return diagnosis, proposal, reviewer_service, approval_service, candidate_service, status_service


def _seed_event_derived_stage2_job(conn: sqlite3.Connection, tmp_path: Path) -> str:
    job_id = "ddbbf3172a6d4a028dd9efeed6a1621b"
    now = utc_now_text()
    app_root = tmp_path / "modernized-app"
    run_dir = app_root / ".migration" / "runs" / "v2-ddbbf317-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "orchestration").mkdir(parents=True, exist_ok=True)
    (run_dir / "build").mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs" / "phase2_transform.log").write_text(
        "Failed to read artifact descriptor for jakarta.persistence:jakarta.persistence-api:jar:3.0.x\n"
        "PKIX path building failed\nBUILD_FAILED_IN_SANDBOX\n",
        encoding="utf-8",
    )
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}),
        encoding="utf-8",
    )
    (run_dir / "build" / "build-error-20260618-004516-dependency_error.json").write_text(
        json.dumps({"message": "Failed to read artifact descriptor for jakarta.servlet:jakarta.servlet-api:jar:5.0.x"}),
        encoding="utf-8",
    )
    (sandbox_dir / "pom.xml").write_text(
        "<project><dependencies>"
        "<dependency><groupId>jakarta.persistence</groupId><artifactId>jakarta.persistence-api</artifactId><version>3.0.x</version></dependency>"
        "<dependency><groupId>jakarta.servlet</groupId><artifactId>jakarta.servlet-api</artifactId><version>5.0.x</version></dependency>"
        "</dependencies></project>",
        encoding="utf-8",
    )

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_setups.save(
            V2MigrationSetupRecord(
                setup_id="setup-stage2",
                run_name="Migration v2-ddbbf317",
                legacy_app_path=str(tmp_path / "legacy-app"),
                output_parent_path=str(app_root),
                ai_hub_path=str(tmp_path / "ai-hub"),
                java11_home="C:/jdk11",
                java17_home="C:/jdk17",
                java21_home="C:/jdk21",
                maven_cmd="mvn",
                proof_level="standard",
                skip_endpoint_smoke=False,
                migration_flags_json="{}",
                setup_checksum="setup-checksum-stage2",
                checksum_algorithm="sha256",
                created_at=now,
                created_by="test",
                correlation_id=None,
            )
        )
        uow.v2_jobs.save(
            V2MigrationJobRecord(
                job_id=job_id,
                setup_id="setup-stage2",
                setup_checksum="setup-checksum-stage2",
                pipeline_id="springboot-216-to-356-java21-three-stage",
                stage_chain_json="[]",
                status="failed",
                created_at=now,
                updated_at=now,
                correlation_id=None,
            )
        )
        uow.v2_commands.save(
            V2StageCommandRecord(
                command_id="9bdd74daf848439eae7aebed9cee8716",
                job_id=job_id,
                stage_index=2,
                manifest_checksum="manifest-stage2",
                argv_json=json.dumps(["python", "runner.py", "--modernized", str(app_root)]),
                env_json="{}",
                status="failed",
                created_at=now,
                updated_at=now,
                result_json=json.dumps({"sandbox_path": str(sandbox_dir)}),
            )
        )
        for artifact_kind, relative_path in (
            ("sandbox", ".migration\\runs\\v2-ddbbf317-s2\\workspaces\\sandbox"),
            ("orchestration_summary", ".migration\\runs\\v2-ddbbf317-s2\\orchestration\\orchestration_summary.json"),
            ("build_error", ".migration\\runs\\v2-ddbbf317-s2\\build\\build-error-20260618-004516-dependency_error.json"),
        ):
            uow.v2_events.save(
                job_id=job_id,
                stage=2,
                event_type="artifact_written",
                status="completed",
                message=artifact_kind,
                payload={"artifact_kind": artifact_kind, "relative_path": relative_path},
            )
        uow.v2_events.save(
            job_id=job_id,
            stage=2,
            event_type="stage_failed",
            status="failed",
            message="BUILD_FAILED_IN_SANDBOX",
            payload={
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "command_id": "9bdd74daf848439eae7aebed9cee8716",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "orchestration_status": "FAIL",
                "repair_loop_status": "DISABLED",
                "test_status": "",
                "transform_status": "BUILD_FAILED_IN_SANDBOX",
            },
        )
    return job_id


def test_no_diagnosis_maps_to_run_diagnosis(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "none.sqlite3")
    run_dir, sandbox = _fixture_dirs(tmp_path / "none")
    _seed_job_and_command(conn, sandbox)
    _, _, _, _, status_service = _services(conn)

    status = status_service.get_status(job_id="job-1", stage_index=2)

    assert status["next_action"] == "run_diagnosis"
    assert status["diagnosis"] == {}
    assert status["safety"]["legacy_mutated"] is False


def test_diagnosis_only_maps_to_create_proposal(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "diagnosis.sqlite3")
    diagnosis, _ = _prepare_diagnosis(conn, tmp_path / "diagnosis")
    _, _, _, _, status_service = _services(conn)

    status = status_service.get_status(job_id="job-1", stage_index=2)

    assert status["diagnosis"]["diagnosis_id"] == diagnosis.diagnosis_id
    assert status["next_action"] == "create_proposal"


def test_stage2_run_diagnosis_available_does_not_map_to_run_diagnosis(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "stage2.sqlite3")
    diagnosis, _ = _prepare_diagnosis(conn, tmp_path / "stage2")
    _, _, _, _, status_service = _services(conn)

    status = status_service.get_status(job_id="job-1", stage_index=2, diagnosis_id=diagnosis.diagnosis_id)

    assert status["diagnosis"]["diagnosis_id"] == diagnosis.diagnosis_id
    assert status["next_action"] != "run_diagnosis"


def test_proposal_without_review_maps_to_review_proposal(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "proposal.sqlite3")
    _, proposal, _, _, _, status_service = _prepare_proposal(conn, tmp_path / "proposal")

    status = status_service.get_status(job_id="job-1", proposal_id=proposal.proposal_id)

    assert status["proposal"]["proposal_id"] == proposal.proposal_id
    assert status["next_action"] == "review_proposal"


def test_accepted_review_without_approval_maps_to_human_approval_required(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "accepted.sqlite3")
    _, proposal, critique, _, _, _, status_service = _prepare_reviewed(conn, tmp_path / "accepted")

    status = status_service.get_status(job_id="job-1", proposal_id=proposal.proposal_id)

    assert status["review"]["decision"] == "accept"
    assert status["next_action"] == "human_approval_required"


def test_approved_without_candidate_maps_to_create_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "approved.sqlite3")
    _, proposal, _, _, _, status_service = _prepare_approved(conn, tmp_path / "approved")

    status = status_service.get_status(job_id="job-1", proposal_id=proposal.proposal_id)

    assert status["approval"]["status"] == "approved"
    assert status["next_action"] == "create_patch_candidate"


def test_gate_allowed_candidate_maps_to_apply_patch_candidate(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "candidate.sqlite3")
    _, proposal, _, _, candidate_service, status_service = _prepare_approved(conn, tmp_path / "candidate")
    candidate = candidate_service.create_patch_candidate(proposal_id=proposal.proposal_id)

    status = status_service.get_status(job_id="job-1", patch_candidate_id=candidate.patch_candidate_id)

    assert status["patch_candidate"]["status"] == "gate_allowed"
    assert status["next_action"] == "apply_patch_candidate"


def test_applied_maps_to_resolved_and_preview_is_bounded_redacted(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "applied.sqlite3")
    _, proposal, _, _, candidate_service, status_service = _prepare_approved(conn, tmp_path / "applied")
    candidate = candidate_service.create_patch_candidate(proposal_id=proposal.proposal_id)
    conn.execute(
        "UPDATE v2_patch_candidates SET status = ?, unified_diff = ?, artifact_refs_json = ?, validation_status = ?, rollback_status = ? WHERE patch_candidate_id = ?",
        (
            "applied",
            "diff --git a/pom.xml b/pom.xml\n+token=secret123\n+C:\\Users\\private\\workspace\\pom.xml\n" + ("x" * 1200),
            json.dumps({"repair_ledger": "C:\\Users\\private\\run\\repair_ledger.json"}),
            "passed",
            "NOT_NEEDED",
            candidate.patch_candidate_id,
        ),
    )

    status = status_service.get_status(job_id="job-1", patch_candidate_id=candidate.patch_candidate_id)

    assert status["next_action"] == "resolved"
    assert status["apply"]["status"] == "applied"
    assert len(status["patch_candidate"]["unified_diff_preview"]) <= 914
    assert "[REDACTED]" in status["patch_candidate"]["unified_diff_preview"]
    assert "C:\\Users\\private" not in status["patch_candidate"]["unified_diff_preview"]
    assert status["apply"]["artifact_refs"]["repair_ledger"] == "repair_ledger.json"


def test_rolled_back_maps_to_inspect_validation_result(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "rolled.sqlite3")
    _, proposal, _, _, candidate_service, status_service = _prepare_approved(conn, tmp_path / "rolled")
    candidate = candidate_service.create_patch_candidate(proposal_id=proposal.proposal_id)
    conn.execute(
        "UPDATE v2_patch_candidates SET status = ?, validation_status = ?, rollback_status = ? WHERE patch_candidate_id = ?",
        ("rolled_back", "failed", "ROLLED_BACK", candidate.patch_candidate_id),
    )

    status = status_service.get_status(job_id="job-1", patch_candidate_id=candidate.patch_candidate_id)

    assert status["next_action"] == "inspect_validation_result"
    assert status["apply"]["rolled_back"] is True


def test_rejected_or_revise_review_maps_to_blocked(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "blocked.sqlite3")
    _, proposal, critique, _, _, _, status_service = _prepare_reviewed(conn, tmp_path / "blocked", decision="reject")

    status = status_service.get_status(job_id="job-1", proposal_id=proposal.proposal_id)

    assert status["review"]["decision"] == "reject"
    assert status["next_action"] == "blocked"


def test_status_endpoint_is_read_only_and_assistant_can_mention_next_action(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "endpoint.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    _, proposal, critique, _, _, _, status_service = _prepare_reviewed(conn, tmp_path / "endpoint")

    with SqliteUnitOfWork(conn) as uow:
        before = {
            "diagnoses": len(uow.v2_failure_diagnoses.list_for_job("job-1")),
            "proposals": len(uow.v2_repairs.list_proposals_by_diagnosis(proposal.diagnosis_id)),
            "critiques": len(uow.v2_reviewer.list_critiques_by_proposal(proposal.proposal_id)),
            "approvals": len(uow.v2_repairs.list_approval_decisions_by_proposal(proposal.proposal_id)),
            "candidates": len(uow.v2_repairs.list_patch_candidates_by_proposal(proposal.proposal_id)),
        }

    response = client.get("/v1/v2/jobs/job-1/governed-repair/status?stage_index=2")
    assert response.status_code == 200, response.text
    assert response.json()["next_action"] == "human_approval_required"

    ask_response = client.post(
        "/v1/v2/jobs/job-1/assistant/ask",
        json={"question": "why build failed?"},
        headers=_mutation_headers(),
    )
    assert ask_response.status_code == 200, ask_response.text
    assert "next action: human_approval_required" in ask_response.json()["failure_answer"]["answer"].lower()
    assert fake_assistant.calls == []

    with SqliteUnitOfWork(conn) as uow:
        after = {
            "diagnoses": len(uow.v2_failure_diagnoses.list_for_job("job-1")),
            "proposals": len(uow.v2_repairs.list_proposals_by_diagnosis(proposal.diagnosis_id)),
            "critiques": len(uow.v2_reviewer.list_critiques_by_proposal(proposal.proposal_id)),
            "approvals": len(uow.v2_repairs.list_approval_decisions_by_proposal(proposal.proposal_id)),
            "candidates": len(uow.v2_repairs.list_patch_candidates_by_proposal(proposal.proposal_id)),
        }
    assert before == after

    post_response = client.post(
        "/v1/v2/jobs/job-1/governed-repair/status",
        json={"patch_content": "diff --git a/pom.xml b/pom.xml", "command": "mvn test"},
        headers=_mutation_headers(),
    )
    assert post_response.status_code == 405, post_response.text


def test_status_endpoint_uses_event_derived_failure_diagnosis_without_persisted_row(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "event-derived.sqlite3")
    fake_assistant = _NoAssistantModelClient()
    client = _client(conn, fake_assistant)
    job_id = _seed_event_derived_stage2_job(conn, tmp_path / "event-derived")

    with SqliteUnitOfWork(conn) as uow:
        assert uow.v2_failure_diagnoses.list_for_job(job_id) == ()

    response = client.get(f"/v1/v2/jobs/{job_id}/governed-repair/status?stage_index=2")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["diagnosis"]["failure_type"] == "invalid_maven_wildcard_version"
    assert body["next_action"] == "create_proposal"
    assert "invalid wildcard maven versions" in body["diagnosis"]["likely_root_cause"].lower()
    assert fake_assistant.calls == []
