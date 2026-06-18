from __future__ import annotations

from pathlib import Path

from tests.control_tower.test_v2_approved_repair_execution_plan import (
    _create_governed_proposal,
    _write_approval_state,
)
from tests.control_tower.test_v2_assistant_failure_answers import (
    _FakeModelClient,
    _client,
    _seed_event_derived_stage2_job,
)


def test_list_allowed_repair_artifacts_for_proposal(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts")

    assert response.status_code == 200, response.text
    body = response.json()
    artifact_names = {item["artifact_name"] for item in body["artifacts"]}
    assert "repair_proposal.json" in artifact_names
    assert "repair_verification.json" in artifact_names
    assert "repair_proposal.md" in artifact_names
    assert "approval_state.json" in artifact_names
    proposal_entry = next(item for item in body["artifacts"] if item["artifact_name"] == "repair_proposal.json")
    assert proposal_entry["exists"] is True
    assert proposal_entry["kind"] == "json"
    assert proposal_entry["read_only"] is True


def test_preview_allowed_json_and_markdown_artifacts(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)

    json_response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/repair_proposal.json"
    )
    md_response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/repair_proposal.md"
    )

    assert json_response.status_code == 200, json_response.text
    assert json_response.json()["kind"] == "json"
    assert "\"no_auto_apply\": true" in json_response.json()["content"].lower()
    assert json_response.json()["read_only"] is True

    assert md_response.status_code == 200, md_response.text
    assert md_response.json()["kind"] == "markdown"
    assert "# repair proposal" in md_response.json()["content"].lower()
    assert md_response.json()["read_only"] is True


def test_rejects_path_traversal_unknown_and_absolute_artifacts(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, _proposal_dir, _checksum = _create_governed_proposal(client, job_id, run_dir)

    traversal = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/%2E%2E%2Frepair_proposal.json"
    )
    unknown = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/unknown.json"
    )
    absolute = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/C:/temp/evil.txt"
    )

    assert traversal.status_code == 400, traversal.text
    assert traversal.json()["error"]["code"] == "REPAIR_ARTIFACT_PREVIEW_FAILED"
    assert unknown.status_code == 400, unknown.text
    assert unknown.json()["error"]["code"] == "REPAIR_ARTIFACT_PREVIEW_FAILED"
    assert absolute.status_code == 400, absolute.text
    assert absolute.json()["error"]["code"] == "REPAIR_ARTIFACT_PREVIEW_FAILED"


def test_artifact_preview_endpoints_are_read_only(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    job_id, run_dir = _seed_event_derived_stage2_job(conn, tmp_path)
    proposal_id, proposal_dir, checksum = _create_governed_proposal(client, job_id, run_dir)
    _write_approval_state(proposal_dir, state="approved", checksum=checksum)
    before_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}

    list_response = client.get(f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts")
    preview_response = client.get(
        f"/v1/v2/migration-jobs/{job_id}/repair-proposals/{proposal_id}/artifacts/repair_proposal.json"
    )

    assert list_response.status_code == 200, list_response.text
    assert preview_response.status_code == 200, preview_response.text
    after_files = {path.relative_to(run_dir).as_posix() for path in run_dir.rglob("*") if path.is_file()}
    assert after_files == before_files
