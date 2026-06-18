from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork


def _client(tmp_path: Path) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = sqlite3.connect(
        tmp_path / "dual_model_runtime.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def _bundle(*, status: str = "failed", root_cause: str = "Wildcard Maven versions in pom.xml.") -> dict[str, object]:
    failure_bundle = None
    if status == "failed":
        failure_bundle = {
            "failure_type": "invalid_maven_wildcard_version",
            "root_cause": root_cause,
            "confidence": "high",
            "failure_events": [{"type": "build_failed", "message": "Build failed in sandbox"}],
            "missing_artifacts": [],
            "error_contracts": [],
            "log_excerpts": [],
            "pom_excerpts": [],
            "affected_paths": ["pom.xml"],
        }
    return {
        "run_id": "v2-demo-s2",
        "stage_statuses": {"1": "completed", "2": status if status != "approval_required" else "blocked"},
        "migration_status": status,
        "ai_supervision_status": "unavailable_fallback" if status.startswith("completed") else "not_requested",
        "approval_state": "pending_human_approval" if status == "approval_required" else "not_required",
        "final_status": "BUILD_FAILED_IN_SANDBOX" if status == "failed" else "TRANSFORM_APPLIED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX" if status == "failed" else "BUILD_PASSED_IN_SANDBOX",
        "test_status": "PASS_WITH_WARNINGS" if status.startswith("completed") else "",
        "final_proof_level": "compiled" if status.startswith("completed") else "not_verified",
        "latest_trustworthy_migration_event": {"type": "build_failed" if status == "failed" else "stage_completed", "status": "failed" if status == "failed" else "completed"},
        "generated_artifact_refs": [{"label": "pom.xml", "path": "pom.xml"}],
        "failure_events": failure_bundle["failure_events"] if failure_bundle else [],
        "build_test_error_contracts": [],
        "relevant_log_excerpts": [],
        "pom_excerpts": [],
        "deterministic_failure_classification": {"failure_type": "invalid_maven_wildcard_version"} if failure_bundle else None,
        "failure_bundle": failure_bundle,
        "next_operator_action": "review_failure_evidence" if status == "failed" else ("human_approval_required" if status == "approval_required" else "migration_completed_ai_unavailable"),
        "read_only": True,
    }


def test_runtime_status_endpoint_reports_deterministic_fallback_when_provider_missing(tmp_path: Path, monkeypatch) -> None:
    client, _conn = _client(tmp_path)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)

    response = client.get("/v1/v2/model-runtime/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider"] == "azure_openai"
    assert body["model1_ready"] is False
    assert body["model2_ready"] is False
    assert body["fallback_available"] is True
    assert body["errors"]
    assert body["warnings"]


def test_runtime_status_missing_role_deployments_marks_not_ready(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)

    status = V2DualModelRuntimeService().get_status()

    assert status.model1_ready is False
    assert status.model2_ready is False
    assert status.fallback_available is True
    assert not status.errors
    assert status.warnings


def test_model1_deterministic_review_uses_evidence_bundle() -> None:
    service = V2DualModelRuntimeService()
    request = ModelInvocationRequest(
        role=MODEL_1_ROLE,
        objective="Summarize migration state.",
        evidence_bundle=_bundle(status="failed"),
        source_input="Review failure.",
    )

    result = service.invoke_model_1(request)

    assert result.mode == "fallback"
    assert result.provider == "deterministic"
    assert result.structured_output["root_cause"] == "Wildcard Maven versions in pom.xml."
    assert result.structured_output["recommended_action"] == "review_failure_evidence"
    assert "Migration failed" in result.structured_output["summary"]
    assert "pom.xml" in result.structured_output["evidence_refs"]


def test_model2_accepts_evidence_aligned_model1_output() -> None:
    service = V2DualModelRuntimeService()
    bundle = _bundle(status="failed")
    model1 = service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize migration state.",
            evidence_bundle=bundle,
        )
    )

    result = service.invoke_model_2(
        ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify model 1 output.",
            evidence_bundle=bundle,
            model1_output=model1.structured_output,
            source_input="Verify evidence alignment.",
        )
    )

    assert result.mode == "fallback"
    assert result.structured_output["verdict"] == "accepted"
    assert result.structured_output["evidence_alignment"] == "aligned"
    assert result.structured_output["hallucination_check"] == "passed"
    assert result.structured_output["human_approval_required"] is False


def test_model2_rejects_unsupported_model1_claims() -> None:
    service = V2DualModelRuntimeService()
    bundle = _bundle(status="failed")
    unsupported = {
        "summary": "Migration completed successfully.",
        "root_cause": "No issue detected.",
        "confidence": "high",
        "evidence_refs": [],
        "recommended_action": "apply repair immediately",
        "risk_level": "low",
        "proposed_next_steps": ["Run command now."],
    }

    result = service.invoke_model_2(
        ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify model 1 output.",
            evidence_bundle=bundle,
            model1_output=unsupported,
        )
    )

    assert result.structured_output["verdict"] == "rejected"
    assert result.structured_output["hallucination_check"] == "failed"
    assert result.structured_output["human_approval_required"] is True
    assert result.structured_output["issues_found"]


def test_runtime_is_read_only_and_does_not_mutate_run_artifacts(tmp_path: Path) -> None:
    service = V2DualModelRuntimeService()
    pom = tmp_path / "pom.xml"
    original = "<project/>"
    pom.write_text(original, encoding="utf-8")
    bundle = _bundle(status="failed")
    bundle["generated_artifact_refs"] = [{"label": "pom.xml", "path": "pom.xml"}]

    service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Review bundle.",
            evidence_bundle=bundle,
        )
    )
    service.invoke_model_2(
        ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify bundle.",
            evidence_bundle=bundle,
            model1_output={
                "summary": "Migration failed. Evidence points to: Wildcard Maven versions in pom.xml.",
                "root_cause": "Wildcard Maven versions in pom.xml.",
                "confidence": "high",
                "evidence_refs": ["pom.xml"],
                "recommended_action": "review_failure_evidence",
                "risk_level": "high",
                "proposed_next_steps": ["Follow deterministic next action: review_failure_evidence."],
            },
        )
    )

    assert pom.read_text(encoding="utf-8") == original
