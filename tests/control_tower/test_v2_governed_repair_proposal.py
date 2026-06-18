from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_governed_repair_proposal import (
    V2GovernedRepairProposalService,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import (
    FailureEvidenceBundle,
    RunEvidenceBundle,
)


class _FakeStructuredClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def invoke(self, *, request, schema_name: str):
        self.calls.append((request.prompt_text, schema_name))
        from migration_factory.control_tower.application.v2_diagnosis_proposal_flow import StructuredModelCallResult

        return StructuredModelCallResult(
            request_id=request.request_id,
            output_schema_name=schema_name,
            validated_output=dict(self.payload),
            role="proposer" if schema_name == "GovernedRepairProposal" else "reviewer",
            provider="fake",
            deployment_label="configured",
            model_invocation_id=f"{schema_name}-1",
            source="fake",
            model_status="live_ok",
            success=True,
            compatibility_mode="strict_role_separation",
        )


def _failed_bundle() -> RunEvidenceBundle:
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
            {"label": "phase2_transform.log", "path": "phase2_transform.log"},
        ),
        failure_events=({"type": "build_failed", "message": "Build failed in sandbox"},),
        build_test_error_contracts=(
            {
                "label": "build-error-1.json",
                "text": "Failed to read artifact descriptor for jakarta.persistence:jakarta.persistence-api:jar:3.0.x and jakarta.servlet:jakarta.servlet-api:jar:5.0.x",
            },
        ),
        relevant_log_excerpts=(
            {
                "label": "phase2_transform.log",
                "text": "Failed to download jakarta.persistence:jakarta.persistence-api:3.0.x BUILD_FAILED_IN_SANDBOX",
            },
        ),
        pom_excerpts=(
            {
                "label": "pom.xml",
                "text": "<javax.persistence.version>3.0.x</javax.persistence.version><javax.servlet.version>5.0.x</javax.servlet.version>",
            },
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
                {"label": "phase2_transform.log", "text": "jakarta.servlet:jakarta.servlet-api:jar:5.0.x"},
            ),
            pom_excerpts=(
                {"label": "pom.xml", "text": "<javax.persistence.version>3.0.x</javax.persistence.version>"},
            ),
            affected_paths=("pom.xml",),
        ),
        next_operator_action="review_failure_evidence",
        read_only=True,
    )


def _completed_bundle() -> RunEvidenceBundle:
    return RunEvidenceBundle(
        run_id="v2-complete-s3",
        stage_statuses={"3": "completed"},
        migration_status="completed_with_warnings",
        ai_supervision_status="unavailable_fallback",
        approval_state="not_required",
        final_status="TRANSFORM_APPLIED_IN_SANDBOX",
        build_status="BUILD_PASSED_IN_SANDBOX",
        test_status="PASS_WITH_WARNINGS",
        final_proof_level="compiled",
        latest_trustworthy_migration_event={"type": "final_report_completed", "status": "completed"},
        generated_artifact_refs=(),
        failure_events=(),
        build_test_error_contracts=(),
        relevant_log_excerpts=(),
        pom_excerpts=(),
        deterministic_failure_classification=None,
        failure_bundle=None,
        next_operator_action="inspect_ai_supervision_status",
        read_only=True,
    )


def test_governed_repair_proposal_fallback_persists_traces_and_artifacts(tmp_path: Path, monkeypatch) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-failure-s2"
    pom_path = run_root / "workspaces" / "sandbox" / "pom.xml"
    pom_path.parent.mkdir(parents=True, exist_ok=True)
    pom_path.write_text("<project/>", encoding="utf-8")
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", raising=False)
    service = V2GovernedRepairProposalService(
        proposer_client=None,
        reviewer_client=None,
        trace_store=V2DualModelInvocationAuditStore(),
    )

    result = service.propose(
        question="solve this",
        bundle=_failed_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
        diagnosis_review={
            "root_cause": "Generated pom.xml contains wildcard Maven dependency versions.",
            "confidence": "high",
        },
    )

    assert result.model2_verdict == "accepted"
    assert result.proposal["failure_type"] == "invalid_maven_wildcard_version"
    assert "3.1.0" in " ".join(result.proposal["proposed_file_changes"])
    assert "6.0.0" in " ".join(result.proposal["proposed_file_changes"])
    assert result.proposal["read_only"] if "read_only" in result.proposal else True
    assert result.proposal["no_auto_apply"] is True
    assert result.proposal["human_approval_required"] is True
    assert "I prepared a repair proposal; I did not apply it." in result.answer
    assert "jakarta.persistence-api:jar:3.0.x" in result.answer
    assert "jakarta.servlet-api:jar:5.0.x" in result.answer
    assert pom_path.read_text(encoding="utf-8") == "<project/>"
    assert Path(run_root / result.trace_artifact_refs["model1"]["combined"]).is_file()
    assert Path(run_root / result.trace_artifact_refs["model2"]["combined"]).is_file()
    artifact_dir = run_root / "ai_supervision" / "repair_proposals" / result.proposal_id
    assert (artifact_dir / "repair_proposal.json").is_file()
    assert (artifact_dir / "repair_verification.json").is_file()
    assert (artifact_dir / "repair_proposal.md").is_file()
    proposal_payload = json.loads((artifact_dir / "repair_proposal.json").read_text(encoding="utf-8"))
    assert proposal_payload["read_only"] is True
    assert proposal_payload["no_auto_apply"] is True
    assert proposal_payload["human_approval_required"] is True


def test_governed_repair_proposal_completed_run_reports_no_repair_needed(tmp_path: Path) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-complete-s3"
    run_root.mkdir(parents=True, exist_ok=True)
    service = V2GovernedRepairProposalService(
        proposer_client=None,
        reviewer_client=None,
        trace_store=V2DualModelInvocationAuditStore(),
    )

    result = service.propose(
        question="fix this",
        bundle=_completed_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )

    assert result.migration_status == "completed_with_warnings"
    assert "No migration repair is needed" in result.answer
    assert result.trace_artifact_refs == {"model1": {}, "model2": {}}
    assert result.proposal_artifact_refs == {}


def test_governed_repair_proposal_reviewer_rejection_is_surfaced_safely(tmp_path: Path, monkeypatch) -> None:
    output_parent = tmp_path / "modernized-app"
    run_root = output_parent / ".migration" / "runs" / "v2-failure-s2"
    run_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "model1")
    monkeypatch.setenv("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "model2")
    proposer = _FakeStructuredClient(
        {
            "summary": "POM-only repair proposal.",
            "failure_type": "invalid_maven_wildcard_version",
            "root_cause": "Generated pom.xml contains wildcard Maven dependency versions.",
            "confidence": "high",
            "recommended_action": "Review bounded pom.xml proposal before any later approval.",
            "risk_level": "medium",
            "affected_paths": ["pom.xml"],
            "proposed_file_changes": ["Replace wildcard versions with exact versions."],
            "validation_commands": ["Use existing governed Stage 2 sandbox build validation."],
            "rollback_plan": "No patch applied in this ticket.",
            "human_approval_required": True,
            "no_auto_apply": True,
            "evidence_refs": ["pom.xml", "build-error-1.json"],
        }
    )
    reviewer = _FakeStructuredClient(
        {
            "verdict": "rejected",
            "evidence_alignment": "mismatch",
            "hallucination_check": "failed",
            "policy_check": "passed",
            "risk_level": "high",
            "issues_found": ["Proposal did not include exact replacement versions."],
            "human_approval_required": True,
        }
    )
    service = V2GovernedRepairProposalService(
        proposer_client=proposer,
        reviewer_client=reviewer,
        trace_store=V2DualModelInvocationAuditStore(),
    )

    result = service.propose(
        question="solve this",
        bundle=_failed_bundle(),
        setup=SimpleNamespace(output_parent_path=str(output_parent)),
    )

    assert result.model2_verdict == "rejected"
    assert "needs human review" in result.answer.lower()
    assert "Proposal did not include exact replacement versions." in result.answer
    assert len(proposer.calls) == 1
    assert len(reviewer.calls) == 1
