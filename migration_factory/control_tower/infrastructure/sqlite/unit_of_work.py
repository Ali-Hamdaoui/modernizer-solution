"""SQLite unit of work for Control Tower write transactions."""

from __future__ import annotations

import sqlite3

from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteDefinitionRepository,
    SqliteMigrationJobRepository,
)


class SqliteControlTowerUnitOfWork:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.definitions = SqliteDefinitionRepository(connection)
        self.jobs = SqliteMigrationJobRepository(connection)

    def __enter__(self) -> "SqliteControlTowerUnitOfWork":
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.connection.execute("COMMIT")
            return
        if self.connection.in_transaction:
            self.connection.execute("ROLLBACK")
