from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.repair_loop.validation_runner import ValidationResult
from tests.control_tower.test_v2_approved_repair_execution_plan import _create_governed_proposal
from tests.control_tower.test_v2_assistant_failure_answers import (
    _FakeModelClient,
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
        warnings=["api sandbox repair validation passed"],
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
        errors=["api sandbox repair validation failed"],
    )


def _client(tmp_path: Path, validation_runner) -> tuple[TestClient, sqlite3.Connection]:
    conn = sqlite3.connect(
        tmp_path / "governed_repair_workflow_api_e2e.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(
        lambda: SqliteUnitOfWork(conn),
        v2_assistant_model_client=_FakeModelClient(),
        v2_repair_validation_runner=validation_runner,
    )
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _seed_api_workflow(tmp_path: Path, validation_runner):
    client, conn = _client(tmp_path, validation_runner)
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


def _post(client: TestClient, job_id: str, proposal_id: str, step: str, payload: dict | None = None):
    return client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/{step}",
        json=payload or {},
        headers=_mutation_headers(),
    )


def _approve(client: TestClient, job_id: str, proposal_id: str, checksum: str):
    return _post(
        client,
        job_id,
        proposal_id,
        "approve",
        {"expected_checksum": checksum, "operator": "architect"},
    )


def _run_api_chain_to_apply(client: TestClient, job_id: str, proposal_id: str) -> None:
    for step in (
        "materialize-execution-plan",
        "materialize-patch-candidate",
        "apply-to-sandbox",
    ):
        response = _post(client, job_id, proposal_id, step)
        assert response.status_code == 200, response.text


def test_api_governed_repair_workflow_happy_path(tmp_path: Path) -> None:
    client, job_id, run_dir, source_pom, proposal_id, proposal_dir, checksum = _seed_api_workflow(
        tmp_path,
        _validation_success,
    )
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    source_before = source_pom.read_text(encoding="utf-8")

    approval = _approve(client, job_id, proposal_id, checksum)
    assert approval.status_code == 200, approval.text
    assert approval.json()["applied"] is False
    _run_api_chain_to_apply(client, job_id, proposal_id)
    validation = _post(client, job_id, proposal_id, "validate-sandbox-repair")
    assert validation.status_code == 200, validation.text
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")
    assert lifecycle.status_code == 200, lifecycle.text

    sandbox_text = sandbox_pom.read_text(encoding="utf-8")
    validation_body = validation.json()
    lifecycle_proposal = lifecycle.json()["repair_proposals"][0]
    assert "<javax.persistence.version>3.1.0</javax.persistence.version>" in sandbox_text
    assert "<javax.servlet.version>6.0.0</javax.servlet.version>" in sandbox_text
    assert source_pom.read_text(encoding="utf-8") == source_before
    assert (proposal_dir / "sandbox_apply_result.json").is_file()
    assert (proposal_dir / "sandbox_validation_result.json").is_file()
    assert validation_body["validation_result"]["status"] == "passed"
    assert validation_body["source_mutated"] is False
    assert validation_body["sandbox_only"] is True
    assert validation_body["stage_resumed"] is False
    assert lifecycle_proposal["current_state"] == "validation_passed"
    assert lifecycle_proposal["stage_resumed"] is False


def test_api_governed_repair_workflow_rollback_path(tmp_path: Path) -> None:
    client, job_id, run_dir, source_pom, proposal_id, _proposal_dir, checksum = _seed_api_workflow(
        tmp_path,
        _validation_failure,
    )
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    sandbox_before_apply = sandbox_pom.read_text(encoding="utf-8")
    source_before = source_pom.read_text(encoding="utf-8")

    approval = _approve(client, job_id, proposal_id, checksum)
    assert approval.status_code == 200, approval.text
    _run_api_chain_to_apply(client, job_id, proposal_id)
    assert sandbox_pom.read_text(encoding="utf-8") != sandbox_before_apply
    validation = _post(client, job_id, proposal_id, "validate-sandbox-repair")
    assert validation.status_code == 200, validation.text
    lifecycle = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-lifecycle")
    assert lifecycle.status_code == 200, lifecycle.text

    validation_body = validation.json()
    lifecycle_proposal = lifecycle.json()["repair_proposals"][0]
    assert sandbox_pom.read_text(encoding="utf-8") == sandbox_before_apply
    assert source_pom.read_text(encoding="utf-8") == source_before
    assert validation_body["validation_result"]["status"] == "rolled_back"
    assert validation_body["validation_result"]["rollback_performed"] is True
    assert validation_body["source_mutated"] is False
    assert validation_body["sandbox_only"] is True
    assert validation_body["stage_resumed"] is False
    assert lifecycle_proposal["current_state"] == "validation_failed_rolled_back"


def test_api_governed_repair_workflow_safety_gates(tmp_path: Path) -> None:
    client, job_id, run_dir, _source_pom, proposal_id, proposal_dir, checksum = _seed_api_workflow(
        tmp_path,
        _validation_success,
    )

    wrong_approval = _approve(client, job_id, proposal_id, "wrong-checksum")
    assert wrong_approval.status_code == 400
    assert "checksum" in wrong_approval.text.lower()
    assert not (proposal_dir / "approval_state.json").exists()

    before_approval = _post(client, job_id, proposal_id, "materialize-execution-plan")
    assert before_approval.status_code == 404
    assert not (proposal_dir / "repair_execution_plan.json").exists()

    approval = _approve(client, job_id, proposal_id, checksum)
    assert approval.status_code == 200, approval.text
    before_plan = _post(client, job_id, proposal_id, "materialize-patch-candidate")
    assert before_plan.status_code != 200
    assert not (proposal_dir / "repair_patch_candidate.json").exists()

    plan = _post(client, job_id, proposal_id, "materialize-execution-plan")
    assert plan.status_code == 200, plan.text
    before_candidate = _post(client, job_id, proposal_id, "apply-to-sandbox")
    assert before_candidate.status_code != 200
    assert not (proposal_dir / "sandbox_apply_result.json").exists()

    candidate = _post(client, job_id, proposal_id, "materialize-patch-candidate")
    assert candidate.status_code == 200, candidate.text
    before_apply = _post(client, job_id, proposal_id, "validate-sandbox-repair")
    assert before_apply.status_code != 200
    assert "applied to sandbox before validation" in before_apply.text.lower()
    assert not (proposal_dir / "sandbox_validation_result.json").exists()
    assert (run_dir / "workspaces" / "sandbox" / "pom.xml").is_file()
