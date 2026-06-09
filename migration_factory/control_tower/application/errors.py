"""Typed application errors for Control Tower use cases."""

from __future__ import annotations


class ControlTowerApplicationError(Exception):
    """Base exception for application-layer failures."""


class DefinitionNotFoundError(ControlTowerApplicationError):
    """Raised when a requested registered definition does not exist."""


class IncompatibleConfigurationError(ControlTowerApplicationError):
    """Raised when selected runner and pipeline definitions are incompatible."""


class ActiveMigrationJobConflictError(ControlTowerApplicationError):
    """Raised when a nonterminal migration job already occupies the active slot."""


class RepositoryIntegrityError(ControlTowerApplicationError):
    """Raised for integrity failures that are not mapped to a narrower error."""
