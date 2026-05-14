from typing import Literal, TypedDict

PhaseStatus = Literal["PENDING", "PASS", "FAIL"]
ApprovalStatus = Literal["pending", "approved", "rejected", "replan"]


class MigrationState(TypedDict, total=False):
    run_id: str
    legacy_app_path: str
    modernized_app_path: str
    ai_hub_path: str
    profile: str
    thread_id: str
    current_unit: str
    analysis_status: PhaseStatus
    planning_status: PhaseStatus
    approval_status: ApprovalStatus
    transformation_status: PhaseStatus
    errors: list[str]
