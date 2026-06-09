from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from migration_factory.control_tower.application.commands import (
    CreateMigrationJobCommand,
    RegisterArtifactCommand,
)
from migration_factory.control_tower.application.services import (
    ArtifactRegistryService,
    CreateMigrationJobService,
)
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.artifact_paths import hash_registered_artifact
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteControlTowerUnitOfWork
from migration_factory.control_tower.schemas.run_configuration import RunPolicy

from ._helpers import (
    artifact_roots,
    make_migrated_connection,
    seed_pipeline_definition,
    seed_runner_and_pipeline,
    seed_runner_profile_with_roots,
)


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


def test_artifact_registered_event_sequence_uses_job_counter_not_max_event(tmp_path: Path) -> None:
    db_path, roots, job_id = _job_with_artifact_roots(tmp_path)
    artifact = _write_and_hash(roots, "reports/event.txt", b"event")

    with connect_control_tower(db_path) as connection:
        connection.execute(
            """
            INSERT INTO run_events (
                event_id, job_id, sequence, event_type, actor_type, actor_id,
                correlation_id, causation_id, payload_json, payload_checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "out-of-band-event",
                job_id,
                50,
                "job_created",
                "system",
                "tester",
                None,
                None,
                "{}",
                "checksum",
                "2026-01-01T00:00:00.000000Z",
            ),
        )

    _artifact_service_for(db_path).register_artifact(_artifact_command(job_id, artifact))

    with connect_control_tower(db_path) as verification_connection:
        row = verification_connection.execute(
            """
            SELECT sequence, event_type
            FROM run_events
            WHERE job_id = ? AND event_type = ?
            """,
            (job_id, "artifact_registered"),
        ).fetchone()
        job_row = verification_connection.execute(
            """
            SELECT last_event_sequence
            FROM migration_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

    assert row["sequence"] == 2
    assert row["event_type"] == "artifact_registered"
    assert job_row["last_event_sequence"] == 2


def _service_for(db_path: Path) -> CreateMigrationJobService:
    def factory() -> SqliteControlTowerUnitOfWork:
        return SqliteControlTowerUnitOfWork(connect_control_tower(db_path), close_connection=True)

    return CreateMigrationJobService(factory)


def _artifact_service_for(db_path: Path) -> ArtifactRegistryService:
    return ArtifactRegistryService(
        lambda: SqliteControlTowerUnitOfWork(
            connect_control_tower(db_path),
            close_connection=True,
        )
    )


def _job_with_artifact_roots(tmp_path: Path) -> tuple[Path, tuple, str]:
    db_path = tmp_path / "control_tower.sqlite3"
    roots = artifact_roots(tmp_path)
    connection = make_migrated_connection(tmp_path)
    seed_runner_profile_with_roots(connection, roots)
    seed_pipeline_definition(connection)
    connection.close()
    job = _service_for(db_path).execute(_create_command())
    return db_path, roots, job.job_id


def _artifact_command(job_id: str, artifact) -> RegisterArtifactCommand:
    return RegisterArtifactCommand(
        job_id=job_id,
        artifact=artifact,
        artifact_type="report",
        actor_type="user",
        actor_id="tester",
        content_type="text/plain",
        correlation_id="corr-artifact",
    )


def _write_and_hash(roots, relative_path: str, contents: bytes):
    path = Path(roots[0].path) / Path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return hash_registered_artifact(roots, "source-root", relative_path)


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
