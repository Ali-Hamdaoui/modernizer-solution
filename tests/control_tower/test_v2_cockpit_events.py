"""V2 cockpit read, event, and OpenAPI regressions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_setup_service import CreateSetupRequest, V2SetupService
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2PreflightResultRecord,
)


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path: Path) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = sqlite3.connect(
        tmp_path / "v2_cockpit.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_orchestrator_runner=_FakeV2Runner(lambda: SqliteUnitOfWork(conn)))
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


class _FakeV2Runner:
    def __init__(self, uow_factory):
        self._uow_factory = uow_factory

    def start(self, *, job_id: str, command_id: str):
        with self._uow_factory() as uow:
            uow.v2_events.save(job_id=job_id, stage=1, event_type="stage_started", status="running", message="fake runner started", payload={"command_id": command_id})
            uow.v2_events.save(job_id=job_id, stage=1, event_type="command_started", status="running", message="fake command started", payload={"command_id": command_id})
            uow.v2_events.save(job_id=job_id, stage=1, event_type="artifact_written", status="completed", message="fake artifact", payload={"artifact_kind": "analysis_report"})
            uow.v2_events.save(job_id=job_id, stage=1, event_type="proof_updated", status="completed", message="fake proof", payload={})
            uow.v2_events.save(job_id=job_id, stage=1, event_type="stage_completed", status="completed", message="fake complete", payload={"command_id": command_id})
        return None


def _ready_setup(conn: sqlite3.Connection) -> str:
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    setup = service.create_setup(
        CreateSetupRequest(
            run_name="cockpit-uat",
            legacy_app_path="C:/work/legacy",
            output_parent_path="C:/work/out",
            ai_hub_path="C:/work/ai-hub",
            java11_home="C:/java/11",
            java17_home="C:/java/17",
            java21_home="C:/java/21",
            maven_cmd="C:/maven/bin/mvn.cmd",
        )
    )
    now = utc_now_text()
    ready_json = json.dumps({
        "legacy_app_exists": True,
        "legacy_app_has_project_file": True,
        "legacy_app_not_in_output_parent": True,
        "output_parent_writable": True,
        "ai_hub_root_exists": True,
        "ai_hub_profiles_ready": True,
        "ai_hub_catalogs_ready": True,
        "ai_hub_policies_ready": True,
        "jdk11_ready": True,
        "jdk17_ready": True,
        "jdk21_ready": True,
        "maven_ready": True,
        "pipeline_route_ready": True,
        "legacy_marker_ready": True,
        "output_parent_gate_ready": True,
        "azure_model_ready": False,
    })
    repo.save_preflight(
        V2PreflightResultRecord(
            preflight_id="pf-ready",
            setup_id=setup.setup_id,
            setup_checksum=setup.setup_checksum,
            all_ready=True,
            legacy_app_exists=True,
            legacy_app_has_project_file=True,
            legacy_app_not_in_output_parent=True,
            output_parent_writable=True,
            ai_hub_root_exists=True,
            ai_hub_profiles_ready=True,
            ai_hub_catalogs_ready=True,
            ai_hub_policies_ready=True,
            jdk11_ready=True,
            jdk17_ready=True,
            jdk21_ready=True,
            maven_ready=True,
            pipeline_route_ready=True,
            legacy_marker_ready=True,
            output_parent_gate_ready=True,
            readiness_json=ready_json,
            warnings_json="[]",
            errors_json="[]",
            checked_at=now,
            checked_by="test",
            correlation_id=None,
        )
    )
    return setup.setup_id


def _create_started_job(client: TestClient, setup_id: str) -> str:
    job_response = client.post(
        "/v1/v2/migration-jobs",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert job_response.status_code == 201, job_response.text
    job_id = job_response.json()["job_id"]
    start_response = client.post(
        "/v1/v2/migration-jobs/start-stage1",
        json={"job_id": job_id, "setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert start_response.status_code == 200, start_response.text
    assert start_response.json()["job_id"] == job_id
    return job_id


def test_v2_job_read_stages_and_empty_approvals(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_started_job(client, setup_id)

    job_response = client.get(f"/v1/v2/migration-jobs/{job_id}")
    assert job_response.status_code == 200
    assert job_response.json()["job_id"] == job_id

    stages_response = client.get(f"/v1/v2/migration-jobs/{job_id}/stages")
    assert stages_response.status_code == 200
    stages = stages_response.json()["stages"]
    assert [stage["stage_index"] for stage in stages] == [1, 2, 3]
    assert stages[0]["chain_status"] == "completed"
    assert stages[1]["chain_status"] == "pending"
    assert stages[2]["input_source_kind"] == "stage_2_sandbox"

    approvals_response = client.get(f"/v1/v2/jobs/{job_id}/approvals")
    assert approvals_response.status_code == 200
    assert approvals_response.json()["approvals"] == []


def test_v2_nonexistent_reads_return_404(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    assert client.get("/v1/v2/migration-jobs/missing").status_code == 404
    assert client.get("/v1/v2/migration-jobs/missing/stages").status_code == 404
    assert client.get("/v1/v2/jobs/missing/approvals").status_code == 404
    assert client.get("/v1/v2/migration-jobs/missing/events/snapshot").status_code == 404
    assert client.get("/v1/v2/migration-jobs/missing/events").status_code == 404


def test_v2_start_stage1_emits_ordered_events_and_resume_cursor(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_started_job(client, setup_id)

    snapshot = client.get(f"/v1/v2/migration-jobs/{job_id}/events/snapshot")
    assert snapshot.status_code == 200
    events = snapshot.json()["events"]
    event_types = [event["type"] for event in events]
    assert event_types[:3] == ["job_created", "stage_queued", "stage_started"]
    assert "command_started" in event_types
    assert "artifact_written" in event_types
    assert "proof_updated" in event_types
    assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)

    after = events[1]["sequence"]
    resumed = client.get(f"/v1/v2/migration-jobs/{job_id}/events/snapshot?after={after}")
    assert [event["sequence"] for event in resumed.json()["events"]] == [
        event["sequence"] for event in events if event["sequence"] > after
    ]


def test_v2_sse_stream_replays_events(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_started_job(client, setup_id)

    with client.stream("GET", f"/v1/v2/migration-jobs/{job_id}/events?after=0&once=true") as response:
        assert response.status_code == 200
        body = ""
        for chunk in response.iter_text():
            body += chunk
            if "event: stage_started" in body:
                break
    assert "event: job_created" in body
    assert "event: stage_queued" in body
    assert "event: stage_started" in body


def test_v2_events_are_redacted_and_bounded(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_started_job(client, setup_id)

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=1,
            event_type="stdout",
            status="running",
            message="x" * 5000,
            payload={"path": "C:/secret/path", "api_key": "sk-secret"},
        )

    snapshot = client.get(f"/v1/v2/migration-jobs/{job_id}/events/snapshot")
    last = snapshot.json()["events"][-1]
    assert len(last["message"]) <= 4110
    serialized = json.dumps(last)
    assert "sk-secret" not in serialized
    assert "C:/secret/path" not in serialized


def test_openapi_json_includes_v2_paths(tmp_path: Path) -> None:
    client, _ = _api_client(tmp_path)
    response = client.get("/openapi.json")
    assert response.status_code == 200, response.text
    paths = response.json()["paths"]
    assert "/v1/v2/migration-jobs" in paths
    assert "/v1/v2/migration-jobs/{job_id}/stages" in paths
    assert "/v1/v2/jobs/{job_id}/approvals" in paths
    assert "/v1/v2/migration-jobs/{job_id}/events" in paths
