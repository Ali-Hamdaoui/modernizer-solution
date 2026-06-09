"""Typed domain errors for the AI Migration Control Tower."""

from __future__ import annotations

from migration_factory.control_tower.domain.states import JobState


class ControlTowerDomainError(Exception):
    """Base exception for Control Tower domain failures."""


class NotFoundError(ControlTowerDomainError):
    """Raised when a requested Control Tower record does not exist."""


class RegistrationConflictError(ControlTowerDomainError):
    """Raised when an immutable configuration version is registered with changed content."""

    def __init__(self, entity_type: str, entity_id: str, version: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.version = version
        super().__init__(
            f"{entity_type} {entity_id!r} version {version!r} is already registered with different content"
        )


class InvalidJobStateTransitionError(ControlTowerDomainError):
    """Raised when a requested job state transition is not allowed."""

    def __init__(self, current_state: JobState, requested_state: JobState) -> None:
        self.current_state = current_state
        self.requested_state = requested_state
        super().__init__(
            "Invalid job state transition: "
            f"{current_state.value} -> {requested_state.value}"
        )
