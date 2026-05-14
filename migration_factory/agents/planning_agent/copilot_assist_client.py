from migration_factory.agents.planning_agent.assist_config import PlanningAssistConfig
from migration_factory.contracts.planning_assist import (
    PlanningAssistRequest,
    PlanningAssistResult,
)


class CopilotPlanningAssistClient:
    """Provider-neutral planning assist interface. No external SDK calls yet."""

    def review_plan(
        self, request: PlanningAssistRequest, config: PlanningAssistConfig
    ) -> PlanningAssistResult:
        if not config.enabled:
            return PlanningAssistResult(
                status="SKIPPED",
                warnings=["Planning assist disabled by config."],
            )

        return PlanningAssistResult(
            status="FAILED",
            error=(
                "Planning assist provider not bound. "
                "No SDK/MCP adapter configured yet."
            ),
        )
