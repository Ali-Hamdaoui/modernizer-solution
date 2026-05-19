from pathlib import Path
from typing import Literal, TypedDict

READ_ONLY_ASSESSMENT_MODE = "read_only_assessment"

PHASE_STATUS_VALUES = {"PENDING", "RUNNING", "PASS", "FAIL", "SKIPPED"}
APPROVAL_STATUS_VALUES = {"PENDING", "INTERRUPTED", "COMPLETED", "FAILED"}
APPROVAL_DECISION_VALUES = {"approved", "rejected", "replan_required"}

PhaseStatus = Literal["PENDING", "RUNNING", "PASS", "FAIL", "SKIPPED"]
ApprovalStatus = Literal["PENDING", "INTERRUPTED", "COMPLETED", "FAILED"]
ApprovalDecision = Literal["approved", "rejected", "replan_required"]


class MigrationState(TypedDict, total=False):
    run_id: str
    mode: str
    legacy_app_path: str
    modernized_app_path: str
    ai_hub_path: str
    profile_id: str
    thread_id: str
    current_unit: str

    analysis_status: PhaseStatus
    planning_status: PhaseStatus
    assessment_status: PhaseStatus
    orchestration_status: PhaseStatus

    approval_status: ApprovalStatus
    approval_decision: ApprovalDecision | None

    stop_reason: str | None
    blockers: list[str]
    warnings: list[str]
    errors: list[str]

    artifact_refs: dict[str, str]
    analysis_artifacts_valid: bool
    planning_artifacts_valid: bool
    assessment_artifacts_valid: bool
    orchestration_artifacts_valid: bool

    run_dir: str
    analysis_dir: str
    planning_dir: str
    assessment_dir: str
    orchestration_dir: str


def build_initial_state(
    *,
    run_id: str,
    legacy_app_path: str,
    modernized_app_path: str,
    ai_hub_path: str = "",
    profile_id: str = "",
    thread_id: str = "",
    mode: str = READ_ONLY_ASSESSMENT_MODE,
) -> MigrationState:
    run_dir = Path(modernized_app_path) / ".migration" / "runs" / run_id

    return {
        "run_id": run_id,
        "mode": mode,
        "legacy_app_path": str(legacy_app_path),
        "modernized_app_path": str(modernized_app_path),
        "ai_hub_path": str(ai_hub_path),
        "profile_id": profile_id,
        "thread_id": thread_id,
        "current_unit": "",
        "analysis_status": "PENDING",
        "planning_status": "PENDING",
        "assessment_status": "PENDING",
        "orchestration_status": "PENDING",
        "approval_status": "PENDING",
        "approval_decision": None,
        "stop_reason": None,
        "blockers": [],
        "warnings": [],
        "errors": [],
        "artifact_refs": {},
        "analysis_artifacts_valid": False,
        "planning_artifacts_valid": False,
        "assessment_artifacts_valid": False,
        "orchestration_artifacts_valid": False,
        "run_dir": str(run_dir),
        "analysis_dir": str(run_dir / "analysis"),
        "planning_dir": str(run_dir / "planning"),
        "assessment_dir": str(run_dir / "assessment"),
        "orchestration_dir": str(run_dir / "orchestration"),
    }
