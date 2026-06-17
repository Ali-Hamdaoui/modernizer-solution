"""Focused tests for F15 job013 — v2_artifact_revisions SQLite migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)


def _connection(tmp_path: Path, name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(tmp_path / name),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


def test_migration_creates_table(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_artifact_revisions'"
    ).fetchone()
    assert row is not None


def test_insert_draft_revision(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-001", "job-abc", 1, "analysis", "draft", 0,
         "sha256:abc", '["a1"]', "2026-06-17T12:00:00Z", "system"),
    )
    row = conn.execute(
        "SELECT * FROM v2_artifact_revisions WHERE revision_id = 'rev-001'"
    ).fetchone()
    assert row["revision_kind"] == "analysis"
    assert row["revision_status"] == "draft"


def test_stage_index_constraint(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO v2_artifact_revisions
                (revision_id, job_id, stage_index, revision_kind, revision_status,
                 revision_order, evidence_checksum, artifact_refs_json, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("rev-bad", "job-abc", 0, "analysis", "draft", 0,
             "sha256:abc", "[]", "2026-06-17T12:00:00Z", "system"),
        )


def test_accepted_revision_uniqueness(tmp_path: Path) -> None:
    """At most one ACCEPTED revision per (job_id, stage_index, revision_kind)."""
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by,
             accepted_at, accepted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-a1", "job-abc", 1, "analysis", "accepted", 0,
         "sha256:abc", '["a1"]', "2026-06-17T12:00:00Z", "system",
         "2026-06-17T13:00:00Z", "user-1"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO v2_artifact_revisions
                (revision_id, job_id, stage_index, revision_kind, revision_status,
                 revision_order, evidence_checksum, artifact_refs_json, created_at, created_by,
                 accepted_at, accepted_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("rev-a2", "job-abc", 1, "analysis", "accepted", 1,
             "sha256:xyz", '["a2"]', "2026-06-17T14:00:00Z", "system",
             "2026-06-17T15:00:00Z", "user-2"),
        )


def test_different_kind_accepted_allowed(tmp_path: Path) -> None:
    """Different revision_kind can each have an accepted revision."""
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by,
             accepted_at, accepted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-a", "job-abc", 1, "analysis", "accepted", 0,
         "sha256:abc", "[]", "2026-06-17T12:00:00Z", "system",
         "2026-06-17T13:00:00Z", "user-1"),
    )
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by,
             accepted_at, accepted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-p", "job-abc", 1, "planning", "accepted", 0,
         "sha256:def", "[]", "2026-06-17T12:00:00Z", "system",
         "2026-06-17T13:00:00Z", "user-1"),
    )


def test_lineage_fields(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, prior_revision_checksum,
             artifact_refs_json, prior_revision_id, superseded_by_revision_id,
             created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-v1", "job-abc", 1, "analysis", "superseded", 0,
         "sha256:v1", None, "[]", None, "rev-v2",
         "2026-06-17T12:00:00Z", "system"),
    )
    row = conn.execute(
        "SELECT prior_revision_id, superseded_by_revision_id FROM v2_artifact_revisions WHERE revision_id = 'rev-v1'"
    ).fetchone()
    assert row["prior_revision_id"] is None
    assert row["superseded_by_revision_id"] == "rev-v2"


def test_update_blocked(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-u1", "job-abc", 1, "analysis", "draft", 0,
         "sha256:abc", "[]", "2026-06-17T12:00:00Z", "system"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE v2_artifact_revisions SET revision_status = 'accepted' WHERE revision_id = 'rev-u1'"
        )


def test_delete_blocked(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-d1", "job-abc", 1, "analysis", "draft", 0,
         "sha256:abc", "[]", "2026-06-17T12:00:00Z", "system"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM v2_artifact_revisions WHERE revision_id = 'rev-d1'")


def test_accepted_at_gate_id_nullable(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_rev.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_artifact_revisions
            (revision_id, job_id, stage_index, revision_kind, revision_status,
             revision_order, evidence_checksum, artifact_refs_json, created_at, created_by,
             accepted_at_gate_id, accepted_at, accepted_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("rev-g1", "job-abc", 1, "analysis", "accepted", 0,
         "sha256:abc", "[]", "2026-06-17T12:00:00Z", "system",
         "gate-001", "2026-06-17T13:00:00Z", "user-1"),
    )
    row = conn.execute("SELECT accepted_at_gate_id FROM v2_artifact_revisions WHERE revision_id = 'rev-g1'").fetchone()
    assert row["accepted_at_gate_id"] == "gate-001"
