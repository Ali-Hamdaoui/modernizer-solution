from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_approved_repair_execution_plan import (
    V2ApprovedRepairExecutionPlanService,
)
from migration_factory.control_tower.application.v2_approved_repair_patch_candidate import (
    V2ApprovedRepairPatchCandidateService,
)
from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_governed_repair_proposal import (
    V2GovernedRepairProposalService,
)
from tests.control_tower.test_v2_approved_repair_execution_plan import (
    _create_governed_proposal,
    _unknown_bundle,
    _write_approval_state,
)
from tests.control_tower.test_v2_assistant_failure_answers import (
    _FakeModelClient,
    _client,
    _mutation_headers,
    _seed_event_derived_stage2_job,
)


def _materialize_execution_plan(client, job_id: str, proposal_id: str) -> None:
    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text


def test_approved_execution_plan_can_materialize_patch_candidate(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    pom_path = run_dir / "workspaces" / "sandbox" / "pom.xml"
    before = pom_path.read_text(encoding="utf-8")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    candidate = body["patch_candidate"]
    assert candidate["human_approved"] is True
    assert candidate["applied"] is False
    assert candidate["read_only"] is True
    assert candidate["no_source_mutation"] is True
    assert candidate["patch_strategy"] == "bounded_structured_operations"
    assert len(candidate["patch_operations"]) == 2
    assert candidate["patch_operations"][0]["property"] == "javax.persistence.version"
    assert candidate["patch_operations"][0]["from"] == "3.0.x"
    assert candidate["patch_operations"][0]["to"] == "3.1.0"
    assert candidate["patch_operations"][1]["property"] == "javax.servlet.version"
    assert candidate["patch_operations"][1]["from"] == "5.0.x"
    assert candidate["patch_operations"][1]["to"] == "6.0.0"
    assert (proposal_dir / "repair_patch_candidate.json").is_file()
    assert pom_path.read_text(encoding="utf-8") == before


def test_pending_approval_cannot_materialize_patch_candidate(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "pending approval" in response.text.lower()


def test_rejected_proposal_cannot_materialize_patch_candidate(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="rejected", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "rejected" in response.text.lower()


def test_stale_checksum_blocks_patch_candidate_materialization(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="approved", checksum="wrong-checksum")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "checksum" in response.text.lower()


def test_missing_execution_plan_blocks_patch_candidate_materialization(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 404
    assert "REPAIR_PROPOSAL_NOT_FOUND" in response.text


def test_unknown_failure_creates_conservative_empty_candidate(tmp_path: Path) -> None:
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
    (proposal_dir / "repair_proposal.json").write_text(
        json.dumps(final_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (proposal_dir / "repair_verification.json").write_text(
        json.dumps(source_verification, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (proposal_dir / "repair_proposal.md").write_text("read only", encoding="utf-8")
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    V2ApprovedRepairExecutionPlanService().materialize(
        trace_root=run_root,
        proposal_id="proposal-unknown",
    )

    candidate_result = V2ApprovedRepairPatchCandidateService().materialize(
        trace_root=run_root,
        proposal_id="proposal-unknown",
    )

    candidate = candidate_result.patch_candidate
    assert candidate["patch_operations"] == []
    assert candidate["requires_human_review"] is True
    assert "unsupported" in candidate["unsupported_reason"].lower()


def test_get_patch_candidate_returns_persisted_artifact(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    materialize = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )
    assert materialize.status_code == 200, materialize.text

    response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/patch-candidate",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patch_candidate"]["proposal_id"] == proposal_id
    assert body["applied"] is False


def test_no_source_or_sandbox_files_are_modified_by_patch_candidate_materialization(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_execution_plan(client, job_id, proposal_id)
    pom_path = run_dir / "workspaces" / "sandbox" / "pom.xml"
    build_error_path = run_dir / "build" / "build-error-20260618-004516-dependency_error.json"
    before_pom = pom_path.read_text(encoding="utf-8")
    before_build = build_error_path.read_text(encoding="utf-8")
    before_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    after_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}
    assert after_files - before_files == {f"ai_supervision/repair_proposals/{proposal_id}/repair_patch_candidate.json"}
    assert pom_path.read_text(encoding="utf-8") == before_pom
    assert build_error_path.read_text(encoding="utf-8") == before_build


def test_unknown_proposal_returns_not_found_for_patch_candidate(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir = _seed_event_derived_stage2_job(conn, tmp_path)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/does-not-exist/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 404
    assert "REPAIR_PROPOSAL_NOT_FOUND" in response.text
