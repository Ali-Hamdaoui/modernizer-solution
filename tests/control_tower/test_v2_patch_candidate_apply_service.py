from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import migration_factory.control_tower.application.v2_repair_flow as repair_flow_module
from migration_factory.control_tower.application.v2_assistant_failure_answers import (
    V2AssistantFailureAnswerService,
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


class _FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str):
        self.calls.append({"prompt": prompt, "fallback": fallback})
        raise AssertionError("Apply flow must not call model client")


def _headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _connection(tmp_path: Path) -> sqlite3.Connection:
    tmp_path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        tmp_path / "patch_candidate_apply.sqlite3",
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


def _sandbox(tmp_path: Path) -> tuple[Path, Path]:
    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy" / "App.java"
    sandbox.mkdir(parents=True, exist_ok=True)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    (sandbox / "pom.xml").write_text("<project>\n  <version>3.0.x</version>\n</project>\n", encoding="utf-8")
    legacy.write_text("class App {}\n", encoding="utf-8")
    return sandbox, legacy


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


def _services(
    conn: sqlite3.Connection,
) -> tuple[
    V2RepairFlowService,
    V2ReviewerService,
    V2RepairProposalApprovalService,
    V2PatchCandidateService,
    V2PatchCandidateApplyService,
]:
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
    return repair_flow, reviewer_service, approval_service, candidate_service, apply_service


def _proposal(repair_flow: V2RepairFlowService):
    return repair_flow.create_proposal(
        command_id="cmd-1",
        failure_summary="invalid_maven_wildcard_version: wildcard pom version",
        hypothesis="Pin exact version",
        patch_summary="Replace wildcard version with exact managed version",
        affected_paths=("pom.xml",),
        validation_plan="Run mvn test",
        diagnosis_id="diag-1",
        diagnosis_checksum="diag-checksum-1",
        evidence_pack_checksum="evidence-checksum-1",
        context_pack_checksum="context-checksum-1",
    )


def _approved_candidate(conn: sqlite3.Connection, tmp_path: Path):
    sandbox, legacy = _sandbox(tmp_path)
    _seed_job_and_command(conn, sandbox)
    repair_flow, reviewer_service, approval_service, candidate_service, apply_service = _services(conn)
    proposal = _proposal(repair_flow)
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
    candidate = candidate_service.create_patch_candidate(proposal_id=proposal.proposal_id)
    return proposal, candidate, sandbox, legacy, apply_service, candidate_service, reviewer_service, approval_service


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
        (sandbox / "pom.xml").write_text("<project>\n  <version>3.0.0</version>\n</project>\n", encoding="utf-8")
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


def test_gate_allowed_candidate_can_be_applied_with_matching_checksum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    _, candidate, sandbox, legacy, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", _fake_apply_success_factory(calls))

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=candidate.patch_candidate_checksum,
        operator_note="apply now",
        validation_runner=_validation_success,
    )

    assert result.apply_status == "applied"
    assert result.candidate_status == "applied"
    assert result.applied is True
    assert result.rolled_back is False
    assert calls and str(calls[0]["unified_diff"]) == candidate.unified_diff
    assert "3.0.0" in (sandbox / "pom.xml").read_text(encoding="utf-8")
    assert legacy.read_text(encoding="utf-8") == "class App {}\n"
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_patch_candidate(candidate.patch_candidate_id)
        assert stored is not None
        assert stored.status == "applied"
        assert stored.applied_action_id
        assert stored.operator_note == "apply now"


def test_request_with_raw_patch_content_is_rejected_by_api_model(tmp_path: Path) -> None:
    fake_model = _FakeModelClient()
    client, conn = _client(tmp_path, fake_model)
    _, candidate, _, _, _, _, _, _ = _approved_candidate(conn, tmp_path)

    response = client.post(
        f"/v1/v2/patch-candidates/{candidate.patch_candidate_id}/apply",
        json={
            "patch_candidate_checksum": candidate.patch_candidate_checksum,
            "operator_note": "apply",
            "patch_content": candidate.unified_diff,
        },
        headers=_headers(),
    )

    assert response.status_code == 422, response.text
    assert fake_model.calls == []


def test_checksum_mismatch_rejects_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    _, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)

    with pytest.raises(ValueError, match="checksum mismatch"):
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum="wrong-checksum",
            validation_runner=_validation_success,
        )


def test_unsupported_or_gate_blocked_candidates_reject_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    proposal, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)

    with SqliteUnitOfWork(conn) as uow:
        conn.execute(
            "UPDATE v2_patch_candidates SET status = ? WHERE patch_candidate_id = ?",
            ("unsupported_materialization", candidate.patch_candidate_id),
        )
    with pytest.raises(ValueError, match="must be gate_allowed"):
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum=candidate.patch_candidate_checksum,
            validation_runner=_validation_success,
        )

    unsupported_checksum = V2PatchCandidateService.compute_patch_candidate_checksum(
        proposal=proposal,
        unified_diff=candidate.unified_diff,
        materialization_strategy="unsupported_strategy",
        gate_status=candidate.gate_status,
        gate_reason=candidate.gate_reason,
        touched_paths=candidate.touched_paths,
    )
    conn.execute(
        "UPDATE v2_patch_candidates SET status = ?, materialization_strategy = ?, patch_candidate_checksum = ? WHERE patch_candidate_id = ?",
        ("gate_allowed", "unsupported_strategy", unsupported_checksum, candidate.patch_candidate_id),
    )
    with pytest.raises(ValueError, match="Unsupported patch candidate materialization strategy"):
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum=unsupported_checksum,
            validation_runner=_validation_success,
        )


def test_unapproved_proposal_rejects_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    proposal, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repairs.update_proposal_status(proposal.proposal_id, "draft")

    with pytest.raises(ValueError, match="must remain approved"):
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum=candidate.patch_candidate_checksum,
            validation_runner=_validation_success,
        )


def test_stale_reviewer_or_approval_bindings_reject_apply(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    proposal, candidate, _, _, apply_service, _, reviewer_service, _ = _approved_candidate(conn, tmp_path)
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=proposal.context_pack_checksum or "",
        decision="reject",
        reasoning="latest reject",
    )

    with pytest.raises(ValueError, match="reviewer binding is stale"):
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum=candidate.patch_candidate_checksum,
            validation_runner=_validation_success,
        )

    conn = _connection(tmp_path / "second")
    proposal, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path / "second")
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repairs.save_approval_decision(
            V2RepairProposalApprovalDecisionRecord(
                decision_id="stale-human",
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
        apply_service.apply_patch_candidate(
            patch_candidate_id=candidate.patch_candidate_id,
            patch_candidate_checksum=candidate.patch_candidate_checksum,
            validation_runner=_validation_success,
        )


def test_gate_is_rerun_before_apply_and_can_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    _, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)
    calls: list[dict[str, object]] = []

    def fake_gate(**kwargs):
        calls.append(kwargs)
        return PatchGateResult(
            status="HUMAN_REVIEW_REQUIRED",
            reason="blocked at apply",
            rule_id="POM_VERSION_PIN_EXACT",
            risk="LOW",
            touched_paths=("pom.xml",),
            human_review_required=True,
        )

    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_patch_candidate_apply_service.evaluate_patch_proposal",
        fake_gate,
    )

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=candidate.patch_candidate_checksum,
        validation_runner=_validation_success,
    )

    assert calls
    assert result.apply_status == "gate_blocked_at_apply"
    assert result.applied is False
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_patch_candidate(candidate.patch_candidate_id)
        assert stored is not None
        assert stored.status == "gate_blocked_at_apply"


def test_exact_persisted_diff_used_without_rematerialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    proposal, candidate, _, _, apply_service, candidate_service, _, _ = _approved_candidate(conn, tmp_path)
    custom_diff = candidate.unified_diff.replace("3.0.0", "3.0.9")
    custom_checksum = V2PatchCandidateService.compute_patch_candidate_checksum(
        proposal=proposal,
        unified_diff=custom_diff,
        materialization_strategy=candidate.materialization_strategy,
        gate_status=candidate.gate_status,
        gate_reason=candidate.gate_reason,
        touched_paths=candidate.touched_paths,
    )
    conn.execute(
        "UPDATE v2_patch_candidates SET unified_diff = ?, patch_candidate_checksum = ? WHERE patch_candidate_id = ?",
        (custom_diff, custom_checksum, candidate.patch_candidate_id),
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", _fake_apply_success_factory(calls))

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=custom_checksum,
        validation_runner=_validation_success,
    )

    assert result.candidate_status == "applied"
    assert calls and str(calls[0]["unified_diff"]) == custom_diff


def test_validation_success_marks_candidate_applied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    _, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)
    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", _fake_apply_success_factory([]))

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=candidate.patch_candidate_checksum,
        validation_runner=_validation_success,
    )

    assert result.apply_status == "applied"
    assert result.validation_status == "passed"
    assert result.rolled_back is False


def test_validation_failure_triggers_rollback_and_marks_rolled_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    _, candidate, sandbox, legacy, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)
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
    original_legacy = legacy.read_text(encoding="utf-8")

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=candidate.patch_candidate_checksum,
        validation_runner=_validation_failure,
    )

    assert result.apply_status == "rolled_back"
    assert result.candidate_status == "rolled_back"
    assert result.rolled_back is True
    assert result.rollback_status == "ROLLED_BACK"
    assert "3.0.x" in (sandbox / "pom.xml").read_text(encoding="utf-8")
    assert legacy.read_text(encoding="utf-8") == original_legacy


def test_apply_failure_is_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _connection(tmp_path)
    _, candidate, _, _, apply_service, _, _, _ = _approved_candidate(conn, tmp_path)

    def fake_apply(**kwargs):
        run_dir = Path(kwargs["run_dir"])
        patch_path = run_dir / "repairs" / "patch_attempt_1.diff"
        snapshot_dir = run_dir / "repairs" / "snapshots" / "attempt_1"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(str(kwargs["unified_diff"]), encoding="utf-8")
        return PatchApplyResult(
            status="REJECTED",
            reason="git apply --check failed",
            patch_path=patch_path,
            touched_paths=list(kwargs["touched_paths"]),
            before_hashes={"pom.xml": "before"},
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=["git apply --check failed"],
        )

    monkeypatch.setattr(repair_flow_module, "apply_patch_to_sandbox", fake_apply)

    result = apply_service.apply_patch_candidate(
        patch_candidate_id=candidate.patch_candidate_id,
        patch_candidate_checksum=candidate.patch_candidate_checksum,
        validation_runner=_validation_success,
    )

    assert result.candidate_status == "apply_failed"
    assert result.applied is False
    with SqliteUnitOfWork(conn) as uow:
        stored = uow.v2_repairs.get_patch_candidate(candidate.patch_candidate_id)
        assert stored is not None
        assert stored.status == "apply_failed"


def test_assistant_reports_applied_and_rolled_back_states_accurately() -> None:
    applied = V2AssistantFailureAnswerService().answer_failure_question(
        job_id="job-1",
        latest_diagnosis_data={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "POM wildcard version.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
            "recommended_next_step": "none",
            "evidence": [],
            "missing_artifacts": [],
        },
        latest_proposal_data={
            "status": "approved",
            "patch_candidate_status": "applied",
            "patch_candidate_gate_status": "ALLOWED",
        },
        latest_reviewer_data={"decision": "accept"},
        existing_message_text="status?",
    )
    rolled_back = V2AssistantFailureAnswerService().answer_failure_question(
        job_id="job-1",
        latest_diagnosis_data={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "POM wildcard version.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
            "recommended_next_step": "none",
            "evidence": [],
            "missing_artifacts": [],
        },
        latest_proposal_data={
            "status": "approved",
            "patch_candidate_status": "rolled_back",
            "patch_candidate_gate_status": "ALLOWED",
        },
        latest_reviewer_data={"decision": "accept"},
        existing_message_text="status?",
    )

    assert "validation passed" in applied.answer.lower()
    assert "legacy source was not modified" in applied.answer.lower()
    assert "rollback happened" in rolled_back.answer.lower()
