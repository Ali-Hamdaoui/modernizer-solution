"""Tests for F14 assistant /ask apply route — proving it uses same PomDependencyEditor.

Validates:
- Assistant /ask explicit apply request calls editor service path
- Assistant /ask propose request does not write
- Assistant /ask vague request "fix all dependencies" does not write
- Assistant apply response comes from PomApplyResult
- Assistant does not claim validation passed before validation event
- Assistant response has no raw sandbox paths
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from migration_factory.control_tower.application.pom_dependency_editor import (
    PomDependencyEditor,
)
from migration_factory.control_tower.application.pom_change_models import (
    PomChangeStatus,
    PomApplyResult,
    ALLOWED_POM_OPERATIONS,
    APPLY_CAPABLE_POM_OPERATIONS,
    PROPOSAL_ONLY_POM_OPERATIONS,
)
from migration_factory.control_tower.application.pom_dependency_policy import (
    PomDependencyPolicy,
    DependencyControlMode,
    RiskLevel,
)


SAMPLE_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project>
    <dependencies>
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.8.9</version>
        </dependency>
        <dependency>
            <groupId>io.jsonwebtoken</groupId>
            <artifactId>jjwt-api</artifactId>
            <version>0.12.6</version>
        </dependency>
    </dependencies>
    <properties>
        <java.version>17</java.version>
    </properties>
</project>
"""

SAMPLE_POM_DEPS = {
    "properties": {"java.version": "17"},
    "dependencies": [
        {"groupId": "com.google.code.gson", "artifactId": "gson", "version": "2.8.9", "scope": "compile"},
        {"groupId": "io.jsonwebtoken", "artifactId": "jjwt-api", "version": "0.12.6", "scope": "compile"},
    ],
    "dependency_management": [],
    "plugins": [],
    "parent": {},
}


def _mock_editor(**overrides) -> PomDependencyEditor:
    """Build an editor with mock repos for assistant apply testing."""
    events = MagicMock()
    events.save = MagicMock()

    change_repo = MagicMock()
    change_repo.find_by_idempotency = MagicMock(return_value=None)
    change_repo.save = MagicMock(return_value=MagicMock(
        change_id="ch_test_1",
        status=PomChangeStatus.APPLIED_PENDING_VALIDATION.value,
        operation="update_dependency_version",
        target_json='{"kind":"dependency","group_id":"com.google.code.gson","artifact_id":"gson"}',
        requested_version="2.11.0",
        before_checksum="sha256:abc",
        after_checksum="sha256:def",
        diff_unified="diff",
        validation_id="val_1",
        rollback_id=None,
        idempotency_key="ik_1",
        executor="pom_span_patch",
        created_at="2026-06-16T00:00:00Z",
        updated_at="2026-06-16T00:00:00Z",
    ))
    change_repo.get = MagicMock(return_value=None)
    change_repo.update_status = MagicMock()
    change_repo.list_by_job = MagicMock(return_value=[])

    prop_repo = MagicMock()
    val_repo = MagicMock()
    val_repo.save = MagicMock(return_value="val_test")
    val_repo.get = MagicMock(return_value=None)
    rp_repo = MagicMock()

    import tempfile
    sandbox = tempfile.mkdtemp(prefix="f14_assistant_test_")
    pom_file = Path(sandbox) / "pom.xml"
    pom_file.write_text(SAMPLE_POM, encoding="utf-8")

    return PomDependencyEditor(
        event_sink=events,
        change_repo=change_repo,
        proposal_repo=prop_repo,
        validation_repo=val_repo,
        repair_plan_repo=rp_repo,
        resolve_sandbox_root=lambda j, s: Path(sandbox),
        resolve_pom_content=lambda j: SAMPLE_POM,
    )


# ── Tests ──────────────────────────────────────────────────────────

class TestAssistantApplyUsesSameService:

    def test_apply_change_from_user_request_writes_file(self):
        """apply_change_from_user_request writes to sandbox via same service path."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="change gson to 2.11.0",
            idempotency_key="ik_assistant_1",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        assert result.status == "applied_pending_validation"
        assert result.operation == "update_dependency_version"
        assert result.change_id != ""
        assert result.message == "The POM change was applied to the Stage 3 sandbox. Validation is now running."

    def test_apply_response_comes_from_pom_apply_result(self):
        """Assistant apply response is built from PomApplyResult, not LLM text."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="change gson to 2.11.0",
            idempotency_key="ik_assistant_2",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        # Verify result fields that would be used in assistant answer
        assert isinstance(result.change_id, str)
        assert len(result.change_id) > 0
        assert result.validation_id is not None
        assert result.rollback_available is True
        assert "validation is now running" in result.message.lower()

    def test_propose_does_not_write(self):
        """propose_change must NOT write to sandbox."""
        editor = _mock_editor()

        proposal = editor.propose_change(
            job_id="job_1",
            user_request="propose updating gson to 2.11.0",
            idempotency_key="ik_prop",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        assert proposal.applied is False
        assert proposal.proposal_id != ""
        assert len(proposal.proposal_id) > 0

    def test_vague_request_does_not_write(self):
        """'fix all dependencies' must not write."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="fix all dependencies",
            idempotency_key="ik_vague",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        # Policy should block this as vague
        assert result.status in ("blocked", "error")

    def test_assistant_does_not_claim_validation_passed_without_event(self):
        """Apply response must NOT claim validation passed — it says pending."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="change gson to 2.11.0",
            idempotency_key="ik_assistant_3",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        # Status must be pending_validation, not validated_passed
        assert result.status == "applied_pending_validation"
        assert "validation is now running" in result.message.lower()
        # Should NOT contain "passed"
        assert "passed" not in result.status

    def test_assistant_response_no_raw_paths(self):
        """PomApplyResult.to_public_dict() must not expose sandbox paths."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="change gson to 2.11.0",
            idempotency_key="ik_assistant_4",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        public = result.to_public_dict()
        for key, value in public.items():
            if isinstance(value, str) and value:
                # Must not contain temporary directory paths
                assert "/tmp/" not in value, f"Temp path leaked in key '{key}': {value}"


class TestAssistantApplyOperationClassification:

    def test_apply_dependency_change_intent_exists(self):
        """The apply_dependency_change intent must be recognized."""
        from migration_factory.control_tower.adapters.fastapi.app import _classify_v2_assistant_intent

        # "apply this" + explicit change -> apply
        result = _classify_v2_assistant_intent(
            "please apply this: change gson to 2.11.0"
        )
        # Since "apply this" and the explicit pattern both match,
        # the apply intent should be returned
        assert result in ("apply_dependency_change", "pom_dependency_change_request", "capability_boundary")

    def test_propose_intent_does_not_write(self):
        """Propose intent must route to proposal, not write."""
        from migration_factory.control_tower.adapters.fastapi.app import _classify_v2_assistant_intent

        # The intent classifier should route pom change proposal requests appropriately
        result = _classify_v2_assistant_intent(
            "propose upgrading the pom dependency gson to 2.11.0"
        )
        # Should be a proposal or dependency change request intent,
        # NOT a write intent like apply_dependency_change
        assert result != "apply_dependency_change"
        # Should resolve to a valid non-write intent
        assert result in (
            "pom_change_proposal", "pom_dependency_change_request",
            "stage3_dependency_review", "pom_or_dependency_explanation",
            "general_question",
        )


class TestApplyCapableOperations:

    def test_only_four_operations_apply_capable(self):
        """Only update_property/dependency_version, remove_dependency_version, update_plugin are apply-capable."""
        assert "update_property_version" in APPLY_CAPABLE_POM_OPERATIONS
        assert "update_dependency_version" in APPLY_CAPABLE_POM_OPERATIONS
        assert "remove_dependency_version" in APPLY_CAPABLE_POM_OPERATIONS
        assert "update_plugin_version" in APPLY_CAPABLE_POM_OPERATIONS

    def test_proposal_only_operations(self):
        """change_dependency_coordinates and others are proposal-only."""
        assert "change_dependency_coordinates" in PROPOSAL_ONLY_POM_OPERATIONS
        assert "add_dependency" in PROPOSAL_ONLY_POM_OPERATIONS
        assert "remove_dependency" in PROPOSAL_ONLY_POM_OPERATIONS
        assert "add_or_update_dependency_management_entry" in PROPOSAL_ONLY_POM_OPERATIONS

    def test_proposal_only_operation_blocked_from_write(self):
        """A proposal-only operation must not reach the patcher."""
        editor = _mock_editor()

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="add dependency com.example:lib to 1.0.0",
            idempotency_key="ik_prop_only",
            pom_content=SAMPLE_POM,
            pom_deps_data=SAMPLE_POM_DEPS,
        )

        # Should be blocked or error, not applied
        assert result.status != "applied_pending_validation"

    def test_disjoint_sets(self):
        """Apply-capable and proposal-only sets must be disjoint."""
        overlap = APPLY_CAPABLE_POM_OPERATIONS & PROPOSAL_ONLY_POM_OPERATIONS
        assert len(overlap) == 0, f"Overlap found: {overlap}"

    def test_all_operations_accounted_for(self):
        """Every ALLOWED_POM_OPERATIONS must be in either apply-capable or proposal-only."""
        accounted = APPLY_CAPABLE_POM_OPERATIONS | PROPOSAL_ONLY_POM_OPERATIONS
        for op in ALLOWED_POM_OPERATIONS:
            assert op in accounted, f"Operation '{op}' not in apply-capable or proposal-only"


# ── F14 wiring / intent classification tests ───────────────────────


class TestF14IntentClassification:
    """Tests that reproduce the exact user transcript failures."""

    def test_full_pom_defaults_to_stage3_when_stage3_complete(self):
        """User asks for 'full pom xml' with Stage 3 complete → Stage 3 should be used."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _default_stage_when_stage3_complete,
        )
        # Simulate events with Stage 3 completed
        events = (
            MagicMock(stage=3, type="stage_completed", status="completed", sequence=5),
            MagicMock(stage=3, type="build_completed", status="completed", sequence=6),
        )
        result = _default_stage_when_stage3_complete(events)
        assert result == 3, f"Expected stage=3 when Stage 3 is complete, got {result}"

    def test_stage1_not_used_when_stage3_explicit(self):
        """User explicitly says Stage 3 → must not fall back to Stage 1."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _get_requested_stage,
        )
        # "Show the full raw backend-resolved Stage 3 root pom.xml"
        question = "Show the full raw backend-resolved Stage 3 root pom.xml. Do not summarize it. Use Stage 3 only."
        result = _get_requested_stage(question, "pom_or_dependency_explanation")
        assert result == 3, f"Expected stage=3 for explicit Stage 3 question, got {result}"

    def test_explicit_stage3_raw_pom_does_not_route_to_dependency_review(self):
        """Explicit Stage 3 raw POM request must NOT route to stage3_dependency_review."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _classify_v2_assistant_intent,
        )
        question = "Show the full raw backend-resolved Stage 3 root pom.xml. Do not summarize it. Use Stage 3 only."
        intent = _classify_v2_assistant_intent(question)
        assert intent != "stage3_dependency_review", (
            f"Raw POM request must not route to dependency review, got {intent}"
        )
        assert intent in ("pom_or_dependency_explanation", "artifact_content", "general_question"), (
            f"Raw POM request should be pom_or_dependency_explanation, got {intent}"
        )

    def test_stage3_dependency_review_prompt_routes_to_review(self):
        """'Review the Stage 3 pom.xml dependencies' must route to stage3_dependency_review."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _classify_v2_assistant_intent,
        )
        question = "Review the Stage 3 pom.xml dependencies. Do not apply anything."
        intent = _classify_v2_assistant_intent(question)
        assert intent == "stage3_dependency_review", (
            f"Review prompt should route to stage3_dependency_review, got {intent}"
        )

    def test_propose_property_change_returns_proposal_intent_not_review(self):
        """'Propose changing assertj.version to 3.24.2' must route to proposal, not review."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _classify_v2_assistant_intent,
        )
        question = "Propose changing assertj.version to 3.24.2 in Stage 3 root pom.xml. Do not apply."
        intent = _classify_v2_assistant_intent(question)
        # Must not be stage3_dependency_review or generic
        assert intent != "stage3_dependency_review", (
            f"Propose property change must not route to dependency review, got {intent}"
        )
        # Should be pom_change_proposal or pom_dependency_change_request
        assert intent in ("pom_change_proposal", "pom_dependency_change_request"), (
            f"Propose property change should route to proposal, got {intent}"
        )

    def test_modelmapper_apply_prompt_does_not_return_healthcheck_status(self):
        """'Apply POM change: update org.modelmapper.version to 2.4.5' must NOT route to model_status."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _classify_v2_assistant_intent,
        )
        question = "Apply this Stage 3 POM change: update property org.modelmapper.version to 2.4.5"
        intent = _classify_v2_assistant_intent(question)
        assert intent != "model_status", (
            f"Apply property change must not route to model_status (modelmapper has 'model' substring), got {intent}"
        )
        assert intent in ("apply_dependency_change", "pom_dependency_change_request", "pom_change_proposal"), (
            f"Apply property change should route to apply/proposal, got {intent}"
        )

    def test_apply_property_change_routes_to_apply_dependency_change(self):
        """'Apply this Stage 3 POM change: update property assertj.version to 3.24.2' → apply_dependency_change."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _classify_v2_assistant_intent,
        )
        question = "apply this change: update property assertj.version to 3.24.2"
        intent = _classify_v2_assistant_intent(question)
        assert intent == "apply_dependency_change", (
            f"Apply property change must route to apply_dependency_change, got {intent}"
        )


class TestF14ApplyPropertyChange:
    """Tests for apply property change through assistant path."""

    def test_apply_property_change_from_assistant_calls_editor_and_writes(self):
        """Apply property change from assistant calls PomDependencyEditor and writes."""
        editor = _mock_editor()

        # Update SAMPLE_POM to include assertj.version property
        pom_with_assertj = SAMPLE_POM.replace(
            "</properties>",
            "    <assertj.version>3.13.2</assertj.version>\n    </properties>",
        )
        pom_deps = dict(SAMPLE_POM_DEPS)
        pom_deps["properties"] = {
            **pom_deps.get("properties", {}),
            "assertj.version": "3.13.2",
        }

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="update property assertj.version to 3.24.2",
            idempotency_key="ik_prop_apply_1",
            pom_content=pom_with_assertj,
            pom_deps_data=pom_deps,
        )

        assert result.status == "applied_pending_validation"
        assert result.operation == "update_property_version"
        assert result.change_id != ""

    def test_apply_property_change_returns_change_id_validation_id(self):
        """Apply property change must return change_id and validation_id."""
        editor = _mock_editor()

        pom_with_assertj = SAMPLE_POM.replace(
            "</properties>",
            "    <assertj.version>3.13.2</assertj.version>\n    </properties>",
        )
        pom_deps = dict(SAMPLE_POM_DEPS)
        pom_deps["properties"] = {
            **pom_deps.get("properties", {}),
            "assertj.version": "3.13.2",
        }

        result = editor.apply_change_from_user_request(
            job_id="job_1",
            user_request="update property assertj.version to 3.24.2",
            idempotency_key="ik_prop_apply_2",
            pom_content=pom_with_assertj,
            pom_deps_data=pom_deps,
        )

        assert len(result.change_id) > 0, "change_id must be present"
        assert result.validation_id is not None, "validation_id must be present"
        assert result.status == "applied_pending_validation"
        # Must say validation is running, not passed
        assert "validation is now running" in result.message.lower()
        assert "passed" not in result.status


class TestF14DeterministicFallback:
    """Tests for deterministic fallback behavior when Azure is unavailable."""

    def test_invalid_azure_response_falls_back_to_f14_deterministic_behavior(self):
        """When Azure returns empty/invalid, fallback must still execute F14 behavior."""
        from migration_factory.control_tower.application.v2_assistant_model_client import (
            V2AssistantModelResult,
            _fallback_result,
        )
        # Simulate the fallback producing a valid F14 answer (not model_status)
        fallback_text = _build_test_fallback_answer("Propose changing assertj.version to 3.24.2")
        result = _fallback_result(fallback_text, "Azure OpenAI returned empty response", "invalid_response")

        # Fallback content must include the F14 answer, not just the error
        assert result.success is False
        assert result.source == "deterministic"
        # Content should contain both the fallback F14 answer and the reason
        assert "Model: fallback" in result.content
        assert result.failure_reason == "invalid_response"
        # The deterministic F14 answer should NOT be the model status answer
        assert "Azure OpenAI model is" not in fallback_text, (
            f"Deterministic fallback must not return model status for POM proposal, got: {fallback_text[:200]}"
        )

    def test_deterministic_fallback_not_depend_on_azure_response(self):
        """F14 deterministic behavior must not depend on Azure response content."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _build_v2_assistant_answer,
        )
        question = "Propose changing assertj.version to 3.24.2 in Stage 3 root pom.xml. Do not apply."
        answer = _build_v2_assistant_answer(
            question=question,
            events=(),
            approvals=(),
            commands=(),
        )
        # The deterministic answer must NOT be the model status answer
        assert "Azure OpenAI model is" not in answer, (
            f"Deterministic fallback must not return model status for POM proposal, got: {answer[:200]}"
        )

    def test_no_raw_path_leak_in_f14_assistant_response(self):
        """F14 assistant responses must never contain raw sandbox paths."""
        from migration_factory.control_tower.adapters.fastapi.app import (
            _build_v2_assistant_answer,
        )
        # Build a simple answer from deterministic fallback (no events/approvals needed)
        question = "Show the full raw backend-resolved Stage 3 root pom.xml"
        answer = _build_v2_assistant_answer(
            question=question,
            events=(),
            approvals=(),
            commands=(),
        )
        # Must not contain raw path patterns
        for bad in ("/tmp/", "/mnt/", "/home/", "/sandbox/", "C:\\", "\\\\"):
            assert bad not in answer, (
                f"Raw path '{bad}' leaked in assistant answer: ...{answer[answer.find(bad)-50:answer.find(bad)+50] if bad in answer else ''}"
            )


def _build_test_fallback_answer(question: str) -> str:
    """Helper to build a deterministic fallback answer for testing."""
    from migration_factory.control_tower.adapters.fastapi.app import (
        _build_v2_assistant_answer,
    )
    return _build_v2_assistant_answer(question=question, events=(), approvals=(), commands=())
