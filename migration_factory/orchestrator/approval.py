from langgraph.types import interrupt

from migration_factory.orchestrator.state import MigrationState

_ALLOWED = {"approve", "reject", "replan"}
_MAP = {
    "approve": "approved",
    "reject": "rejected",
    "replan": "replan",
}


def approval_node(state: MigrationState) -> MigrationState:
    decision = state.get("approval_status")

    if decision in _MAP.values():
        return {
            "approval_status": decision,
            "current_unit": "approval",
        }

    user_decision = interrupt(
        {
            "message": "Approval decision required",
            "decisions": sorted(_ALLOWED),
        }
    )

    if user_decision not in _ALLOWED:
        errors = list(state.get("errors", []))
        errors.append(f"Invalid approval decision: {user_decision}")
        return {
            "approval_status": "rejected",
            "current_unit": "approval",
            "errors": errors,
        }

    return {
        "approval_status": _MAP[user_decision],
        "current_unit": "approval",
    }
