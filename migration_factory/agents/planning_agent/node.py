from migration_factory.agents.planning_agent.assist_config import (
    load_planning_assist_config,
)
from migration_factory.agents.planning_agent.copilot_assist_client import (
    CopilotPlanningAssistClient,
)
from migration_factory.contracts.planning_assist import PlanningAssistRequest
from migration_factory.orchestrator.state import MigrationState


def planning_node(state: MigrationState) -> MigrationState:
    config = load_planning_assist_config()
    request = PlanningAssistRequest(
        run_id=state.get("run_id", ""),
        agent="planning_agent",
        phase="planning",
        model=config.model_override,
        prompt="Review planning output for advisory feedback only.",
        context={"state_keys": sorted(state.keys())},
        allowed_fields=["warnings", "approval_summary", "operator_notes", "risks"],
        forbidden_fields=[
            "unit_order",
            "tools",
            "blockers",
            "approval_required",
            "executable",
        ],
    )
    assist_result = CopilotPlanningAssistClient().review_plan(
        request=request, config=config
    )

    return {
        "planning_status": "PASS",
        "current_unit": "planning",
        "planning_assist_status": assist_result.status,
        "planning_assist_error": assist_result.error,
        "planning_assist_warnings": assist_result.warnings,
    }
