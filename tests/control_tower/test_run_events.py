from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from migration_factory.control_tower.application.commands import TransitionJobStateCommand
from migration_factory.control_tower.domain.checksums import canonical_json
from migration_factory.control_tower.domain.errors import (
    ExpectedVersionRequiredError,
    InvalidJobStateTransitionError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from tests.control_tower.transition_helpers import (
    count_audit_records,
    count_run_events,
    fetch_job,
    migrated_connection,
    seed_job,
    service,
)


def test_successful_transition_creates_job_state_changed_event(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        service(connection).transition_job_state(_command(JobState.QUEUED))

        event = _single_event(connection)
        assert event.event_type == "job_state_changed"
        assert event.job_id == "job-1"
        assert event.sequence == 1
        assert event.actor_type == "user"
        assert event.actor_id == "tester"
        assert event.correlation_id == "corr-1"
        assert event.causation_id == "cause-1"
    finally:
        connection.close()


def test_event_sequence_starts_from_existing_last_event_sequence_plus_one(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED, last_event_sequence=4)

        service(connection).transition_job_state(_command(JobState.QUEUED))

        event = _single_event(connection)
        assert event.sequence == 5
        assert fetch_job(connection)["last_event_sequence"] == 5
    finally:
        connection.close()


def test_event_payload_records_state_actor_reason_and_versions(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.RUNNING, version=3)

        service(connection).transition_job_state(
            _command(JobState.PAUSED_FOR_PLAN_APPROVAL, expected_version=3)
        )

        payload = _single_event(connection).payload
        assert payload["job_id"] == "job-1"
        assert payload["prior_state"] == "RUNNING"
        assert payload["new_state"] == "PAUSED_FOR_PLAN_APPROVAL"
        assert payload["prior_version"] == 3
        assert payload["new_version"] == 4
        assert payload["actor_type"] == "user"
        assert payload["actor_id"] == "tester"
        assert payload["reason"] == "advance lifecycle"
        assert payload["correlation_id"] == "corr-1"
        assert payload["causation_id"] == "cause-1"
    finally:
        connection.close()


def test_event_payload_checksum_matches_canonical_payload_json(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        service(connection).transition_job_state(_command(JobState.QUEUED))

        event = _single_event(connection)
        assert event.payload_json == canonical_json(event.payload)
        assert event.payload_checksum == hashlib.sha256(
            event.payload_json.encode("utf-8")
        ).hexdigest()
    finally:
        connection.close()


def test_event_failure_rolls_back_job_update_and_sequence(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)
        transition_service = service_with_failing_events(connection)

        with pytest.raises(RuntimeError, match="event failed"):
            transition_service.transition_job_state(_command(JobState.QUEUED))

        row = fetch_job(connection)
        assert row["status"] == "CREATED"
        assert row["version"] == 1
        assert row["active_slot"] == 1
        assert row["last_event_sequence"] == 0
        assert count_run_events(connection) == 0
        assert count_audit_records(connection) == 0
    finally:
        connection.close()


def test_no_event_is_created_for_invalid_transition(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        with pytest.raises(InvalidJobStateTransitionError):
            service(connection).transition_job_state(_command(JobState.RUNNING))

        assert count_run_events(connection) == 0
    finally:
        connection.close()


def test_no_event_is_created_for_stale_version(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED, version=2)

        with pytest.raises(StaleVersionError):
            service(connection).transition_job_state(
                _command(JobState.QUEUED, expected_version=1)
            )

        assert count_run_events(connection) == 0
    finally:
        connection.close()


def test_no_event_is_created_for_missing_expected_version(tmp_path: Path) -> None:
    connection = migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        with pytest.raises(ExpectedVersionRequiredError):
            service(connection).transition_job_state(
                _command(JobState.QUEUED, expected_version=None)
            )

        assert count_run_events(connection) == 0
    finally:
        connection.close()


class _FailingRunEventRepository:
    def append_job_state_changed_event(self, **kwargs) -> None:
        raise RuntimeError("event failed")


def service_with_failing_events(connection):
    def factory() -> SqliteUnitOfWork:
        uow = SqliteUnitOfWork(connection)
        uow.run_events = _FailingRunEventRepository()
        return uow

    from migration_factory.control_tower.application.services import ControlTowerRegistrationService

    return ControlTowerRegistrationService(factory)


def _single_event(connection):
    with SqliteUnitOfWork(connection) as uow:
        events = uow.run_events.list_for_job("job-1")
    assert len(events) == 1
    return events[0]


def _command(
    target_state: JobState,
    *,
    expected_version: int | None = 1,
) -> TransitionJobStateCommand:
    return TransitionJobStateCommand(
        job_id="job-1",
        expected_version=expected_version,
        target_state=target_state,
        actor_type="user",
        actor_id="tester",
        reason="advance lifecycle",
        correlation_id="corr-1",
        causation_id="cause-1",
    )
