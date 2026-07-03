"""Runtime wiring regression for repair gate diagnosis callbacks."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.application.v2_repair_strategy_packet import (
    create_repair_strategy_packet,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2PreflightResultRecord,
)
from ._helpers import canonical_json, seed_runner_profile, sha256_json
from .test_v2_repair_strategy_packet import _powermock_classification, _powermock_evidence
from .v1_fixtures import make_v1_pipeline_definition
from migration_factory.control_tower.schemas.run_configuration import (
    RunPolicy,
    StageContinuationPolicy,
)


class _FakeShadowClient:
    provider = "fake"
    deployment = "shadow-deployment"
    endpoint_metadata = "endpoint_host=[redacted-endpoint]"

    def answer_with_role(self, *, role: Any, prompt: str, fallback: str, **_: Any) -> Any:
        role_value = getattr(role, "value", str(role))
        content = (
            {
                "status": "available",
                "role": "repair_reviewer",
                "verdict": "advisory_accept",
                "critique": "Advisory accept only.",
                "risks": [],
                "missing_evidence": [],
                "unsafe_assumptions": [],
                "recommended_next_action": "keep_non_actionable",
                "confidence": "medium",
            }
            if role_value == "reviewer"
            else {
                "status": "available",
                "role": "repair_proposer",
                "root_cause": "initMocks marker.",
                "repair_strategy": "openMocks candidate.",
                "expected_change": "test-local replacement.",
                "affected_files": ["src/test/java/ExampleTest.java"],
                "risk_notes": [],
                "required_backend_recipe": "INITMOCKS_TO_OPENMOCKS",
                "confidence": "medium",
            }
        )
        return type("FakeShadowResult", (), {
            "content": json.dumps(content),
            "provider": "fake",
            "source": "fake",
            "model_status": "live_ok",
            "success": True,
            "failure_reason": "",
            "fallback_used": False,
            "deployment": "shadow-deployment",
            "endpoint_metadata": "endpoint_host=[redacted-endpoint]",
        })()


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import (
        DEFAULT_FRONTEND_CLIENT_ID,
    )

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _app_and_client(tmp_path: Path) -> tuple[object, TestClient, sqlite3.Connection]:
    conn = sqlite3.connect(
        str(tmp_path / "repair_runtime.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    return app, TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _ready_setup(conn: sqlite3.Connection) -> str:
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    setup = service.create_setup(
        CreateSetupRequest(
            run_name="repair-runtime",
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
    seed_runner_profile(conn)
    pipeline_payload = make_v1_pipeline_definition()
    conn.execute(
        """
        INSERT INTO pipeline_definitions (
            pipeline_id, pipeline_version, display_name, schema_version,
            graph_version, graph_state_schema_version, payload_json, payload_checksum,
            created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pipeline_payload["pipeline_id"],
            pipeline_payload["pipeline_version"],
            pipeline_payload["display_name"],
            pipeline_payload["schema_version"],
            pipeline_payload["graph_version"],
            pipeline_payload["graph_state_schema_version"],
            canonical_json(pipeline_payload),
            sha256_json(pipeline_payload),
            now,
            "test",
        ),
    )
    return setup.setup_id


def _create_job(client: TestClient, setup_id: str) -> str:
    response = client.post(
        "/v1/v2/migration-jobs",
        json={"setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert response.status_code == 201, response.text
    return response.json()["job_id"]


def _seed_policy(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    stage_continuation_policy: StageContinuationPolicy = StageContinuationPolicy.AUTO_ON_GREEN,
    enable_build_repair: bool = True,
) -> None:
    policy = RunPolicy(
        stage_continuation_policy=stage_continuation_policy,
        enable_build_repair=enable_build_repair,
    )
    conn.execute(
        """
        UPDATE run_configurations
        SET policy_json = ?
        WHERE job_id = ?
        """,
        (
            policy.model_dump_json(),
            job_id,
        ),
    )


def test_repair_strategy_read_endpoints_return_safe_persisted_packets(tmp_path: Path) -> None:
    _app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    packet = create_repair_strategy_packet(
        job_id=job_id,
        stage_index=2,
        classification=_powermock_classification(),
        stage_evidence={**_powermock_evidence(), "job_id": job_id},
    )
    with SqliteUnitOfWork(conn) as uow:
        first = uow.v2_repair_strategies.save_strategy_packet(packet)
        changed = dict(packet)
        changed["recommended_strategy"] = "Alternate engineer-reviewed plan."
        second = uow.v2_repair_strategies.save_strategy_packet(changed)

    latest = client.get(f"/v1/v2/jobs/{job_id}/repair-strategies/latest")
    assert latest.status_code == 200, latest.text
    body = latest.json()["strategy"]
    assert body["strategy_id"] == second["strategy_id"]
    assert body["version"] == 2
    assert body["history_count"] == 2
    assert body["backend_gate"]["llm_can_apply"] is False

    history = client.get(f"/v1/v2/jobs/{job_id}/repair-strategies")
    assert history.status_code == 200, history.text
    assert [item["version"] for item in history.json()["strategies"]] == [2, 1]

    stage_latest = client.get(f"/v1/v2/jobs/{job_id}/stages/2/repair-strategies/latest")
    assert stage_latest.status_code == 200, stage_latest.text
    assert stage_latest.json()["strategy"]["strategy_id"] == second["strategy_id"]

    by_id = client.get(f"/v1/v2/jobs/{job_id}/repair-strategies/{first['strategy_id']}")
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["strategy"]["version"] == 1


def test_live_powermock_failure_persists_strategy_overlays_summary_and_chatbot(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    _seed_policy(conn, job_id)
    sandbox = tmp_path / "sandbox"
    test_source = sandbox / "src" / "test" / "java" / "LegacyPowerMockTest.java"
    test_source.parent.mkdir(parents=True)
    test_source.write_text(
        "\n".join(
            [
                "import org.powermock.modules.junit4.PowerMockRunner;",
                "import org.powermock.core.classloader.annotations.PrepareForTest;",
                "import org.powermock.api.mockito.PowerMockito;",
                "@RunWith(PowerMockRunner.class)",
                "@PrepareForTest({LegacyFactory.class, StaticUtil.class})",
                "class LegacyPowerMockTest {",
                "  void testLegacy() throws Exception {",
                "    PowerMockito.mockStatic(StaticUtil.class);",
                "    PowerMockito.whenNew(LegacyFactory.class).withNoArguments().thenReturn(new LegacyFactory());",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    payload = {
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "FAILED",
        "sandbox_path": str(sandbox),
        "message": "org.powermock PowerMockRunner PrepareForTest PowerMockito.mockStatic PowerMockito.whenNew",
        "artifact_refs": {
            "sandbox": str(sandbox),
            "test_source": str(test_source),
            "pom_xml": str(tmp_path / "pom.xml"),
            "test_report": str(tmp_path / "TEST-LegacyPowerMockTest.xml"),
            "build_error_contract": str(tmp_path / "build-error.json"),
        },
    }
    (tmp_path / "pom.xml").write_text("<dependency>org.powermock</dependency>", encoding="utf-8")
    (tmp_path / "TEST-LegacyPowerMockTest.xml").write_text("<failure>PowerMockRunner</failure>", encoding="utf-8")
    (tmp_path / "build-error.json").write_text('{"error":"PowerMockito.mockStatic"}', encoding="utf-8")

    callback = app.state.v2_orchestrator_runner._diagnosis_callback
    callback(job_id, 2, "cmd-powermock-live", "test_failed", payload)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=2,
            event_type="test_failed",
            status="failed",
            message=payload["message"],
            payload=payload,
        )

    with SqliteUnitOfWork(conn) as uow:
        history = uow.v2_repair_strategies.history_for_stage(job_id, 2)
        assert len(history) == 1
        persisted = history[0]
        assert persisted["strategy_id"]
        assert persisted["version"] >= 1
        assert persisted["strategy_checksum"].startswith("sha256:")
        assert persisted["family"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
        assert persisted["risk_level"] == "high"
        assert persisted["apply_candidate_allowed"] is False
        assert persisted["backend_recipe_available"] is False
        assert persisted["human_gate_required"] is True
        assert uow.v2_repair_candidates.latest_public_for_job(job_id) is None

    latest = client.get(f"/v1/v2/jobs/{job_id}/repair-strategies/latest")
    assert latest.status_code == 200, latest.text
    latest_strategy = latest.json()["strategy"]
    assert latest_strategy["strategy_id"] == persisted["strategy_id"]
    assert latest_strategy["family"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert latest_strategy["backend_gate"]["llm_can_apply"] is False
    assert latest_strategy["backend_gate"]["llm_can_approve"] is False
    assert latest_strategy["backend_gate"]["downstream_start_allowed"] is False

    all_strategies = client.get(f"/v1/v2/jobs/{job_id}/repair-strategies")
    assert all_strategies.status_code == 200, all_strategies.text
    assert len(all_strategies.json()["strategies"]) >= 1
    stage_latest = client.get(f"/v1/v2/jobs/{job_id}/stages/2/repair-strategies/latest")
    assert stage_latest.status_code == 200, stage_latest.text
    assert stage_latest.json()["strategy"]["strategy_id"] == persisted["strategy_id"]

    summary = client.get(f"/v1/v2/jobs/{job_id}/failure-summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    top_strategy = body["repair_strategy_packet"]
    nested_classification = body["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]
    nested_strategy = nested_classification["repair_strategy_packet"]
    assert top_strategy["strategy_id"] == persisted["strategy_id"]
    assert nested_strategy["strategy_id"] == persisted["strategy_id"]
    assert nested_classification["failure_type"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert nested_classification["classification_status"] == "unsupported_known_failure"
    assert nested_strategy["family"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert nested_strategy["risk_level"] == "high"
    assert nested_strategy["apply_candidate_allowed"] is False
    assert nested_strategy["backend_recipe_available"] is False
    assert nested_strategy["human_gate_required"] is True
    assert nested_classification["repair_apply_candidate"] is None
    assert nested_classification["downstream_stage_state"]["auto_started"] is False

    before_candidates = conn.execute(
        "SELECT COUNT(*) AS count FROM v2_repair_apply_candidates WHERE job_id = ?",
        (job_id,),
    ).fetchone()["count"]
    ask_response = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        headers=_mutation_headers(),
        json={"question": "Explain the repair strategy for this migration failure."},
    )
    assert ask_response.status_code == 200, ask_response.text
    answer = ask_response.json()["assistant_message"]["content"]
    assert "POWERMOCK_LEGACY_TEST_STRATEGY" in answer
    assert "risk=high" in answer
    assert "version=" in answer or "id=repair-strategy" in answer
    assert "fallback model invoked=" in answer
    assert "Engineer next:" in answer or "Create engineer-reviewed PowerMock modernization plan" in answer
    assert "Apply candidate: none" in answer
    assert "Apply allowed: False" in answer
    assert "Assistant cannot approve, apply, execute, or start downstream" in answer
    after_candidates = conn.execute(
        "SELECT COUNT(*) AS count FROM v2_repair_apply_candidates WHERE job_id = ?",
        (job_id,),
    ).fetchone()["count"]
    assert before_candidates == 0
    assert after_candidates == 0
    events = conn.execute("SELECT type, stage FROM v2_job_events WHERE job_id = ?", (job_id,)).fetchall()
    assert not any(str(row["type"]) == "stage_started" and int(row["stage"] or 0) > 2 for row in events)
    assert "PowerMockito.whenNew" in test_source.read_text(encoding="utf-8")


def test_fastapi_create_app_repair_gate_callback_creates_repair_review_gate(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    _seed_policy(conn, job_id)

    callback = app.state.v2_orchestrator_runner._diagnosis_callback
    callback(
        job_id,
        1,
        "cmd-build-1",
        "build_failed",
        {
            "build_status": "FAILED",
            "message": "build exploded",
            "stderr": "boom",
            "artifact_refs": {"analysis": "analysis:1"},
        },
    )

    with SqliteUnitOfWork(conn) as uow:
        open_gates = uow.phase_gates.list_open(job_id)
        assert open_gates
        assert any(gate.gate_phase == "repair_review" for gate in open_gates)


def test_fastapi_create_app_skips_repair_gate_when_disabled(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    _seed_policy(conn, job_id, enable_build_repair=False)

    callback = app.state.v2_orchestrator_runner._diagnosis_callback
    callback(
        job_id,
        1,
        "cmd-build-1",
        "build_failed",
        {
            "build_status": "FAILED",
            "message": "build exploded",
            "stderr": "boom",
            "artifact_refs": {"analysis": "analysis:1"},
        },
    )

    with SqliteUnitOfWork(conn) as uow:
        open_gates = uow.phase_gates.list_open(job_id)
        assert not any(gate.gate_phase == "repair_review" for gate in open_gates)


def test_live_diagnosis_persists_repair_candidate_then_approve_and_apply(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    _seed_policy(conn, job_id)
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_client = _FakeShadowClient()
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_enabled = True
    sandbox = tmp_path / "sandbox"
    target = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    target.parent.mkdir(parents=True)
    target.write_text("class ExampleTest { void setUp(){ MockitoAnnotations.initMocks(this); } }\n", encoding="utf-8")

    callback = app.state.v2_orchestrator_runner._diagnosis_callback
    payload = {
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "sandbox_path": str(sandbox),
        "message": "MockitoAnnotations.initMocks(this);",
        "artifact_refs": {
            "sandbox": str(sandbox),
            "test_source": str(target),
        },
    }
    callback(job_id, 2, "cmd-initmocks-live", "build_failed", payload)
    callback(job_id, 2, "cmd-initmocks-live", "build_failed", payload)
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=2,
            event_type="build_failed",
            status="failed",
            message="MockitoAnnotations.initMocks(this);",
            payload=payload,
        )

    rows = conn.execute("SELECT repair_candidate_id FROM v2_repair_apply_candidates WHERE job_id = ?", (job_id,)).fetchall()
    assert len(rows) == 1
    repair_candidate_id = str(rows[0]["repair_candidate_id"])

    summary_response = client.get(f"/v1/v2/jobs/{job_id}/failure-summary")
    assert summary_response.status_code == 200, summary_response.text
    summary_candidate = summary_response.json()["repair_apply_candidate"]
    assert summary_candidate["repair_candidate_id"] == repair_candidate_id
    assert summary_candidate["status"] == "pending_human_approval"
    assert "_target_path" not in json.dumps(summary_candidate)

    get_response = client.get(f"/v1/v2/jobs/{job_id}/stages/2/repair-candidates/{repair_candidate_id}")
    assert get_response.status_code == 200, get_response.text
    candidate = get_response.json()["candidate"]
    assert candidate["repair_candidate_id"] == repair_candidate_id
    assert "_sandbox_root" not in json.dumps(candidate)

    approve_response = client.post(
        f"/v1/v2/jobs/{job_id}/stages/2/repair-candidates/{repair_candidate_id}/approve",
        headers=_mutation_headers(),
        json={
            "repair_candidate_id": repair_candidate_id,
            "patch_checksum": candidate["patch_checksum"],
            "target_file_checksum": candidate["target_file_checksum"],
            "review_checksum": candidate["review_checksum"],
        },
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["candidate"]["status"] == "approved"
    assert approve_response.json()["candidate"]["apply_enabled"] is True
    approved_summary = client.get(f"/v1/v2/jobs/{job_id}/failure-summary").json()
    approved_nested = approved_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_apply_candidate"]
    assert approved_nested["repair_candidate_id"] == repair_candidate_id
    assert approved_nested["status"] == "approved"
    assert approved_nested["apply_enabled"] is True
    strategy = approved_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_strategy_packet"]
    assert strategy["backend_gate"]["downstream_start_allowed"] is False

    ask_response = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        headers=_mutation_headers(),
        json={"question": "Explain the repair strategy and whether you can apply it"},
    )
    assert ask_response.status_code == 200, ask_response.text
    answer = ask_response.json()["assistant_message"]["content"]
    assert "Repair strategy:" in answer
    assert "Apply candidate: exists" in answer
    assert "Assistant cannot approve, apply, execute, or start downstream" in answer

    apply_response = client.post(
        f"/v1/v2/jobs/{job_id}/stages/2/repair-candidates/{repair_candidate_id}/apply",
        headers=_mutation_headers(),
        json={"repair_candidate_id": repair_candidate_id},
    )
    assert apply_response.status_code == 200, apply_response.text
    assert apply_response.json()["execution"]["execution_status"] == "verified"
    assert apply_response.json()["execution"]["downstream_start_allowed"] is False
    assert "openMocks" in target.read_text(encoding="utf-8")
    verified_summary = client.get(f"/v1/v2/jobs/{job_id}/failure-summary").json()
    verified_nested = verified_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_apply_candidate"]
    assert verified_nested["status"] == "verified"
    assert verified_nested["apply_enabled"] is False
    assert verified_nested["proof_artifact"]

    events = conn.execute("SELECT type, stage FROM v2_job_events WHERE job_id = ?", (job_id,)).fetchall()
    assert not any(str(row["type"]) == "stage_started" and int(row["stage"] or 0) > 2 for row in events)
