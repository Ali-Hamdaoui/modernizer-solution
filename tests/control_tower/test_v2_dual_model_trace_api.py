from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    V2MigrationSetupRecord,
)


def _client(tmp_path: Path) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = sqlite3.connect(
        tmp_path / "dual_model_trace_api.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000"), conn


def _bundle() -> dict[str, object]:
    return {
        "run_id": "v2-demo-s2",
        "migration_status": "failed",
        "ai_supervision_status": "not_requested",
        "approval_state": "not_required",
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "",
        "final_proof_level": "not_verified",
        "latest_trustworthy_migration_event": {"type": "build_failed", "status": "failed"},
        "generated_artifact_refs": [{"label": "pom.xml", "path": "pom.xml"}],
        "failure_bundle": {
            "failure_type": "invalid_maven_wildcard_version",
            "root_cause": "Wildcard Maven versions in pom.xml.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
        },
        "next_operator_action": "review_failure_evidence",
        "read_only": True,
    }


def _seed_job(conn: sqlite3.Connection, *, tmp_path: Path, job_id: str) -> Path:
    now = utc_now_text()
    output_parent = tmp_path / "modernized-app"
    run_dir = output_parent / ".migration" / "runs" / "v2-demo-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    (sandbox_dir / "pom.xml").write_text("<project/>", encoding="utf-8")

    with SqliteUnitOfWork(conn) as uow:
        setup = V2MigrationSetupRecord(
            setup_id="setup-1",
            run_name="trace-api",
            legacy_app_path=str(tmp_path / "legacy-app"),
            output_parent_path=str(output_parent),
            ai_hub_path=str(tmp_path / "ai-hub"),
            java11_home="C:/jdk11",
            java17_home="C:/jdk17",
            java21_home="C:/jdk21",
            maven_cmd="mvn",
            proof_level="standard",
            skip_endpoint_smoke=False,
            migration_flags_json="{}",
            setup_checksum="setup-checksum",
            checksum_algorithm="sha256",
            created_at=now,
            created_by="test",
            correlation_id=None,
        )
        job = V2MigrationJobRecord(
            job_id=job_id,
            setup_id=setup.setup_id,
            setup_checksum=setup.setup_checksum,
            pipeline_id="springboot-216-to-356-java21-three-stage",
            stage_chain_json="[]",
            status="running",
            created_at=now,
            updated_at=now,
            correlation_id=None,
        )
        command = V2StageCommandRecord(
            command_id="cmd-1",
            job_id=job_id,
            stage_index=2,
            manifest_checksum="manifest-1",
            argv_json='["python","runner.py"]',
            env_json="{}",
            status="failed",
            created_at=now,
            updated_at=now,
            result_json='{"sandbox_path": ""}',
        )
        uow.v2_setups.save(setup)
        uow.v2_jobs.save(job)
        uow.v2_commands.save(command)
        uow.v2_events.save(
            job_id=job_id,
            stage=2,
            event_type="artifact_written",
            status="completed",
            message="sandbox",
            payload={"artifact_kind": "sandbox", "relative_path": ".migration\\runs\\v2-demo-s2\\workspaces\\sandbox"},
        )
    return run_dir


def test_dual_model_traces_endpoint_returns_empty_read_only_payload(tmp_path: Path) -> None:
    client, conn = _client(tmp_path)
    job_id = "job-empty"
    _seed_job(conn, tmp_path=tmp_path, job_id=job_id)

    with SqliteUnitOfWork(conn) as uow:
        before_events = len(uow.v2_events.list_by_job(job_id))

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/dual-model-traces")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == job_id
    assert body["run_id"] == "v2-demo-s2"
    assert body["trace_count"] == 0
    assert body["latest_model1_trace"] is None
    assert body["latest_model2_trace"] is None
    assert body["traces"] == []
    assert body["artifact_refs"] == []
    assert body["read_only"] is True

    with SqliteUnitOfWork(conn) as uow:
        after_events = len(uow.v2_events.list_by_job(job_id))
    assert after_events == before_events


def test_dual_model_traces_endpoint_returns_persisted_model1_and_model2_summaries(tmp_path: Path) -> None:
    client, conn = _client(tmp_path)
    job_id = "job-traces"
    run_dir = _seed_job(conn, tmp_path=tmp_path, job_id=job_id)
    service = V2DualModelRuntimeService(trace_store=V2DualModelInvocationAuditStore())
    bundle = _bundle()

    model1 = service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize failure.",
            evidence_bundle=bundle,
            trace_root=str(run_dir),
            supervision_context="stage_2_failure_review",
        )
    )
    service.invoke_model_2(
        ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify summary.",
            evidence_bundle=bundle,
            model1_output=model1.structured_output,
            trace_root=str(run_dir),
            supervision_context="stage_2_failure_review",
        )
    )

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/dual-model-traces")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == job_id
    assert body["run_id"] == "v2-demo-s2"
    assert body["trace_count"] == 2
    assert body["latest_model1_trace"]["model_role"] == MODEL_1_ROLE
    assert body["latest_model1_trace"]["provider"] == "deterministic"
    assert body["latest_model1_trace"]["fallback_used"] is True
    assert body["latest_model1_trace"]["risk_level"] == "high"
    assert body["latest_model2_trace"]["model_role"] == MODEL_2_ROLE
    assert body["latest_model2_trace"]["verdict"] == "accepted"
    assert body["latest_model2_trace"]["human_approval_required"] is False
    assert body["latest_model2_trace"]["artifact_refs"]["combined"].endswith("dual_model_invocation_trace.json")
    assert len(body["artifact_refs"]) == 2
    assert body["read_only"] is True


def test_dual_model_traces_endpoint_unknown_job_returns_404(tmp_path: Path) -> None:
    client, _conn = _client(tmp_path)

    response = client.get("/v1/v2/migration-jobs/missing/dual-model-traces")

    assert response.status_code == 404
