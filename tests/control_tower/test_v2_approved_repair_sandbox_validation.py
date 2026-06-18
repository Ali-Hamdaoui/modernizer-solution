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
        warnings=["build ok"],
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
        errors=["build validation failed after repair patch"],
    )


def _materialize_and_apply(client, job_id: str, proposal_id: str) -> None:
    for endpoint in (
        "materialize-execution-plan",
        "materialize-patch-candidate",
        "apply-to-sandbox",
    ):
        response = client.post(
            f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{endpoint}",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text


def _service() -> V2ApprovedRepairSandboxValidationService:
    return V2ApprovedRepairSandboxValidationService()


def test_validation_runs_only_after_successful_sandbox_apply(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)
    service = _service()
    source_pom = tmp_path / "legacy-app" / "pom.xml"
    source_pom.parent.mkdir(parents=True, exist_ok=True)
    source_pom.write_text("<project><version>legacy</version></project>", encoding="utf-8")
    source_before = source_pom.read_text(encoding="utf-8")

    outcome = service.validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_success,
    )

    result = outcome.validation_result
    assert result["status"] == "passed"
    assert result["rollback_performed"] is False
    assert result["source_mutated"] is False
    assert outcome.stage_resumed is False
    assert source_pom.read_text(encoding="utf-8") == source_before
    assert (proposal_dir / "sandbox_validation_result.json").is_file()


def test_validation_cannot_run_before_apply(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    for endpoint in ("materialize-execution-plan", "materialize-patch-candidate"):
        response = client.post(
            f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{endpoint}",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text

    with pytest.raises(ValueError, match="applied to sandbox before validation"):
        _service().validate(
            trace_root=run_dir,
            proposal_id=proposal_id,
            validation_runner=_validation_success,
        )


def test_pending_or_rejected_approval_cannot_validate(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)

    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)
    with pytest.raises(ValueError, match="pending approval"):
        _service().validate(trace_root=run_dir, proposal_id=proposal_id, validation_runner=_validation_success)

    _write_approval_state(proposal_dir, state="rejected", checksum=checksum)
    with pytest.raises(ValueError, match="rejected"):
        _service().validate(trace_root=run_dir, proposal_id=proposal_id, validation_runner=_validation_success)


def test_stale_checksum_blocks_validation(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="approved", checksum="wrong-checksum")

    with pytest.raises(ValueError, match="checksum"):
        _service().validate(trace_root=run_dir, proposal_id=proposal_id, validation_runner=_validation_success)


def test_validation_failure_restores_sandbox_pom_from_backup(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    original_pom = (proposal_dir / "backups").exists()
    assert original_pom is False
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    before_apply = sandbox_pom.read_text(encoding="utf-8")
    _materialize_and_apply(client, job_id, proposal_id)
    applied_text = sandbox_pom.read_text(encoding="utf-8")
    assert applied_text != before_apply

    outcome = _service().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_failure,
    )

    result = outcome.validation_result
    assert result["status"] == "rolled_back"
    assert result["rollback_performed"] is True
    assert "build validation failed" in result["rollback_reason"]
    assert sandbox_pom.read_text(encoding="utf-8") == before_apply


def test_rollback_failure_is_reported_as_controlled_error(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)

    def _failing_restore(src: Path, dst: Path) -> None:
        raise OSError("restore failed")

    outcome = _service().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_failure,
        backup_restorer=_failing_restore,
    )

    result = outcome.validation_result
    assert result["status"] == "failed"
    assert result["rollback_performed"] is False
    assert result["rollback_error"] == "restore failed"
    assert "build validation failed" in result["rollback_reason"]


def test_get_validation_result_returns_persisted_artifact(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)
    _service().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_success,
    )

    response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/sandbox-validation-result",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["validation_result"]["proposal_id"] == proposal_id
    assert body["sandbox_only"] is True
    assert body["source_mutated"] is False
    assert body["stage_resumed"] is False


def test_no_stage_resume_and_no_source_mutation_on_validation_failure(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_and_apply(client, job_id, proposal_id)
    source_pom = tmp_path / "legacy-app" / "pom.xml"
    source_pom.parent.mkdir(parents=True, exist_ok=True)
    source_pom.write_text("<project><version>legacy</version></project>", encoding="utf-8")
    source_before = source_pom.read_text(encoding="utf-8")

    outcome = _service().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_failure,
    )

    assert outcome.stage_resumed is False
    assert outcome.source_mutated is False
    assert source_pom.read_text(encoding="utf-8") == source_before
