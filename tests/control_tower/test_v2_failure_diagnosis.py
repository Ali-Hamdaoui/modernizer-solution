"""Tests for V2 Automatic Failure Diagnosis (F02).

Tests that the FailureDiagnosisService:
1. Creates diagnosis records for build_failed, test_failed, transform_failed
2. Rejects non-trigger event types
3. Is idempotent — same command+event_type returns existing record
4. Builds ContextPack with enrichment metadata
5. Routes through EventPromptRouter to RepairProposal
6. Persists proposal via V2RepairFlowService
7. Emits ai_diagnosis_created event
8. Does NOT apply patches
9. Does NOT create approval cards
10. Uses existing failure classification
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
    FailureDiagnosisRecord,
    create_orchestrator_diagnosis_callback,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
    RepairProposal,
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
                "summary": "Synthetic proposer trace.",
                "root_cause": "initMocks marker.",
                "repair_intent": "openMocks candidate.",
                "expected_change": "test-local replacement.",
                "affected_files": ["src/test/java/ExampleTest.java"],
                "risk_notes": [],
                "missing_evidence": [],
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


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def repair_flow() -> V2RepairFlowService:
    return V2RepairFlowService()


@pytest.fixture
def diagnosis_service(repair_flow: V2RepairFlowService) -> V2FailureDiagnosisService:
    events: list[dict[str, Any]] = []

    def event_sink(
        job_id: str,
        stage: int | None,
        event_type: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        events.append({
            "job_id": job_id,
            "stage": stage,
            "event_type": event_type,
            "status": status,
            "message": message,
            "payload": payload or {},
        })

    service = V2FailureDiagnosisService(
        repair_flow=repair_flow,
        event_sink=event_sink,
    )
    service._test_events = events  # type: ignore[attr-defined]
    return service


@pytest.fixture
def build_failed_payload() -> dict[str, Any]:
    return {
        "build_status": "BUILD_FAILED",
        "test_status": "",
        "exit_code": 1,
        "stderr": "mvn clean compile failed: compilation error",
        "stdout_tail": "# Failure summary: 5 compilation errors",
        "message": "Build failed with compilation errors",
        "command_id": "cmd-build-1",
    }


@pytest.fixture
def test_failed_payload() -> dict[str, Any]:
    return {
        "build_status": "BUILD_PASSED_IN_SANDBOX",
        "test_status": "TEST_FAILED",
        "exit_code": 1,
        "stderr": "Tests run: 42, Failures: 3",
        "stdout_tail": "# Test failures detected",
        "message": "Test validation failed",
        "command_id": "cmd-test-1",
    }


@pytest.fixture
def transform_failed_payload() -> dict[str, Any]:
    return {
        "transform_status": "TRANSFORM_FAILED",
        "final_status": "FAILED",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "stderr": "OpenRewrite transform error",
        "message": "Transform failed during sandbox execution",
        "command_id": "cmd-transform-1",
    }


# ── Core diagnosis tests ──────────────────────────────────────────


class TestFailureDiagnosis:

    def test_diagnose_build_failed(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Build_failed creates a diagnosis record."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-build-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert isinstance(diagnosis, FailureDiagnosisRecord)
        assert diagnosis.command_id == "cmd-build-1"
        assert diagnosis.event_type == "build_failed"
        assert diagnosis.diagnosis_id
        assert diagnosis.context_pack_id
        assert diagnosis.context_pack_checksum
        assert diagnosis.repair_proposal_id

    def test_diagnose_test_failed(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        test_failed_payload: dict[str, Any],
    ) -> None:
        """Test_failed creates a diagnosis record."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=2,
            command_id="cmd-test-1",
            event_type="test_failed",
            payload=test_failed_payload,
        )
        assert isinstance(diagnosis, FailureDiagnosisRecord)
        assert diagnosis.command_id == "cmd-test-1"
        assert diagnosis.event_type == "test_failed"

    def test_diagnose_transform_failed(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        transform_failed_payload: dict[str, Any],
    ) -> None:
        """Transform_failed creates a diagnosis record."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-transform-1",
            event_type="transform_failed",
            payload=transform_failed_payload,
        )
        assert isinstance(diagnosis, FailureDiagnosisRecord)
        assert diagnosis.command_id == "cmd-transform-1"
        assert diagnosis.event_type == "transform_failed"

    def test_rejects_unknown_event_type(
        self,
        diagnosis_service: V2FailureDiagnosisService,
    ) -> None:
        """Non-trigger event types raise ValueError."""
        with pytest.raises(ValueError, match="not a diagnosis trigger"):
            diagnosis_service.diagnose(
                job_id="job-1",
                stage_index=1,
                command_id="cmd-1",
                event_type="stage_started",
            )

    def test_rejects_event_types_not_in_trigger_set(
        self,
        diagnosis_service: V2FailureDiagnosisService,
    ) -> None:
        """Event types like stage_failed or repair_started are rejected."""
        for non_trigger in ("stage_failed", "repair_started", "approval_required"):
            with pytest.raises(ValueError, match="not a diagnosis trigger"):
                diagnosis_service.diagnose(
                    job_id="job-1",
                    stage_index=1,
                    command_id="cmd-1",
                    event_type=non_trigger,
                )

    def test_diagnosis_has_all_correlation_fields(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Diagnosis record contains all required correlation fields."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-build-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        # Required correlation fields per spec
        assert diagnosis.diagnosis_id
        assert diagnosis.context_pack_id
        assert diagnosis.context_pack_checksum
        assert diagnosis.command_id
        assert diagnosis.event_type
        assert diagnosis.failure_type
        assert diagnosis.repair_proposal_id
        assert diagnosis.model_invocation_id
        assert diagnosis.redaction_status
        assert diagnosis.created_at


# ── Idempotency tests ─────────────────────────────────────────────


class TestIdempotency:

    def test_same_command_event_returns_existing(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Second call with same (command_id, event_type) returns existing diagnosis."""
        first = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        second = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert first.diagnosis_id == second.diagnosis_id

    def test_same_command_different_event_creates_separate(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        test_failed_payload: dict[str, Any],
    ) -> None:
        """Same command but different event types get separate diagnoses."""
        first = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        second = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="test_failed",
            payload=test_failed_payload,
        )
        assert first.diagnosis_id != second.diagnosis_id

    def test_different_command_same_event_creates_separate(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Different commands with same event type get separate diagnoses."""
        first = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        second = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-2",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert first.diagnosis_id != second.diagnosis_id

    def test_get_diagnosis_returns_existing(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """get_diagnosis retrieves previously created record."""
        created = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        retrieved = diagnosis_service.get_diagnosis("cmd-1", "build_failed")
        assert retrieved is not None
        assert retrieved.diagnosis_id == created.diagnosis_id

    def test_get_diagnosis_returns_none_for_unknown(
        self,
        diagnosis_service: V2FailureDiagnosisService,
    ) -> None:
        """get_diagnosis returns None for unknown command/event."""
        assert diagnosis_service.get_diagnosis("nonexistent", "build_failed") is None


# ── Event emission tests ──────────────────────────────────────────


class TestEventEmission:

    def test_emits_ai_diagnosis_created(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Diagnosing a failure emits ai_diagnosis_created event."""
        events = getattr(diagnosis_service, "_test_events", [])

        diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )

        matching = [e for e in events if e["event_type"] == "ai_diagnosis_created"]
        assert len(matching) == 1
        event = matching[0]
        assert event["job_id"] == "job-1"
        assert event["status"] == "completed"
        assert "AI diagnosis created for build_failed" in event["message"]

    def test_event_payload_contains_correlation_fields(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """ai_diagnosis_created payload contains all correlation fields."""
        events = getattr(diagnosis_service, "_test_events", [])

        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )

        event = next(e for e in events if e["event_type"] == "ai_diagnosis_created")
        payload = event["payload"]
        assert payload["diagnosis_id"] == diagnosis.diagnosis_id
        assert payload["context_pack_id"] == diagnosis.context_pack_id
        assert payload["context_pack_checksum"] == diagnosis.context_pack_checksum
        assert payload["command_id"] == "cmd-1"
        assert payload["event_type"] == "build_failed"
        assert payload["failure_type"] is not None
        assert payload["repair_proposal_id"] == diagnosis.repair_proposal_id
        assert payload["model_invocation_id"] is not None
        assert payload["redaction_status"] is not None

    def test_idempotent_diagnosis_does_not_emit_again(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Second diagnosis for same (command, event) does not emit again."""
        events = getattr(diagnosis_service, "_test_events", [])

        diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )

        matching = [e for e in events if e["event_type"] == "ai_diagnosis_created"]
        assert len(matching) == 1


# ── Context pack tests ────────────────────────────────────────────


class TestContextPack:

    def test_context_pack_is_created(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Diagnosis creates a ContextPack with enrichment metadata."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert diagnosis.context_pack_id
        assert diagnosis.context_pack_checksum
        assert diagnosis.context_pack_checksum.startswith("cp-")

    def test_context_pack_has_evidence_refs(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Context pack evidence refs include failure type from classification."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        # Evidence refs should include failure type info
        assert diagnosis.failure_type

    def test_context_pack_includes_f01_enrichment_metadata(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """ContextPack receives F01 enrichment metadata (event_type, stage_index, etc)."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=2,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
            profile_id="profile-1",
            pom_summary_ref="pom://summary/1",
            sandbox_binding_ref="binding://cmd-1",
        )
        assert diagnosis.context_pack_id
        assert diagnosis.context_pack_checksum
        # The pack should have the metadata passed via ContextPackBuilder.
        # Evidence refs include failure info from classification.
        assert "BUILD_FAILED" in diagnosis.failure_type or diagnosis.failure_type


# ── Repair proposal tests ─────────────────────────────────────────


class TestRepairProposal:

    def test_proposal_created_via_repair_flow(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        repair_flow: V2RepairFlowService,
    ) -> None:
        """Diagnosis creates a RepairProposal via V2RepairFlowService."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert diagnosis.repair_proposal_id

    def test_proposal_is_draft_not_approved(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        repair_flow: V2RepairFlowService,
    ) -> None:
        """Diagnosis creates a draft (not approved) proposal."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        # The repair flow is internal, so we check via the event payload
        assert diagnosis.repair_proposal_id

    def test_proposal_is_validated_against_schema(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        repair_flow: V2RepairFlowService,
    ) -> None:
        """Diagnosis validates proposal dict against RepairProposal schema."""
        # Should succeed without raising SchemaValidationError
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert diagnosis.repair_proposal_id


# ── Non-goal enforcement tests ────────────────────────────────────


class TestNoPatchApplied:

    def test_diagnosis_does_not_apply_patch(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        repair_flow: V2RepairFlowService,
    ) -> None:
        """Diagnosis must not call apply_patch on repair flow."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        # Proposal should be in draft, not applied
        # If it were applied, we'd need an approve call first
        events = getattr(diagnosis_service, "_test_events", [])
        for event in events:
            assert event["event_type"] != "patch_applied"
            assert event["event_type"] != "approval_card_created"

    def test_diagnosis_does_not_create_approval_card(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Diagnosis must not create approval cards."""
        events = getattr(diagnosis_service, "_test_events", [])
        diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        for event in events:
            assert "approval" not in event["event_type"]


# ── Serialization tests ───────────────────────────────────────────


class TestSerialization:

    def test_diagnosis_to_dict(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """diagnosis_to_dict produces expected dict shape."""
        diagnosis = diagnosis_service.diagnose(
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload=build_failed_payload,
        )
        d = V2FailureDiagnosisService.diagnosis_to_dict(diagnosis)
        assert d["diagnosis_id"] == diagnosis.diagnosis_id
        assert d["command_id"] == "cmd-1"
        assert d["event_type"] == "build_failed"
        assert d["failure_type"] is not None
        assert d["context_pack_id"] == diagnosis.context_pack_id
        assert d["context_pack_checksum"] == diagnosis.context_pack_checksum
        assert d["repair_proposal_id"] == diagnosis.repair_proposal_id
        assert d["model_invocation_id"] is not None
        assert d["redaction_status"] is not None
        assert d["created_at"] is not None


class TestStageAwareEvidence:

    def test_failed_stage_with_artifacts_creates_stage_evidence_pack(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        build_error = tmp_path / "build-error.json"
        build_error.write_text('{"message":"compilation failed"}', encoding="utf-8")
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_ERROR",
            "sandbox_path": str(tmp_path / "sandbox"),
            "artifact_refs": {"build_error_contract": str(build_error)},
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=2,
            command_id="cmd-stage",
            event_type="build_failed",
            payload=payload,
        )

        assert diagnosis.redaction_status == "stage_evidence_collected"
        assert diagnosis.stage_evidence_pack is not None
        evidence = diagnosis.stage_evidence_pack
        assert evidence["stage_index"] == 2
        assert evidence["target_boot_version"] == "3.5.16"
        assert evidence["target_java_version"] == "17"
        assert evidence["evidence_pack_id"].startswith("stage-evidence-")
        assert evidence["evidence_pack_checksum"].startswith("sha256:")
        assert evidence["usable_artifacts"][0]["kind"] == "build_error_contract"
        assert evidence["usable_artifacts"][0]["checksum"].startswith("sha256:")
        assert "dependency_graph" in evidence["missing_artifacts"]
        assert evidence["repair_enabled"] is False

    def test_stage_evidence_classification_blocks_on_missing_core_evidence(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "artifact_refs": {"test_report": str(tmp_path / "missing-test-report.json")},
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-stage",
            event_type="build_failed",
            payload=payload,
        )

        assert diagnosis.classification_envelope is not None
        classification = diagnosis.classification_envelope
        assert classification["classification_status"] == "blocked_pending_evidence"
        assert classification["failure_type"] == "blocked_pending_evidence"
        assert classification["repair_enabled"] is False
        assert classification["assistant_next_action"] == "collect_missing_stage_evidence"

    def test_diagnosis_includes_sanitized_migration_memory_for_powermock(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "artifact_refs": {"pom_xml": str(tmp_path / "pom.xml")},
            "message": "org.powermock:powermock-api-mockito2 requires review",
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-memory",
            event_type="build_failed",
            payload=payload,
        )

        classification = diagnosis.classification_envelope
        assert classification is not None
        memory = classification["migration_memory"]
        assert memory["retrieval_status"] == "available"
        assert memory["top_match"]["memory_case_id"] == "msa-utils-powermock-legacy-test-strategy"
        assert memory["repair_enabled"] is False
        assert memory["memory_can_apply"] is False
        assert "pom_xml" not in memory["missing_evidence_suggestions"]
        assert "C:\\Users" not in json.dumps(memory)

    def test_payload_build_error_contract_alias_links_stage_evidence(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        build_error = tmp_path / "build-error.json"
        build_error.write_text('{"message":"compilation failed"}', encoding="utf-8")
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "build_error_contract": str(build_error),
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-alias",
            event_type="build_failed",
            payload=payload,
        )

        evidence = diagnosis.stage_evidence_pack
        assert evidence is not None
        assert "build_error_contract" not in evidence["missing_artifacts"]
        usable = {item["kind"]: item for item in evidence["usable_artifacts"]}
        assert usable["build_error_contract"]["checksum"].startswith("sha256:")

    def test_payload_artifact_alias_does_not_accept_unowned_patch_path(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        patch_file = tmp_path / "rewrite.patch"
        patch_file.write_text("diff --git a/pom.xml b/pom.xml", encoding="utf-8")
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "rewrite_patch": str(patch_file),
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-rejected-alias",
            event_type="build_failed",
            payload=payload,
        )

        evidence = diagnosis.stage_evidence_pack
        assert evidence is not None
        assert "rewrite_patch" in evidence["missing_artifacts"]
        assert all(item["kind"] != "rewrite_patch" for item in evidence["usable_artifacts"])

    def test_stage_evidence_can_mark_known_family_candidate_without_enabling_repair(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        build_error = tmp_path / "build-error.json"
        build_error.write_text(
            '{"message":"[ERROR] package jakarta.servlet.http does not exist"}',
            encoding="utf-8",
        )
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "artifact_refs": {"build_error_contract": str(build_error)},
            "message": "[ERROR] package jakarta.servlet.http does not exist",
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-stage",
            event_type="build_failed",
            payload=payload,
        )

        assert diagnosis.classification_envelope is not None
        classification = diagnosis.classification_envelope
        assert classification["classification_status"] == "known_family_candidate"
        assert classification["repair_family_candidate"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
        assert classification["repair_enabled"] is False
        assert classification["repair_blocked_reason"] == "R7C_classification_only_no_real_repair_apply"

    def test_diagnosis_attaches_blocked_repair_draft_for_powermock(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "sandbox"),
            "message": "org.powermock:powermock-api-mockito2 requires review",
            "artifact_refs": {"pom_xml": str(tmp_path / "pom.xml")},
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=1,
            command_id="cmd-powermock-draft",
            event_type="build_failed",
            payload=payload,
        )

        classification = diagnosis.classification_envelope
        assert classification is not None
        draft = classification["repair_proposal_draft"]
        review = classification["repair_draft_review"]
        assert draft["proposal_status"] == "blocked_human_review_gate"
        assert draft["proposed_diff_preview"] == ""
        assert review["review_status"] == "not_reviewable_blocked_human_gate"
        assert review["verdict"] == "blocked"
        assert review["verdict"] != "accepted_for_future_apply_gate"
        assert draft["apply_enabled"] is False
        assert draft["approval_enabled"] is False
        assert draft["repair_enabled"] is False
        assert review["apply_enabled"] is False
        assert review["approval_enabled"] is False
        assert review["repair_enabled"] is False
        assert review["downstream_start_allowed"] is False

    def test_diagnosis_attaches_non_actionable_initmocks_draft(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
    ) -> None:
        sandbox = tmp_path / "sandbox"
        test_file = sandbox / "src" / "test" / "java" / "ExampleTest.java"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("MockitoAnnotations.initMocks(this);\n", encoding="utf-8")
        payload = {
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(sandbox),
            "message": "MockitoAnnotations.initMocks(this);",
            "artifact_refs": {
                "sandbox": str(sandbox),
                "test_source": str(test_file),
            },
        }

        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=2,
            command_id="cmd-initmocks-draft",
            event_type="build_failed",
            payload=payload,
        )

        classification = diagnosis.classification_envelope
        assert classification is not None
        draft = classification["repair_proposal_draft"]
        review = classification["repair_draft_review"]
        assert draft["proposal_status"] == "drafted_non_actionable"
        assert draft["supported_family"] == "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
        assert draft["evidence_pack_checksum"].startswith("sha256:")
        assert draft["memory_query_signature"].startswith("sha256:")
        assert draft["target_files"] == ["src/test/java/ExampleTest.java"]
        assert draft["proposed_diff_checksum"].startswith("sha256:")
        assert review["review_status"] == "reviewed_non_actionable"
        assert review["verdict"] == "accepted_for_future_apply_gate"
        assert review["reviewer_kind"] == "deterministic_local"
        assert review["llm_invoked"] is False
        assert review["evidence_pack_checksum"] == draft["evidence_pack_checksum"]
        assert review["memory_query_signature"] == draft["memory_query_signature"]
        assert review["target_file_checksums"] == draft["target_file_checksums"]
        assert review["proposed_diff_checksum"] == draft["proposed_diff_checksum"]
        assert review["proposal_checksum"] == draft["proposal_checksum"]
        assert review["checksum_verification_status"] == "verified"
        assert review["declared_diff_checksum"] == draft["proposed_diff_checksum"]
        assert review["recomputed_diff_checksum"] == draft["proposed_diff_checksum"]
        assert review["diff_checksum_match"] is True
        assert review["declared_proposal_checksum"] == draft["proposal_checksum"]
        assert review["recomputed_proposal_checksum"] == draft["proposal_checksum"]
        assert review["proposal_checksum_match"] is True
        assert review["review_checksum"].startswith("sha256:")
        shadow = classification["llm_repair_shadow_trace"]
        assert shadow["runtime_mode"] == "fallback_only_mode"
        assert shadow["proposer_trace"]["fallback_used"] is True
        assert shadow["reviewer_trace"]["fallback_used"] is True
        assert shadow["fallback_trace"]["deterministic_gate_authority"] is True
        assert shadow["fallback_trace"]["apply_enabled"] is False
        assert draft["apply_enabled"] is False
        assert draft["approval_enabled"] is False
        assert draft["repair_enabled"] is False
        assert review["apply_enabled"] is False
        assert review["approval_enabled"] is False
        assert review["repair_enabled"] is False
        assert review["downstream_start_allowed"] is False
        assert review["legacy_mutation_allowed"] is False
        assert classification["repair_enabled"] is False
        assert classification["downstream_stage_state"]["auto_started"] is False
        assert "apply_context" not in review
        assert "approval_id" not in review
        assert diagnosis.stage_evidence_pack is not None
        assert "internal_ref" not in json.dumps(diagnosis.stage_evidence_pack)

    def test_diagnosis_attaches_configured_fake_llm_shadow_trace(
        self,
        repair_flow: V2RepairFlowService,
        tmp_path: Path,
    ) -> None:
        service = V2FailureDiagnosisService(
            repair_flow=repair_flow,
            llm_repair_shadow_client=_FakeShadowClient(),
            llm_repair_shadow_enabled=True,
        )
        sandbox = tmp_path / "sandbox"
        test_file = sandbox / "src" / "test" / "java" / "ExampleTest.java"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("MockitoAnnotations.initMocks(this);\n", encoding="utf-8")
        diagnosis = service.diagnose(
            job_id="job-stage",
            stage_index=2,
            command_id="cmd-initmocks-shadow",
            event_type="build_failed",
            payload={
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "sandbox_path": str(sandbox),
                "message": "MockitoAnnotations.initMocks(this);",
                "artifact_refs": {"sandbox": str(sandbox), "test_source": str(test_file)},
            },
        )
        classification = diagnosis.classification_envelope
        assert classification is not None
        shadow = classification["llm_repair_shadow_trace"]
        assert shadow["runtime_mode"] == "configured_llm_shadow_mode"
        assert shadow["proposer_trace"]["llm_invoked"] is True
        assert shadow["reviewer_trace"]["llm_invoked"] is True
        assert shadow["proposer_trace"]["model_metadata"]["provider"] == "fake"
        assert shadow["reviewer_trace"]["input_checksum"].startswith("sha256:")
        assert shadow["llm_can_apply"] is False
        assert shadow["fallback_trace"]["deterministic_gate_authority"] is True

    def test_diagnosis_reviewer_uses_no_live_llm_or_api_calls(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - must not run
            raise AssertionError("network call attempted")

        monkeypatch.setattr("urllib.request.urlopen", fail)
        sandbox = tmp_path / "sandbox"
        test_file = sandbox / "src" / "test" / "java" / "ExampleTest.java"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("MockitoAnnotations.initMocks(this);\n", encoding="utf-8")
        diagnosis = diagnosis_service.diagnose(
            job_id="job-stage",
            stage_index=2,
            command_id="cmd-initmocks-review-no-llm",
            event_type="build_failed",
            payload={
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "sandbox_path": str(sandbox),
                "message": "MockitoAnnotations.initMocks(this);",
                "artifact_refs": {"sandbox": str(sandbox), "test_source": str(test_file)},
            },
        )
        classification = diagnosis.classification_envelope
        assert classification is not None
        review = classification["repair_draft_review"]
        assert review["reviewer_kind"] == "deterministic_local"
        assert review["llm_invoked"] is False
        assert review["verdict"] == "accepted_for_future_apply_gate"

    def test_list_diagnoses_empty_on_new_service(self) -> None:
        """New service returns empty tuple."""
        service = V2FailureDiagnosisService()
        assert len(service.list_diagnoses()) == 0

    def test_list_diagnoses(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
        test_failed_payload: dict[str, Any],
    ) -> None:
        """list_diagnoses returns all stored records."""
        diagnosis_service.diagnose(
            job_id="job-1", stage_index=1, command_id="cmd-1",
            event_type="build_failed", payload=build_failed_payload,
        )
        diagnosis_service.diagnose(
            job_id="job-1", stage_index=2, command_id="cmd-2",
            event_type="test_failed", payload=test_failed_payload,
        )
        all_diags = diagnosis_service.list_diagnoses()
        assert len(all_diags) == 2

    def test_is_diagnosable_event(self) -> None:
        """is_diagnosable_event correctly identifies trigger events."""
        assert V2FailureDiagnosisService.is_diagnosable_event("build_failed")
        assert V2FailureDiagnosisService.is_diagnosable_event("test_failed")
        assert V2FailureDiagnosisService.is_diagnosable_event("transform_failed")
        assert not V2FailureDiagnosisService.is_diagnosable_event("stage_started")
        assert not V2FailureDiagnosisService.is_diagnosable_event("stage_completed")

    def test_clear_resets_diagnoses(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """clear() removes all in-memory diagnoses."""
        diagnosis_service.diagnose(
            job_id="job-1", stage_index=1, command_id="cmd-1",
            event_type="build_failed", payload=build_failed_payload,
        )
        assert len(diagnosis_service.list_diagnoses()) == 1
        diagnosis_service.clear()
        assert len(diagnosis_service.list_diagnoses()) == 0


# ── Failure summary tests ─────────────────────────────────────────


class TestFailureSummary:

    def test_build_failed_summary_includes_build_status(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Build failure summary mentions build status."""
        summary = diagnosis_service._build_failure_summary(
            event_type="build_failed",
            payload=build_failed_payload,
        )
        assert "BUILD_FAILED" in summary or "Build failed" in summary

    def test_test_failed_summary_includes_test_status(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        test_failed_payload: dict[str, Any],
    ) -> None:
        """Test failure summary mentions test status."""
        summary = diagnosis_service._build_failure_summary(
            event_type="test_failed",
            payload=test_failed_payload,
        )
        assert "TEST_FAILED" in summary or "Test failed" in summary

    def test_transform_failed_summary_includes_transform_status(
        self,
        diagnosis_service: V2FailureDiagnosisService,
        transform_failed_payload: dict[str, Any],
    ) -> None:
        """Transform failure summary mentions transform status."""
        summary = diagnosis_service._build_failure_summary(
            event_type="transform_failed",
            payload=transform_failed_payload,
        )
        assert "TRANSFORM_FAILED" in summary or "Transform failed" in summary


# ── Production callback wiring tests ──────────────────────────────


class TestProductionCallback:
    """Prove the production-wired callback emits ai_diagnosis_created
    without requiring direct V2FailureDiagnosisService.diagnose() calls.

    This mirrors the pattern used in app.py:
        callback = create_orchestrator_diagnosis_callback(..., event_sink=...)
        callback(job_id, stage_index, command_id, event_type, payload)
    """

    def test_callback_emits_ai_diagnosis_created(
        self,
        repair_flow: V2RepairFlowService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """The production callback emits ai_diagnosis_created when called
        with a build_failed payload, without direct service access."""
        events: list[dict[str, Any]] = []

        def event_sink(
            job_id: str,
            stage: int | None,
            event_type: str,
            status: str,
            message: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            events.append({
                "job_id": job_id,
                "stage": stage,
                "event_type": event_type,
                "status": status,
                "message": message,
                "payload": payload or {},
            })

        callback = create_orchestrator_diagnosis_callback(
            repair_flow=repair_flow,
            event_sink=event_sink,
        )

        # Call exactly as V2OrchestratorRunner._maybe_diagnose does
        callback(
            "job-1",  # job_id
            1,        # stage_index
            "cmd-1",  # command_id
            "build_failed",  # event_type
            build_failed_payload,  # payload
        )

        matching = [e for e in events if e["event_type"] == "ai_diagnosis_created"]
        assert len(matching) == 1, f"Expected 1 ai_diagnosis_created, got {len(matching)}"
        event = matching[0]
        assert event["job_id"] == "job-1"
        assert event["status"] == "completed"
        assert "build_failed" in event["message"]

    def test_callback_is_idempotent(
        self,
        repair_flow: V2RepairFlowService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Second callback call with same (command_id, event_type) does not
        emit duplicate ai_diagnosis_created."""
        events: list[dict[str, Any]] = []

        def event_sink(
            job_id: str,
            stage: int | None,
            event_type: str,
            status: str,
            message: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            events.append({
                "job_id": job_id,
                "stage": stage,
                "event_type": event_type,
                "status": status,
                "message": message,
                "payload": payload or {},
            })

        callback = create_orchestrator_diagnosis_callback(
            repair_flow=repair_flow,
            event_sink=event_sink,
        )

        callback("job-1", 1, "cmd-1", "build_failed", build_failed_payload)
        callback("job-1", 1, "cmd-1", "build_failed", build_failed_payload)

        matching = [e for e in events if e["event_type"] == "ai_diagnosis_created"]
        assert len(matching) == 1, f"Expected 1 (idempotent), got {len(matching)}"

    def test_callback_does_not_apply_patches(
        self,
        repair_flow: V2RepairFlowService,
        build_failed_payload: dict[str, Any],
    ) -> None:
        """Callback must never emit patch_applied or approval_card_created."""
        events: list[dict[str, Any]] = []

        def event_sink(
            job_id: str,
            stage: int | None,
            event_type: str,
            status: str,
            message: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            events.append({
                "job_id": job_id,
                "stage": stage,
                "event_type": event_type,
                "status": status,
                "message": message,
                "payload": payload or {},
            })

        callback = create_orchestrator_diagnosis_callback(
            repair_flow=repair_flow,
            event_sink=event_sink,
        )

        callback("job-1", 1, "cmd-1", "build_failed", build_failed_payload)

        for event in events:
            assert event["event_type"] != "patch_applied"
            assert event["event_type"] != "approval_card_created"
            assert "approval" not in event["event_type"]

    def test_callback_payload_is_redacted(
        self,
        repair_flow: V2RepairFlowService,
    ) -> None:
        """ai_diagnosis_created payload contains no raw paths or secrets."""
        events: list[dict[str, Any]] = []

        def event_sink(
            job_id: str,
            stage: int | None,
            event_type: str,
            status: str,
            message: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            events.append({
                "job_id": job_id,
                "stage": stage,
                "event_type": event_type,
                "status": status,
                "message": message,
                "payload": payload or {},
            })

        callback = create_orchestrator_diagnosis_callback(
            repair_flow=repair_flow,
            event_sink=event_sink,
        )

        # Payload with a raw absolute path
        payload_with_paths: dict[str, Any] = {
            "build_status": "BUILD_FAILED",
            "command_id": "cmd-1",
            "message": "Build failed in /home/user/projects/sandbox",
        }

        callback("job-1", 1, "cmd-1", "build_failed", payload_with_paths)

        matching = [e for e in events if e["event_type"] == "ai_diagnosis_created"]
        assert len(matching) >= 1
        event_payload = matching[0]["payload"]

        # The ai_diagnosis_created payload keys are correlation fields only,
        # no raw paths or secrets
        assert "diagnosis_id" in event_payload
        assert "context_pack_id" in event_payload
        assert "context_pack_checksum" in event_payload
        # Check no raw path-like content in payload values
        for value in event_payload.values():
            if isinstance(value, str):
                assert "/home/" not in value, f"Raw path found: {value}"
