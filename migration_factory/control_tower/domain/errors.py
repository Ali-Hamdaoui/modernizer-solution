"""Typed domain errors for the AI Migration Control Tower."""

from __future__ import annotations

from migration_factory.control_tower.domain.states import JobState


class ControlTowerError(Exception):
    """Base exception for Control Tower failures."""


class ControlTowerDomainError(ControlTowerError):
    """Base exception for Control Tower domain failures."""


class NotFoundError(ControlTowerDomainError):
    """Raised when a required Control Tower record is missing."""

    def __init__(self, entity_name: str, identifier: str | None = None) -> None:
        self.entity_name = entity_name
        self.identifier = identifier
        message = entity_name if identifier is None else f"{entity_name} not found: {identifier}"
        super().__init__(message)


class RegistrationConflictError(ControlTowerDomainError):
    """Raised when an immutable configuration version is registered with changed content."""

    def __init__(self, entity_type: str, entity_id: str, version: str) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.version = version
        super().__init__(
            f"{entity_type} {entity_id!r} version {version!r} is already registered with different content"
        )


class ExpectedVersionRequiredError(ControlTowerDomainError):
    """Raised when an optimistic transition command omits expected_version."""

    def __init__(self) -> None:
        super().__init__("expected_version is required")


class StaleVersionError(ControlTowerDomainError):
    """Raised when a transition uses a job version that is no longer current."""

    def __init__(self, job_id: str, expected_version: int, actual_version: int | None) -> None:
        self.job_id = job_id
        self.expected_version = expected_version
        self.actual_version = actual_version
        actual = "missing" if actual_version is None else str(actual_version)
        super().__init__(
            f"Stale version for job {job_id!r}: expected {expected_version}, actual {actual}"
        )


class ConcurrencyConflictError(ControlTowerDomainError):
    """Raised when database-enforced single-writer invariants reject a change."""


class InvalidJobStateTransitionError(ControlTowerDomainError):
    """Raised when a requested job state transition is not allowed."""

    def __init__(self, current_state: JobState, requested_state: JobState) -> None:
        self.current_state = current_state
        self.requested_state = requested_state
        super().__init__(
            "Invalid job state transition: "
            f"{current_state.value} -> {requested_state.value}"
        )


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
