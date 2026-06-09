"""SQLite foundation for Control Tower persistence."""

from migration_factory.control_tower.infrastructure.sqlite.connection import (
    ControlTowerSqliteError,
    UnsupportedJournalModeError,
    configure_control_tower_journal_mode,
    connect_control_tower,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    AppliedMigrationChecksumMismatchError,
    MigrationDiscoveryError,
    MigrationExecutionError,
    MigrationFile,
    MigrationSafetyError,
    apply_pending_migrations,
    discover_migrations,
    migrate_control_tower,
    split_sql_statements,
)
from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteAuditRecordRepository,
    SqliteMigrationJobRepository,
    SqlitePipelineDefinitionRepository,
    SqliteRunnerProfileRepository,
    SqliteRunEventRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork

__all__ = [
    "AppliedMigrationChecksumMismatchError",
    "ControlTowerSqliteError",
    "MigrationDiscoveryError",
    "MigrationExecutionError",
    "MigrationFile",
    "MigrationSafetyError",
    "SqliteAuditRecordRepository",
    "SqliteMigrationJobRepository",
    "SqlitePipelineDefinitionRepository",
    "SqliteRunnerProfileRepository",
    "SqliteRunEventRepository",
    "SqliteUnitOfWork",
    "UnsupportedJournalModeError",
    "apply_pending_migrations",
    "configure_control_tower_journal_mode",
    "connect_control_tower",
    "discover_migrations",
    "migrate_control_tower",
    "split_sql_statements",
]
