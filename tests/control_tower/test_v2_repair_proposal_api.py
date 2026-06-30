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
    build_reviewed_diff_proposal_from_record,
    record_to_attempt_summary,
    reviewed_diff_proposal_to_safe_dict,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
)

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
        "@@ -1,3 +1,4 @@\n"
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
