"""Domain contracts for the AI Migration Control Tower."""

from migration_factory.control_tower.domain.errors import (
    ArtifactChangedDuringHashingError,
    ArtifactEscapedRootError,
    ArtifactIsNotAFileError,
    ArtifactNotFoundError,
    ControlTowerDomainError,
    InvalidJobStateTransitionError,
    UnknownRegisteredRootError,
    UnsafeArtifactPathError,
    UnsafeSymlinkOrReparsePointError,
    UnsupportedArtifactPathError,
)
from migration_factory.control_tower.domain.states import (
    JobState,
    StageState,
    TargetProofLevel,
)
from migration_factory.control_tower.domain.transitions import (
    JOB_STATE_TRANSITIONS,
    TERMINAL_JOB_STATES,
    allowed_job_transitions_from,
    can_transition_job_state,
    is_terminal_job_state,
    validate_job_state_transition,
)

__all__ = [
    "ControlTowerDomainError",
    "ArtifactChangedDuringHashingError",
    "ArtifactEscapedRootError",
    "ArtifactIsNotAFileError",
    "ArtifactNotFoundError",
    "InvalidJobStateTransitionError",
    "JOB_STATE_TRANSITIONS",
    "JobState",
    "StageState",
    "TERMINAL_JOB_STATES",
    "TargetProofLevel",
    "UnknownRegisteredRootError",
    "UnsafeArtifactPathError",
    "UnsafeSymlinkOrReparsePointError",
    "UnsupportedArtifactPathError",
    "allowed_job_transitions_from",
    "can_transition_job_state",
    "is_terminal_job_state",
    "validate_job_state_transition",
]
