from typing import Literal, TypedDict

PhaseStatus = Literal["PENDING", "PASS", "FAIL"]
ApprovalStatus = Literal["pending", "approved", "rejected", "replan"]
AssistStatus = Literal["SKIPPED", "USED", "FAILED"]


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
    planning_assist_status: AssistStatus
    planning_assist_error: str
    planning_assist_warnings: list[str]
    errors: list[str]
