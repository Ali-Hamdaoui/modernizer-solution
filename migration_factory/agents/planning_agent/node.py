from migration_factory.agents.planning_agent.assist_config import (
    load_planning_assist_config,
)
from migration_factory.agents.planning_agent.artifact_reader import (
    load_analysis_artifacts,
)
from migration_factory.agents.planning_agent.analysis_validator import (
    validate_analysis_completeness,
)
from migration_factory.agents.planning_agent.copilot_assist_client import (
    CopilotPlanningAssistClient,
)
from migration_factory.agents.planning_agent.profile_reader import (
    load_migration_profile,
)
from migration_factory.contracts.planning_assist import PlanningAssistRequest
from migration_factory.orchestrator.state import MigrationState


def planning_node(state: MigrationState) -> MigrationState:
    loaded_artifacts = load_analysis_artifacts(
        modernized_app_path=state.get("modernized_app_path", ""),
        run_id=state.get("run_id", ""),
    )
    validation = validate_analysis_completeness(loaded_artifacts)
    if not validation.ok:
        errors = [*validation.errors]
        if validation.non_executable_reason:
            errors.append(f"Analysis not executable: {validation.non_executable_reason}")
        return {
            "planning_status": "FAIL",
            "current_unit": "planning",
            "errors": errors,
            "planning_assist_status": "SKIPPED",
            "planning_assist_error": "Planning skipped due to analysis artifact load failure.",
            "planning_assist_warnings": validation.warnings,
        }

    loaded_profile = load_migration_profile(
        ai_hub_path=state.get("ai_hub_path", ""),
        profile_id=state.get("profile", ""),
    )
    if not loaded_profile.ok:
        return {
            "planning_status": "FAIL",
            "current_unit": "planning",
            "errors": loaded_profile.errors,
            "planning_assist_status": "SKIPPED",
            "planning_assist_error": "Planning skipped due to migration profile load failure.",
            "planning_assist_warnings": [],
        }

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
