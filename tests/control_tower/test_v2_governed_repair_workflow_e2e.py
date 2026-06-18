from __future__ import annotations

from pathlib import Path

import pytest

from migration_factory.control_tower.application.v2_approved_repair_sandbox_validation import (
    V2ApprovedRepairSandboxValidationService,
)
from migration_factory.repair_loop.validation_runner import ValidationResult
from tests.control_tower.test_v2_approved_repair_execution_plan import (
    _create_governed_proposal,
    _write_approval_state,
)
from tests.control_tower.test_v2_assistant_failure_answers import (
    _FakeModelClient,
    _client,
    _mutation_headers,
    _seed_event_derived_stage2_job,
)


def _validation_success(**kwargs) -> ValidationResult:
    return ValidationResult(
        passed=True,
        build_status="BUILD_PASSED_IN_SANDBOX",
        test_status="TEST_PASSED",
        h2_status="H2_STARTUP_SKIPPED",
        validation_commands=[["mvn", "test"]],
        artifact_refs={},
        warnings=["sandbox repair validation passed"],
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
        errors=["sandbox repair validation failed"],
    )


def _seed_governed_repair(tmp_path: Path):
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    source_pom = tmp_path / "legacy-app" / "pom.xml"
    source_pom.parent.mkdir(parents=True, exist_ok=True)
    source_pom.write_text(
        "<project><properties>"
        "<javax.persistence.version>2.2</javax.persistence.version>"
        "<javax.servlet.version>2.5</javax.servlet.version>"
        "</properties></project>",
        encoding="utf-8",
    )
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    return client, job_id, run_dir, source_pom, proposal_id, proposal_dir, checksum


def _post_repair_step(client, job_id: str, proposal_id: str, step: str):
    return client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{step}",
        json={},
        headers=_mutation_headers(),
    )


def _approve(proposal_dir: Path, *, checksum: str) -> None:
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)


def _materialize_plan_candidate_and_apply(client, job_id: str, proposal_id: str) -> None:
    for step in (
        "materialize-execution-plan",
        "materialize-patch-candidate",
        "apply-to-sandbox",
    ):
        response = _post_repair_step(client, job_id, proposal_id, step)
        assert response.status_code == 200, response.text


def test_governed_repair_workflow_happy_path_validates_sandbox_only(tmp_path: Path) -> None:
    client, job_id, run_dir, source_pom, proposal_id, proposal_dir, checksum = _seed_governed_repair(tmp_path)
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    source_before = source_pom.read_text(encoding="utf-8")

    _approve(proposal_dir, checksum=checksum)
    _materialize_plan_candidate_and_apply(client, job_id, proposal_id)
    validation = V2ApprovedRepairSandboxValidationService().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_success,
    )

    sandbox_text = sandbox_pom.read_text(encoding="utf-8")
    validation_result = validation.validation_result
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")
    assert lifecycle.status_code == 200, lifecycle.text
    lifecycle_proposal = lifecycle.json()["repair_proposals"][0]

    assert "<javax.persistence.version>3.1.0</javax.persistence.version>" in sandbox_text
    assert "<javax.servlet.version>6.0.0</javax.servlet.version>" in sandbox_text
    assert "3.0.x" not in sandbox_text
    assert "5.0.x" not in sandbox_text
    assert source_pom.read_text(encoding="utf-8") == source_before
    assert (proposal_dir / "sandbox_apply_result.json").is_file()
    assert (proposal_dir / "sandbox_validation_result.json").is_file()
    assert validation_result["status"] == "passed"
    assert validation_result["source_mutated"] is False
    assert validation_result["sandbox_only"] is True
    assert validation.stage_resumed is False
    assert lifecycle_proposal["current_state"] == "validation_passed"
    assert lifecycle_proposal["stage_resumed"] is False


def test_governed_repair_workflow_rolls_back_failed_sandbox_validation(tmp_path: Path) -> None:
    client, job_id, run_dir, source_pom, proposal_id, proposal_dir, checksum = _seed_governed_repair(tmp_path)
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    sandbox_before_apply = sandbox_pom.read_text(encoding="utf-8")
    source_before = source_pom.read_text(encoding="utf-8")

    _approve(proposal_dir, checksum=checksum)
    _materialize_plan_candidate_and_apply(client, job_id, proposal_id)
    assert sandbox_pom.read_text(encoding="utf-8") != sandbox_before_apply
    validation = V2ApprovedRepairSandboxValidationService().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_failure,
    )

    validation_result = validation.validation_result
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")
    assert lifecycle.status_code == 200, lifecycle.text
    lifecycle_proposal = lifecycle.json()["repair_proposals"][0]

    assert sandbox_pom.read_text(encoding="utf-8") == sandbox_before_apply
    assert source_pom.read_text(encoding="utf-8") == source_before
    assert validation_result["status"] == "rolled_back"
    assert validation_result["rollback_performed"] is True
    assert "sandbox repair validation failed" in validation_result["rollback_reason"]
    assert validation_result["source_mutated"] is False
    assert validation_result["sandbox_only"] is True
    assert lifecycle_proposal["current_state"] == "validation_failed_rolled_back"
    assert lifecycle_proposal["stage_resumed"] is False


def test_governed_repair_workflow_safety_gates_fail_closed(tmp_path: Path) -> None:
    client, job_id, run_dir, _source_pom, proposal_id, proposal_dir, checksum = _seed_governed_repair(tmp_path)

    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)
    before_approval = _post_repair_step(client, job_id, proposal_id, "materialize-execution-plan")
    assert before_approval.status_code == 400
    assert not (proposal_dir / "repair_execution_plan.json").exists()

    _approve(proposal_dir, checksum=checksum)
    before_plan = _post_repair_step(client, job_id, proposal_id, "materialize-patch-candidate")
    assert before_plan.status_code != 200
    assert not (proposal_dir / "repair_patch_candidate.json").exists()

    plan = _post_repair_step(client, job_id, proposal_id, "materialize-execution-plan")
    assert plan.status_code == 200, plan.text
    before_candidate = _post_repair_step(client, job_id, proposal_id, "apply-to-sandbox")
    assert before_candidate.status_code != 200
    assert not (proposal_dir / "sandbox_apply_result.json").exists()

    candidate = _post_repair_step(client, job_id, proposal_id, "materialize-patch-candidate")
    assert candidate.status_code == 200, candidate.text
    with pytest.raises(ValueError, match="applied to sandbox before validation"):
        V2ApprovedRepairSandboxValidationService().validate(
            trace_root=run_dir,
            proposal_id=proposal_id,
            validation_runner=_validation_success,
        )

    stale_dir = tmp_path / "stale"
    stale_dir.mkdir()
    stale_client, stale_job_id, _stale_run_dir, _stale_source, stale_proposal_id, stale_proposal_dir, _ = (
        _seed_governed_repair(stale_dir)
    )
    _write_approval_state(stale_proposal_dir, state="approved", checksum="wrong-checksum")
    stale_response = _post_repair_step(
        stale_client,
        stale_job_id,
        stale_proposal_id,
        "materialize-execution-plan",
    )
    assert stale_response.status_code == 400
    assert "checksum" in stale_response.text.lower()
    assert not (stale_proposal_dir / "repair_execution_plan.json").exists()
