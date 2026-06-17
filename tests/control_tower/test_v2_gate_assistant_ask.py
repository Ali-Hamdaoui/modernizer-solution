"""Focused tests for F15 gate-aware /ask endpoint with two-step confirmation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
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
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2PreflightResultRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import (
    SqlitePhaseGateRepository,
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
        str(tmp_path / "gate_ask.sqlite3"),
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
    )
    runner_payload = {
        "schema_version": "1.0.0",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "display_name": "Default local runner",
        "python_executable": "",
        "ai_hub_path": "",
        "maven": {"executable_path": "mvn", "expected_version": "3.9.9", "allow_wrapper": False},
        "jdks": [],
        "filesystem": {"roots": []},
        "network": {"mode": "allowlisted", "allowed_hosts": []},
        "ai_profile": {"profile_id": "local-disabled"},
    }
    now = utc_now_text()
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
        "pipeline_id": "springboot-216-to-356-java21-three-stage",
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
                "target": {"diagnostic": "foundation"},
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
    now = utc_now_text()
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    setup = service.create_setup(
        CreateSetupRequest(
            run_name="gate-ask",
            legacy_app_path="C:/work/legacy",
            output_parent_path="C:/work/out",
            ai_hub_path="C:/work/ai-hub",
            java11_home="C:/java/11",
            java17_home="C:/java/17",
            java21_home="C:/java/21",
            maven_cmd="C:/maven/bin/mvn.cmd",
        )
    )
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
        "azure_model_ready": True,
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


def _create_job(client: TestClient, setup_id: str) -> str:
    resp = client.post(
        "/v1/v2/migration-jobs",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["job_id"]


def _create_gate(
    conn: sqlite3.Connection,
    job_id: str,
    phase: str = "approval_review",
    stage_index: int = 2,
) -> str:
    with SqliteUnitOfWork(conn) as uow:
        gate_service = V2PhaseGateService(uow.phase_gates)
        result = gate_service.create_gate(
            CreateGateRequest(
                job_id=job_id,
                gate_phase=phase,
                stage_index=stage_index,
                source_artifact_checksum="sha256:gate",
                source_artifact_refs=("analysis:1", "plan:1"),
            )
        )
    assert result.status == "created"
    return result.gate_id


def _seed_stage1_command(
    conn: sqlite3.Connection,
    job_id: str,
    sandbox_path: str = "C:/work/sandbox/analysis-001",
) -> str:
    """Seed a fake completed Stage 1 command so resolve_prior_stage_output can find it."""
    from uuid import uuid4
    now = utc_now_text()
    command_id = uuid4().hex
    result_json = json.dumps({
        "sandbox_path": sandbox_path,
        "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "build_status": "BUILD_PASSED_IN_SANDBOX",
        "test_status": "PASS",
        "orchestration_status": "PASS",
    })
    record = V2StageCommandRecord(
        command_id=command_id,
        job_id=job_id,
        stage_index=1,
        manifest_checksum="test-seed-1",
        argv_json=json.dumps(["test-runner", "--stage", "1"], separators=(",", ":")),
        env_json=json.dumps({}, separators=(",", ":")),
        status="completed",
        created_at=now,
        updated_at=now,
        result_json=result_json,
    )
    repo = SqliteV2CommandRepository(conn)
    repo.save(record)
    return command_id


# ── Tests ──────────────────────────────────────────────────────────────


def test_ask_without_gate_falls_back(tmp_path: Path) -> None:
    """No open gate → existing assistant behavior."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "What is the status?"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "user_message" in data
    assert "assistant_message" in data
    assert "model" in data
    assert data.get("guardrails", {}).get("read_only") is True


def test_ask_with_open_gate_returns_gate_aware(tmp_path: Path) -> None:
    """Open gate → gate-aware mode."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "What is the current gate?"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gate_aware") is True
    assert "user_message" in data
    assert "assistant_message" in data
    assert len(data["assistant_message"]["content"]) > 0


def test_ask_state_changing_intent_returns_preview(tmp_path: Path) -> None:
    """State-changing intent → action preview with pending_confirmation."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "approve"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gate_aware") is True
    assert data.get("executed") is False
    assert "action_preview" in data
    preview = data["action_preview"]
    assert preview.get("pending_confirmation") is True
    assert "action_type" in preview
    assert preview["action_type"] != ""


def test_ask_ambiguous_intent_returns_clarification(tmp_path: Path) -> None:
    """Ambiguous intent → clarification."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "xyzzy flurbo gate"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gate_aware") is True
    assert data.get("ambiguous") is True
    assert "available_actions" in data


def test_ask_confirm_without_pending_returns_message(tmp_path: Path) -> None:
    """Confirm without pending → info message."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "confirm"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gate_aware") is True
    assert "assistant_message" in data


def test_ask_preview_then_confirm(tmp_path: Path) -> None:
    """Preview → confirm flow — approval_review + approve requires
    human actor, so execution is expected to fail."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp1 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "approve"},
        headers=_mutation_headers(),
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1.get("executed") is False
    assert data1.get("action_preview", {}).get("pending_confirmation") is True

    resp2 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "confirm"},
        headers=_mutation_headers(),
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2.get("gate_aware") is True
    assert "assistant_message" in data2
    # approve from assistant actor fails — execution did not succeed
    assert data2.get("executed") is False
    er = data2.get("execution_result", {})
    assert er.get("success") is False
    assert er.get("status") == "actor_not_authoritative"


def test_ask_yes_pattern(tmp_path: Path) -> None:
    """Yes pattern triggers confirmation."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp1 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "approve"},
        headers=_mutation_headers(),
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1.get("action_preview", {}).get("pending_confirmation") is True

    resp2 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "yes"},
        headers=_mutation_headers(),
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json().get("gate_aware") is True


def test_ask_read_only_question_no_execution(tmp_path: Path) -> None:
    """Read-only question with open gate → no execution."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    gate_id = _create_gate(conn, job_id)

    resp = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "What phase is this gate?"},
        headers=_mutation_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("gate_aware") is True
    assert data.get("executed") is False
    assert "action_preview" not in data


def test_ask_analysis_continue_preview_then_confirm_with_progression(tmp_path: Path) -> None:
    """analysis_review CONTINUE → preview → confirm → planning command queued
    (NOT synthetic planning_review gate)."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)

    # Seed a completed Stage 1 command so resolve_prior_stage_output
    # finds the sandbox_path and queue_next_stage_from_gate succeeds.
    _seed_stage1_command(conn, job_id)

    gate_id = _create_gate(conn, job_id, phase="analysis_review", stage_index=1)

    # Step 1: state-changing intent → preview
    resp1 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "accept analysis and continue"},
        headers=_mutation_headers(),
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1.get("executed") is False
    assert data1.get("action_preview", {}).get("pending_confirmation") is True
    preview_action_type = data1["action_preview"]["action_type"]
    assert preview_action_type == "continue_from_gate"

    gate_repo = SqlitePhaseGateRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)

    # Step 2: confirm → execution succeeds + planning command queued
    resp2 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "confirm"},
        headers=_mutation_headers(),
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2.get("gate_aware") is True
    assert data2.get("executed") is True

    er = data2.get("execution_result", {})
    assert er.get("success") is True
    assert er.get("status") == "executed"
    assert er.get("decision_id") != ""

    pr = data2.get("progression_result")
    assert pr is not None, "progression_result should be present for analysis_review continue"
    # P0: status must be "planning_queued", NOT "phase_advanced"
    assert pr.get("status") == "planning_queued", (
        f"Expected planning_queued, got {pr.get('status')}"
    )
    assert pr.get("from_phase") == "analysis_review"
    assert pr.get("to_phase") == "planning_review"
    assert pr.get("stage_index") == 1
    assert pr.get("planning_command_id", "") != "", (
        "Expected planning_command_id in progression_result"
    )
    message = pr.get("message", "")
    assert "Stage 2 was not started" in message

    # Verify NO Stage 2 command was created
    stage2_commands = command_repo.list_by_job_and_stage(job_id, 2)
    assert len(stage2_commands) == 0, (
        f"Expected no Stage 2 commands, got {len(stage2_commands)}"
    )

    # P0: NO synthetic planning_review gate was created directly.
    # Real planning must run and produce artifacts first.
    gates = gate_repo.list_by_job(job_id)
    planning_gates = [g for g in gates if g.gate_phase == "planning_review" and g.stage_index == 1]
    assert len(planning_gates) == 0, (
        f"Expected NO planning_review gate (synthetic), "
        f"but found {len(planning_gates)}"
    )

    # Instead, a planning_pending command was queued
    planning_commands = command_repo.list_by_job_and_stage(job_id, 1)
    planning_pending = [
        c for c in planning_commands
        if c.status == "planning_pending" and c.manifest_checksum == "phase:planning"
    ]
    assert len(planning_pending) >= 1, (
        "Expected at least one planning_pending command"
    )
    assert planning_pending[0].command_id == pr.get("planning_command_id")

    # Step 3: repeated confirm → gate is already resolved so /ask
    # falls back to non-gate-aware assistant. No duplicate gate.
    resp3 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "confirm"},
        headers=_mutation_headers(),
    )
    assert resp3.status_code == 200, resp3.text
    # No second planning_review gate (still zero)
    planning_gates_after = [
        g for g in gate_repo.list_by_job(job_id)
        if g.gate_phase == "planning_review" and g.stage_index == 1
    ]
    assert len(planning_gates_after) == 0, (
        "Expected zero planning_review gates (still synthetic-free)"
    )


def test_ask_analysis_reanalysis_does_not_queue_planning(tmp_path: Path) -> None:
    """analysis_review REANALYZE → gate resolved but no planning."""
    client, conn = _api_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    seed_job(conn, job_id=job_id)
    _seed_stage1_command(conn, job_id)
    gate_id = _create_gate(conn, job_id, phase="analysis_review", stage_index=1)

    # Preview reanalyze
    resp1 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "reanalyze"},
        headers=_mutation_headers(),
    )
    assert resp1.status_code == 200, resp1.text
    data1 = resp1.json()
    assert data1.get("action_preview", {}).get("pending_confirmation") is True

    # Confirm reanalyze
    resp2 = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        json={"question": "confirm"},
        headers=_mutation_headers(),
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2.get("executed") is True
    er = data2.get("execution_result", {})
    assert er.get("success") is True

    # Verify NO planning command was created (reanalyze should not
    # trigger progression)
    repo = SqliteV2CommandRepository(conn)
    stage2_commands = repo.list_by_job_and_stage(job_id, 2)
    assert len(stage2_commands) == 0
