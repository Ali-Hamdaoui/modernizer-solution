"""Tests for V2 stage auto-progression."""

import sqlite3
from pathlib import Path
import pytest

from migration_factory.control_tower.application.v2_stage_progression import (
    V2StageProgressionService,
    STAGE_CONFIG,
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


def test_stage4_requires_accepted_artifact_revision(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "test3.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    repo = SqliteV2SetupRepository(conn)
    setup_id = _create_setup(repo)

    service = V2StageProgressionService(repo)
    with pytest.raises(ValueError, match="Stage 3 has no completed output"):
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
