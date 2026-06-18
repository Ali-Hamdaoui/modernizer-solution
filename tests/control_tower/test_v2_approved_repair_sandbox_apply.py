from __future__ import annotations

import json
from pathlib import Path

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


def _materialize_patch_candidate(client, job_id: str, proposal_id: str) -> None:
    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-execution-plan",
        json={},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text
    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/materialize-patch-candidate",
        json={},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text


def test_approved_bounded_candidate_applies_to_sandbox_pom(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    source_pom = tmp_path / "legacy-app" / "pom.xml"
    source_pom.parent.mkdir(parents=True, exist_ok=True)
    source_pom.write_text("<project><properties><javax.persistence.version>2.2</javax.persistence.version></properties></project>", encoding="utf-8")
    source_before = source_pom.read_text(encoding="utf-8")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    apply_result = body["apply_result"]
    updated = sandbox_pom.read_text(encoding="utf-8")
    assert "3.1.0" in updated
    assert "6.0.0" in updated
    assert "3.0.x" not in updated
    assert "5.0.x" not in updated
    assert apply_result["applied"] is True
    assert apply_result["validation_started"] is False
    assert apply_result["sandbox_only"] is True
    assert body["source_mutated"] is False
    assert source_pom.read_text(encoding="utf-8") == source_before


def test_backup_created_before_sandbox_modification(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    before = sandbox_pom.read_text(encoding="utf-8")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    backup_path = proposal_dir / "backups" / "pom.xml.before-repair"
    assert backup_path.is_file()
    assert backup_path.read_text(encoding="utf-8") == before


def test_pending_approval_cannot_apply_to_sandbox(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="pending_approval", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "pending approval" in response.text.lower()


def test_rejected_approval_cannot_apply_to_sandbox(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="rejected", checksum=checksum)

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "rejected" in response.text.lower()


def test_stale_checksum_blocks_sandbox_apply(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    _write_approval_state(proposal_dir, state="approved", checksum="wrong-checksum")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "checksum" in response.text.lower()


def test_unknown_or_unsupported_operation_blocks_apply(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    candidate_path = proposal_dir / "repair_patch_candidate.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["patch_operations"] = [
        {
            "target_file": "pom.xml",
            "operation": "replace_xml_block",
            "property": "javax.persistence.version",
            "from": "3.0.x",
            "to": "3.1.0",
        }
    ]
    candidate_path.write_text(json.dumps(candidate, indent=2, sort_keys=True), encoding="utf-8")
    before = (run_dir / "workspaces" / "sandbox" / "pom.xml").read_text(encoding="utf-8")

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 400
    assert "unsupported" in response.text.lower()
    assert (run_dir / "workspaces" / "sandbox" / "pom.xml").read_text(encoding="utf-8") == before


def test_double_apply_is_rejected(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)

    first = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )
    second = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 400
    assert "double apply" in second.text.lower() or "already has a sandbox apply result" in second.text.lower()


def test_apply_result_persisted_and_get_endpoint_reads_it(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)

    apply_response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )
    assert apply_response.status_code == 200, apply_response.text

    response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/sandbox-apply-result",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["apply_result"]["proposal_id"] == proposal_id
    assert body["sandbox_only"] is True
    assert body["validation_started"] is False
    assert body["source_mutated"] is False
    assert (proposal_dir / "sandbox_apply_result.json").is_file()


def test_no_files_outside_sandbox_and_audit_artifacts_are_modified(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    _materialize_patch_candidate(client, job_id, proposal_id)
    sandbox_pom = run_dir / "workspaces" / "sandbox" / "pom.xml"
    build_error_path = run_dir / "build" / "build-error-20260618-004516-dependency_error.json"
    source_pom = tmp_path / "legacy-app" / "pom.xml"
    source_pom.parent.mkdir(parents=True, exist_ok=True)
    source_pom.write_text("<project><version>legacy</version></project>", encoding="utf-8")
    before_build = build_error_path.read_text(encoding="utf-8")
    before_source = source_pom.read_text(encoding="utf-8")
    before_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}

    response = client.post(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/apply-to-sandbox",
        json={},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    after_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}
    assert after_files - before_files == {
        f"ai_supervision/repair_proposals/{proposal_id}/backups/pom.xml.before-repair",
        f"ai_supervision/repair_proposals/{proposal_id}/sandbox_apply_result.json",
    }
    assert build_error_path.read_text(encoding="utf-8") == before_build
    assert source_pom.read_text(encoding="utf-8") == before_source
    assert sandbox_pom.read_text(encoding="utf-8") != before_source
