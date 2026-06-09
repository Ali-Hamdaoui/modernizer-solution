from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from migration_factory.control_tower.infrastructure.sqlite.connection import (
    UnsupportedJournalModeError,
    configure_control_tower_journal_mode,
    connect_control_tower,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    AppliedMigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationExecutionError,
    MigrationSafetyError,
    apply_pending_migrations,
    discover_migrations,
    split_sql_statements,
)


def test_foreign_keys_enabled_on_every_connection(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        value = connection.execute("PRAGMA foreign_keys").fetchone()[0]
        assert value == 1
    finally:
        connection.close()


def test_busy_timeout_is_configured(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        value = connection.execute("PRAGMA busy_timeout").fetchone()[0]
        assert value == 5000
    finally:
        connection.close()


def test_default_journal_mode_is_delete(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        value = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).upper()
        assert value == "DELETE"
    finally:
        connection.close()


def test_unsupported_journal_mode_is_rejected(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        with pytest.raises(UnsupportedJournalModeError):
            configure_control_tower_journal_mode(connection, journal_mode="MEMORY")
    finally:
        connection.close()


def test_migrations_are_discovered_and_ordered_correctly(tmp_path: Path) -> None:
    _write_sql(tmp_path, "0001_first.sql", "CREATE TABLE first_table (id INTEGER PRIMARY KEY);")
    _write_sql(tmp_path, "0002_second.sql", "CREATE TABLE second_table (id INTEGER PRIMARY KEY);")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2]
    assert [migration.name for migration in migrations] == ["first", "second"]


def test_duplicate_migration_versions_are_rejected(tmp_path: Path) -> None:
    _write_sql(tmp_path, "0001_first.sql", "CREATE TABLE first_table (id INTEGER PRIMARY KEY);")
    _write_sql(tmp_path, "0001_second.sql", "CREATE TABLE second_table (id INTEGER PRIMARY KEY);")

    with pytest.raises(MigrationDiscoveryError, match="Duplicate migration version"):
        discover_migrations(tmp_path)


def test_changed_checksum_for_applied_migration_is_rejected(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(migrations_dir, "0001_first.sql", "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);")
    _write_sql(migrations_dir, "0002_second.sql", "CREATE TABLE example_table (id INTEGER PRIMARY KEY);")

    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        apply_pending_migrations(connection, migrations_dir=migrations_dir)
        _write_sql(migrations_dir, "0002_second.sql", "CREATE TABLE example_table (id INTEGER PRIMARY KEY, name TEXT NOT NULL);")

        with pytest.raises(AppliedMigrationChecksumMismatchError):
            apply_pending_migrations(connection, migrations_dir=migrations_dir)
    finally:
        connection.close()


def test_migration_execution_does_not_use_executescript() -> None:
    import migration_factory.control_tower.infrastructure.sqlite.migrations as migrations_module

    assert "executescript" not in migrations_module.__file__
    source = Path(migrations_module.__file__).read_text(encoding="utf-8")
    assert "executescript" not in source


def test_each_migration_uses_begin_immediate(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    trace: list[str] = []
    connection.set_trace_callback(trace.append)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(migrations_dir, "0001_schema_migrations.sql", "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);")
    _write_sql(migrations_dir, "0002_demo.sql", "CREATE TABLE demo_table (id INTEGER PRIMARY KEY);")
    try:
        apply_pending_migrations(connection, migrations_dir=migrations_dir)
    finally:
        connection.close()

    assert sum(1 for statement in trace if statement == "BEGIN IMMEDIATE") == 2


def test_schema_changes_and_schema_history_insertion_are_atomic(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(migrations_dir, "0001_schema_migrations.sql", "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);")
    _write_sql(
        migrations_dir,
        "0002_fail.sql",
        """
        CREATE TABLE atomic_table (id INTEGER PRIMARY KEY);
        CREATE UNIQUE INDEX ux_atomic_duplicate ON atomic_table (missing_column);
        """,
    )
    try:
        with pytest.raises(MigrationExecutionError):
            apply_pending_migrations(connection, migrations_dir=migrations_dir)

        table_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'atomic_table'"
        ).fetchone()
        history = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()

        assert table_exists is None
        assert [row[0] for row in history] == [1]
    finally:
        connection.close()


def test_failed_migration_rolls_back_completely(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(migrations_dir, "0001_schema_migrations.sql", "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);")
    _write_sql(
        migrations_dir,
        "0002_fail.sql",
        """
        CREATE TABLE rollback_table (id INTEGER PRIMARY KEY);
        INSERT INTO missing_table (id) VALUES (1);
        """,
    )
    try:
        with pytest.raises(MigrationExecutionError):
            apply_pending_migrations(connection, migrations_dir=migrations_dir)

        table_exists = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'rollback_table'"
        ).fetchone()
        assert table_exists is None
    finally:
        connection.close()


def test_foreign_key_check_happens_before_commit(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    trace: list[str] = []
    connection.set_trace_callback(trace.append)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(
        migrations_dir,
        "0001_schema_migrations.sql",
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);",
    )
    try:
        apply_pending_migrations(connection, migrations_dir=migrations_dir)
    finally:
        connection.close()

    foreign_key_check_index = trace.index("PRAGMA foreign_key_check")
    commit_index = trace.index("COMMIT")
    assert foreign_key_check_index < commit_index


def test_trigger_bodies_with_internal_semicolons_work(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(
        migrations_dir,
        "0001_schema_migrations.sql",
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);
        CREATE TABLE parent_table (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE child_table (id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL, FOREIGN KEY (parent_id) REFERENCES parent_table (id));
        CREATE TRIGGER child_table_touch
        AFTER INSERT ON parent_table
        BEGIN
            INSERT INTO child_table (id, parent_id) VALUES (NEW.id, NEW.id);
            INSERT INTO child_table (id, parent_id) VALUES (NEW.id + 100, NEW.id);
        END;
        """,
    )
    try:
        apply_pending_migrations(connection, migrations_dir=migrations_dir)
        connection.execute("INSERT INTO parent_table (id, value) VALUES (1, 'ok')")
        child_rows = connection.execute(
            "SELECT COUNT(*) FROM child_table WHERE parent_id = 1"
        ).fetchone()[0]
        assert child_rows == 2
    finally:
        connection.close()


def test_quoted_semicolons_work() -> None:
    statements = split_sql_statements(
        """
        CREATE TABLE quoted_values (
            id INTEGER PRIMARY KEY,
            value TEXT NOT NULL DEFAULT ';quoted;value;'
        );
        INSERT INTO quoted_values (id, value) VALUES (1, 'a;b;c');
        """
    )

    assert len(statements) == 2


def test_transaction_statements_are_rejected(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(
        migrations_dir,
        "0001_begin.sql",
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);
        BEGIN;
        """,
    )
    try:
        with pytest.raises(MigrationExecutionError, match="forbidden transaction-control"):
            apply_pending_migrations(connection, migrations_dir=migrations_dir)
    finally:
        connection.close()


def test_dangerous_pragmas_are_rejected(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    _write_sql(
        migrations_dir,
        "0001_schema_migrations.sql",
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum_sha256 TEXT NOT NULL, applied_utc TEXT NOT NULL);",
    )
    _write_sql(
        migrations_dir,
        "0002_bad_pragma.sql",
        "PRAGMA foreign_keys = OFF;",
    )
    try:
        with pytest.raises(MigrationExecutionError, match="forbidden PRAGMA"):
            apply_pending_migrations(connection, migrations_dir=migrations_dir)
    finally:
        connection.close()


def test_all_m1_tables_exist_after_foundation_migration(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        apply_pending_migrations(connection)
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {
        "schema_migrations",
        "runner_profiles",
        "pipeline_definitions",
        "migration_jobs",
        "run_configurations",
        "stage_runs",
        "run_events",
        "artifacts",
        "audit_records",
    }.issubset(actual_tables)


def test_audit_records_update_delete_is_blocked_by_triggers(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        apply_pending_migrations(connection)
        _seed_foundation_references(connection)
        connection.execute(
            """
            INSERT INTO audit_records (
                audit_record_id, job_id, stage_run_id, entity_type, entity_id, action,
                payload_json, recorded_utc, actor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "audit-1",
                "job-1",
                "stage-1",
                "migration_job",
                "job-1",
                "CREATED",
                "{}",
                "2026-01-01T00:00:00Z",
                "tester",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE audit_records SET actor = ? WHERE audit_record_id = ?",
                ("other", "audit-1"),
            )

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM audit_records WHERE audit_record_id = ?",
                ("audit-1",),
            )
    finally:
        connection.close()


def test_one_active_job_index_and_active_slot_check_exist_and_work(tmp_path: Path) -> None:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    try:
        apply_pending_migrations(connection)
        connection.execute(
            """
            INSERT INTO runner_profiles (profile_id, display_name, config_json, created_utc, updated_utc)
            VALUES ('profile-1', 'Profile', '{}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO pipeline_definitions (pipeline_id, pipeline_name, pipeline_version, description, created_utc, updated_utc)
            VALUES ('pipeline-1', 'Pipeline', '1.0', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO migration_jobs (
                job_id, pipeline_id, runner_profile_id, requested_by, state, active_slot,
                created_utc, updated_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-1",
                "pipeline-1",
                "profile-1",
                "tester",
                "RUNNING",
                1,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
            ),
        )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO migration_jobs (
                    job_id, pipeline_id, runner_profile_id, requested_by, state, active_slot,
                    created_utc, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-2",
                    "pipeline-1",
                    "profile-1",
                    "tester",
                    "QUEUED",
                    1,
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO migration_jobs (
                    job_id, pipeline_id, runner_profile_id, requested_by, state, active_slot,
                    created_utc, updated_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-3",
                    "pipeline-1",
                    "profile-1",
                    "tester",
                    "COMPLETED",
                    1,
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:00Z",
                ),
            )

        connection.execute(
            """
            INSERT INTO migration_jobs (
                job_id, pipeline_id, runner_profile_id, requested_by, state, active_slot,
                created_utc, updated_utc, finished_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-4",
                "pipeline-1",
                "profile-1",
                "tester",
                "COMPLETED",
                0,
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
            ),
        )
    finally:
        connection.close()


def _seed_foundation_references(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO runner_profiles (profile_id, display_name, config_json, created_utc, updated_utc)
        VALUES ('profile-1', 'Profile', '{}', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO pipeline_definitions (pipeline_id, pipeline_name, pipeline_version, description, created_utc, updated_utc)
        VALUES ('pipeline-1', 'Pipeline', '1.0', '', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO migration_jobs (
            job_id, pipeline_id, runner_profile_id, requested_by, state, active_slot,
            created_utc, updated_utc
        ) VALUES ('job-1', 'pipeline-1', 'profile-1', 'tester', 'RUNNING', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
        """
    )
    connection.execute(
        """
        INSERT INTO stage_runs (
            stage_run_id, job_id, stage_name, state, ordinal, started_utc, details_json
        ) VALUES ('stage-1', 'job-1', 'analysis', 'RUNNING', 1, '2026-01-01T00:00:00Z', '{}')
        """
    )


def _write_sql(directory: Path, name: str, sql: str) -> Path:
    path = directory / name
    path.write_text(sql.strip() + "\n", encoding="utf-8")
    return path
