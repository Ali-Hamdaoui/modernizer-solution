from __future__ import annotations

from threading import Barrier, Thread

import pytest

from migration_factory.control_tower.application.errors import (
    ActiveMigrationJobConflictError,
    RepositoryIntegrityError,
)
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower

from .conftest import make_create_command, make_service, register_default_definitions


def test_second_active_job_is_rejected(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    service.create_migration_job(make_create_command(correlation_id="first"))

    with pytest.raises(ActiveMigrationJobConflictError):
        service.create_migration_job(make_create_command(correlation_id="second"))


def test_concurrent_creators_allow_exactly_one_success(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)
    barrier = Barrier(2)
    results: list[str] = []

    def worker(correlation_id: str) -> None:
        local_service = make_service(control_tower_db_path)
        barrier.wait()
        try:
            local_service.create_migration_job(
                make_create_command(correlation_id=correlation_id)
            )
            results.append("success")
        except ActiveMigrationJobConflictError:
            results.append("conflict")

    threads = [Thread(target=worker, args=(f"corr-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["conflict", "success"]
    assert _count_rows(control_tower_db_path, "migration_jobs") == 1
    assert _count_rows(control_tower_db_path, "run_events") == 1


def test_unrelated_integrity_error_is_not_reported_as_active_job_conflict(
    control_tower_db_path,
) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)
    connection = connect_control_tower(control_tower_db_path)
    try:
        connection.execute(
            """
            CREATE TRIGGER unrelated_job_integrity_failure
            BEFORE INSERT ON migration_jobs
            BEGIN
                SELECT RAISE(ABORT, 'unrelated integrity failure');
            END
            """
        )
    finally:
        connection.close()

    with pytest.raises(RepositoryIntegrityError, match="unrelated integrity failure"):
        service.create_migration_job(make_create_command())


def _count_rows(db_path, table_name: str) -> int:
    connection = connect_control_tower(db_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
    finally:
        connection.close()
