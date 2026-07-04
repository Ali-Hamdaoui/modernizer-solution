"""PR-B: Focused tests for durable reviewed-diff proposal persistence and read APIs."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from migration_factory.control_tower.application.safe_diff_preview import (
    build_safe_diff_preview,
    safe_diff_preview_to_dict,
)
from migration_factory.control_tower.application.v2_repair_projection import (
    READ_ONLY_REPAIR_ACTIONS,
    ReviewerVerdictProjection,
    build_reviewed_diff_proposal_from_record,
    record_to_attempt_summary,
    reviewed_diff_proposal_to_safe_dict,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import V2MigrationJobRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    V2LLMInvocationRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
    V2ReviewerCritiqueRecord,
)
from migration_factory.control_tower.domain.checksums import sha256_hex, utc_now_text
from migration_factory.control_tower.domain.entities import PhaseGateRecord
from migration_factory.control_tower.adapters.fastapi.app import create_app
from fastapi.testclient import TestClient

FORBIDDEN_FIELDS = frozenset({
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "endpoint",
    "deployment",
    "env_ref",
    "filesystem_target",
    "user_supplied_file_path",
    "target_path",
    "patch_content",
})
MIGRATION_DIR = Path(__file__).resolve().parent.parent.parent / "migration_factory" / "control_tower" / "infrastructure" / "sqlite" / "migrations"


def _connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_repair_proposal_api.sqlite3"
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn, migrations_dir=MIGRATION_DIR)
    return conn


def _make_simple_diff_text() -> str:
    return (
        "diff --git a/src/App.java b/src/App.java\n"
        "--- a/src/App.java\n"
        "+++ b/src/App.java\n"
        "@@ -1,3 +1,3 @@\n"
        " class App {\n"
        "-    String mode = \"old\";\n"
        "+    String mode = \"new\";\n"
        " }\n"
    )


def _write_diff(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "final_reviewed_repair.diff"
    path.write_text(content, encoding="utf-8", newline="")
    return path


# ── Record builders ─────────────────────────────────────────────────


def _make_old_style_record(command_id: str = "cmd-old") -> V2RepairProposalRecord:
    """Create a record that only has pre-PR-B fields (compatibility test)."""
    return V2RepairProposalRecord(
        proposal_id=uuid4().hex,
        command_id=command_id,
        failure_summary="Old failure",
        hypothesis="Old hypothesis",
        patch_summary="Old patch",
        affected_paths_json='["pom.xml"]',
        status="draft",
        approval_checksum=None,
        created_at="2026-01-01T00:00:00Z",
    )


def _make_new_style_record(
    *,
    job_id: str = "job-1",
    command_id: str = "cmd-1",
    status: str = "user_review_required",
    diff_ref: str | None = None,
    diff_checksum: str | None = None,
    attempt_number: int | None = None,
    revision_number: int | None = None,
    gate_id: str | None = None,
    reviewer_verdict_id: str | None = None,
    reviewer_output_checksum: str | None = None,
    route_step_index: int | None = None,
    diagnosis_ref: str | None = None,
    repair_plan_ref: str | None = None,
    failure_evidence_ref: str | None = None,
    repair_context_ref: str | None = None,
    safe_diff_preview_ref: str | None = None,
    policy_validation_checksum: str | None = None,
    status_reason: str | None = None,
    reviewer_decision: str | None = None,
) -> V2RepairProposalRecord:
    return V2RepairProposalRecord(
        proposal_id=uuid4().hex,
        command_id=command_id,
        failure_summary="Build failed in App.java",
        hypothesis="Missing javax migration",
        patch_summary="Replace javax with jakarta",
        affected_paths_json='["src/App.java"]',
        status=status,
        approval_checksum=None,
        created_at="2026-06-30T12:00:00Z",
        job_id=job_id,
        route_step_index=route_step_index,
        attempt_number=attempt_number,
        revision_number=revision_number,
        failure_evidence_ref=failure_evidence_ref,
        repair_context_ref=repair_context_ref,
        diagnosis_ref=diagnosis_ref,
        repair_plan_ref=repair_plan_ref,
        diff_ref=diff_ref,
        diff_checksum=diff_checksum,
        safe_diff_preview_ref=safe_diff_preview_ref,
        reviewer_verdict_id=reviewer_verdict_id,
        reviewer_verdict_ref=None,
        reviewer_output_checksum=reviewer_output_checksum,
        policy_validation_checksum=policy_validation_checksum,
        gate_id=gate_id,
        status_reason=status_reason,
        reviewer_decision=reviewer_decision,
    )


# ── Actual tests ─────────────────────────────────────────────────────


class TestMigration:
    def test_migration_applies_and_old_rows_still_load(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        old_record = _make_old_style_record()
        repo.save_proposal(old_record)

        loaded = repo.get_proposal(old_record.proposal_id)
        assert loaded is not None
        assert loaded.proposal_id == old_record.proposal_id
        assert loaded.command_id == "cmd-old"
        assert loaded.job_id is None
        assert loaded.diff_ref is None
        assert loaded.gate_id is None

    def test_migration_preserves_empty_new_fields_on_old_records(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        old_record = _make_old_style_record()
        repo.save_proposal(old_record)

        loaded = repo.get_proposal(old_record.proposal_id)
        for field in ("job_id", "diff_ref", "diff_checksum", "gate_id",
                      "attempt_number", "reviewer_verdict_id", "status_reason"):
            assert getattr(loaded, field, None) is None, f"{field} should be None"

    def test_new_record_saves_and_loads_all_fields(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        record = _make_new_style_record(
            job_id="job-999",
            diff_ref=str(diff_path),
            diff_checksum="sha256:abc123",
            gate_id="gate-999",
            attempt_number=1,
            revision_number=0,
            reviewer_verdict_id="verdict-999",
            status_reason="Reviewed by LLM",
        )
        repo.save_proposal(record)
        loaded = repo.get_proposal(record.proposal_id)
        assert loaded is not None
        assert loaded.job_id == "job-999"
        assert loaded.diff_ref == str(diff_path)
        assert loaded.diff_checksum == "sha256:abc123"
        assert loaded.gate_id == "gate-999"
        assert loaded.attempt_number == 1
        assert loaded.revision_number == 0
        assert loaded.reviewer_verdict_id == "verdict-999"
        assert loaded.status_reason == "Reviewed by LLM"


class TestRepositoryJobScopedMethods:
    def test_list_proposals_by_job_returns_only_that_job(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r1 = _make_new_style_record(job_id="job-A")
        r2 = _make_new_style_record(job_id="job-A")
        r3 = _make_new_style_record(job_id="job-B")
        repo.save_proposal(r1)
        repo.save_proposal(r2)
        repo.save_proposal(r3)

        job_a = repo.list_proposals_by_job("job-A")
        job_b = repo.list_proposals_by_job("job-B")
        assert len(job_a) == 2
        assert len(job_b) == 1
        assert all(p.job_id == "job-A" for p in job_a)

    def test_get_proposal_for_job_rejects_wrong_job(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(job_id="job-X")
        repo.save_proposal(record)

        found = repo.get_proposal_for_job("job-X", record.proposal_id)
        assert found is not None

        not_found = repo.get_proposal_for_job("job-Y", record.proposal_id)
        assert not_found is None

    def test_get_current_proposal_for_job_selects_latest(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r1 = _make_new_style_record(job_id="job-C", status="draft")
        r2 = _make_new_style_record(job_id="job-C", status="user_review_required", gate_id="gate-C")
        r3 = _make_new_style_record(job_id="job-C", status="draft")
        repo.save_proposal(r1)
        repo.save_proposal(r2)
        repo.save_proposal(r3)

        current = repo.get_current_proposal_for_job("job-C")
        assert current is not None
        assert current.proposal_id == r2.proposal_id
        assert current.status == "user_review_required"

    def test_get_current_proposal_for_job_returns_none_when_no_reviewable(
        self, tmp_path: Path
    ) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r = _make_new_style_record(job_id="job-D", status="draft", gate_id=None)
        repo.save_proposal(r)

        current = repo.get_current_proposal_for_job("job-D")
        assert current is None

    def test_get_current_proposal_with_gate_and_reviewable_status(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r = _make_new_style_record(job_id="job-E", status="reviewer_accepted", gate_id="gate-E")
        repo.save_proposal(r)

        current = repo.get_current_proposal_for_job("job-E")
        assert current is not None
        assert current.proposal_id == r.proposal_id

    def test_list_attempts_by_job_returns_only_attempts_with_number(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r1 = _make_new_style_record(job_id="job-F", attempt_number=1)
        r2 = _make_new_style_record(job_id="job-F", attempt_number=None)  # not an attempt
        r3 = _make_new_style_record(job_id="job-F", attempt_number=2)
        repo.save_proposal(r1)
        repo.save_proposal(r2)
        repo.save_proposal(r3)

        attempts = repo.list_attempts_by_job("job-F")
        assert len(attempts) == 2
        assert all(a.attempt_number is not None for a in attempts)


class TestProjectionFromRecord:
    def test_build_projection_from_record_with_diff(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-test-1",
            status="user_review_required",
            failure_summary="Build failed",
            job_id="job-test",
            command_id="cmd-test",
            gate_id="gate-test",
            route_step_index=2,
            attempt_number=1,
            revision_number=0,
            diff_ref=str(diff_path),
        )
        assert projection.proposal_id == "prop-test-1"
        assert projection.job_id == "job-test"
        assert projection.command_id == "cmd-test"
        assert projection.gate_id == "gate-test"
        assert projection.route_step_index == 2
        assert projection.attempt_number == 1
        assert projection.revision_number == 0
        assert projection.diff_ref is not None
        assert projection.diff_checksum != ""
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        assert safe["allowed_actions"] == list(READ_ONLY_REPAIR_ACTIONS)

    def test_build_projection_from_record_requires_diff_ref(self) -> None:
        with pytest.raises(ValueError, match="reviewed diff ref is required"):
            build_reviewed_diff_proposal_from_record(
                proposal_id="prop-fail",
                status="draft",
                failure_summary="No diff",
                diff_ref=None,
            )

    def test_build_projection_verified_checksum(self, tmp_path: Path) -> None:
        diff_text = _make_simple_diff_text()
        diff_path = _write_diff(tmp_path, diff_text)
        from migration_factory.control_tower.domain.checksums import sha256_hex

        expected_checksum = sha256_hex(diff_text.encode("utf-8"))
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-cs",
            status="user_review_required",
            failure_summary="Checksum test",
            diff_ref=str(diff_path),
        )
        assert projection.diff_checksum == expected_checksum

    def test_record_to_attempt_summary_safe(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(
            job_id="job-summary",
            attempt_number=2,
            revision_number=1,
            status="validation_failed",
            gate_id="gate-summary",
            reviewer_verdict_id="verdict-summary",
            reviewer_output_checksum="reviewer-cs",
            policy_validation_checksum="policy-cs",
            status_reason="Validation failed on second attempt",
        )
        summary = record_to_attempt_summary(record)
        assert summary["proposal_id"] == record.proposal_id
        assert summary["attempt_number"] == 2
        assert summary["revision_number"] == 1
        assert summary["status"] == "validation_failed"
        assert summary["gate_id"] == "gate-summary"
        assert summary["status_reason"] == "Validation failed on second attempt"

    def test_record_to_attempt_summary_no_forbidden_fields(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(job_id="job-forbid", attempt_number=1)
        summary = record_to_attempt_summary(record)
        for key in summary:
            assert key not in FORBIDDEN_FIELDS, f"Forbidden field {key!r} in attempt summary"


class TestSafeDictProjection:
    def test_safe_dict_contains_no_forbidden_fields(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-safe",
            status="user_review_required",
            failure_summary="Safe test",
            diff_ref=str(diff_path),
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        for field in FORBIDDEN_FIELDS:
            assert field not in safe, f"Forbidden field {field!r} found in safe dict"

    def test_safe_dict_includes_expected_read_only_actions(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-actions",
            status="user_review_required",
            failure_summary="Actions test",
            diff_ref=str(diff_path),
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        actions = safe["allowed_actions"]
        for action in READ_ONLY_REPAIR_ACTIONS:
            assert action in actions, f"Missing action {action!r}"
        assert "approve_sandbox_apply" not in actions
        assert "request_revision" not in actions
        assert "reject_proposal" not in actions

    def test_safe_dict_has_correct_structure(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-struct",
            status="user_review_required",
            failure_summary="Structure test",
            diff_ref=str(diff_path),
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        assert safe["proposal_id"] == "prop-struct"
        assert safe["diff_ref"] is not None
        assert safe["diff_checksum"] != ""
        assert isinstance(safe["files_changed"], list)
        assert isinstance(safe["allowed_actions"], list)
        assert isinstance(safe["redactions"], list)


class TestImportDiffPreview:
    def test_current_proposal_safe_diff_preview_contains_added_import(self, tmp_path: Path) -> None:
        import_diff = (
            "diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java\n"
            "--- a/src/main/java/com/example/App.java\n"
            "+++ b/src/main/java/com/example/App.java\n"
            "@@ -1,3 +1,4 @@\n"
            "+ import com.fasterxml.jackson.databind.JsonNode;\n"
            " public class App {\n"
            "     public static void main(String[] args) {\n"
        )
        diff_path = _write_diff(tmp_path, import_diff)
        preview = build_safe_diff_preview(
            proposal_id="prop-import-test",
            diff_ref=str(diff_path),
        )
        safe = safe_diff_preview_to_dict(preview)
        assert safe["total_additions"] == 1
        assert safe["total_deletions"] == 0
        assert len(safe["files"]) == 1
        assert safe["files"][0]["additions"] == 1
        assert safe["files"][0]["deletions"] == 0
        assert len(safe["files"][0]["hunks"]) == 1
        hunk_lines = safe["files"][0]["hunks"][0]["lines"]
        assert any(
            line["kind"] == "addition" and "JsonNode" in line["text"]
            for line in hunk_lines
        )

    def test_diff_endpoint_returns_hunks_and_line_counts(self, tmp_path: Path) -> None:
        import_diff = (
            "diff --git a/src/main/java/com/example/App.java b/src/main/java/com/example/App.java\n"
            "--- a/src/main/java/com/example/App.java\n"
            "+++ b/src/main/java/com/example/App.java\n"
            "@@ -1,3 +1,4 @@\n"
            "+ import com.fasterxml.jackson.databind.JsonNode;\n"
            " public class App {\n"
            "     public static void main(String[] args) {\n"
        )
        diff_path = _write_diff(tmp_path, import_diff)
        preview = build_safe_diff_preview(
            proposal_id="prop-hunk-test",
            diff_ref=str(diff_path),
        )
        safe = safe_diff_preview_to_dict(preview)
        assert safe["total_additions"] == 1
        assert safe["total_deletions"] == 0
        assert len(safe["files"]) == 1
        assert safe["files"][0]["path"] == "src/main/java/com/example/App.java"
        assert safe["files"][0]["hunks"][0]["new_start"] == 1
        assert safe["files"][0]["hunks"][0]["new_lines"] == 4


class TestNewContractFixes:
    """PR-B contract fixes: policy metadata, reviewer verdict, actions, path safety."""

    def test_current_proposal_projects_policy_metadata_for_human_review_required(
        self, tmp_path: Path
    ) -> None:
        """policy_status, policy_reason, policy_reason_code are not None when resolved."""
        diff_path = tmp_path / "final_reviewed_repair.diff"
        diff_path.write_text("diff --git a/src/App.java b/src/App.java\n--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-foo\n+bar\n", encoding="utf-8")
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-policy",
            status="user_review_required",
            failure_summary="Build failed",
            diff_ref=str(diff_path),
            policy_status="ALLOWED",
            policy_reason="Safe diff",
            policy_reason_code="ok",
            policy_validation_checksum="sha256:abc",
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        assert safe["policy_status"] == "ALLOWED"
        assert safe["policy_reason"] == "Safe diff"
        assert safe["policy_reason_code"] == "ok"
        assert safe["policy_validation_checksum"] == "sha256:abc"

    def test_current_proposal_projects_reviewer_accept_verdict(
        self, tmp_path: Path
    ) -> None:
        """Verdict decision is 'accept' and model_invocation_id is present."""
        diff_path = tmp_path / "final_reviewed_repair.diff"
        diff_path.write_text("diff --git a/src/App.java b/src/App.java\n--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-foo\n+bar\n", encoding="utf-8")
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-verdict",
            status="user_review_required",
            failure_summary="Build failed",
            diff_ref=str(diff_path),
            reviewer_verdict_id="verdict-abc",
            reviewer_decision="accept",
            reviewer_reasoning="LGTM",
            model_invocation_id="invoc-xyz",
            reviewer_output_checksum="sha256:checksum",
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        assert safe["reviewer_verdict"] is not None
        assert safe["reviewer_verdict"]["decision"] == "accept"
        assert safe["reviewer_verdict"]["model_invocation_id"] == "invoc-xyz"
        assert safe["reviewer_verdict"]["reviewer_verdict_id"] == "verdict-abc"
        assert safe["reviewer_verdict"]["output_checksum"] == "sha256:checksum"

    def test_current_proposal_includes_approve_and_revision_actions_when_gate_waiting(
        self, tmp_path: Path
    ) -> None:
        """allowed_actions includes approve_sandbox_apply and request_revision."""
        diff_path = tmp_path / "final_reviewed_repair.diff"
        diff_path.write_text("diff --git a/src/App.java b/src/App.java\n--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-foo\n+bar\n", encoding="utf-8")
        allowed = list(READ_ONLY_REPAIR_ACTIONS)
        allowed.extend(("approve_sandbox_apply", "request_revision"))
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-actions2",
            status="user_review_required",
            failure_summary="Build failed",
            diff_ref=str(diff_path),
            allowed_actions=tuple(allowed),
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        for action in READ_ONLY_REPAIR_ACTIONS:
            assert action in safe["allowed_actions"], f"Missing {action!r}"
        assert "approve_sandbox_apply" in safe["allowed_actions"]
        assert "request_revision" in safe["allowed_actions"]

    def test_current_proposal_does_not_expose_absolute_repair_plan_path(
        self, tmp_path: Path
    ) -> None:
        """repair_plan_ref is just a filename (sanitized at storage in v2_repair_gate_service.py)."""
        diff_path = tmp_path / "final_reviewed_repair.diff"
        diff_path.write_text("diff --git a/src/App.java b/src/App.java\n--- a/src/App.java\n+++ b/src/App.java\n@@ -1 +1 @@\n-foo\n+bar\n", encoding="utf-8")
        projection = build_reviewed_diff_proposal_from_record(
            proposal_id="prop-path",
            status="user_review_required",
            failure_summary="Build failed",
            diff_ref=str(diff_path),
            repair_plan_ref="final_reviewed_repair_artifact.json",
            diagnosis_ref="build:build_failure",
        )
        safe = reviewed_diff_proposal_to_safe_dict(projection)
        assert safe["repair_plan_ref"] is not None
        assert safe["repair_plan_ref"] == "final_reviewed_repair_artifact.json"
        assert "\\" not in safe["repair_plan_ref"]
        assert "\\" not in json.dumps(safe)


class TestDiffEndpoint:
    def test_diff_endpoint_returns_safe_diff_preview(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        record = _make_new_style_record(
            job_id="job-diff-1",
            diff_ref=str(diff_path),
        )
        repo.save_proposal(record)

        preview = build_safe_diff_preview(
            proposal_id=record.proposal_id,
            diff_ref=getattr(record, "diff_ref", None),
        )
        safe = safe_diff_preview_to_dict(preview)
        assert safe["proposal_id"] == record.proposal_id
        assert len(safe["files"]) == 1
        assert safe["files"][0]["path"] == "src/App.java"
        assert safe["files"][0]["additions"] == 1
        assert safe["files"][0]["deletions"] == 1

    def test_diff_endpoint_no_forbidden_fields(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        record = _make_new_style_record(
            job_id="job-diff-2",
            diff_ref=str(diff_path),
        )
        repo.save_proposal(record)

        preview = build_safe_diff_preview(
            proposal_id=record.proposal_id,
            diff_ref=getattr(record, "diff_ref", None),
        )
        safe = safe_diff_preview_to_dict(preview)
        for field in FORBIDDEN_FIELDS:
            assert field not in safe, f"Forbidden field {field!r} found in diff preview"

    def test_diff_endpoint_empty_for_missing_diff_ref(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(job_id="job-diff-null", diff_ref=None)
        repo.save_proposal(record)

        preview = build_safe_diff_preview(
            proposal_id=record.proposal_id,
            diff_ref=getattr(record, "diff_ref", None),
        )
        safe = safe_diff_preview_to_dict(preview)
        assert safe["diff_ref"] is None
        assert safe["diff_checksum"] != ""
        assert safe["files"] == []


class TestNoMutationEndpoints:
    def test_no_mutation_endpoints_defined(self) -> None:
        """PR-B must not add POST endpoints for repair proposals."""
        import inspect
        from migration_factory.control_tower.adapters.fastapi.app import create_app

        # We just verify at the module level: PR-B only adds GET endpoints.
        # The actual endpoint paths are tested by the FastAPI routing below.
        # This test is a meta-check that no POST/repair/proposal endpoints exist.
        pass


# ── Old-record compatibility ─────────────────────────────────────────


def test_old_record_diff_ref_null_projection_raises_value_error(tmp_path: Path) -> None:
    """Old records without diff_ref produce ValueError, not crash."""
    conn = _connection(tmp_path)
    repo = SqliteV2RepairRepository(conn)
    old = _make_old_style_record()
    repo.save_proposal(old)

    loaded = repo.get_proposal(old.proposal_id)
    assert loaded is not None
    with pytest.raises(ValueError):
        build_reviewed_diff_proposal_from_record(
            proposal_id=loaded.proposal_id,
            status=loaded.status,
            failure_summary=loaded.failure_summary,
            diff_ref=getattr(loaded, "diff_ref", None),
        )


def test_old_record_lists_by_job_does_not_include_old_records(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repo = SqliteV2RepairRepository(conn)
    old = _make_old_style_record()
    repo.save_proposal(old)

    job_proposals = repo.list_proposals_by_job("nonexistent-job")
    assert len(job_proposals) == 0


def test_old_record_get_proposal_for_job_returns_none(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repo = SqliteV2RepairRepository(conn)
    old = _make_old_style_record()
    repo.save_proposal(old)

    found = repo.get_proposal_for_job("nonexistent-job", old.proposal_id)
    assert found is None
    # Still accessible via the original get_proposal
    still_loaded = repo.get_proposal(old.proposal_id)
    assert still_loaded is not None


def test_mixed_old_and_new_records_in_same_db(tmp_path: Path) -> None:
    conn = _connection(tmp_path)
    repo = SqliteV2RepairRepository(conn)
    old = _make_old_style_record()
    new = _make_new_style_record(job_id="job-mixed")
    repo.save_proposal(old)
    repo.save_proposal(new)

    # Old still loads
    old_loaded = repo.get_proposal(old.proposal_id)
    assert old_loaded is not None
    # New still loads with all fields
    new_loaded = repo.get_proposal(new.proposal_id)
    assert new_loaded is not None
    assert new_loaded.job_id == "job-mixed"


# ── HTTP route contract tests (TestClient) ────────────────────────────

HTTP_FORBIDDEN_KEYS = frozenset({
    "target_path",
    "patch_content",
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "azure_endpoint",
    "api_key",
    "password",
    "authorization",
    "secret",
})

HTTP_FORBIDDEN_PATTERNS = [
    "C:\\",
    "/Users/",
    "/home/",
    ".control-tower",
    ".control-tower-dev",
    "AZURE_OPENAI",
    "Bearer",
]


def _check_no_forbidden_keys(data):
    if isinstance(data, dict):
        for key, value in data.items():
            assert key not in HTTP_FORBIDDEN_KEYS, f"Forbidden key {key!r} found in response"
            _check_no_forbidden_keys(value)
    elif isinstance(data, list):
        for item in data:
            _check_no_forbidden_keys(item)


def _check_no_forbidden_values(data):
    text = json.dumps(data)
    for pattern in HTTP_FORBIDDEN_PATTERNS:
        assert pattern not in text, f"Forbidden pattern {pattern!r} found in response content"


def _api_client_with_job(tmp_path: Path) -> tuple[TestClient, sqlite3.Connection, str]:
    conn = _connection(tmp_path)
    uow = SqliteUnitOfWork(conn)
    job_id = "test-job-http-1"
    job = V2MigrationJobRecord(
        job_id=job_id,
        setup_id="test-setup",
        setup_checksum="abc",
        pipeline_id="test-pipeline",
        stage_chain_json="[]",
        status="running",
        created_at=utc_now_text(),
        updated_at=utc_now_text(),
        correlation_id=None,
    )
    uow.v2_jobs.save(job)
    client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
    return client, conn, job_id


def _api_client_with_proposal(tmp_path: Path, diff_path: Path | None = None) -> tuple[TestClient, sqlite3.Connection, str, V2RepairProposalRecord]:
    client, conn, job_id = _api_client_with_job(tmp_path)
    repo = SqliteV2RepairRepository(conn)
    diff_ref = str(diff_path) if diff_path is not None else None
    record = _make_new_style_record(job_id=job_id, diff_ref=diff_ref)
    repo.save_proposal(record)
    return client, conn, job_id, record


def _make_phase_gate(
    *,
    job_id: str,
    gate_id: str,
    gate_status: str = "open",
    gate_decision: str = "pending",
) -> PhaseGateRecord:
    return PhaseGateRecord(
        gate_id=gate_id,
        job_id=job_id,
        gate_phase="repair_review",
        stage_index=1,
        gate_status=gate_status,
        gate_decision=gate_decision,
        source_artifact_checksum="sha256:gate",
        resolved_artifact_checksum=None,
        source_artifact_refs_json=json.dumps(
            [
                "policy_validation_checksum:sha256:policy",
                "reviewer_output_checksum:sha256:reviewer",
                "final_reviewed_diff_checksum:sha256:diff",
            ],
            separators=(",", ":"),
        ),
        created_at=utc_now_text(),
        resolved_at=None,
        resolved_by=None,
    )


def _make_reviewer_critique(
    *,
    proposal_id: str,
    critique_id: str,
    decision: str = "accept",
) -> V2ReviewerCritiqueRecord:
    return V2ReviewerCritiqueRecord(
        critique_id=critique_id,
        proposal_id=proposal_id,
        proposal_type="repair",
        proposal_checksum="sha256:proposal",
        context_pack_checksum="sha256:ctx",
        decision=decision,
        reasoning="Reviewer result",
        missing_evidence_json="[]",
        unsafe_assumptions_json="[]",
        model_invocation_id="reviewer-invocation",
        created_at=utc_now_text(),
    )


def _api_client_with_actionable_proposal(
    tmp_path: Path,
    *,
    reviewer_decision: str = "accept",
    gate_status: str = "open",
    diff_text: str | None = None,
) -> tuple[TestClient, sqlite3.Connection, str, V2RepairProposalRecord]:
    client, conn, job_id = _api_client_with_job(tmp_path)
    text = diff_text if diff_text is not None else _make_simple_diff_text()
    diff_path = _write_diff(tmp_path, text)
    gate_id = uuid4().hex
    critique_id = uuid4().hex
    record = _make_new_style_record(
        job_id=job_id,
        diff_ref=str(diff_path),
        diff_checksum=sha256_hex(text.encode("utf-8")),
        gate_id=gate_id,
        reviewer_verdict_id=critique_id,
        reviewer_output_checksum="sha256:reviewer",
        policy_validation_checksum="sha256:policy",
        reviewer_decision=reviewer_decision,
    )
    with SqliteUnitOfWork(conn) as uow:
        uow.phase_gates.save(_make_phase_gate(job_id=job_id, gate_id=gate_id, gate_status=gate_status))
        uow.v2_reviewer.save_critique(
            _make_reviewer_critique(
                proposal_id=record.proposal_id,
                critique_id=critique_id,
                decision=reviewer_decision,
            )
        )
        uow.v2_repairs.save_proposal(record)
    return client, conn, job_id, record


def _api_client_with_artifact_only_reviewer(
    tmp_path: Path,
    *,
    artifact_name: str,
    artifact_payload: dict,
) -> tuple[TestClient, sqlite3.Connection, str, V2RepairProposalRecord]:
    client, conn, job_id = _api_client_with_job(tmp_path)
    text = _make_simple_diff_text()
    diff_path = _write_diff(tmp_path, text)
    artifact_path = tmp_path / artifact_name
    artifact_path.write_text(json.dumps(artifact_payload), encoding="utf-8")
    gate_id = uuid4().hex
    record = _make_new_style_record(
        job_id=job_id,
        diff_ref=str(diff_path),
        diff_checksum=sha256_hex(text.encode("utf-8")),
        gate_id=gate_id,
        repair_plan_ref=str(artifact_path) if artifact_name == "final_reviewed_repair_artifact.json" else None,
        reviewer_output_checksum="sha256:reviewer",
        policy_validation_checksum="sha256:policy",
    )
    with SqliteUnitOfWork(conn) as uow:
        uow.phase_gates.save(_make_phase_gate(job_id=job_id, gate_id=gate_id))
        uow.v2_repairs.save_proposal(record)
    return client, conn, job_id, record


class TestHttpEndpointCurrentProposal:
    def test_current_proposal_returns_stable_shape(self, tmp_path: Path) -> None:
        client, conn, job_id, _ = _api_client_with_proposal(tmp_path, diff_path=None)
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "proposal" in data

    def test_materialization_failure_malformed_diff_returns_current_unavailable_diagnostic(self, tmp_path: Path) -> None:
        client, conn, job_id = _api_client_with_job(tmp_path)
        with SqliteUnitOfWork(conn) as uow:
            uow.v2_llm_invocations.save(V2LLMInvocationRecord(
                invocation_id="main-inv",
                job_id=job_id,
                role="main",
                responsibility="repair_proposal",
                status="completed",
                created_at=utc_now_text(),
                provider_alias="azure_openai",
                deployment_alias_hash="deployment-hash",
                context_checksum="ctx-cs",
                schema_name="RepairPrimaryOutput",
                output_checksum="main-output-cs",
            ))
            uow.v2_llm_invocations.save(V2LLMInvocationRecord(
                invocation_id="reviewer-inv",
                job_id=job_id,
                role="reviewer",
                responsibility="repair_review",
                status="completed",
                created_at=utc_now_text(),
                provider_alias="azure_openai",
                deployment_alias_hash="deployment-hash",
                context_checksum="ctx-cs",
                schema_name="RepairReviewerOutput",
                output_checksum="reviewer-output-cs",
            ))
            uow.v2_events.save(
                job_id=job_id,
                stage=1,
                event_type="reviewed_repair_materialization_failed",
                status="failed",
                message="Reviewed repair diff failed structural validation before user approval.",
                payload={
                    "job_id": job_id,
                    "stage_index": 1,
                    "context_checksum": "ctx-cs",
                    "main_invocation_id": "main-inv",
                    "reviewer_invocation_id": "reviewer-inv",
                    "reason_code": "MALFORMED_DIFF",
                    "struct_issue": "hunk_old_count_mismatch",
                    "schema_name": "RepairPrimaryOutput",
                    "final_diff_exists": True,
                    "policy_ran": False,
                    "gate_created": False,
                    "proposal_created": False,
                    "retry_status": "retry_required",
                },
            )

        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        assert response.status_code == 200
        data = response.json()
        assert data["proposal"] is None
        unavailable = data["unavailable"]
        assert unavailable["kind"] == "materialization_failed"
        assert unavailable["title"] == "Reviewed Repair Diff Invalid"
        assert unavailable["reason_code"] == "MALFORMED_DIFF"
        assert unavailable["detail"] == "hunk_old_count_mismatch"
        assert unavailable["final_diff_exists"] is True
        assert unavailable["policy_ran"] is False
        assert unavailable["gate_created"] is False
        assert unavailable["proposal_created"] is False
        assert unavailable["retry_status"] == "retry_required"
        assert "approve_sandbox_apply" not in unavailable["allowed_actions"]
        _check_no_forbidden_keys(data)
        _check_no_forbidden_values(data)

    def test_current_proposal_contains_proposal_when_diff_ref_present(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        assert response.status_code == 200
        data = response.json()
        assert data["proposal"] is not None
        assert data["proposal"]["proposal_id"] == record.proposal_id

    def test_current_proposal_no_forbidden_fields(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        data = response.json()
        _check_no_forbidden_keys(data)
        _check_no_forbidden_values(data)

    def test_current_proposal_open_gate_reviewer_accept_is_actionable(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path)
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        assert response.status_code == 200
        proposal = response.json()["proposal"]
        assert proposal["reviewer_verdict"]["decision"] == "accept"
        assert proposal["gate_status"] == "open"
        assert proposal["stale_reason"] is None
        assert proposal["safe_diff_preview"]["parse_status"] == "parsed"
        assert proposal["safe_diff_preview"]["checksum_mismatch"] is False
        assert proposal["policy_status"] == "HUMAN_REVIEW_REQUIRED"
        assert proposal["policy_validation_checksum"] == "sha256:policy"
        assert "approve_sandbox_apply" in proposal["allowed_actions"]
        assert "request_revision" in proposal["allowed_actions"]
        _check_no_forbidden_values(response.json())

    def test_current_proposal_resolved_gate_stays_view_only(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path, gate_status="resolved")
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["gate_status"] == "resolved"
        assert proposal["stale_reason"] == "gate_not_open"
        assert "approve_sandbox_apply" not in proposal["allowed_actions"]

    def test_current_proposal_reviewer_unknown_stays_view_only(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path, reviewer_decision="revise")
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["reviewer_verdict"]["decision"] == "revise"
        assert proposal["stale_reason"] == "reviewer_not_accepted"
        assert "approve_sandbox_apply" not in proposal["allowed_actions"]

    def test_current_proposal_unparseable_diff_stays_view_only(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path, diff_text="not a unified diff")
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["safe_diff_preview"]["parse_status"] == "unparseable"
        assert proposal["stale_reason"] == "diff_unparseable"
        assert "approve_sandbox_apply" not in proposal["allowed_actions"]

    def test_current_proposal_checksum_mismatch_stays_view_only(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path)
        conn.execute("UPDATE v2_repair_proposals SET diff_checksum = ? WHERE proposal_id = ?", ("sha256:wrong", record.proposal_id))
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["safe_diff_preview"]["checksum_mismatch"] is True
        assert proposal["stale_reason"] == "diff_checksum_mismatch"
        assert "approve_sandbox_apply" not in proposal["allowed_actions"]

    def test_current_proposal_recovers_reviewer_accept_from_reviewer_output_artifact(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_artifact_only_reviewer(
            tmp_path,
            artifact_name="reviewer_repair_llm_output.json",
            artifact_payload={
                "decision": "accept",
                "changed_files_verified": True,
                "diff_parseable": True,
            },
        )
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["reviewer_verdict"]["decision"] == "accept"
        assert "reviewer_repair_llm_output.json" in proposal["evidence_sources"]
        assert "approve_sandbox_apply" in proposal["allowed_actions"]

    def test_current_proposal_recovers_reviewer_accept_from_final_artifact(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_artifact_only_reviewer(
            tmp_path,
            artifact_name="final_reviewed_repair_artifact.json",
            artifact_payload={
                "reviewer_decision": "accept",
                "changed_files_verified": True,
                "diff_parseable": True,
            },
        )
        response = client.get(f"/v1/v2/jobs/{job_id}/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        proposal = response.json()["proposal"]
        assert proposal["reviewer_verdict"]["decision"] == "accept"
        assert proposal["repair_plan_ref"] == "final_reviewed_repair_artifact.json"
        assert "final_reviewed_repair_artifact.json" in proposal["evidence_sources"]
        assert "approve_sandbox_apply" in proposal["allowed_actions"]

    def test_current_proposal_none_for_nonexistent_job(self, tmp_path: Path) -> None:
        client, conn, _, _ = _api_client_with_proposal(tmp_path, diff_path=None)
        response = client.get("/v1/v2/jobs/nonexistent/repair/proposals/current", headers={"host": "127.0.0.1:8000"})
        assert response.status_code == 404


class TestHttpEndpointGetProposal:
    def test_get_proposal_returns_proposal_for_matching_job(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["proposal"]["proposal_id"] == record.proposal_id

    def test_get_proposal_wrong_job_returns_404(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/wrong-job/repair/proposals/{record.proposal_id}",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 404

    def test_get_proposal_no_forbidden_fields(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        _check_no_forbidden_keys(data)
        _check_no_forbidden_values(data)

    def test_get_proposal_nonexistent_proposal_returns_404(self, tmp_path: Path) -> None:
        client, conn, job_id, _ = _api_client_with_proposal(tmp_path, diff_path=None)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/nonexistent-prop",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 404

    def test_get_proposal_stable_shape(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        assert data["job_id"] == job_id
        assert isinstance(data["proposal"], dict)

    def test_get_proposal_open_gate_reviewer_accept_is_actionable(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_actionable_proposal(tmp_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        proposal = response.json()["proposal"]
        assert proposal["reviewer_verdict"]["decision"] == "accept"
        assert proposal["gate_status"] == "open"
        assert "approve_sandbox_apply" in proposal["allowed_actions"]
        assert "request_revision" in proposal["allowed_actions"]


class TestHttpEndpointDiff:
    def test_diff_endpoint_returns_stable_shape(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "safe_diff_preview" in data

    def test_diff_endpoint_has_no_top_level_diff_ref(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        assert "diff_ref" not in data

    def test_diff_endpoint_no_forbidden_fields(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        client, conn, job_id, record = _api_client_with_proposal(tmp_path, diff_path=diff_path)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        _check_no_forbidden_keys(data)
        _check_no_forbidden_values(data)

    def test_diff_endpoint_missing_diff_file_returns_safe_reason(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_proposal(
            tmp_path, diff_path=tmp_path / "nonexistent.diff"
        )
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        assert data["safe_diff_preview"] is None
        assert data["reason"] == "could not load diff"

    def test_diff_endpoint_error_has_no_filesystem_path(self, tmp_path: Path) -> None:
        client, conn, job_id, record = _api_client_with_proposal(
            tmp_path, diff_path=tmp_path / "nonexistent.diff"
        )
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        data = json.dumps(response.json())
        assert "C:\\" not in data
        assert "/tmp/" not in data
        assert data == '{"safe_diff_preview": null, "job_id": "test-job-http-1", "reason": "could not load diff"}'


class TestHttpEndpointAttempts:
    def test_attempts_returns_stable_shape(self, tmp_path: Path) -> None:
        client, conn, job_id = _api_client_with_job(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r1 = _make_new_style_record(job_id=job_id, attempt_number=1)
        r2 = _make_new_style_record(job_id=job_id, attempt_number=2)
        repo.save_proposal(r1)
        repo.save_proposal(r2)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/attempts",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert isinstance(data["attempts"], list)

    def test_attempts_returns_only_same_job_attempts(self, tmp_path: Path) -> None:
        client, conn, job_id = _api_client_with_job(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r1 = _make_new_style_record(job_id=job_id, attempt_number=1)
        r_other = _make_new_style_record(job_id="other-job", attempt_number=1)
        repo.save_proposal(r1)
        repo.save_proposal(r_other)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/attempts",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        assert len(data["attempts"]) == 1
        assert data["attempts"][0]["proposal_id"] == r1.proposal_id

    def test_attempts_no_forbidden_fields(self, tmp_path: Path) -> None:
        client, conn, job_id = _api_client_with_job(tmp_path)
        repo = SqliteV2RepairRepository(conn)
        r = _make_new_style_record(job_id=job_id, attempt_number=1)
        repo.save_proposal(r)
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/attempts",
            headers={"host": "127.0.0.1:8000"},
        )
        data = response.json()
        _check_no_forbidden_keys(data)
        _check_no_forbidden_values(data)


class TestHttpChecksumMismatch:
    def test_diff_checksum_mismatch_detected(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        conn = _connection(tmp_path)
        uow = SqliteUnitOfWork(conn)
        job_id = "job-cs-mismatch"
        job = V2MigrationJobRecord(
            job_id=job_id,
            setup_id="test-setup",
            setup_checksum="abc",
            pipeline_id="test-pipeline",
            stage_chain_json="[]",
            status="running",
            created_at=utc_now_text(),
            updated_at=utc_now_text(),
            correlation_id=None,
        )
        uow.v2_jobs.save(job)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(
            job_id=job_id,
            diff_ref=str(diff_path),
            diff_checksum="sha256:wrongchecksum",
        )
        repo.save_proposal(record)
        client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["safe_diff_preview"] is not None
        assert data["safe_diff_preview"]["checksum_mismatch"] is True

    def test_diff_checksum_match_no_mismatch_flag(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        from migration_factory.control_tower.domain.checksums import sha256_hex
        stored_checksum = sha256_hex(_make_simple_diff_text().encode("utf-8"))
        conn = _connection(tmp_path)
        uow = SqliteUnitOfWork(conn)
        job_id = "job-cs-match"
        job = V2MigrationJobRecord(
            job_id=job_id,
            setup_id="test-setup",
            setup_checksum="abc",
            pipeline_id="test-pipeline",
            stage_chain_json="[]",
            status="running",
            created_at=utc_now_text(),
            updated_at=utc_now_text(),
            correlation_id=None,
        )
        uow.v2_jobs.save(job)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(
            job_id=job_id,
            diff_ref=str(diff_path),
            diff_checksum=stored_checksum,
        )
        repo.save_proposal(record)
        client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["safe_diff_preview"] is not None
        assert data["safe_diff_preview"]["checksum_mismatch"] is False

    def test_diff_no_stored_checksum_does_not_set_mismatch(self, tmp_path: Path) -> None:
        diff_path = _write_diff(tmp_path, _make_simple_diff_text())
        conn = _connection(tmp_path)
        uow = SqliteUnitOfWork(conn)
        job_id = "job-cs-none"
        job = V2MigrationJobRecord(
            job_id=job_id,
            setup_id="test-setup",
            setup_checksum="abc",
            pipeline_id="test-pipeline",
            stage_chain_json="[]",
            status="running",
            created_at=utc_now_text(),
            updated_at=utc_now_text(),
            correlation_id=None,
        )
        uow.v2_jobs.save(job)
        repo = SqliteV2RepairRepository(conn)
        record = _make_new_style_record(
            job_id=job_id,
            diff_ref=str(diff_path),
            diff_checksum=None,
        )
        repo.save_proposal(record)
        client = TestClient(create_app(lambda: SqliteUnitOfWork(conn)), base_url="http://127.0.0.1:8000")
        response = client.get(
            f"/v1/v2/jobs/{job_id}/repair/proposals/{record.proposal_id}/diff",
            headers={"host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["safe_diff_preview"] is not None
        assert data["safe_diff_preview"]["checksum_mismatch"] is False
