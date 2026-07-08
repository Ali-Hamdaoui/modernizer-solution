"""Runtime wiring regression for repair gate diagnosis callbacks."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.application.v2_repair_strategy_packet import (
    create_repair_strategy_packet,
)
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    create_repair_apply_candidate,
)
from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
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
from migration_factory.control_tower.infrastructure.sqlite.v2_event_repository import (
    SqliteV2JobEventRepository,
)
from ._helpers import canonical_json, seed_runner_profile, sha256_json
from .test_v2_repair_strategy_packet import _powermock_classification, _powermock_evidence
from .test_v2_repair_apply_candidate_r8_1 import _jackson_evidence, _jackson_pom
from .v1_fixtures import make_v1_pipeline_definition, make_v2_pipeline_definition
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


class _CountingShadowClient(_FakeShadowClient):
    def __init__(self) -> None:
        self.calls = 0

    def answer_with_role(self, **kwargs: Any) -> Any:
        self.calls += 1
        return super().answer_with_role(**kwargs)


class _NoCallModelClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def answer_with_role(self, *, role: Any, prompt: str, fallback: str, **_: Any) -> Any:
        self.calls.append(getattr(role, "value", str(role)))
        raise AssertionError("deterministic route must not invoke WF-03A model calls")


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
    for pipeline_payload in (make_v1_pipeline_definition(), make_v2_pipeline_definition()):
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


def _create_job(client: TestClient, setup_id: str, policy: dict | None = None) -> str:
    payload: dict = {"setup_id": setup_id}
    if policy is not None:
        payload["policy"] = policy
    response = client.post(
        "/v1/v2/migration-jobs",
        json=payload,
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


class _RunConfigurationOverrideRepository:
    def __init__(
        self,
        delegate: Any,
        *,
        missing_job_ids: set[str],
        policy_json_by_job_id: dict[str, str],
    ) -> None:
        self._delegate = delegate
        self._missing_job_ids = missing_job_ids
        self._policy_json_by_job_id = policy_json_by_job_id

    def get_for_job(self, job_id: str) -> Any:
        if job_id in self._missing_job_ids:
            return None
        if job_id in self._policy_json_by_job_id:
            return SimpleNamespace(policy_json=self._policy_json_by_job_id[job_id])
        return self._delegate.get_for_job(job_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


class _RunConfigurationOverrideUnitOfWork:
    def __init__(
        self,
        delegate: SqliteUnitOfWork,
        *,
        missing_job_ids: set[str],
        policy_json_by_job_id: dict[str, str],
    ) -> None:
        self._delegate = delegate
        self.run_configurations = _RunConfigurationOverrideRepository(
            delegate.run_configurations,
            missing_job_ids=missing_job_ids,
            policy_json_by_job_id=policy_json_by_job_id,
        )

    def __enter__(self) -> "_RunConfigurationOverrideUnitOfWork":
        self._delegate.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
        return self._delegate.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)


def _invoke_deterministic_repair_runtime(
    app: Any,
    tmp_path: Path,
    *,
    job_id: str,
    command_id: str,
) -> None:
    sandbox = tmp_path / command_id / "sandbox"
    source = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    source.parent.mkdir(parents=True)
    source.write_text("class ExampleTest { void setUp(){ MockitoAnnotations.initMocks(this); } }", encoding="utf-8")
    test_report = tmp_path / command_id / "TEST-ExampleTest.xml"
    test_report.parent.mkdir(parents=True, exist_ok=True)
    test_report.write_text("<failure>test setup failed</failure>", encoding="utf-8")
    build_error = tmp_path / command_id / "build-error.json"
    build_error.write_text('{"error":"test setup failed"}', encoding="utf-8")
    run_dir = tmp_path / command_id / "deterministic-run"
    run_dir.mkdir(parents=True)

    app.state.v2_orchestrator_runner._maybe_write_repair_failure_context(
        job_id=job_id,
        stage_index=2,
        command_id=command_id,
        result={
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "run_dir": str(run_dir),
            "sandbox_path": str(sandbox),
            "message": "MockitoAnnotations.initMocks(this);",
            "artifact_refs": {
                "sandbox": str(sandbox),
                "test_source": str(source),
                "test_report": str(test_report),
                "build_error_contract": str(build_error),
            },
        },
        stdout_tail="",
        stderr_tail="MockitoAnnotations.initMocks(this);",
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
    job_id = _create_job(client, setup_id, policy={
        "stage_continuation_policy": "auto_on_green",
        "enable_build_repair": True,
    })
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
    subfamily = nested_classification["repair_subfamily_assessment"]
    assert top_strategy["strategy_id"] == persisted["strategy_id"]
    assert nested_strategy["strategy_id"] == persisted["strategy_id"]
    assert nested_classification["failure_type"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert nested_classification["classification_status"] == "unsupported_known_failure"
    assert nested_strategy["family"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert nested_strategy["risk_level"] == "high"
    assert nested_strategy["apply_candidate_allowed"] is False
    assert nested_strategy["backend_recipe_available"] is False
    assert nested_strategy["human_gate_required"] is True
    assert subfamily["subfamily"] == "POWERMOCK_CONSTRUCTOR_MOCKING"
    assert subfamily["promotion_status"] == "human_refactor_required"
    assert subfamily["apply_candidate_allowed"] is False
    assert nested_strategy["repair_subfamily_assessment"]["assessment_id"] == subfamily["assessment_id"]
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
    assert "POWERMOCK_CONSTRUCTOR_MOCKING" in answer
    assert "promotion=human_refactor_required" in answer
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


def test_fastapi_diagnosis_callback_does_not_create_parallel_repair_gate(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)

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
        assert open_gates == ()
    diagnosis = app.state.v2_failure_diagnosis_service.get_diagnosis("cmd-build-1", "build_failed")
    assert diagnosis is not None


def test_failure_summary_exposes_persisted_jackson_next_candidate(tmp_path: Path) -> None:
    _app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom("2.13.5"), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)
    stage_evidence["job_id"] = job_id
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repair_candidates.save_candidate(candidate)

    summary = client.get(f"/v1/v2/migration-jobs/{job_id}/failure-summary")

    assert summary.status_code == 200, summary.text
    public = summary.json()["repair_apply_candidate"]
    assert public["family"] == "JACKSON_VERSION_ALIGNMENT_DRIFT"
    assert public["recipe_id"] == "JACKSON_PROPERTY_BOM_ALIGNMENT"
    assert public["target_file"] == "pom.xml"
    assert public["target_files"] == ["pom.xml"]
    assert public["status"] == "pending_human_approval"
    assert public["approval_required"] is True
    assert public["apply_enabled"] is False
    assert public["sandbox_only"] is True
    assert public["downstream_start_allowed"] is False
    assert "patch" not in public
    assert "_target_path" not in json.dumps(public)


def test_failure_summary_exposes_post_repair_next_candidate_blocked_reason(tmp_path: Path) -> None:
    _app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id)
    sandbox = tmp_path / "sandbox"
    pom = sandbox / "pom.xml"
    sandbox.mkdir(parents=True)
    pom.write_text(_jackson_pom("2.13.5"), encoding="utf-8")
    classification, stage_evidence = _jackson_evidence(pom, sandbox)
    stage_evidence["job_id"] = job_id
    candidate = create_repair_apply_candidate(classification, stage_evidence, {})
    assert candidate is not None
    execution = {
        "status": "verified",
        "execution_status": "verified",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "post_repair_verification_status": "failed",
        "stage_recovery_status": "still_failed",
        "post_repair_verification": {
            "next_repair_candidate_blocked_reason": "jackson_alignment_candidate_safety_gate_failed",
            "next_repair_candidate_blocked_gate": "backend_deterministic_candidate",
        },
        "next_repair_candidate": None,
        "next_repair_candidate_blocked_reason": "jackson_alignment_candidate_safety_gate_failed",
        "next_repair_candidate_blocked_gate": "backend_deterministic_candidate",
        "next_repair_candidate_gate_trace": {
            "failure_type": "JACKSON_VERSION_ALIGNMENT_DRIFT",
            "classification_status": "known_family_candidate",
        },
    }
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_repair_candidates.save_candidate(candidate)
        uow.v2_repair_candidates.save_execution(
            job_id,
            int(candidate["stage_index"]),
            str(candidate["repair_candidate_id"]),
            execution,
        )

    summary = client.get(f"/v1/v2/migration-jobs/{job_id}/failure-summary")

    assert summary.status_code == 200, summary.text
    public = summary.json()["repair_apply_candidate"]
    assert public["next_repair_candidate"] is None
    assert public["next_repair_candidate_blocked_reason"] == "jackson_alignment_candidate_safety_gate_failed"
    assert public["next_repair_candidate_blocked_gate"] == "backend_deterministic_candidate"
    assert public["next_repair_candidate_gate_trace"]["failure_type"] == "JACKSON_VERSION_ALIGNMENT_DRIFT"


def test_fastapi_create_app_skips_repair_gate_when_disabled(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id, policy={
        "stage_continuation_policy": "auto_on_green",
        "enable_build_repair": False,
    })

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


def test_classify_for_repair_route_is_side_effect_free_with_shadow_enabled(tmp_path: Path) -> None:
    shadow = _CountingShadowClient()
    candidates: list[dict[str, Any]] = []
    strategies: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    sandbox = tmp_path / "sandbox"
    source = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class ExampleTest {\n"
        "  void setUp(){\n"
        "    MockitoAnnotations.initMocks(this);\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    service = V2FailureDiagnosisService(
        event_sink=lambda **kwargs: events.append(kwargs),
        repair_candidate_sink=candidates.append,
        repair_strategy_sink=lambda packet: strategies.append(packet) or packet,
        llm_repair_shadow_client=shadow,
        llm_repair_shadow_enabled=True,
    )
    classification = service.classify_for_repair_route(
        job_id="job-pure",
        stage_index=2,
        command_id="cmd-pure",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(sandbox),
            "message": "MockitoAnnotations.initMocks(this);",
            "artifact_refs": {"test_source": str(source), "sandbox": str(sandbox)},
        },
    )

    assert classification["classification_status"] == "known_family_candidate"
    assert classification["failure_type"] == "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
    assert shadow.calls == 0
    assert strategies == []
    assert candidates == []
    assert events == []
    assert service.get_diagnosis("cmd-pure", "build_failed") is None


@pytest.mark.parametrize("policy_authority", ("missing", "empty", "invalid", "disabled"))
def test_app_deterministic_route_fails_closed_without_valid_build_repair_policy(
    tmp_path: Path,
    policy_authority: str,
) -> None:
    conn = sqlite3.connect(str(tmp_path / f"{policy_authority}.sqlite3"), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    client = _NoCallModelClient()
    missing_job_ids: set[str] = set()
    policy_json_by_job_id: dict[str, str] = {}

    def unit_of_work_factory() -> _RunConfigurationOverrideUnitOfWork:
        return _RunConfigurationOverrideUnitOfWork(
            SqliteUnitOfWork(conn),
            missing_job_ids=missing_job_ids,
            policy_json_by_job_id=policy_json_by_job_id,
        )

    app = create_app(unit_of_work_factory, v2_assistant_model_client=client)
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_client = _FakeShadowClient()
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_enabled = True
    setup_id = _ready_setup(conn)
    job_id = _create_job(client=TestClient(app, base_url="http://127.0.0.1:8000"), setup_id=setup_id, policy={
        "stage_continuation_policy": "auto_on_green",
        "enable_build_repair": policy_authority != "disabled",
    })
    if policy_authority == "missing":
        missing_job_ids.add(job_id)
    elif policy_authority == "empty":
        policy_json_by_job_id[job_id] = ""
    elif policy_authority == "invalid":
        policy_json_by_job_id[job_id] = "{not valid json"

    _invoke_deterministic_repair_runtime(
        app,
        tmp_path,
        job_id=job_id,
        command_id=f"cmd-deterministic-{policy_authority}",
    )

    events = SqliteV2JobEventRepository(conn).list_by_job(job_id)
    event_types = [event.type for event in events]
    event_payloads = [json.loads(event.payload_json or "{}") for event in events]
    assert "repair_route_selected" in event_types, list(zip(event_types, event_payloads))
    route_payload = json.loads(events[event_types.index("repair_route_selected")].payload_json)
    assert route_payload["route"] == "deterministic_recipe"
    assert client.calls == []
    with SqliteUnitOfWork(conn) as uow:
        open_gates = uow.phase_gates.list_open(job_id)
    assert not any(gate.gate_phase == "repair_review" for gate in open_gates)


def test_app_deterministic_route_preserves_candidate_and_repair_review_gate(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "deterministic.sqlite3"), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    client = _NoCallModelClient()
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=client)
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_client = _FakeShadowClient()
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_enabled = True
    setup_id = _ready_setup(conn)
    job_id = _create_job(TestClient(app, base_url="http://127.0.0.1:8000"), setup_id, policy={
        "stage_continuation_policy": "auto_on_green",
        "enable_build_repair": True,
    })
    _invoke_deterministic_repair_runtime(
        app,
        tmp_path,
        job_id=job_id,
        command_id="cmd-deterministic",
    )

    events = SqliteV2JobEventRepository(conn).list_by_job(job_id)
    event_types = [event.type for event in events]
    event_payloads = [json.loads(event.payload_json or "{}") for event in events]
    assert "repair_route_selected" in event_types, list(zip(event_types, event_payloads))
    route_payload = json.loads(events[event_types.index("repair_route_selected")].payload_json)
    assert route_payload["route"] == "deterministic_recipe"
    assert client.calls == []
    with SqliteUnitOfWork(conn) as uow:
        candidate = uow.v2_repair_candidates.latest_public_for_job(job_id)
        open_gates = uow.phase_gates.list_open(job_id)
    diagnosis = app.state.v2_failure_diagnosis_service.get_diagnosis("cmd-deterministic", "build_failed")
    envelope = getattr(diagnosis, "classification_envelope", {}) or {}
    assert envelope["failure_type"] == "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
    assert envelope["repair_proposal_draft"]["proposal_status"] == "drafted_non_actionable"
    assert envelope["repair_subfamily_assessment"]["apply_candidate_allowed"] is True
    assert any(gate.gate_phase == "repair_review" for gate in open_gates)
    if candidate is not None:
        assert candidate["candidate_kind"] != "llm_unknown_family"


def test_live_diagnosis_persists_repair_candidate_then_approve_and_apply(tmp_path: Path) -> None:
    app, client, conn = _app_and_client(tmp_path)
    setup_id = _ready_setup(conn)
    job_id = _create_job(client, setup_id, policy={
        "stage_continuation_policy": "auto_on_green",
        "enable_build_repair": True,
    })
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_client = _FakeShadowClient()
    app.state.v2_failure_diagnosis_service._llm_repair_shadow_enabled = True
    legacy = tmp_path / "legacy" / "src" / "test" / "java" / "ExampleTest.java"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("class ExampleTest { void setUp(){ MockitoAnnotations.initMocks(this); } }\n", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    target = sandbox / "src" / "test" / "java" / "ExampleTest.java"
    target.parent.mkdir(parents=True)
    target.write_text("class ExampleTest { void setUp(){ MockitoAnnotations.initMocks(this); } }\n", encoding="utf-8")
    test_report = tmp_path / "TEST-ExampleTest.xml"
    test_report.write_text("<failure>test setup failed</failure>", encoding="utf-8")
    build_error = tmp_path / "build-error.json"
    build_error.write_text('{"error":"test setup failed"}', encoding="utf-8")

    callback = app.state.v2_orchestrator_runner._diagnosis_callback
    payload = {
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "sandbox_path": str(sandbox),
        "message": "MockitoAnnotations.initMocks(this);",
        "artifact_refs": {
            "sandbox": str(sandbox),
            "test_source": str(target),
            "test_report": str(test_report),
            "build_error_contract": str(build_error),
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
    assessment = approved_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_subfamily_assessment"]
    assert assessment["subfamily"] == "INITMOCKS_DIRECT_REPLACEMENT"
    assert assessment["promotion_status"] == "safe_recipe_candidate"
    assert assessment["backend_recipe_available"] is True
    assert assessment["apply_candidate_allowed"] is True
    assert assessment["missing_evidence"] == []

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
    assert "initMocks" not in target.read_text(encoding="utf-8")
    assert "initMocks" in legacy.read_text(encoding="utf-8")
    verified_summary = client.get(f"/v1/v2/jobs/{job_id}/failure-summary").json()
    assert verified_summary["repair_strategy_packet"]
    verified_nested = verified_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_apply_candidate"]
    assert verified_nested["status"] == "verified"
    assert verified_nested["apply_enabled"] is False
    assert verified_nested["verification_status"] == "passed"
    assert verified_nested["rollback_status"]
    assert verified_nested["proof_artifact"]
    assert verified_nested["downstream_start_allowed"] is False
    verified_assessment = verified_summary["failures"][0]["supervision_trace"]["ai_diagnosis"]["classification"]["repair_subfamily_assessment"]
    assert verified_assessment["subfamily"] == "INITMOCKS_DIRECT_REPLACEMENT"

    final_ask_response = client.post(
        f"/v1/v2/jobs/{job_id}/assistant/ask",
        headers=_mutation_headers(),
        json={"question": "Explain the repair status and whether the migration can continue."},
    )
    assert final_ask_response.status_code == 200, final_ask_response.text
    final_answer = final_ask_response.json()["assistant_message"]["content"]
    assert "INITMOCKS_DIRECT_REPLACEMENT" in final_answer
    assert "promotion=safe_recipe_candidate" in final_answer
    assert "Apply candidate: exists" in final_answer
    assert "Status: verified" in final_answer
    assert "Verification: passed" in final_answer
    assert "Proof:" in final_answer
    assert "Downstream remains blocked" in final_answer
    assert "Assistant cannot approve, apply, execute, or start downstream" in final_answer

    events = conn.execute("SELECT type, stage FROM v2_job_events WHERE job_id = ?", (job_id,)).fetchall()
    assert not any(str(row["type"]) == "stage_started" and int(row["stage"] or 0) > 2 for row in events)
