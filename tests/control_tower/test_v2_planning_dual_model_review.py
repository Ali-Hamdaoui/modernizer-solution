from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    ModelInvocationRequest,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.application.v2_planning_dual_model_review import (
    V2PlanningDualModelReviewService,
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


class _FakeModelClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[ModelInvocationRequest] = []

    def invoke(self, request: ModelInvocationRequest) -> dict[str, object]:
        self.calls.append(request)
        return self.payload


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        tmp_path / "planning_dual_model_review.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _seed_job(conn: sqlite3.Connection, tmp_path: Path) -> tuple[Path, dict[str, object]]:
    now = utc_now_text()
    output_parent = tmp_path / "modernized-app"
    run_dir = output_parent / ".migration" / "runs" / "v2-job-1-s1"
    planning_dir = run_dir / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    plan_path = planning_dir / "migration_plan.json"
    plan_path.write_text('{"summary":"plan ok"}', encoding="utf-8")

    with SqliteUnitOfWork(conn) as uow:
        uow.v2_setups.save(
            V2MigrationSetupRecord(
                setup_id="setup-1",
                run_name="planning-review",
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
        )
        uow.v2_jobs.save(
            V2MigrationJobRecord(
                job_id="job-1",
                setup_id="setup-1",
                setup_checksum="setup-checksum",
                pipeline_id="springboot-216-to-356-java21-three-stage",
                stage_chain_json="[]",
                status="running",
                created_at=now,
                updated_at=now,
                correlation_id=None,
            )
        )
        uow.v2_commands.save(
            V2StageCommandRecord(
                command_id="cmd-1",
                job_id="job-1",
                stage_index=1,
                manifest_checksum="manifest-1",
                argv_json=json.dumps(["python", "-m", "runner", "--modernized", str(output_parent)]),
                env_json="{}",
                status="completed",
                created_at=now,
                updated_at=now,
                result_json=json.dumps({"sandbox_path": str(run_dir / "workspaces" / "sandbox")}),
            )
        )
        uow.v2_events.save(job_id="job-1", stage=1, event_type="analysis_completed", status="completed", message="analysis ok", payload={})
        uow.v2_events.save(job_id="job-1", stage=1, event_type="planning_completed", status="completed", message="planning ok", payload={"command_id": "cmd-1"})
        uow.v2_events.save(job_id="job-1", stage=1, event_type="assessment_completed", status="completed", message="assessment ok", payload={})
        uow.v2_events.save(
            job_id="job-1",
            stage=1,
            event_type="artifact_written",
            status="completed",
            message="plan",
            payload={"artifact_kind": "plan", "relative_path": ".migration\\runs\\v2-job-1-s1\\planning\\migration_plan.json"},
        )
    result = {
        "status": "human_approval_required",
        "run_id": "v2-job-1-s1",
        "summary": "Deterministic planning completed for migration units.",
        "planning_status": "completed",
        "assessment_status": "completed",
        "generated_migration_units": [{"unit_id": "u1", "summary": "upgrade pom"}],
        "artifact_refs": {"plan": str(plan_path)},
        "decision_options": ["approved", "rejected", "replan_required"],
    }
    return run_dir, result


def test_planning_review_invokes_model1_and_model2_with_same_bundle(tmp_path: Path, monkeypatch) -> None:
    conn = _conn(tmp_path)
    _run_dir, result = _seed_job(conn, tmp_path)
    model1 = _FakeModelClient(
        {
            "summary": "Planning looks consistent.",
            "root_cause": "Planning rationale reviewed.",
            "confidence": "high",
            "evidence_refs": ["migration_plan.json", "event:planning_completed"],
            "recommended_action": "human_approval_required",
            "risk_level": "medium",
            "proposed_next_steps": ["Await human approval."],
        }
    )
    model2 = _FakeModelClient(
        {
            "verdict": "accepted",
            "evidence_alignment": "aligned",
            "hallucination_check": "passed",
            "policy_check": "passed",
            "risk_level": "medium",
            "issues_found": [],
            "human_approval_required": True,
        }
    )
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "model1")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "model2")
    runtime = V2DualModelRuntimeService(
        model1_client=model1,
        model2_client=model2,
        trace_store=V2DualModelInvocationAuditStore(),
    )
    service = V2PlanningDualModelReviewService(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        runtime_service=runtime,
    )

    review = service.review_planning_for_approval(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        result=result,
    )

    assert len(model1.calls) == 1
    assert len(model2.calls) == 1
    assert model1.calls[0].supervision_context == "planning_review"
    assert model2.calls[0].supervision_context == "planning_verification"
    assert model2.calls[0].model1_output == review.model1_result.structured_output
    assert model1.calls[0].evidence_bundle["run_id"] == model2.calls[0].evidence_bundle["run_id"]
    assert review.model2_result.structured_output["verdict"] == "accepted"


def test_planning_review_persists_traces_and_returns_approval_summary(tmp_path: Path, monkeypatch) -> None:
    conn = _conn(tmp_path)
    run_dir, result = _seed_job(conn, tmp_path)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "model1")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "model2")
    runtime = V2DualModelRuntimeService(
        model1_client=_FakeModelClient(
            {
                "summary": "Planning looks consistent.",
                "root_cause": "Planning rationale reviewed.",
                "confidence": "high",
                "evidence_refs": ["migration_plan.json"],
                "recommended_action": "human_approval_required",
                "risk_level": "medium",
                "proposed_next_steps": ["Await human approval."],
            }
        ),
        model2_client=_FakeModelClient(
            {
                "verdict": "needs_human_review",
                "evidence_alignment": "aligned",
                "hallucination_check": "passed",
                "policy_check": "warning",
                "risk_level": "medium",
                "issues_found": ["Migration unit ordering needs human confirmation."],
                "human_approval_required": True,
            }
        ),
        trace_store=V2DualModelInvocationAuditStore(),
    )
    service = V2PlanningDualModelReviewService(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        runtime_service=runtime,
    )

    review = service.review_planning_for_approval(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        result=result,
    )

    assert (run_dir / "ai_supervision").is_dir()
    assert "planning_model1_review" in review.artifact_refs
    assert "planning_model2_verification" in review.artifact_refs
    assert Path(review.artifact_refs["planning_model1_review"]).is_file()
    assert Path(review.artifact_refs["planning_model2_verification"]).is_file()
    assert "Model 2 verdict: needs_human_review." in review.approval_summary
    assert "Exact checksum approval still required." in review.approval_summary


def test_planning_review_deterministic_fallback_continues_when_provider_missing(tmp_path: Path, monkeypatch) -> None:
    conn = _conn(tmp_path)
    _run_dir, result = _seed_job(conn, tmp_path)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)
    runtime = V2DualModelRuntimeService(trace_store=V2DualModelInvocationAuditStore())
    service = V2PlanningDualModelReviewService(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        runtime_service=runtime,
    )

    review = service.review_planning_for_approval(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        result=result,
    )

    assert review.model1_result.mode == "fallback"
    assert review.model1_result.provider == "deterministic"
    assert review.model2_result.mode == "fallback"
    assert review.model2_result.provider == "deterministic"
    assert "Exact checksum approval still required." in review.approval_summary
