from __future__ import annotations

import json
import sqlite3

import pytest

from migration_factory.control_tower.application.errors import (
    DefinitionNotFoundError,
    IncompatibleConfigurationError,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json
from migration_factory.control_tower.domain.states import JobState, StageState
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteControlTowerUnitOfWork,
)

from .conftest import (
    make_create_command,
    make_pipeline_definition,
    make_runner_profile,
    make_service,
    register_default_definitions,
)


def test_create_job_persists_job_configuration_stages_event_and_audit(
    control_tower_db_path,
) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    job = service.create_migration_job(make_create_command())

    connection = connect_control_tower(control_tower_db_path)
    try:
        repository = SqliteControlTowerUnitOfWork(connection).jobs
        stored_job = repository.get_job(job.job_id)
        configuration = repository.get_run_configuration(job.job_id)
        stages = repository.list_stages(job.job_id)
        events = repository.list_events(job.job_id)
        audit_records = repository.list_audit_records(job.job_id)
    finally:
        connection.close()

    assert stored_job.version == 1
    assert stored_job.state == JobState.CREATED.value
    assert stored_job.last_event_sequence == 1
    assert configuration.job_id == job.job_id
    config_payload = json.loads(configuration.config_json)
    assert config_payload["runner_profile_version"] == "2026.06"
    assert configuration.config_checksum_sha256 == sha256_canonical_json(config_payload)
    assert [stage.stage_name for stage in stages] == ["analyze", "transform"]
    assert [stage.ordinal for stage in stages] == [1, 2]
    assert {stage.state for stage in stages} == {StageState.PENDING.value}
    assert [(event.sequence, event.event_type) for event in events] == [(1, "job_created")]
    assert [record.action for record in audit_records] == ["job_created"]


def test_missing_runner_version_is_rejected(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    with pytest.raises(DefinitionNotFoundError):
        service.create_migration_job(
            make_create_command(runner_profile_version="missing-version")
        )


def test_missing_pipeline_version_is_rejected(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    with pytest.raises(DefinitionNotFoundError):
        service.create_migration_job(make_create_command(pipeline_version="missing-version"))


def test_missing_runner_jdk_reference_rejects_creation_before_persistent_job_state(
    control_tower_db_path,
) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(
        service,
        runner=make_runner_profile(jdk_ids=("jdk-17",)),
        pipeline=make_pipeline_definition(command_jdk="jdk-21"),
    )

    with pytest.raises(IncompatibleConfigurationError):
        service.create_migration_job(make_create_command())

    assert _table_count(control_tower_db_path, "migration_jobs") == 0
    assert _table_count(control_tower_db_path, "run_configurations") == 0
    assert _table_count(control_tower_db_path, "stage_runs") == 0
    assert _table_count(control_tower_db_path, "run_events") == 0


def test_failure_during_stage_insertion_rolls_back_everything(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(
        service,
        pipeline=make_pipeline_definition(stage_ids=("duplicate", "duplicate")),
    )

    with pytest.raises(Exception):
        service.create_migration_job(make_create_command())

    _assert_no_job_fragments(control_tower_db_path)


def test_failure_during_event_insertion_rolls_back_everything(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)
    connection = connect_control_tower(control_tower_db_path)
    try:
        connection.execute(
            """
            CREATE TRIGGER fail_job_created_event
            BEFORE INSERT ON run_events
            BEGIN
                SELECT RAISE(ABORT, 'forced event failure');
            END
            """
        )
    finally:
        connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced event failure"):
        service.create_migration_job(make_create_command())

    _assert_no_job_fragments(control_tower_db_path)


def test_failure_during_audit_insertion_rolls_back_everything(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)
    connection = connect_control_tower(control_tower_db_path)
    try:
        connection.execute(
            """
            CREATE TRIGGER fail_job_created_audit
            BEFORE INSERT ON audit_records
            WHEN NEW.action = 'job_created'
            BEGIN
                SELECT RAISE(ABORT, 'forced audit failure');
            END
            """
        )
    finally:
        connection.close()

    with pytest.raises(sqlite3.IntegrityError, match="forced audit failure"):
        service.create_migration_job(make_create_command())

    _assert_no_job_fragments(control_tower_db_path)


def test_created_state_survives_database_restart(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)
    job = service.create_migration_job(make_create_command())

    restarted = connect_control_tower(control_tower_db_path)
    try:
        repository = SqliteControlTowerUnitOfWork(restarted).jobs
        assert repository.get_job(job.job_id).state == JobState.CREATED.value
        assert repository.get_run_configuration(job.job_id).job_id == job.job_id
        assert len(repository.list_stages(job.job_id)) == 2
        assert repository.list_events(job.job_id)[0].event_type == "job_created"
        assert repository.list_audit_records(job.job_id)[0].action == "job_created"
    finally:
        restarted.close()


def test_no_excluded_execution_or_interface_tables_are_introduced(control_tower_db_path) -> None:
    connection = connect_control_tower(control_tower_db_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert "worker_leases" not in tables
    assert "approvals" not in tables
    assert "node_executions" not in tables
    assert "command_executions" not in tables


def _assert_no_job_fragments(db_path) -> None:
    assert _table_count(db_path, "migration_jobs") == 0
    assert _table_count(db_path, "run_configurations") == 0
    assert _table_count(db_path, "stage_runs") == 0
    assert _table_count(db_path, "run_events") == 0
    assert _table_count(db_path, "audit_records", "WHERE action = 'job_created'") == 0


def _table_count(db_path, table_name: str, suffix: str = "") -> int:
    connection = connect_control_tower(db_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table_name} {suffix}").fetchone()[0])
    finally:
        connection.close()
