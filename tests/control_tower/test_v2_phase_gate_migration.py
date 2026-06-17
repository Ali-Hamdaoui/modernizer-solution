"""Focused tests for F15 job011 — v2_phase_gates SQLite migration."""

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
    conn = _connection(tmp_path, "test_gates.sqlite3")
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_phase_gates'"
    ).fetchone()
    assert row is not None


def test_insert_open_gate(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "gate-001", "job-abc", "analysis_review", 1, "open", "pending",
            "sha256:abc123", '["artifact-1"]', "2026-06-17T12:00:00Z",
        ),
    )

    row = conn.execute("SELECT * FROM v2_phase_gates WHERE gate_id = ?", ("gate-001",)).fetchone()
    assert row is not None
    assert row["gate_id"] == "gate-001"
    assert row["gate_phase"] == "analysis_review"
    assert row["stage_index"] == 1
    assert row["gate_status"] == "open"


def test_stage_index_constraint(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO v2_phase_gates
                (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
                 source_artifact_checksum, source_artifact_refs_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gate-bad", "job-abc", "analysis_review", 0, "open", "pending",
             "", "[]", "2026-06-17T12:00:00Z"),
        )


def test_open_gate_uniqueness(tmp_path: Path) -> None:
    """At most one open gate per (job_id, gate_phase, stage_index)."""
    conn = _connection(tmp_path, "test_gates.sqlite3")

    # First insert succeeds
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-001", "job-abc", "analysis_review", 1, "open", "pending",
         "sha256:abc", '["a1"]', "2026-06-17T12:00:00Z"),
    )

    # Second insert with same (job_id, gate_phase, stage_index, status='open') must fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """
            INSERT INTO v2_phase_gates
                (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
                 source_artifact_checksum, source_artifact_refs_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("gate-002", "job-abc", "analysis_review", 1, "open", "pending",
             "sha256:xyz", '["a2"]', "2026-06-17T13:00:00Z"),
        )


def test_different_phase_open_allowed(tmp_path: Path) -> None:
    """Different gate_phase values can both be open for the same job/stage."""
    conn = _connection(tmp_path, "test_gates.sqlite3")

    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-001", "job-abc", "analysis_review", 1, "open", "pending",
         "", "[]", "2026-06-17T12:00:00Z"),
    )
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-002", "job-abc", "planning_review", 1, "open", "pending",
         "", "[]", "2026-06-17T12:00:00Z"),
    )

    rows = conn.execute(
        "SELECT gate_id FROM v2_phase_gates WHERE job_id = ? AND gate_status = 'open'",
        ("job-abc",),
    ).fetchall()
    assert len(rows) == 2


def test_resolved_gate_allows_new_open(tmp_path: Path) -> None:
    """After a gate is resolved, a new open gate for the same key is allowed."""
    conn = _connection(tmp_path, "test_gates.sqlite3")

    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at,
             resolved_at, resolved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-001", "job-abc", "analysis_review", 1, "resolved", "continue",
         "sha256:abc", '["a1"]', "2026-06-17T12:00:00Z",
         "2026-06-17T13:00:00Z", "user-1"),
    )

    # New open gate for same key succeeds (previous is now resolved)
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-002", "job-abc", "analysis_review", 1, "open", "pending",
         "sha256:xyz", '["a2"]', "2026-06-17T14:00:00Z"),
    )


def test_delete_blocked_by_trigger(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-del", "job-abc", "analysis_review", 1, "open", "pending",
         "", "[]", "2026-06-17T12:00:00Z"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM v2_phase_gates WHERE gate_id = ?", ("gate-del",))


def test_update_resolved_blocked_by_trigger(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at,
             resolved_at, resolved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-res", "job-abc", "analysis_review", 1, "resolved", "continue",
         "sha256:abc", '["a1"]', "2026-06-17T12:00:00Z",
         "2026-06-17T13:00:00Z", "user-1"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE v2_phase_gates SET gate_decision = ? WHERE gate_id = ?",
            ("reject", "gate-res"),
        )


def test_update_open_gate_allowed(tmp_path: Path) -> None:
    """Open gates can be updated (e.g. to resolve them)."""
    conn = _connection(tmp_path, "test_gates.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-open", "job-abc", "analysis_review", 1, "open", "pending",
         "", "[]", "2026-06-17T12:00:00Z"),
    )
    conn.execute(
        """
        UPDATE v2_phase_gates
        SET gate_status = 'resolved', gate_decision = 'continue',
            resolved_at = '2026-06-17T13:00:00Z', resolved_by = 'user-1'
        WHERE gate_id = ?
        """,
        ("gate-open",),
    )
    row = conn.execute("SELECT gate_status FROM v2_phase_gates WHERE gate_id = ?", ("gate-open",)).fetchone()
    assert row["gate_status"] == "resolved"


def test_indexes_exist(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    indexes = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='v2_phase_gates'"
    ).fetchall()
    names = {r["name"] for r in indexes}
    assert "ix_v2_phase_gates_job" in names
    assert "ix_v2_phase_gates_job_stage" in names
    assert "uq_v2_phase_gates_open" in names


def test_superseded_update_blocked(tmp_path: Path) -> None:
    conn = _connection(tmp_path, "test_gates.sqlite3")
    conn.execute(
        """
        INSERT INTO v2_phase_gates
            (gate_id, job_id, gate_phase, stage_index, gate_status, gate_decision,
             source_artifact_checksum, source_artifact_refs_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("gate-sup", "job-abc", "analysis_review", 1, "superseded", "pending",
         "", "[]", "2026-06-17T12:00:00Z"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE v2_phase_gates SET gate_decision = ? WHERE gate_id = ?",
            ("continue", "gate-sup"),
        )
