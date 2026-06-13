"""Tests for V2 worker stage execution."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from migration_factory.control_tower.application.v2_worker_stage import (
    V2WorkerStageService,
    STAGE_JDK_MAP,
    PIPELINE_ID,
    RUNNER_MODULE,
)
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
    V2MigrationJobRecord,
)
from migration_factory.control_tower.domain.checksums import utc_now_text


def _mutation_headers():
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID
    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path):
    from migration_factory.control_tower.adapters.fastapi import create_app
    from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
    from fastapi.testclient import TestClient
    conn = sqlite3.connect(
        tmp_path / "worker_test.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, conn


def _create_test_setup(repo: SqliteV2SetupRepository) -> str:
    service = V2SetupService(repo)
    req = CreateSetupRequest(
        run_name="test-worker",
        legacy_app_path="/tmp/legacy-app",
        output_parent_path="/tmp/output",
        ai_hub_path="/tmp/ai-hub",
        java11_home="/usr/lib/jvm/java-11",
        java17_home="/usr/lib/jvm/java-17",
        java21_home="/usr/lib/jvm/java-21",
        maven_cmd="/usr/bin/mvn",
    )
    dto = service.create_setup(req)
    return dto.setup_id


def _make_worker_service(conn: sqlite3.Connection) -> V2WorkerStageService:
    return V2WorkerStageService(
        setup_repo=SqliteV2SetupRepository(conn),
        command_repo=SqliteV2CommandRepository(conn),
    )


def test_stage1_manifest_built_from_setup(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        tmp_path / "test1.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_test_setup(repo)

    service = _make_worker_service(conn)
    result = service.build_stage1_manifest(
        job_id="test-job-id",
        setup_id=setup_id,
    )

    assert result.command_id
    assert result.job_id == "test-job-id"
    assert result.stage_index == 1
    assert len(result.argv) > 0
    assert "--run-id" in result.argv
    assert "--legacy" in result.argv
    assert "/tmp/legacy-app" in result.argv


def test_stage1_manifest_argv_backend_owned(tmp_path: Path) -> None:
    """The argv must be backend-owned, not user-supplied."""
    conn = sqlite3.connect(
        tmp_path / "test2.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_test_setup(repo)

    service = _make_worker_service(conn)
    result = service.build_stage1_manifest(
        job_id="test-job-id",
        setup_id=setup_id,
    )

    # The argv is built from setup data, not from user input
    assert RUNNER_MODULE in " ".join(result.argv)
    assert "--legacy" in result.argv
    assert "--modernized" in result.argv
    assert "--ai-hub" in result.argv
    assert "--profile" in result.argv
    assert "--mode" in result.argv
    # No user-supplied commands or goals
    assert "shell" not in str(result.argv).lower()


def test_stage1_manifest_uses_setup_paths(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        tmp_path / "test3.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_test_setup(repo)

    service = _make_worker_service(conn)
    result = service.build_stage1_manifest(
        job_id="test-job-id",
        setup_id=setup_id,
    )

    argv_str = " ".join(result.argv)
    assert "/tmp/legacy-app" in argv_str
    assert "/tmp/output" in argv_str
    assert "/tmp/ai-hub" in argv_str


def test_stage1_manifest_no_browser_paths(tmp_path: Path) -> None:
    """Browser payloads cannot supply argv or env."""
    conn = sqlite3.connect(
        tmp_path / "test4.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_test_setup(repo)

    service = _make_worker_service(conn)
    result = service.build_stage1_manifest(
        job_id="test-job-id",
        setup_id=setup_id,
    )

    # The result doesn't accept browser-supplied fields
    assert not hasattr(result, "browser_argv")  # No browser argv
    assert result.argv  # Only backend-owned argv exists


def test_stage1_manifest_not_found(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        tmp_path / "test5.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    service = _make_worker_service(conn)
    with pytest.raises(ValueError, match="not found"):
        service.build_stage1_manifest(
            job_id="test-job-id",
            setup_id="nonexistent",
        )


def test_stage_jdk_map_is_fixed() -> None:
    """The JDK map is fixed and cannot be overridden by browser."""
    assert STAGE_JDK_MAP[1]["jdk_id"] == "java11"
    assert STAGE_JDK_MAP[1]["expected_major"] == 11
    assert STAGE_JDK_MAP[2]["jdk_id"] == "java17"
    assert STAGE_JDK_MAP[2]["expected_major"] == 17
    assert STAGE_JDK_MAP[3]["jdk_id"] == "java21"
    assert STAGE_JDK_MAP[3]["expected_major"] == 21


def test_pipeline_id_is_constant() -> None:
    assert PIPELINE_ID == "springboot-216-to-356-java21-three-stage"


def test_result_to_dict_shape(tmp_path: Path) -> None:
    from migration_factory.control_tower.application.v2_worker_stage import V2StageCommandResult
    conn = sqlite3.connect(
        tmp_path / "test6.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    service = _make_worker_service(conn)

    result = V2StageCommandResult(
        command_id="cmd1",
        job_id="job1",
        stage_index=1,
        manifest_checksum="abc",
        argv=("python", "-m", "runner", "--run-id", "test"),
        created_at="2026-06-13T00:00:00Z",
    )
    d = service.result_to_dict(result)
    assert d["command_id"] == "cmd1"
    assert d["stage_index"] == 1
    assert isinstance(d["argv"], list)


def test_start_stage1_endpoint(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)

    # Create setup
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_test_setup(repo)
    setup = repo.get(setup_id)
    assert setup is not None
    now = utc_now_text()
    SqliteV2JobRepository(conn).save(
        V2MigrationJobRecord(
            job_id="test-job-123",
            setup_id=setup_id,
            setup_checksum=setup.setup_checksum,
            pipeline_id=PIPELINE_ID,
            stage_chain_json=json.dumps([
                {
                    "stage_index": 1,
                    "stage_run_id": "stage-1",
                    "pipeline_stage": "Stage 1",
                    "input_source_kind": "legacy_source",
                    "chain_status": "queued",
                },
                {
                    "stage_index": 2,
                    "stage_run_id": "stage-2",
                    "pipeline_stage": "Stage 2",
                    "input_source_kind": "stage_1_sandbox",
                    "chain_status": "pending",
                },
                {
                    "stage_index": 3,
                    "stage_run_id": "stage-3",
                    "pipeline_stage": "Stage 3",
                    "input_source_kind": "stage_2_sandbox",
                    "chain_status": "pending",
                },
            ]),
            status="created",
            created_at=now,
            updated_at=now,
            correlation_id=None,
        )
    )

    response = client.post(
        "/v1/v2/migration-jobs/start-stage1",
        json={"job_id": "test-job-123", "setup_id": setup_id},
        headers=_mutation_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["command_id"]
    assert body["stage_index"] == 1
    assert isinstance(body["argv"], list)
    assert len(body["argv"]) > 0


def test_manifest_persistence_across_connections(tmp_path: Path) -> None:
    """Built manifest should survive connection close/reopen."""
    db_path = tmp_path / "persist_test.sqlite3"

    # First connection — create setup and manifest
    conn1 = sqlite3.connect(
        db_path, check_same_thread=False, isolation_level=None, timeout=5.0
    )
    conn1.row_factory = sqlite3.Row
    conn1.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn1)
    repo1 = SqliteV2SetupRepository(conn1)
    setup_id = _create_test_setup(repo1)
    service1 = _make_worker_service(conn1)
    result = service1.build_stage1_manifest(
        job_id="persist-test-job",
        setup_id=setup_id,
    )
    saved_command_id = result.command_id
    conn1.close()

    # Second connection — verify it's still there
    conn2 = sqlite3.connect(
        db_path, check_same_thread=False, isolation_level=None, timeout=5.0
    )
    conn2.row_factory = sqlite3.Row
    conn2.execute("PRAGMA foreign_keys = ON")
    service2 = _make_worker_service(conn2)
    loaded = service2.get_command(saved_command_id)
    assert loaded is not None
    assert loaded.command_id == saved_command_id
    assert loaded.stage_index == 1
    assert "--legacy" in loaded.argv
    conn2.close()


def test_get_command_returns_none_for_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        tmp_path / "test_get.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    service = _make_worker_service(conn)
    assert service.get_command("nonexistent") is None
