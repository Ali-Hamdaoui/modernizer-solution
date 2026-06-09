"""Typed domain errors for the AI Migration Control Tower."""

from __future__ import annotations

from migration_factory.control_tower.domain.states import JobState


class ControlTowerDomainError(Exception):
    """Base exception for Control Tower domain failures."""


class UnknownRegisteredRootError(ControlTowerDomainError):
    """Raised when an artifact references an unknown registered root."""

    def __init__(self, registered_root_id: str) -> None:
        self.registered_root_id = registered_root_id
        super().__init__(f"Unknown registered root: {registered_root_id}")


class UnsupportedArtifactPathError(ControlTowerDomainError):
    """Raised when an artifact path uses an unsupported form."""

    def __init__(self, artifact_path: str, reason: str) -> None:
        self.artifact_path = artifact_path
        self.reason = reason
        super().__init__(f"Unsupported artifact path {artifact_path!r}: {reason}")


class UnsafeArtifactPathError(ControlTowerDomainError):
    """Raised when an artifact path violates traversal or root safety rules."""

    def __init__(self, artifact_path: str, reason: str) -> None:
        self.artifact_path = artifact_path
        self.reason = reason
        super().__init__(f"Unsafe artifact path {artifact_path!r}: {reason}")


class ArtifactNotFoundError(ControlTowerDomainError):
    """Raised when an expected artifact file does not exist."""

    def __init__(self, artifact_path: str) -> None:
        self.artifact_path = artifact_path
        super().__init__(f"Artifact not found: {artifact_path}")


class ArtifactIsNotAFileError(ControlTowerDomainError):
    """Raised when an artifact path resolves to a directory instead of a file."""

    def __init__(self, artifact_path: str) -> None:
        self.artifact_path = artifact_path
        super().__init__(f"Artifact is not a file: {artifact_path}")


class ArtifactEscapedRootError(ControlTowerDomainError):
    """Raised when a resolved artifact path escapes its registered root."""

    def __init__(self, artifact_path: str, registered_root_id: str) -> None:
        self.artifact_path = artifact_path
        self.registered_root_id = registered_root_id
        super().__init__(
            f"Artifact escaped registered root {registered_root_id}: {artifact_path}"
        )


class UnsafeSymlinkOrReparsePointError(ControlTowerDomainError):
    """Raised when an artifact path traverses an unsafe symlink or reparse point."""

    def __init__(self, artifact_path: str, component: str) -> None:
        self.artifact_path = artifact_path
        self.component = component
        super().__init__(
            f"Unsafe symlink or reparse point in artifact path {artifact_path!r}: {component}"
        )


class ArtifactChangedDuringHashingError(ControlTowerDomainError):
    """Raised when artifact metadata changes during streamed hashing."""

    def __init__(self, artifact_path: str, reason: str) -> None:
        self.artifact_path = artifact_path
        self.reason = reason
        super().__init__(f"Artifact changed during hashing {artifact_path!r}: {reason}")


class InvalidJobStateTransitionError(ControlTowerDomainError):
    """Raised when a requested job state transition is not allowed."""

    def __init__(self, current_state: JobState, requested_state: JobState) -> None:
        self.current_state = current_state
        self.requested_state = requested_state
        super().__init__(
            "Invalid job state transition: "
            f"{current_state.value} -> {requested_state.value}"
        )
