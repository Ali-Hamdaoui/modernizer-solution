from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    ModelInvocationRequest,
    V2DualModelRuntimeService,
)
from migration_factory.control_tower.application.v2_failure_dual_model_diagnosis import (
    V2FailureDualModelDiagnosisService,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import (
    FailureEvidenceBundle,
    RunEvidenceBundle,
)


class _FakeStructuredClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[ModelInvocationRequest] = []

    def invoke(self, request: ModelInvocationRequest) -> dict[str, object]:
        self.calls.append(request)
        return self.payload


def _bundle() -> RunEvidenceBundle:
    return RunEvidenceBundle(
        run_id="v2-failure-s2",
        stage_statuses={"2": "failed"},
        migration_status="failed",
        ai_supervision_status="not_requested",
        approval_state="not_required",
        final_status="BUILD_FAILED_IN_SANDBOX",
        build_status="BUILD_FAILED_IN_SANDBOX",
        test_status="",
        final_proof_level="not_verified",
        latest_trustworthy_migration_event={"type": "build_failed", "status": "failed"},
        generated_artifact_refs=(
            {"label": "pom.xml", "path": "pom.xml"},
            {"label": "build-error-1.json", "path": "build-error-1.json"},
        ),
        failure_events=({"type": "build_failed", "message": "Build failed in sandbox"},),
        build_test_error_contracts=(
            {"label": "build-error-1.json", "text": "jakarta.persistence:jakarta.persistence-api:jar:3.0.x"},
        ),
        relevant_log_excerpts=(
            {"label": "phase2_transform.log", "text": "Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x"},
        ),
        pom_excerpts=(
            {"label": "pom.xml", "text": "<javax.persistence.version>3.0.x</javax.persistence.version>"},
        ),
        deterministic_failure_classification={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "Wildcard Maven versions in pom.xml.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
        },
        failure_bundle=FailureEvidenceBundle(
            failure_type="invalid_maven_wildcard_version",
            root_cause="Wildcard Maven versions in pom.xml.",
            confidence="high",
            failure_events=({"type": "build_failed", "message": "Build failed in sandbox"},),
            missing_artifacts=(),
            error_contracts=(
                {"label": "build-error-1.json", "text": "jakarta.persistence:jakarta.persistence-api:jar:3.0.x"},
            ),
            log_excerpts=(
                {"label": "phase2_transform.log", "text": "Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x"},
            ),
            pom_excerpts=(
                {"label": "pom.xml", "text": "<javax.persistence.version>3.0.x</javax.persistence.version>"},
            ),
            affected_paths=("pom.xml",),
        ),
        next_operator_action="review_failure_evidence",
        read_only=True,
    )


def test_failure_dual_model_diagnosis_invokes_both_roles_and_persists_traces(tmp_path: Path, monkeypatch) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-failure-s2"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "model1")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "model2")
    model1 = _FakeStructuredClient(
        {
            "summary": "Migration failed because wildcard Maven versions were written into pom.xml.",
            "root_cause": "Wildcard Maven versions in pom.xml.",
            "confidence": "high",
            "evidence_refs": ["pom.xml", "build-error-1.json"],
            "recommended_action": "review_failure_evidence",
            "risk_level": "high",
            "proposed_next_steps": ["Review pom.xml and dependency evidence."],
        }
    )
    model2 = _FakeStructuredClient(
        {
            "verdict": "accepted",
            "evidence_alignment": "aligned",
            "hallucination_check": "passed",
            "policy_check": "passed",
            "risk_level": "high",
            "issues_found": [],
            "human_approval_required": False,
        }
    )
    runtime = V2DualModelRuntimeService(
        model1_client=model1,
        model2_client=model2,
        trace_store=V2DualModelInvocationAuditStore(),
    )
    service = V2FailureDualModelDiagnosisService(runtime_service=runtime)

    result = service.diagnose(
        question="Why did it fail?",
        bundle=_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )

    assert len(model1.calls) == 1
    assert len(model2.calls) == 1
    assert model1.calls[0].supervision_context == "failure_diagnosis"
    assert model2.calls[0].supervision_context == "failure_diagnosis_verification"
    assert model2.calls[0].model1_output == result.model1["structured_output"]
    assert model1.calls[0].evidence_bundle["run_id"] == model2.calls[0].evidence_bundle["run_id"]
    assert result.model2_verdict == "accepted"
    assert "Verified root cause: Wildcard Maven versions in pom.xml." in result.answer
    assert "Model 2 verdict: accepted" in result.answer
    assert "pom.xml" in result.answer
    assert "build-error-1.json" in result.answer
    assert (run_root / "ai_supervision").is_dir()
    assert Path(run_root / result.trace_artifact_refs["model1"]["combined"]).is_file()
    assert Path(run_root / result.trace_artifact_refs["model2"]["combined"]).is_file()


def test_failure_dual_model_diagnosis_rejection_is_cautious(tmp_path: Path, monkeypatch) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-failure-s2"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "model1")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "model2")
    runtime = V2DualModelRuntimeService(
        model1_client=_FakeStructuredClient(
            {
                "summary": "Migration completed successfully.",
                "root_cause": "No issue detected.",
                "confidence": "high",
                "evidence_refs": ["pom.xml"],
                "recommended_action": "review_failure_evidence",
                "risk_level": "low",
                "proposed_next_steps": ["Do nothing."],
            }
        ),
        model2_client=_FakeStructuredClient(
            {
                "verdict": "rejected",
                "evidence_alignment": "mismatch",
                "hallucination_check": "failed",
                "policy_check": "passed",
                "risk_level": "high",
                "issues_found": ["Model 1 contradicted deterministic failure evidence."],
                "human_approval_required": True,
            }
        ),
        trace_store=V2DualModelInvocationAuditStore(),
    )
    service = V2FailureDualModelDiagnosisService(runtime_service=runtime)

    result = service.diagnose(
        question="what happened?",
        bundle=_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )

    assert result.model2_verdict == "rejected"
    assert "Diagnosis needs human review" in result.answer
    assert "Model 2 verdict: rejected" in result.answer
    assert "Verifier issues:" in result.answer
    assert "Model 1 contradicted deterministic failure evidence." in result.answer
    assert "Verified root cause: No issue detected." not in result.answer


def test_failure_dual_model_diagnosis_uses_deterministic_fallback_when_provider_missing(tmp_path: Path, monkeypatch) -> None:
    output_parent = tmp_path / "modernized-app"
    (output_parent / ".migration" / "runs" / "v2-failure-s2").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)
    service = V2FailureDualModelDiagnosisService(
        runtime_service=V2DualModelRuntimeService(trace_store=V2DualModelInvocationAuditStore())
    )

    result = service.diagnose(
        question="what happened?",
        bundle=_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )

    assert result.model1["mode"] == "fallback"
    assert result.model1["provider"] == "deterministic"
    assert result.model2["mode"] == "fallback"
    assert result.model2["provider"] == "deterministic"
    assert "Verified root cause: Wildcard Maven versions in pom.xml." in result.answer
