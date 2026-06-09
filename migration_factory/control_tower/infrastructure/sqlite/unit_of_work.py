"""SQLite unit of work for Control Tower application services."""

from __future__ import annotations

import sqlite3

from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteArtifactRepository,
    SqliteAuditRecordRepository,
    SqliteMigrationJobRepository,
    SqlitePipelineDefinitionRepository,
    SqliteRunConfigurationRepository,
    SqliteRunEventRepository,
    SqliteRunnerProfileRepository,
    SqliteStageRunRepository,
)


class SqliteControlTowerUnitOfWork:
    def __init__(self, connection: sqlite3.Connection, *, close_connection: bool = False) -> None:
        self.connection = connection
        self._close_connection = close_connection
        self.runner_profiles = SqliteRunnerProfileRepository(connection)
        self.pipeline_definitions = SqlitePipelineDefinitionRepository(connection)
        self.migration_jobs = SqliteMigrationJobRepository(connection)
        self.run_configurations = SqliteRunConfigurationRepository(connection)
        self.stage_runs = SqliteStageRunRepository(connection)
        self.run_events = SqliteRunEventRepository(connection)
        self.artifacts = SqliteArtifactRepository(connection)
        self.audit_records = SqliteAuditRecordRepository(connection)

    def __enter__(self) -> "SqliteControlTowerUnitOfWork":
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if exc_type is None:
            self.connection.execute("COMMIT")
        elif self.connection.in_transaction:
            self.connection.execute("ROLLBACK")
        if self._close_connection:
            self.connection.close()
        return None


SqliteUnitOfWork = SqliteControlTowerUnitOfWork
