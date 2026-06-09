"""Typed domain errors for the AI Migration Control Tower."""

from __future__ import annotations

from migration_factory.control_tower.domain.states import JobState


class ControlTowerError(Exception):
    """Base exception for Control Tower failures."""


class ControlTowerDomainError(ControlTowerError):
    """Base exception for Control Tower domain failures."""


class InvalidJobStateTransitionError(ControlTowerDomainError):
    """Raised when a requested job state transition is not allowed."""

    def __init__(self, current_state: JobState, requested_state: JobState) -> None:
        self.current_state = current_state
        self.requested_state = requested_state
        super().__init__(
            "Invalid job state transition: "
            f"{current_state.value} -> {requested_state.value}"
        )


class NotFoundError(ControlTowerError):
    """Raised when a required Control Tower record is missing."""

    def __init__(self, entity_name: str, identifier: str) -> None:
        self.entity_name = entity_name
        self.identifier = identifier
        super().__init__(f"{entity_name} not found: {identifier}")


class StaleVersionError(ControlTowerError):
    """Raised when an optimistic version check fails."""


class ConcurrencyConflictError(ControlTowerError):
    """Raised when the active-job slot is already occupied."""


class CompatibilityError(ControlTowerError):
    """Raised when loaded configuration objects cannot be combined safely."""


class ArtifactPathError(ControlTowerError):
    """Raised when an artifact path is not trusted."""


class ArtifactHashError(ControlTowerError):
    """Raised when artifact hashing detects a race or mismatch."""


class StorageIntegrityError(ControlTowerError):
    """Raised when a persistence layer integrity violation cannot be classified."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
