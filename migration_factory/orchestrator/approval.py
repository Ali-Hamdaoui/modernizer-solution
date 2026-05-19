from typing import Any

from langgraph.types import interrupt

from migration_factory.orchestrator.state import (
    APPROVAL_DECISION_VALUES,
    MigrationState,
)

DECISION_OPTIONS = ["approved", "rejected", "replan_required"]


def build_approval_payload(state: MigrationState) -> dict[str, Any]:
    summary = {
        key: state[key]
        for key in (
            "analysis_status",
            "planning_status",
            "assessment_status",
            "orchestration_status",
        )
        if key in state
    }

    return {
        "type": "human_approval_required",
        "run_id": state.get("run_id", ""),
        "summary": summary,
        "artifact_refs": dict(state.get("artifact_refs", {})),
        "blockers": list(state.get("blockers", [])),
        "warnings": list(state.get("warnings", [])),
        "decision_options": DECISION_OPTIONS,
    }


def approval_node(state: MigrationState) -> MigrationState:
    resume_payload = interrupt(build_approval_payload(state))
    decision = (
        resume_payload.get("decision")
        if isinstance(resume_payload, dict)
        else None
    )

    if decision in APPROVAL_DECISION_VALUES:
        return {
            "approval_status": "COMPLETED",
            "approval_decision": decision,
            "current_phase": "approval",
            "stop_reason": f"Approval decision '{decision}' received; stopping.",
        }

    message = f"Invalid approval decision: {decision!r}"
    return {
        "approval_status": "FAILED",
        "approval_decision": None,
        "current_phase": "approval",
        "stop_reason": message,
        "blockers": [*state.get("blockers", []), message],
        "errors": [*state.get("errors", []), message],
    }
