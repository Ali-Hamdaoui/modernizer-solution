from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_approved_repair_execution_plan import (
    V2ApprovedRepairExecutionPlanService,
)
from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_governed_repair_proposal import (
    V2GovernedRepairProposalService,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import (
    FailureEvidenceBundle,
    RunEvidenceBundle,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from tests.control_tower.test_v2_assistant_failure_answers import (
    _FakeModelClient,
    _client,
    _mutation_headers,
    _seed_event_derived_stage2_job,
)
from tests.control_tower.test_v2_governed_repair_proposal import _failed_bundle


def _write_approval_state(proposal_dir: Path, *, state: str, checksum: str) -> None:
    payload = json.loads((proposal_dir / "repair_proposal.json").read_text(encoding="utf-8"))
    approval_state = {
        "proposal_id": payload["proposal_id"],
        "run_id": payload["run_id"],
        "state": state,
        "checksum": checksum,
        "approved_at": utc_now_text() if state == "approved" else None,
        "rejected_at": utc_now_text() if state == "rejected" else None,
        "operator": "architect",
        "read_only_until_apply": True,
        "no_auto_apply": True,
    }
    (proposal_dir / "approval_state.json").write_text(
        json.dumps(approval_state, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _create_governed_proposal(client, job_id: str, run_dir: Path) -> tuple[str, Path, str]:
    response = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "solve this"},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    proposal_id = body["repair_proposal_review"]["proposal_id"]
    proposal_dir = run_dir / "ai_supervision" / "repair_proposals" / proposal_id
    payload = json.loads((proposal_dir / "repair_proposal.json").read_text(encoding="utf-8"))
    checksum = V2ApprovedRepairExecutionPlanService().compute_proposal_checksum(payload)
    return proposal_id, proposal_dir, checksum


def _unknown_bundle() -> RunEvidenceBundle:
    return RunEvidenceBundle(
        run_id="v2-unknown-s2",
        stage_statuses={"2": "failed"},
        migration_status="failed",
        ai_supervision_status="not_requested",
        approval_state="not_required",
        final_status="BUILD_FAILED_IN_SANDBOX",
        build_status="BUILD_FAILED_IN_SANDBOX",
        test_status="",
        final_proof_level="not_verified",
        latest_trustworthy_migration_event={"type": "build_failed", "status": "failed"},
        generated_artifact_refs=({"label": "pom.xml", "path": "pom.xml"},),
        failure_events=({"type": "build_failed", "message": "Build failed in sandbox"},),
        build_test_error_contracts=(),
        relevant_log_excerpts=(),
        pom_excerpts=(),
        deterministic_failure_classification={
            "failure_type": "unknown_build_failure",
            "likely_root_cause": "Unknown root cause.",
            "confidence": "low",
            "affected_paths": ["pom.xml"],
        },
        failure_bundle=FailureEvidenceBundle(
            failure_type="unknown_build_failure",
            root_cause="Unknown root cause.",
            confidence="low",
            failure_events=({"type": "build_failed", "message": "Build failed in sandbox"},),
            missing_artifacts=(),
            error_contracts=(),
            log_excerpts=(),
            pom_excerpts=(),
            affected_paths=("pom.xml",),
        ),
        next_operator_action="review_failure_evidence",
        read_only=True,
    )


def test_approved_proposal_can_materialize_execution_plan(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    pom_path = run_dir / "workspaces" / "sandbox" / "pom.xml"
    before = pom_path.read_text(encoding="utf-8")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    plan = body["execution_plan"]
    assert plan["human_approved"] is True
    assert plan["applied"] is False
    assert plan["requires_sandbox_apply"] is True
    assert plan["requires_validation"] is True
    assert len(plan["planned_operations"]) == 2
    assert plan["planned_operations"][0]["property"] == "javax.persistence.version"
    assert plan["planned_operations"][1]["property"] == "javax.servlet.version"
    assert (proposal_dir / "repair_execution_plan.json").is_file()
    assert pom_path.read_text(encoding="utf-8") == before


def test_pending_proposal_cannot_materialize_execution_plan(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "pending approval" in response.text.lower()
    assert not (proposal_dir / "repair_execution_plan.json").exists()


def test_rejected_proposal_cannot_materialize_execution_plan(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="rejected", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "rejected" in response.text.lower()


def test_wrong_checksum_blocks_materialization(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, _checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum="wrong-checksum")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "checksum" in response.text.lower()


def test_unknown_failure_creates_conservative_no_auto_operation_plan(tmp_path: Path) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-unknown-s2"
    proposal_dir = run_root / "ai_supervision" / "repair_proposals" / "proposal-unknown"
    proposal_dir.mkdir(parents=True, exist_ok=True)
    service = V2GovernedRepairProposalService(
        proposer_client=None,
        reviewer_client=None,
        trace_store=V2DualModelInvocationAuditStore(),
    )
    result = service.propose(
        question="solve this",
        bundle=_unknown_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )
    source_dir = run_root / "ai_supervision" / "repair_proposals" / result.proposal_id
    source_payload = json.loads((source_dir / "repair_proposal.json").read_text(encoding="utf-8"))
    source_verification = json.loads((source_dir / "repair_verification.json").read_text(encoding="utf-8"))
    final_payload = source_payload | {"proposal_id": "proposal-unknown"}
    checksum = V2ApprovedRepairExecutionPlanService().compute_proposal_checksum(final_payload)
    target_dir = proposal_dir
    (target_dir / "repair_proposal.json").write_text(json.dumps(final_payload, indent=2, sort_keys=True), encoding="utf-8")
    (target_dir / "repair_verification.json").write_text(json.dumps(source_verification, indent=2, sort_keys=True), encoding="utf-8")
    (target_dir / "repair_proposal.md").write_text("read only", encoding="utf-8")
    _write_approval_state(target_dir, state="approved", checksum=checksum)

    plan_result = V2ApprovedRepairExecutionPlanService().materialize(
        trace_root=run_root,
        proposal_id="proposal-unknown",
    )

    plan = plan_result.execution_plan
    assert plan["planned_operations"] == []
    assert plan["requires_human_review"] is True
    assert "unsupported" in plan["unsupported_reason"].lower()


def test_get_execution_plan_returns_persisted_artifact(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    materialize = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )
    assert materialize.status_code == 200, materialize.text

    response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/execution-plan",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["execution_plan"]["proposal_id"] == proposal_id
    assert body["applied"] is False


def test_unknown_proposal_returns_not_found(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir = _seed_event_derived_stage2_job(conn, tmp_path)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/does-not-exist/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 404
    assert "REPAIR_PROPOSAL_NOT_FOUND" in response.text


def test_no_source_or_sandbox_files_are_modified_by_materialization(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    pom_path = run_dir / "workspaces" / "sandbox" / "pom.xml"
    build_error_path = run_dir / "build" / "build-error-20260618-004516-dependency_error.json"
    before_pom = pom_path.read_text(encoding="utf-8")
    before_build = build_error_path.read_text(encoding="utf-8")
    before_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    after_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}
    assert after_files - before_files == {f"ai_supervision/repair_proposals/{proposal_id}/repair_execution_plan.json"}
    assert pom_path.read_text(encoding="utf-8") == before_pom
    assert build_error_path.read_text(encoding="utf-8") == before_build
