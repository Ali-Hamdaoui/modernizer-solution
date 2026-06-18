from __future__ import annotations

from pathlib import Path

from migration_factory.control_tower.application.v2_approved_repair_sandbox_validation import (
    V2ApprovedRepairSandboxValidationService,
)
from migration_factory.control_tower.application.v2_repair_lifecycle_projection import (
    V2RepairLifecycleProjectionService,
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
        errors=["build validation failed after repair patch"],
    )


def _post(client, url: str) -> None:
    response = client.post(url, json={}, headers=_mutation_headers())
    assert response.status_code == 200, response.text


def _prepare_proposal(client, conn, tmp_path: Path):
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    return job_id, run_dir, proposal_id, proposal_dir, checksum


def test_no_repair_proposals_returns_empty_lifecycle_list(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir = _seed_event_derived_stage2_job(conn, tmp_path)

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["repair_proposals"] == []
    assert body["read_only"] is True


def test_proposal_created_or_pending_approval_state(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle")

    assert response.status_code == 200, response.text
    lifecycle = response.json()["repair_lifecycle"]
    assert lifecycle["current_state"] == "pending_approval"
    assert lifecycle["next_operator_action"] == "approve repair proposal"


def test_approved_proposal_returns_approved_state(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)

    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]

    assert lifecycle["current_state"] == "approved"
    assert lifecycle["next_operator_action"] == "materialize execution plan"


def test_execution_plan_and_patch_candidate_states(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)

    _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan")
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]
    assert lifecycle["current_state"] == "execution_plan_ready"
    assert lifecycle["next_operator_action"] == "materialize patch candidate"

    _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate")
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]
    assert lifecycle["current_state"] == "patch_candidate_ready"
    assert lifecycle["next_operator_action"] == "apply patch to sandbox"


def test_applied_to_sandbox_state(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    for endpoint in ("materialize-execution-plan", "materialize-patch-candidate", "apply-to-sandbox"):
        _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{endpoint}")

    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]

    assert lifecycle["current_state"] == "applied_to_sandbox"
    assert lifecycle["sandbox_apply_state"] == "applied"
    assert lifecycle["next_operator_action"] == "validate sandbox repair"


def test_validation_passed_and_rolled_back_states(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    (tmp_path / "passed").mkdir(parents=True, exist_ok=True)
    client, conn = _client(tmp_path, fake)
    job_id, run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path / "passed")
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    for endpoint in ("materialize-execution-plan", "materialize-patch-candidate", "apply-to-sandbox"):
        _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{endpoint}")
    V2ApprovedRepairSandboxValidationService().validate(
        trace_root=run_dir,
        proposal_id=proposal_id,
        validation_runner=_validation_success,
    )
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]
    assert lifecycle["current_state"] == "validation_passed"
    assert lifecycle["next_operator_action"] == "no action required"

    fake2 = _FakeModelClient()
    (tmp_path / "rolled_back").mkdir(parents=True, exist_ok=True)
    client2, conn2 = _client(tmp_path / "rolled_back", fake2)
    job_id2, run_dir2, proposal_id2, proposal_dir2, checksum2 = _prepare_proposal(client2, conn2, tmp_path / "rolled_back")
    _write_approval_state(proposal_dir2, state="approved", checksum=checksum2)
    for endpoint in ("materialize-execution-plan", "materialize-patch-candidate", "apply-to-sandbox"):
        _post(client2, f"/v1/v2/migration-jobs/{job_id2}/repair-proposals/{proposal_id2}/{endpoint}")
    V2ApprovedRepairSandboxValidationService().validate(
        trace_root=run_dir2,
        proposal_id=proposal_id2,
        validation_runner=_validation_failure,
    )
    lifecycle2 = client2.get(f"/v1/v2/migration-jobs/{job_id2}/repair-proposals/{proposal_id2}/lifecycle").json()["repair_lifecycle"]
    assert lifecycle2["current_state"] == "validation_failed_rolled_back"
    assert lifecycle2["rollback_performed"] is True
    assert lifecycle2["next_operator_action"] == "inspect rollback"


def test_rejected_proposal_returns_rejected_state(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="rejected", checksum=checksum)

    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/lifecycle").json()["repair_lifecycle"]

    assert lifecycle["current_state"] == "rejected"
    assert lifecycle["next_operator_action"] == "human review required"


def test_projection_is_read_only_and_does_not_modify_artifacts(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    before_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")

    assert response.status_code == 200, response.text
    after_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}
    assert after_files == before_files


def test_repair_status_question_returns_lifecycle_answer_without_action(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, _run_dir, proposal_id, proposal_dir, checksum = _prepare_proposal(client, conn, tmp_path)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan")
    _post(client, f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate")

    response = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "did you apply it?"},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"]["status"] == "repair_lifecycle_projection"
    assert "current state: patch_candidate_ready" in body["assistant_message"]["content"].lower()
    assert "no validation run" in body["assistant_message"]["content"].lower()
    assert "no patch applied by this answer" in body["assistant_message"]["content"].lower()
