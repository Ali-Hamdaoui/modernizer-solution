from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from migration_factory.control_tower.application.commands import CreateMigrationJobCommand
from migration_factory.control_tower.application.services import CreateMigrationJobService
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteControlTowerUnitOfWork
from migration_factory.control_tower.schemas.run_configuration import RunPolicy

from ._helpers import make_migrated_connection, seed_runner_and_pipeline


def test_job_created_event_sequence_is_one(tmp_path: Path) -> None:
    db_path = tmp_path / "control_tower.sqlite3"
    connection = make_migrated_connection(tmp_path)
    seed_runner_and_pipeline(connection)
    connection.close()

    result = _service_for(db_path).execute(_create_command())

    with connect_control_tower(db_path) as verification_connection:
        row = verification_connection.execute(
            """
            SELECT sequence, event_type, actor_type, actor_id
            FROM run_events
            WHERE job_id = ?
            """,
            (result.job_id,),
        ).fetchone()

    assert row is not None
    assert row["sequence"] == 1
    assert row["event_type"] == "job_created"
    assert row["actor_type"] == "user"
    assert row["actor_id"] == "tester"


def test_event_sequence_is_unique_per_job(tmp_path: Path) -> None:
    db_path = tmp_path / "control_tower.sqlite3"
    connection = make_migrated_connection(tmp_path)
    seed_runner_and_pipeline(connection)
    connection.close()

    result = _service_for(db_path).execute(_create_command())

    with connect_control_tower(db_path) as verification_connection:
        with pytest.raises(sqlite3.IntegrityError):
            verification_connection.execute(
                """
                INSERT INTO run_events (
                    event_id, job_id, sequence, event_type, actor_type, actor_id,
                    correlation_id, causation_id, payload_json, payload_checksum, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "duplicate-event",
                    result.job_id,
                    1,
                    "job_created",
                    "user",
                    "tester",
                    None,
                    None,
                    "{}",
                    "checksum",
                    "2026-01-01T00:00:00.000000Z",
                ),
            )


def _service_for(db_path: Path) -> CreateMigrationJobService:
    def factory() -> SqliteControlTowerUnitOfWork:
        return SqliteControlTowerUnitOfWork(connect_control_tower(db_path), close_connection=True)

    return CreateMigrationJobService(factory)


def _create_command() -> CreateMigrationJobCommand:
    return CreateMigrationJobCommand(
        actor="tester",
        legacy_source_ref="C:/legacy/source",
        output_root_ref="C:/workspace/output",
        runner_profile_id="runner-default",
        runner_profile_version="2026.06",
        pipeline_id="pipeline-default",
        pipeline_version="2026.06",
        target_proof_level=TargetProofLevel.BUILD_TEST_VERIFIED,
        enabled_gates=("build", "test"),
        policy=RunPolicy(),
        correlation_id="corr-1",
    )
