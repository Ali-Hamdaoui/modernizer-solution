"""Domain contracts for the AI Migration Control Tower."""

from migration_factory.control_tower.domain.errors import (
    ArtifactHashError,
    ArtifactPathError,
    ControlTowerDomainError,
    ControlTowerError,
    CompatibilityError,
    ConcurrencyConflictError,
    InvalidJobStateTransitionError,
    NotFoundError,
    StaleVersionError,
    StorageIntegrityError,
)
from migration_factory.control_tower.domain.checksums import (
    canonical_json_bytes,
    canonical_json_text,
    sha256_canonical_json,
    sha256_hex,
    stream_sha256,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import (
    AuditRecord,
    MigrationJobRecord,
    PipelineDefinitionRecord,
    RunConfigurationRecord,
    RunEventRecord,
    RunnerProfileRecord,
    StageRunRecord,
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
    "ArtifactHashError",
    "ArtifactPathError",
    "AuditRecord",
    "MigrationJobRecord",
    "PipelineDefinitionRecord",
    "RunConfigurationRecord",
    "RunEventRecord",
    "RunnerProfileRecord",
    "StageRunRecord",
    "CompatibilityError",
    "ConcurrencyConflictError",
    "ControlTowerDomainError",
    "ControlTowerError",
    "NotFoundError",
    "StaleVersionError",
    "StorageIntegrityError",
    "canonical_json_bytes",
    "canonical_json_text",
    "InvalidJobStateTransitionError",
    "JOB_STATE_TRANSITIONS",
    "JobState",
    "StageState",
    "TERMINAL_JOB_STATES",
    "TargetProofLevel",
    "sha256_canonical_json",
    "sha256_hex",
    "stream_sha256",
    "allowed_job_transitions_from",
    "can_transition_job_state",
    "is_terminal_job_state",
    "utc_now_text",
    "validate_job_state_transition",
]
