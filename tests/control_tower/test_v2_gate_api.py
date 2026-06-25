"""Focused regression tests for the F15 gate API."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_phase_gate_service import (
    CreateGateRequest,
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.application.v2_job_service import PIPELINE_ID
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.domain.entities import RunConfigurationRecord
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_approval_repository import (
    SqliteV2ApprovalRepository,
    V2ApprovalDecisionRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2PreflightResultRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from tests.control_tower.transition_helpers import seed_job


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import (
        DEFAULT_FRONTEND_CLIENT_ID,
    )

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path: Path) -> tuple[TestClient, sqlite3.Connection]:
    conn = sqlite3.connect(
        str(tmp_path / "gate_api.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    _seed_fk_refs(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _seed_fk_refs(conn: sqlite3.Connection) -> None:
    from migration_factory.control_tower.domain.checksums import (
        canonical_json_text,
        sha256_canonical_json,
        utc_now_text,
    )
    now = utc_now_text()
    runner_payload = {
        "schema_version": "1.0.0",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "display_name": "Default local runner",
        "python_executable": "C:/Python/python.exe",
        "ai_hub_path": "C:/work/ai-hub",
        "maven": {"executable_path": "mvn", "expected_version": "3.9.9", "allow_wrapper": False},
        "jdks": [
            {"jdk_id": "jdk-17", "java_home": "C:/java/17", "expected_major": 17, "role": "source"},
            {"jdk_id": "jdk-21", "java_home": "C:/java/21", "expected_major": 21, "role": "target"},
        ],
        "filesystem": {
            "roots": [
                {"root_id": "source-root", "kind": "source", "path": "C:/work/legacy"},
                {"root_id": "output-root", "kind": "output", "path": "C:/work/out"},
            ]
        },
        "network": {"mode": "allowlisted", "allowed_hosts": ["repo.local"]},
        "ai_profile": {"profile_id": "local-disabled"},
    }
    conn.execute(
        """INSERT OR IGNORE INTO runner_profiles (
            runner_profile_id, runner_profile_version, display_name, schema_version,
            payload_json, payload_checksum, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            runner_payload["runner_profile_id"],
            runner_payload["runner_profile_version"],
            runner_payload["display_name"],
            runner_payload["schema_version"],
            canonical_json_text(runner_payload),
            sha256_canonical_json(runner_payload),
            now,
            "test",
        ),
    )
    pipeline_payload = {
        "schema_version": "1.0.0",
        "pipeline_id": PIPELINE_ID,
        "pipeline_version": "2026.06",
        "display_name": "F15 test pipeline",
        "graph_version": "1.0",
        "graph_state_schema_version": "1.0",
        "stages": [
            {
                "stage_index": 1,
                "stage_id": "foundation-diagnostic",
                "profile_id": "diagnostic-profile",
                "command_jdk": "jdk-17",
                "input_source": {"kind": "legacy_source"},
                "continuation_policy_id": "default",
                "target": {"java": 17, "spring_boot": "3.5.6"},
            },
        ],
    }
    conn.execute(
        """INSERT OR IGNORE INTO pipeline_definitions (
            pipeline_id, pipeline_version, display_name, schema_version,
            graph_version, graph_state_schema_version, payload_json, payload_checksum,
            created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            pipeline_payload["pipeline_id"],
            pipeline_payload["pipeline_version"],
            pipeline_payload["display_name"],
            pipeline_payload["schema_version"],
            pipeline_payload["graph_version"],
            pipeline_payload["graph_state_schema_version"],
            canonical_json_text(pipeline_payload),
            sha256_canonical_json(pipeline_payload),
            now,
            "test",
        ),
    )


def _ready_setup(conn: sqlite3.Connection) -> str:
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    setup = service.create_setup(
        CreateSetupRequest(
            run_name="gate-api",
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
    ready_json = json.dumps(
        {
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
            "azure_model_ready": True,
        }
    )
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


def _create_job(client: TestClient, setup_id: str) -> str:
    response = client.post(
        "/v1/v2/migration-jobs",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert response.status_code == 201, response.text
    job_id = response.json()["job_id"]
    return job_id


def _create_gate(conn: sqlite3.Connection, job_id: str, phase: str = "approval_review") -> str:
    with SqliteUnitOfWork(conn) as uow:
        gate_service = V2PhaseGateService(uow.phase_gates)
        result = gate_service.create_gate(
            CreateGateRequest(
                job_id=job_id,
                gate_phase=phase,
                stage_index=2,
                source_artifact_checksum="sha256:gate",
                source_artifact_refs=("analysis:1", "plan:1"),
            )
    )
    assert result.status == "created"
    return result.gate_id


def _seed_approval_card(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    checksum: str,
    stage_index: int = 2,
) -> str:
    approval_repo = SqliteV2ApprovalRepository(conn)
    card_id = f"approval-card-{stage_index}"
    approval_repo.save_card(
        V2ApprovalDecisionRecord(
            card_id=card_id,
            job_id=job_id,
            interrupt_id="run-1",
            request_checksum=checksum,
            stage_index=stage_index,
            summary="Pre-transform review",
            status="pending",
            created_at=utc_now_text(),
        )
    )
    return card_id


def _seed_approval_resume_command(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    stage_index: int = 2,
    run_id: str = "run-1",
) -> str:
    command_id = f"command-{stage_index}"
    now = utc_now_text()
    record = V2StageCommandRecord(
        command_id=command_id,
        job_id=job_id,
        stage_index=stage_index,
        manifest_checksum="manifest-checksum",
        argv_json=json.dumps(
            [
                "python",
                "-m",
                "migration_factory.orchestrator.runner",
                "--run-id",
                run_id,
                "--modernized",
                "C:/work/modernized",
            ],
            separators=(",", ":"),
        ),
        env_json="{}",
        status="completed",
        created_at=now,
        updated_at=now,
        result_json=None,
    )
    SqliteV2CommandRepository(conn).save(record)
    return command_id


def test_v2_gate_list_open_detail_and_legacy_proof_route(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    open_before = client.get(f"/v1/v2/jobs/{job_id}/gates/open")
    assert open_before.status_code == 200
    open_gate = open_before.json()["gate"]
    assert open_gate["gate_id"] == gate_id
    assert open_gate["source_artifact_refs"] == ["analysis:1", "plan:1"]

    list_response = client.get(f"/v1/v2/jobs/{job_id}/gates")
    assert list_response.status_code == 200
    gates = list_response.json()["gates"]
    assert len(gates) == 1
    assert gates[0]["gate_id"] == gate_id
    assert gates[0]["gate_phase"] == "approval_review"
    assert gates[0]["available_actions"]

    detail_response = client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["gate"]["gate_id"] == gate_id
    assert detail["gate"]["checksum"]
    assert detail["gate"]["available_actions"]
    assert "evidence" in detail

    proof_response = client.get(f"/v1/jobs/{job_id}/proof-gates")
    assert proof_response.status_code in {200, 400}


def test_v2_gate_action_rejects_assistant_authoritative_actions(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    payload = {
        "action": "reject",
        "expected_gate_checksum": client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}").json()["checksum"],
        "idempotency_key": "idem-assistant",
        "decided_by": "assistant-1",
        "actor_type": "assistant",
        "reason": "needs more work",
    }
    response = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json=payload,
        headers=_mutation_headers(),
    )
    assert response.status_code == 403, response.text


def test_v2_gate_action_blocks_approve_after_revision_requested(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)
    checksum = client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}").json()["checksum"]

    approval_repo = SqliteV2ApprovalRepository(conn)
    approval_repo.save_card(
        V2ApprovalDecisionRecord(
            card_id="approval-card-blocked",
            interrupt_id="run-1",
            request_checksum=checksum,
            stage_index=2,
            summary="Revision requested",
            status="blocked",
            created_at=utc_now_text(),
            job_id=job_id,
        )
    )

    payload = {
        "action": "approve",
        "expected_gate_checksum": checksum,
        "idempotency_key": "idem-approve-blocked",
        "decided_by": "human-1",
        "actor_type": "human",
    }
    response = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json=payload,
        headers=_mutation_headers(),
    )
    assert response.status_code == 422, response.text
    assert "A revision request is pending" in response.text


def test_v2_gate_action_success_idempotency_and_conflict(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)
    checksum = client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}").json()["checksum"]

    base_payload = {
        "action": "reject",
        "expected_gate_checksum": checksum,
        "idempotency_key": "idem-human",
        "decided_by": "human-1",
        "actor_type": "human",
        "reason": "not ready",
    }

    first = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json=base_payload,
        headers=_mutation_headers(),
    )
    assert first.status_code == 200, first.text
    first_result = first.json()["result"]
    assert first_result["status"] == "executed"

    second = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json=base_payload,
        headers=_mutation_headers(),
    )
    assert second.status_code == 200, second.text
    assert second.json()["result"]["status"] == "idempotent"
    assert second.json()["result"]["decision_id"] == first_result["decision_id"]

    conflict_payload = dict(base_payload)
    conflict_payload["reason"] = "different reason"
    conflict = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json=conflict_payload,
        headers=_mutation_headers(),
    )
    assert conflict.status_code == 409, conflict.text


def test_v2_gate_action_rejects_unsafe_fields_and_unsupported_action(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)
    checksum = client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}").json()["checksum"]

    unsafe_response = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json={
            "action": "reject",
            "expected_gate_checksum": checksum,
            "idempotency_key": "idem-unsafe",
            "decided_by": "human-1",
            "actor_type": "human",
            "reason": "not ready",
            "sandbox_path": "/tmp/evil",
            "argv": ["rm", "-rf", "/"],
            "env": {"PATH": "bad"},
            "raw_command": "rm -rf /",
            "filesystem_target": "C:/evil",
        },
        headers=_mutation_headers(),
    )
    assert unsafe_response.status_code == 422, unsafe_response.text

    unsupported_response = client.post(
        f"/v1/v2/jobs/{job_id}/gates/{gate_id}/actions",
        json={
            "action": "bogus",
            "expected_gate_checksum": checksum,
            "idempotency_key": "idem-unsupported",
            "decided_by": "human-1",
            "actor_type": "human",
        },
        headers=_mutation_headers(),
    )
    assert unsupported_response.status_code == 422, unsupported_response.text


def test_v2_approval_route_retries_when_resume_launch_is_locked(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    _seed_approval_resume_command(conn, job_id=job_id, stage_index=2, run_id="run-1")
    gate_id = _create_gate(conn, job_id)
    checksum = client.get(f"/v1/v2/jobs/{job_id}/gates/{gate_id}").json()["checksum"]
    card_id = _seed_approval_card(conn, job_id=job_id, checksum=checksum)

    class _LockedRunner:
        def __init__(self) -> None:
            self.started: list[str] = []

        def start_resume(self, *, job_id: str, resume_id: str):
            self.started.append(resume_id)
            raise sqlite3.OperationalError("database is locked")

        def start(self, *, job_id: str, command_id: str):
            raise AssertionError("transform commands must not be launched here")

    runner = _LockedRunner()
    client.app.state.v2_orchestrator_runner = runner

    response = client.post(
        f"/v1/v2/jobs/{job_id}/approvals/{card_id}/approve",
        json={"expected_checksum": checksum},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["launch_status"] == "retrying"
    assert runner.started == [data["resume_id"]]

    repeat = client.post(
        f"/v1/v2/jobs/{job_id}/approvals/{card_id}/approve",
        json={"expected_checksum": checksum},
        headers=_mutation_headers(),
    )
    assert repeat.status_code == 200, repeat.text
    repeat_data = repeat.json()
    assert repeat_data["launch_status"] == "retrying"
    assert runner.started == [data["resume_id"]]


class TestV2JobPolicyPersistence:
    def test_create_job_defaults_to_manual_policy(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        response = client.post(
            "/v1/v2/migration-jobs",
            json={"setup_id": setup_id},
            headers=_mutation_headers(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["stage_continuation_policy"] == "manual"
        assert data["run_configuration_id"]

        row = conn.execute(
            "SELECT job_id, policy_json FROM run_configurations WHERE job_id = ?",
            (data["job_id"],),
        ).fetchone()
        assert row is not None
        policy = json.loads(row["policy_json"])
        assert policy["stage_continuation_policy"] == "manual"

    def test_create_job_with_explicit_manual_policy(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        response = client.post(
            "/v1/v2/migration-jobs",
            json={
                "setup_id": setup_id,
                "policy": {"stage_continuation_policy": "manual"},
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["stage_continuation_policy"] == "manual"

        row = conn.execute(
            "SELECT policy_json FROM run_configurations WHERE job_id = ?",
            (data["job_id"],),
        ).fetchone()
        assert row is not None
        policy = json.loads(row["policy_json"])
        assert policy["stage_continuation_policy"] == "manual"

    def test_create_job_with_auto_on_green_policy(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        response = client.post(
            "/v1/v2/migration-jobs",
            json={
                "setup_id": setup_id,
                "policy": {"stage_continuation_policy": "auto_on_green"},
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["stage_continuation_policy"] == "auto_on_green"

        row = conn.execute(
            "SELECT policy_json FROM run_configurations WHERE job_id = ?",
            (data["job_id"],),
        ).fetchone()
        assert row is not None
        policy = json.loads(row["policy_json"])
        assert policy["stage_continuation_policy"] == "auto_on_green"

    def test_create_job_with_manual_on_warning_policy(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        response = client.post(
            "/v1/v2/migration-jobs",
            json={
                "setup_id": setup_id,
                "policy": {"stage_continuation_policy": "manual_on_warning_or_failure"},
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["stage_continuation_policy"] == "manual_on_warning_or_failure"

    def test_create_job_rejects_unknown_policy(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        response = client.post(
            "/v1/v2/migration-jobs",
            json={
                "setup_id": setup_id,
                "policy": {"stage_continuation_policy": "skip_stages"},
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, response.text

    def test_get_job_returns_policy_for_existing_job(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _ready_setup(conn)

        create_resp = client.post(
            "/v1/v2/migration-jobs",
            json={
                "setup_id": setup_id,
                "policy": {"stage_continuation_policy": "manual"},
            },
            headers=_mutation_headers(),
        )
        job_id = create_resp.json()["job_id"]

        get_resp = client.get(f"/v1/v2/migration-jobs/{job_id}")
        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert data["stage_continuation_policy"] == "manual"
        assert data["run_configuration_id"]
