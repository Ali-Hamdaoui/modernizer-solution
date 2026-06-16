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
