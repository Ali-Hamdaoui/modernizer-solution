"""Tests for V2 stage auto-progression."""

import json
import sqlite3
from pathlib import Path
import pytest

from migration_factory.control_tower.application.v2_stage_progression import (
    V2StageProgressionService,
    STAGE_CONFIG,
    RUNNER_MODULE,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
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
    V2StageCommandRecord,
)


def _create_setup(repo):
    service = V2SetupService(repo)
    req = CreateSetupRequest(
        run_name="test-progression",
        legacy_app_path="/tmp/legacy",
        output_parent_path="/tmp/output",
        ai_hub_path="/tmp/ai-hub",
        java11_home="/usr/lib/jvm/java-11",
        java17_home="/usr/lib/jvm/java-17",
        java21_home="/usr/lib/jvm/java-21",
        maven_cmd="/usr/bin/mvn",
    )
    return service.create_setup(req).setup_id


def _save_successful_stage3_command(command_repo: SqliteV2CommandRepository, *, job_id: str = "job-1") -> None:
    now = utc_now_text()
    command_repo.save(
        V2StageCommandRecord(
            command_id="cmd-stage3",
            job_id=job_id,
            stage_index=3,
            manifest_checksum="checksum-stage3",
            argv_json=json.dumps(["python", "-m", RUNNER_MODULE, "--run-id", f"v2-{job_id[:8]}-s3"]),
            env_json="{}",
            status="completed",
            created_at=now,
            updated_at=now,
            result_json=json.dumps({
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "orchestration_status": "PASS",
                "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "build_status": "BUILD_PASSED_IN_SANDBOX",
                "test_status": "PASS",
                "sandbox_path": "/tmp/sandbox/stage3",
            }),
        )
    )


def test_queue_stage2_from_stage1(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test1.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo)
    result = service.queue_next_stage(
        job_id="job-1",
        setup_id=setup_id,
        current_stage=1,
        sandbox_path="/tmp/sandbox/stage1",
    )

    assert result.to_stage == 2
    assert result.from_stage == 1
    assert result.status == "queued"
    assert "springboot-2.7-to-3.5-java17" in " ".join(result.argv)


def test_queue_stage3_from_stage2(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test2.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo)
    result = service.queue_next_stage(
        job_id="job-1",
        setup_id=setup_id,
        current_stage=2,
        sandbox_path="/tmp/sandbox/stage2",
    )

    assert result.to_stage == 3
    assert "springboot-3.5-java17-to-java21" in " ".join(result.argv)


def test_queue_stage4_from_stage3_with_successful_evidence(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test3.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    setup_id = _create_setup(repo)
    _save_successful_stage3_command(command_repo)

    service = V2StageProgressionService(repo, command_repo)
    result = service.queue_next_stage(
        job_id="job-1",
        setup_id=setup_id,
        current_stage=3,
        sandbox_path="/tmp/sandbox/stage3",
    )

    assert result.status == "queued"
    assert result.from_stage == 3
    assert result.to_stage == 4
    assert result.command_id
    assert "--run-id" in result.argv
    assert "v2-job-1-s4" in result.argv
    assert "--legacy" in result.argv
    assert "/tmp/sandbox/stage3" in result.argv
    assert "springboot-3.5-java21-to-4.0-java21" in " ".join(result.argv)

    commands = command_repo.list_by_job_and_stage("job-1", 4)
    assert len(commands) == 1
    assert commands[0].stage_index == 4
    assert "v2-job-1-s4" in commands[0].argv_json


def test_stage4_blocks_when_stage3_success_evidence_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test3_missing.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo, command_repo)
    with pytest.raises(ValueError, match="successful Stage 3 output evidence"):
        service.queue_next_stage(
            job_id="job-1",
            setup_id=setup_id,
            current_stage=3,
            sandbox_path="/tmp/sandbox/stage3",
        )


def test_argv_is_backend_owned(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test4.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo)
    result = service.queue_next_stage(
        job_id="job-1",
        setup_id=setup_id,
        current_stage=1,
        sandbox_path="/tmp/sandbox/stage1",
    )

    assert RUNNER_MODULE in " ".join(result.argv)
    assert "--profile" in result.argv


def test_sandbox_path_is_input(tmp_path: Path) -> None:
    """The sandbox path from previous stage becomes the --legacy input."""
    conn = sqlite3.connect(str(tmp_path / "test5.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo)
    result = service.queue_next_stage(
        job_id="job-1",
        setup_id=setup_id,
        current_stage=1,
        sandbox_path="/tmp/sandbox/stage1-output",
    )

    assert "/tmp/sandbox/stage1-output" in " ".join(result.argv)


def test_boot4_path_is_valid(tmp_path: Path) -> None:
    """Boot 4 is a valid stage target in the four-stage pipeline."""
    assert 4 in STAGE_CONFIG
    assert STAGE_CONFIG[4]["profile"] == "springboot-3.5-java21-to-4.0-java21"
    assert STAGE_CONFIG[4]["jdk_id"] == "java21"


def test_stage_profiles_are_correct() -> None:
    assert STAGE_CONFIG[2]["profile"] == "springboot-2.7-to-3.5-java17"
    assert STAGE_CONFIG[3]["profile"] == "springboot-3.5-java17-to-java21"
    assert STAGE_CONFIG[4]["profile"] == "springboot-3.5-java21-to-4.0-java21"
    assert STAGE_CONFIG[2]["jdk_id"] == "java17"
    assert STAGE_CONFIG[3]["jdk_id"] == "java21"
    assert STAGE_CONFIG[4]["jdk_id"] == "java21"


def test_missing_setup_rejected(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test6.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)

    service = V2StageProgressionService(repo)
    with pytest.raises(ValueError, match="not found"):
        service.queue_next_stage(
            job_id="job-1",
            setup_id="nonexistent",
            current_stage=1,
            sandbox_path="/tmp/sandbox",
        )
