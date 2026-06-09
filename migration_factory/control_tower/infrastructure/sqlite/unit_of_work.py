"""SQLite transaction wrapper for Control Tower registration operations."""

from __future__ import annotations

import sqlite3

from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteAuditRecordRepository,
    SqlitePipelineDefinitionRepository,
    SqliteRunnerProfileRepository,
)


class SqliteUnitOfWork:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.runner_profiles = SqliteRunnerProfileRepository(connection)
        self.pipeline_definitions = SqlitePipelineDefinitionRepository(connection)
        self.audit_records = SqliteAuditRecordRepository(connection)

    def __enter__(self) -> "SqliteUnitOfWork":
        self._connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self._connection.execute("COMMIT")
            return
        if self._connection.in_transaction:
            self._connection.execute("ROLLBACK")
