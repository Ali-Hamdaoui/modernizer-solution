from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from migration_factory.control_tower.application.commands import (
    RegisterPipelineDefinitionCommand,
    RegisterRunnerProfileCommand,
    TransitionJobStateCommand,
)
from migration_factory.control_tower.application.dto import AuditRecordDto
from migration_factory.control_tower.application.services import ControlTowerRegistrationService
from migration_factory.control_tower.domain.errors import (
    ExpectedVersionRequiredError,
    InvalidJobStateTransitionError,
    StaleVersionError,
)
from migration_factory.control_tower.domain.states import JobState
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteAuditRecordRepository,
    SqliteMigrationJobRepository,
    SqlitePipelineDefinitionRepository,
    SqliteRunnerProfileRepository,
    SqliteRunEventRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from tests.control_tower.transition_helpers import (
    count_audit_records,
    count_run_events,
    fetch_job,
    seed_job,
)


def test_global_audit_records_allow_null_job_id(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        service.register_runner_profile(_runner_command())

        row = connection.execute("SELECT job_id FROM audit_records").fetchone()
        assert row["job_id"] is None
    finally:
        connection.close()


def test_registration_and_audit_commit_atomically(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        service.register_runner_profile(_runner_command())

        assert _count(connection, "runner_profiles") == 1
        assert _count(connection, "audit_records") == 1
    finally:
        connection.close()


def test_audit_failure_rolls_back_runner_profile_registration(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = ControlTowerRegistrationService(lambda: _FailingAuditUnitOfWork(connection))

        with pytest.raises(RuntimeError, match="audit failed"):
            service.register_runner_profile(_runner_command())

        assert _count(connection, "runner_profiles") == 0
        assert _count(connection, "audit_records") == 0
    finally:
        connection.close()


def test_audit_failure_rolls_back_pipeline_definition_registration(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = ControlTowerRegistrationService(lambda: _FailingAuditUnitOfWork(connection))

        with pytest.raises(RuntimeError, match="audit failed"):
            service.register_pipeline_definition(_pipeline_command())

        assert _count(connection, "pipeline_definitions") == 0
        assert _count(connection, "audit_records") == 0
    finally:
        connection.close()


def test_audit_payload_json_is_valid_json(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        service.register_runner_profile(_runner_command())

        payload = json.loads(str(_audit_row(connection)["payload_json"]))
        assert payload["registration_type"] == "runner_profile"
    finally:
        connection.close()


def test_audit_payload_includes_registration_and_actor_context(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        registered = service.register_pipeline_definition(
            _pipeline_command(correlation_id="corr-1", causation_id="cause-1")
        )

        audit = _audit_row(connection)
        payload = json.loads(str(audit["payload_json"]))
        assert payload["id"] == registered.pipeline_id
        assert payload["version"] == registered.pipeline_version
        assert payload["checksum"] == registered.payload_checksum
        assert payload["actor_type"] == "user"
        assert payload["actor_id"] == "tester"
        assert payload["correlation_id"] == "corr-1"
        assert payload["causation_id"] == "cause-1"
        assert payload["action"] == "pipeline_definition_registered"
        assert audit["action"] == "pipeline_definition_registered"
    finally:
        connection.close()


def test_audit_records_are_append_only(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        service.register_runner_profile(_runner_command())
        audit_id = str(_audit_row(connection)["audit_id"])

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE audit_records SET actor_id = ? WHERE audit_id = ?", ("other", audit_id))

        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM audit_records WHERE audit_id = ?", (audit_id,))
    finally:
        connection.close()


def test_audit_query_helpers_return_dtos_and_scalars_not_sqlite_rows(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        service = _service(connection)
        service.register_runner_profile(_runner_command())
        with SqliteUnitOfWork(connection) as uow:
            audits = uow.audit_records.list()
            count = uow.audit_records.count()

        assert count == 1
        assert isinstance(audits[0], AuditRecordDto)
        assert not isinstance(audits[0], sqlite3.Row)
    finally:
        connection.close()


def test_transition_creates_one_job_scoped_audit_record(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        _service(connection).transition_job_state(_transition_command(JobState.QUEUED))

        with SqliteUnitOfWork(connection) as uow:
            audits = uow.audit_records.list_for_job("job-1")
            count = uow.audit_records.count_for_job("job-1")

        assert count == 1
        assert len(audits) == 1
        assert audits[0].job_id == "job-1"
        assert audits[0].action == "job_state_changed"
    finally:
        connection.close()


def test_transition_audit_records_states_version_actor_and_reason(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.RUNNING, version=3)

        _service(connection).transition_job_state(
            _transition_command(JobState.COMPLETED, expected_version=3)
        )

        audit = _transition_audit(connection)
        assert audit.prior_state == "RUNNING"
        assert audit.new_state == "COMPLETED"
        assert audit.job_version == 4
        assert audit.payload["prior_state"] == "RUNNING"
        assert audit.payload["new_state"] == "COMPLETED"
        assert audit.payload["prior_version"] == 3
        assert audit.payload["new_version"] == 4
        assert audit.payload["event_sequence"] == 1
        assert audit.payload["actor_type"] == "user"
        assert audit.payload["actor_id"] == "tester"
        assert audit.payload["reason"] == "advance lifecycle"
        assert audit.payload["correlation_id"] == "corr-1"
        assert audit.payload["causation_id"] == "cause-1"
    finally:
        connection.close()


def test_audit_failure_rolls_back_job_state_update_and_run_event_insert(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)
        service = ControlTowerRegistrationService(lambda: _FailingAuditUnitOfWork(connection))

        with pytest.raises(RuntimeError, match="audit failed"):
            service.transition_job_state(_transition_command(JobState.QUEUED))

        row = fetch_job(connection)
        assert row["status"] == "CREATED"
        assert row["version"] == 1
        assert row["active_slot"] == 1
        assert row["last_event_sequence"] == 0
        assert count_run_events(connection) == 0
        assert count_audit_records(connection) == 0
    finally:
        connection.close()


def test_no_audit_is_created_for_invalid_transition(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        with pytest.raises(InvalidJobStateTransitionError):
            _service(connection).transition_job_state(_transition_command(JobState.RUNNING))

        assert count_audit_records(connection) == 0
    finally:
        connection.close()


def test_no_audit_is_created_for_stale_version(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED, version=2)

        with pytest.raises(StaleVersionError):
            _service(connection).transition_job_state(
                _transition_command(JobState.QUEUED, expected_version=1)
            )

        assert count_audit_records(connection) == 0
    finally:
        connection.close()


def test_no_audit_is_created_for_missing_expected_version(tmp_path: Path) -> None:
    connection = _migrated_connection(tmp_path)
    try:
        seed_job(connection, status=JobState.CREATED)

        with pytest.raises(ExpectedVersionRequiredError):
            _service(connection).transition_job_state(
                _transition_command(JobState.QUEUED, expected_version=None)
            )

        assert count_audit_records(connection) == 0
    finally:
        connection.close()


class _FailingAuditRepository:
    def append_global_audit(self, **kwargs) -> None:
        raise RuntimeError("audit failed")

    def append_job_state_changed_audit(self, **kwargs) -> None:
        raise RuntimeError("audit failed")

    def list(self) -> tuple[AuditRecordDto, ...]:
        return ()

    def count(self) -> int:
        return 0


class _FailingAuditUnitOfWork:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.runner_profiles = SqliteRunnerProfileRepository(connection)
        self.pipeline_definitions = SqlitePipelineDefinitionRepository(connection)
        self.migration_jobs = SqliteMigrationJobRepository(connection)
        self.run_events = SqliteRunEventRepository(connection)
        self.audit_records = _FailingAuditRepository()

    def __enter__(self) -> "_FailingAuditUnitOfWork":
        self._connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self._connection.execute("COMMIT")
            return
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")


def _service(connection: sqlite3.Connection) -> ControlTowerRegistrationService:
    return ControlTowerRegistrationService(lambda: SqliteUnitOfWork(connection))


def _migrated_connection(tmp_path: Path) -> sqlite3.Connection:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    apply_pending_migrations(connection)
    return connection


def _runner_command() -> RegisterRunnerProfileCommand:
    return RegisterRunnerProfileCommand(
        profile={
            "schema_version": "1.0.0",
            "runner_profile_id": "runner-default",
            "runner_profile_version": "v1",
            "display_name": "Default runner",
            "filesystem_roots": (
                {
                    "root_id": "source-root",
                    "kind": "source",
                    "path": "C:/workspace/source",
                },
            ),
            "maven": {"maven_id": "maven-3.9"},
            "jdk_inventory": (
                {
                    "jdk_id": "jdk-17",
                    "java_home": "C:/jdks/temurin-17",
                    "major_version": 17,
                },
            ),
            "network_policy": {"allow_outbound": True},
            "ai_profiles": (
                {
                    "profile_id": "azure-gpt",
                    "profile_version": "1",
                    "provider": "azure-openai",
                    "deployment_ref": "deployments/gpt-4.1",
                },
            ),
        },
        actor_type="user",
        actor_id="tester",
    )


def _pipeline_command(
    *,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> RegisterPipelineDefinitionCommand:
    return RegisterPipelineDefinitionCommand(
        pipeline={
            "schema_version": "1.0.0",
            "pipeline_id": "pipeline-default",
            "pipeline_version": "v1",
            "display_name": "Default pipeline",
            "graph_version": "graph-v1",
            "graph_state_schema_version": "graph-state-v1",
            "stages": (
                {
                    "stage_index": 1,
                    "stage_id": "analysis",
                    "display_name": "Analysis",
                    "input_source": {"kind": "legacy_source"},
                    "command_jdk": "jdk-17",
                },
            ),
        },
        actor_type="user",
        actor_id="tester",
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _transition_command(
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


def _audit_row(connection: sqlite3.Connection) -> sqlite3.Row:
    return connection.execute("SELECT * FROM audit_records").fetchone()


def _transition_audit(connection: sqlite3.Connection) -> AuditRecordDto:
    with SqliteUnitOfWork(connection) as uow:
        audits = uow.audit_records.list_for_job("job-1")
    assert len(audits) == 1
    return audits[0]


def _count(connection: sqlite3.Connection, table_name: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
