"""Tests for M2-07 command cancellation and timeout."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from migration_factory.control_tower.application.commands import (
    CancelCommand,
    CreateMigrationJobCommand,
    LaunchWorkerCommand,
    PrepareCommandWorkspaceCommand,
    StartMigrationJobCommand,
)
from migration_factory.control_tower.application.services import (
    CancelService,
    CommandWorkspaceService,
    CreateMigrationJobService,
    DiagnosticJobService,
    WorkerLaunchService,
)
from migration_factory.control_tower.domain.commands import CommandState
from migration_factory.control_tower.domain.entities import CommandExecutionRecord
from migration_factory.control_tower.domain.errors import (
    InvalidJobStateTransitionError,
    NotFoundError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import JobState, TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteControlTowerUnitOfWork,
)
from migration_factory.control_tower.infrastructure.worker_launcher import (
    UnsupportedPlatformWorkerLauncher,
)
from migration_factory.control_tower.schemas.run_configuration import RunPolicy
from tests.control_tower._helpers import (
    canonical_json,
    make_migrated_connection,
    seed_pipeline_definition,
    seed_runner_profile_with_roots,
    seed_runner_profile_with_workspace_root,
    artifact_roots,
    sha256_json,
)


def _service_for(db_path: Path, service_cls):
    return service_cls(
        lambda: SqliteControlTowerUnitOfWork(
            connect_control_tower(db_path),
            close_connection=True,
        )
    )


def _seed_job_with_active_command(tmp_path: Path) -> tuple[Path, str, str]:
    """Seed a job with a queued command and prepared workspace.

    Returns (db_path, job_id, command_id).
    """
    db_path = tmp_path / "control_tower.sqlite3"
    connection = make_migrated_connection(tmp_path)
    seed_runner_profile_with_workspace_root(connection, tmp_path)
    _set_runner_python_executable(connection, sys.executable)
    seed_pipeline_definition(connection)
    connection.close()

    job_service = _service_for(db_path, CreateMigrationJobService)
    now = __import__("migration_factory.control_tower.domain.checksums", fromlist=["utc_now_text"]).utc_now_text()
    job = job_service.execute(
        CreateMigrationJobCommand(
            actor="tester",
            legacy_source_ref="source-root:source",
            output_root_ref="output-root:output",
            runner_profile_id="runner-default",
            runner_profile_version="2026.06",
            pipeline_id="pipeline-default",
            pipeline_version="2026.06",
            target_proof_level=TargetProofLevel.BUILD_TEST_VERIFIED,
            enabled_gates=("build", "test"),
            policy=RunPolicy(),
            correlation_id="corr-job",
        )
    )

    with connect_control_tower(db_path) as conn:
        with SqliteControlTowerUnitOfWork(conn) as uow:
            cmd = CommandExecutionRecord(
                command_id=f"command-{uuid4().hex}",
                job_id=job.job_id,
                operation="foundation_diagnostic",
                status=CommandState.QUEUED,
                created_at=now,
                updated_at=now,
                correlation_id="corr-cmd",
                causation_id=None,
            )
            uow.command_executions.insert_queued(cmd)
            command_id = cmd.command_id

    workspace_service = _service_for(db_path, CommandWorkspaceService)
    workspace_service.prepare_workspace(
        PrepareCommandWorkspaceCommand(
            command_id=command_id,
            job_id=job.job_id,
            working_directory_root_id="working-root",
            working_directory_relative_path=job.job_id,
            worker_id="worker-1",
            launch_attempt=1,
            actor_type="system",
            actor_id="worker",
            correlation_id="corr-ws",
            causation_id=None,
        )
    )

    return db_path, job.job_id, command_id


def _seed_started_job_with_active_command(tmp_path: Path) -> tuple[Path, str, str]:
    """Seed a job that has been started (QUEUED state) with active command.

    This is required because CREATED cannot transition to CANCELLING.
    Returns (db_path, job_id, command_id).
    """
    db_path, job_id, command_id = _seed_job_with_active_command(tmp_path)

    # Transition job from CREATED to QUEUED manually
    with connect_control_tower(db_path) as conn:
        with SqliteControlTowerUnitOfWork(conn) as uow:
            now = __import__("migration_factory.control_tower.domain.checksums", fromlist=["utc_now_text"]).utc_now_text()
            uow.migration_jobs.transition_state(
                job_id,
                1,
                JobState.QUEUED,
                1,
                now,
            )

    return db_path, job_id, command_id


def _seed_job_via_diagnostic_api(tmp_path: Path) -> tuple[Path, str, str, int]:
    """Seed a diagnostic job via the full API path.

    Returns (db_path, job_id, command_id, job_version).
    """
    db_path = tmp_path / "control_tower.sqlite3"
    connection = make_migrated_connection(tmp_path)
    seed_runner_profile_with_roots(connection, artifact_roots(tmp_path))
    seed_pipeline_definition(connection)
    connection.close()

    diag_service = DiagnosticJobService(
        lambda: SqliteControlTowerUnitOfWork(
            connect_control_tower(db_path), close_connection=True
        )
    )
    from migration_factory.control_tower.application.commands import (
        CreateDiagnosticJobCommand,
    )

    created = diag_service.create_diagnostic_job(
        CreateDiagnosticJobCommand(
            idempotency_key="cancel-test-create",
            runner_profile_id="runner-default",
            runner_profile_version="2026.06",
            pipeline_id="pipeline-default",
            pipeline_version="2026.06",
            legacy_source_root_id="source-root",
            legacy_source_relative_path="src",
            output_root_id="output-root",
            output_relative_path="out",
            target_proof_level=TargetProofLevel.ANALYZED,
            enabled_gates=(),
            policy=RunPolicy(),
        )
    )
    job_id = created.job.job_id
    job_version = created.job.version

    started = diag_service.start_migration_job(
        StartMigrationJobCommand(
            job_id=job_id,
            expected_version=job_version,
            idempotency_key="cancel-test-start",
            actor_type="user",
            actor_id="tester",
        )
    )
    command_id = started.active_command.command_id

    return db_path, job_id, command_id, started.job.version


def _set_runner_python_executable(connection, python_executable: str) -> None:
    row = connection.execute(
        "SELECT payload_json FROM runner_profiles WHERE runner_profile_id = ?",
        ("runner-default",),
    ).fetchone()
    assert row is not None
    payload = json.loads(row["payload_json"])
    payload["python_executable"] = python_executable
    connection.execute(
        """
        UPDATE runner_profiles
        SET payload_json = ?, payload_checksum = ?
        WHERE runner_profile_id = ?
        """,
        (
            canonical_json(payload),
            sha256_json(payload),
            "runner-default",
        ),
    )


# ── Cancel service tests ────────────────────────────────────────


class TestCancelService:
    def test_cancel_transitions_to_cancelling(self, tmp_path: Path) -> None:
        db_path, job_id, command_id = _seed_started_job_with_active_command(tmp_path)

        service = CancelService(
            lambda: SqliteControlTowerUnitOfWork(
                connect_control_tower(db_path), close_connection=True
            ),
        )

        # Get current job version
        with connect_control_tower(db_path) as conn:
            row = conn.execute(
                "SELECT version FROM migration_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        expected_version = int(row["version"])

        projection = service.cancel(
            CancelCommand(
                job_id=job_id,
                expected_version=expected_version,
                actor_type="user",
                actor_id="tester",
            )
        )

        assert projection.job.status == JobState.CANCELLING
        assert projection.active_command is not None
        assert projection.active_command.status == CommandState.CANCELLING

    def test_cancel_creates_cancelling_event(self, tmp_path: Path) -> None:
        db_path, job_id, command_id = _seed_started_job_with_active_command(tmp_path)

        with connect_control_tower(db_path) as conn:
            row = conn.execute(
                "SELECT version FROM migration_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        expected_version = int(row["version"])

        service = CancelService(
            lambda: SqliteControlTowerUnitOfWork(
                connect_control_tower(db_path), close_connection=True
            ),
        )
        service.cancel(
            CancelCommand(
                job_id=job_id,
                expected_version=expected_version,
                actor_type="user",
                actor_id="tester",
            )
        )

        with connect_control_tower(db_path) as conn:
            events = conn.execute(
                "SELECT event_type, payload_json FROM run_events WHERE job_id = ? ORDER BY sequence",
                (job_id,),
            ).fetchall()
        event_types = [str(e["event_type"]) for e in events]
        assert "job_state_changed" in event_types

    def test_cancel_rejects_stale_version(self, tmp_path: Path) -> None:
        db_path, job_id, command_id = _seed_started_job_with_active_command(tmp_path)

        service = CancelService(
            lambda: SqliteControlTowerUnitOfWork(
                connect_control_tower(db_path), close_connection=True
            ),
        )

        with pytest.raises(StaleVersionError):
            service.cancel(
                CancelCommand(
                    job_id=job_id,
                    expected_version=999,  # Stale
                    actor_type="user",
                    actor_id="tester",
                )
            )

    def test_cancel_requires_active_command(self, tmp_path: Path) -> None:
        db_path, job_id, command_id = _seed_started_job_with_active_command(tmp_path)

        with connect_control_tower(db_path) as conn:
            row = conn.execute(
                "SELECT version FROM migration_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        expected_version = int(row["version"])

        # Clear the active command
        with connect_control_tower(db_path) as conn:
            conn.execute(
                "UPDATE command_executions SET status = ? WHERE command_id = ?",
                (CommandState.SUCCEEDED.value, command_id),
            )

        service = CancelService(
            lambda: SqliteControlTowerUnitOfWork(
                connect_control_tower(db_path), close_connection=True
            ),
        )

        with pytest.raises(NotFoundError, match="active command"):
            service.cancel(
                CancelCommand(
                    job_id=job_id,
                    expected_version=expected_version,
                    actor_type="user",
                    actor_id="tester",
                )
            )

    def test_cancel_idempotent_via_version(self, tmp_path: Path) -> None:
        db_path, job_id, command_id = _seed_started_job_with_active_command(tmp_path)

        with connect_control_tower(db_path) as conn:
            row = conn.execute(
                "SELECT version FROM migration_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        expected_version = int(row["version"])

        service = CancelService(
            lambda: SqliteControlTowerUnitOfWork(
                connect_control_tower(db_path), close_connection=True
            ),
        )

        # First cancel succeeds
        projection1 = service.cancel(
            CancelCommand(
                job_id=job_id,
                expected_version=expected_version,
                actor_type="user",
                actor_id="tester",
            )
        )
        assert projection1.job.status == JobState.CANCELLING

        # Second cancel with original version fails (stale)
        with pytest.raises(StaleVersionError):
            service.cancel(
                CancelCommand(
                    job_id=job_id,
                    expected_version=expected_version,
                    actor_type="user",
                    actor_id="tester",
                )
            )

    def test_cancel_rejects_nonexistent_job(self, tmp_path: Path) -> None:
        service = CancelService(lambda: _make_empty_uow(tmp_path))

        with pytest.raises(NotFoundError, match="migration job"):
            service.cancel(
                CancelCommand(
                    job_id="nonexistent",
                    expected_version=1,
                    actor_type="user",
                    actor_id="tester",
                )
            )


# ── FastAPI cancel endpoint tests ───────────────────────────────


class TestFastapiCancelEndpoint:
    def test_cancel_endpoint_requires_if_match(self, tmp_path: Path) -> None:
        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from migration_factory.control_tower.adapters.fastapi import create_app

        import sqlite3 as _sqlite3
        test_tmp = tmp_path
        connection = _sqlite3.connect(
            str(test_tmp / "control_tower.sqlite3"),
            check_same_thread=False,
            isolation_level=None,
            timeout=5.0,
        )
        connection.row_factory = _sqlite3.Row
        from migration_factory.control_tower.infrastructure.sqlite.migrations import (
            apply_pending_migrations,
        )
        apply_pending_migrations(connection)
        from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
            SqliteUnitOfWork,
        )
        client = TestClient(create_app(lambda: SqliteUnitOfWork(connection)))

        resp = client.post("/v1/jobs/fake-job/cancel", json={})
        assert resp.status_code == 428
        assert resp.json()["detail"]["error"]["code"] == "PRECONDITION_REQUIRED"

    def test_cancel_endpoint_rejects_bad_etag(self, tmp_path: Path) -> None:
        fastapi = pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from migration_factory.control_tower.adapters.fastapi import create_app

        import sqlite3 as _sqlite3
        test_tmp = tmp_path
        connection = _sqlite3.connect(
            str(test_tmp / "control_tower.sqlite3"),
            check_same_thread=False,
            isolation_level=None,
            timeout=5.0,
        )
        connection.row_factory = _sqlite3.Row
        from migration_factory.control_tower.infrastructure.sqlite.migrations import (
            apply_pending_migrations,
        )
        apply_pending_migrations(connection)
        from tests.control_tower._helpers import (
            seed_runner_profile_with_roots,
            seed_pipeline_definition,
            artifact_roots,
        )
        seed_runner_profile_with_roots(connection, artifact_roots(test_tmp))
        seed_pipeline_definition(connection)
        from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
            SqliteUnitOfWork,
        )
        from tests.control_tower.test_fastapi_diagnostic_queue import _job_payload
        client = TestClient(create_app(lambda: SqliteUnitOfWork(connection)))

        # Create a job to get a real job_id
        create_resp = client.post(
            "/v1/jobs",
            json=_job_payload(),
            headers={"Idempotency-Key": "cancel-etag-test"},
        )
        assert create_resp.status_code == 201
        job_id = create_resp.json()["job"]["job_id"]

        # Cancel with wrong etag
        resp = client.post(
            f"/v1/jobs/{job_id}/cancel",
            json={},
            headers={"If-Match": '"job-fake-v999"'},
        )
        assert resp.status_code == 412
        assert resp.json()["detail"]["error"]["code"] == "JOB_VERSION_CONFLICT"


# ── Helpers ──────────────────────────────────────────────────────


def _make_empty_uow(tmp_path: Path):
    from migration_factory.control_tower.domain.checksums import utc_now_text
    connection = make_migrated_connection(tmp_path)
    return SqliteControlTowerUnitOfWork(connection, close_connection=True)
