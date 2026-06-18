from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import (
    V2RunEvidenceBundleService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_approval_repository import (
    V2ApprovalDecisionRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    V2MigrationSetupRecord,
)


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


class _FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str) -> V2AssistantModelResult:
        self.calls.append({"prompt": prompt, "fallback": fallback})
        return V2AssistantModelResult(
            content="unexpected model path",
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role="assistant",
            success=True,
            redacted_summary="ok",
            failure_reason="",
        )


def _client(tmp_path: Path, model_client: _FakeModelClient) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = sqlite3.connect(
        tmp_path / "run_evidence_bundle.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=model_client)
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _save_setup_and_job(
    conn: sqlite3.Connection,
    *,
    tmp_path: Path,
    job_id: str,
    status: str = "running",
) -> tuple[V2MigrationSetupRecord, V2MigrationJobRecord, Path]:
    now = utc_now_text()
    app_root = tmp_path / "modernized-app"
    setup = V2MigrationSetupRecord(
        setup_id=f"setup-{job_id}",
        run_name=f"Migration {job_id}",
        legacy_app_path=str(tmp_path / "legacy-app"),
        output_parent_path=str(app_root),
        ai_hub_path=str(tmp_path / "ai-hub"),
        java11_home="C:/jdk11",
        java17_home="C:/jdk17",
        java21_home="C:/jdk21",
        maven_cmd="mvn",
        proof_level="standard",
        skip_endpoint_smoke=False,
        migration_flags_json="{}",
        setup_checksum=f"checksum-{job_id}",
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
        status=status,
        created_at=now,
        updated_at=now,
        correlation_id=None,
    )
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_setups.save(setup)
        uow.v2_jobs.save(job)
    return setup, job, app_root


def _save_command(
    conn: sqlite3.Connection,
    *,
    job_id: str,
    stage_index: int,
    app_root: Path,
    sandbox_path: Path | None = None,
    status: str = "running",
) -> V2StageCommandRecord:
    now = utc_now_text()
    record = V2StageCommandRecord(
        command_id=f"cmd-{job_id}-{stage_index}",
        job_id=job_id,
        stage_index=stage_index,
        manifest_checksum=f"manifest-{job_id}-{stage_index}",
        argv_json=json.dumps(["python", "runner.py", "--modernized", str(app_root)]),
        env_json="{}",
        status=status,
        created_at=now,
        updated_at=now,
        result_json=json.dumps({"sandbox_path": str(sandbox_path)}) if sandbox_path is not None else "{}",
    )
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_commands.save(record)
    return record


def test_completed_migration_with_late_model_failure_reports_ai_unavailable(tmp_path: Path) -> None:
    client, conn = _client(tmp_path, _FakeModelClient())
    _, job, app_root = _save_setup_and_job(conn, tmp_path=tmp_path, job_id="job-complete", status="completed")
    _save_command(conn, job_id=job.job_id, stage_index=3, app_root=app_root, status="completed")

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(job_id=job.job_id, stage=1, event_type="stage_completed", status="completed", message="stage 1 done", payload={})
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="stage_completed", status="completed", message="stage 2 done", payload={})
        uow.v2_events.save(
            job_id=job.job_id,
            stage=3,
            event_type="build_completed",
            status="completed",
            message="build passed",
            payload={"build_status": "BUILD_PASSED_IN_SANDBOX"},
        )
        uow.v2_events.save(
            job_id=job.job_id,
            stage=3,
            event_type="test_completed",
            status="completed",
            message="tests warnings",
            payload={"test_status": "PASS_WITH_WARNINGS"},
        )
        uow.v2_events.save(
            job_id=job.job_id,
            stage=3,
            event_type="stage_completed",
            status="completed",
            message="stage 3 completed",
            payload={
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "final_proof_level": "compiled",
            },
        )
        uow.v2_events.save(job_id=job.job_id, stage=3, event_type="final_report_completed", status="completed", message="final report done", payload={})
        uow.v2_events.save(
            job_id=job.job_id,
            stage=None,
            event_type="model_invocation_failed",
            status="failed",
            message="Azure OpenAI endpoint not configured",
            payload={"provider": "deterministic", "source": "deterministic", "success": False},
        )
        setup = uow.v2_setups.get(job.setup_id)
        events = uow.v2_events.list_by_job(job.job_id)
        approvals = uow.v2_approvals.list_cards_by_job(job.job_id)
        commands = uow.v2_commands.list_by_job(job.job_id)

    bundle = V2RunEvidenceBundleService().build_bundle(
        job_id=job.job_id,
        setup=setup,
        events=events,
        approvals=approvals,
        commands=commands,
    )
    assert bundle.migration_status == "completed_with_warnings"
    assert bundle.ai_supervision_status == "unavailable_fallback"
    assert bundle.failure_bundle is None

    response = client.post(
        f"/v1/v2/jobs/{job.job_id}/assistant/ask",
        json={"question": "what happened?"},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"]["status"] == "deterministic_evidence_bundle"
    assert body["evidence_bundle"]["migration_status"] == "completed_with_warnings"
    assert body["evidence_bundle"]["ai_supervision_status"] == "unavailable_fallback"
    assert "migration status: completed_with_warnings" in body["assistant_message"]["content"].lower()
    assert "ai supervision status: unavailable_fallback" in body["assistant_message"]["content"].lower()


def test_build_failed_bundle_includes_dependency_failure_details_and_artifacts(tmp_path: Path) -> None:
    _client_instance, conn = _client(tmp_path, _FakeModelClient())
    _, job, app_root = _save_setup_and_job(conn, tmp_path=tmp_path, job_id="job-fail", status="failed")
    run_dir = app_root / ".migration" / "runs" / "v2-fail-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "orchestration").mkdir(parents=True, exist_ok=True)
    (run_dir / "build").mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs" / "phase2_transform.log").write_text(
        "Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x\nPKIX path building failed\n",
        encoding="utf-8",
    )
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}),
        encoding="utf-8",
    )
    (run_dir / "build" / "build-error-20260618-004516-dependency_error.json").write_text(
        json.dumps(
            {
                "message": (
                    "Failed to read artifact descriptor for jakarta.persistence:jakarta.persistence-api:jar:3.0.x\n"
                    "Failed to read artifact descriptor for jakarta.servlet:jakarta.servlet-api:jar:5.0.x\n"
                    "PKIX path building failed"
                ),
            }
        ),
        encoding="utf-8",
    )
    pom_path = sandbox_dir / "pom.xml"
    original_pom = (
        "<project><properties>"
        "<javax.persistence.version>3.0.x</javax.persistence.version>"
        "<javax.servlet.version>5.0.x</javax.servlet.version>"
        "</properties><dependencies>"
        "<dependency><artifactId>jakarta.persistence-api</artifactId></dependency>"
        "<dependency><artifactId>jakarta.servlet-api</artifactId></dependency>"
        "</dependencies></project>"
    )
    pom_path.write_text(original_pom, encoding="utf-8")
    _save_command(conn, job_id=job.job_id, stage_index=2, app_root=app_root, sandbox_path=sandbox_dir, status="failed")

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="artifact_written", status="completed", message="sandbox", payload={"artifact_kind": "sandbox", "relative_path": ".migration\\runs\\v2-fail-s2\\workspaces\\sandbox"})
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="artifact_written", status="completed", message="build error", payload={"artifact_kind": "build_error", "relative_path": ".migration\\runs\\v2-fail-s2\\build\\build-error-20260618-004516-dependency_error.json"})
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="artifact_written", status="completed", message="summary", payload={"artifact_kind": "orchestration_summary", "relative_path": ".migration\\runs\\v2-fail-s2\\orchestration\\orchestration_summary.json"})
        uow.v2_events.save(
            job_id=job.job_id,
            stage=2,
            event_type="build_failed",
            status="failed",
            message="Build failed in sandbox",
            payload={
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "result_kind": "dependency_error",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "command_id": f"cmd-{job.job_id}-2",
            },
        )
        setup = uow.v2_setups.get(job.setup_id)
        events = uow.v2_events.list_by_job(job.job_id)
        approvals = uow.v2_approvals.list_cards_by_job(job.job_id)
        commands = uow.v2_commands.list_by_job(job.job_id)

    bundle = V2RunEvidenceBundleService().build_bundle(
        job_id=job.job_id,
        setup=setup,
        events=events,
        approvals=approvals,
        commands=commands,
    )
    assert bundle.migration_status == "failed"
    assert bundle.failure_bundle is not None
    assert bundle.failure_bundle.failure_type == "invalid_maven_wildcard_version"
    assert any("jakarta.persistence-api:jar:3.0.x" in item["text"] for item in bundle.build_test_error_contracts)
    assert any(item["label"] == "pom.xml" for item in bundle.pom_excerpts)
    assert any(ref["label"] == "build-error-20260618-004516-dependency_error.json" for ref in bundle.generated_artifact_refs)
    assert pom_path.read_text(encoding="utf-8") == original_pom


def test_approval_pending_bundle_is_not_called_build_failure(tmp_path: Path) -> None:
    _client_instance, conn = _client(tmp_path, _FakeModelClient())
    _, job, app_root = _save_setup_and_job(conn, tmp_path=tmp_path, job_id="job-approval", status="blocked")
    _save_command(conn, job_id=job.job_id, stage_index=2, app_root=app_root, status="blocked")

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_approvals.save_card(
            V2ApprovalDecisionRecord(
                card_id="card-1",
                interrupt_id="interrupt-1",
                request_checksum="checksum-1",
                stage_index=2,
                summary="Human approval required before Stage 2 resumes.",
                status="pending",
                created_at=utc_now_text(),
                job_id=job.job_id,
            )
        )
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="approval_required", status="blocked", message="approval required", payload={"card_id": "card-1"})
        setup = uow.v2_setups.get(job.setup_id)
        events = uow.v2_events.list_by_job(job.job_id)
        approvals = uow.v2_approvals.list_cards_by_job(job.job_id)
        commands = uow.v2_commands.list_by_job(job.job_id)

    bundle = V2RunEvidenceBundleService().build_bundle(
        job_id=job.job_id,
        setup=setup,
        events=events,
        approvals=approvals,
        commands=commands,
    )
    assert bundle.migration_status == "approval_required"
    assert bundle.approval_state == "pending_human_approval"
    assert bundle.failure_bundle is None
    assert bundle.next_operator_action == "human_approval_required"


def test_chatbot_fallback_what_happened_uses_bundle_and_skips_model_call(tmp_path: Path) -> None:
    fake = _FakeModelClient()
    client, conn = _client(tmp_path, fake)
    _, job, app_root = _save_setup_and_job(conn, tmp_path=tmp_path, job_id="job-chat-fail", status="failed")
    run_dir = app_root / ".migration" / "runs" / "v2-chat-fail-s2"
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (run_dir / "build").mkdir(parents=True, exist_ok=True)
    (run_dir / "orchestration").mkdir(parents=True, exist_ok=True)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs" / "phase2_transform.log").write_text("Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x\n", encoding="utf-8")
    (run_dir / "build" / "build-error-1.json").write_text(json.dumps({"message": "jakarta.persistence:jakarta.persistence-api:jar:3.0.x"}), encoding="utf-8")
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}), encoding="utf-8")
    (sandbox_dir / "pom.xml").write_text("<project><properties><javax.persistence.version>3.0.x</javax.persistence.version></properties><dependencies><dependency><artifactId>jakarta.persistence-api</artifactId></dependency></dependencies></project>", encoding="utf-8")
    _save_command(conn, job_id=job.job_id, stage_index=2, app_root=app_root, sandbox_path=sandbox_dir, status="failed")

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="artifact_written", status="completed", message="sandbox", payload={"artifact_kind": "sandbox", "relative_path": ".migration\\runs\\v2-chat-fail-s2\\workspaces\\sandbox"})
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="artifact_written", status="completed", message="build error", payload={"artifact_kind": "build_error", "relative_path": ".migration\\runs\\v2-chat-fail-s2\\build\\build-error-1.json"})
        uow.v2_events.save(job_id=job.job_id, stage=2, event_type="build_failed", status="failed", message="Build failed in sandbox", payload={"build_status": "BUILD_FAILED_IN_SANDBOX", "result_kind": "dependency_error", "command_id": f"cmd-{job.job_id}-2"})

    response = client.post(
        f"/v1/v2/jobs/{job.job_id}/assistant/ask",
        json={"question": "what happened?"},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert fake.calls == []
    assert body["model"]["status"] == "dual_model_failure_diagnosis"
    assert body["evidence_bundle"]["migration_status"] == "failed"
    assert body["evidence_bundle"]["deterministic_failure_classification"]["failure_type"] == "invalid_maven_wildcard_version"
    assert body["diagnosis_review"]["model2_verdict"] == "accepted"
    lowered = body["assistant_message"]["content"].lower()
    assert "verified root cause:" in lowered
    assert "wildcard maven" in lowered
    assert "model 2 verdict: accepted" in lowered
