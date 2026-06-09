from __future__ import annotations

from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteControlTowerUnitOfWork,
)

from .conftest import make_create_command, make_service, register_default_definitions


def test_job_created_event_is_job_scoped_sequence_one(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    job = service.create_migration_job(make_create_command())

    connection = connect_control_tower(control_tower_db_path)
    try:
        events = SqliteControlTowerUnitOfWork(connection).jobs.list_events(job.job_id)
    finally:
        connection.close()

    assert len(events) == 1
    assert events[0].job_id == job.job_id
    assert events[0].sequence == 1
    assert events[0].event_type == "job_created"


def test_definition_registration_does_not_create_run_events(control_tower_db_path) -> None:
    service = make_service(control_tower_db_path)
    register_default_definitions(service)

    connection = connect_control_tower(control_tower_db_path)
    try:
        event_count = connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0]
        audit_count = connection.execute("SELECT COUNT(*) FROM audit_records").fetchone()[0]
    finally:
        connection.close()

    assert event_count == 0
    assert audit_count == 2
