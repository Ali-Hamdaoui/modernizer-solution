"""Domain contracts for the AI Migration Control Tower."""

from migration_factory.control_tower.domain.errors import (
    ControlTowerDomainError,
    InvalidJobStateTransitionError,
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
    "InvalidJobStateTransitionError",
    "JOB_STATE_TRANSITIONS",
    "JobState",
    "StageState",
    "TERMINAL_JOB_STATES",
    "TargetProofLevel",
    "allowed_job_transitions_from",
    "can_transition_job_state",
    "is_terminal_job_state",
    "validate_job_state_transition",
]

