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
from migration_factory.agents.planning_agent.profile_compatibility import (
    validate_profile_compatibility,
)
from migration_factory.agents.planning_agent.plan_writer import (
    MigrationPlanPayload,
    write_migration_plan,
    write_migration_units,
)
from migration_factory.agents.planning_agent.approval_writer import (
    ApprovalRequestPayload,
    write_approval_request,
)
from migration_factory.agents.planning_agent.summary_writer import (
    PlanSummaryPayload,
    write_plan_summary,
)
from migration_factory.agents.planning_agent.output_validator import (
    validate_planning_outputs,
)
from migration_factory.agents.planning_agent.risk_classifier import (
    classify_planning_risks,
)
from migration_factory.agents.planning_agent.unit_builder import (
    build_migration_units,
)
from migration_factory.agents.planning_agent.profile_reader import (
    load_migration_profile,
)
from migration_factory.agents.planning_agent.assist_merge import (
    merge_advisory_assist_suggestions,
)
from migration_factory.contracts.planning_assist import (
    PlanningAssistRequest,
    PlanningAssistResult,
)
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

    compatibility = validate_profile_compatibility(loaded_artifacts, loaded_profile)
    if not compatibility.ok:
        return {
            "planning_status": "FAIL",
            "current_unit": "planning",
            "errors": compatibility.errors,
            "warnings": compatibility.warnings,
            "planning_assist_status": "SKIPPED",
            "planning_assist_error": "Planning skipped due to profile compatibility validation failure.",
            "planning_assist_warnings": compatibility.warnings,
        }

    risk_result = classify_planning_risks(loaded_artifacts, compatibility.source_stack)
    risk_messages = [f"[{risk.severity}] {risk.code}: {risk.message}" for risk in risk_result.risks]
    blocker_messages = [
        f"{risk.code}: {risk.message}"
        for risk in risk_result.risks
        if risk.severity == "BLOCKER"
    ]
    if blocker_messages:
        return {
            "planning_status": "FAIL",
            "current_unit": "planning",
            "errors": blocker_messages,
            "warnings": compatibility.warnings,
            "risks": risk_messages,
            "planning_assist_status": "SKIPPED",
            "planning_assist_error": "Planning skipped due to deterministic risk blockers.",
            "planning_assist_warnings": compatibility.warnings,
        }

    units = build_migration_units()
    write_migration_plan(
        modernized_app_path=state.get("modernized_app_path", ""),
        payload=MigrationPlanPayload(
            run_id=state.get("run_id", ""),
            profile=state.get("profile", ""),
            source_stack=compatibility.source_stack,
            target_stack=compatibility.target_stack,
            risks=tuple(risk_messages),
            blockers=(),
            warnings=tuple(compatibility.warnings),
            units=units,
        ),
    )
    write_migration_units(
        modernized_app_path=state.get("modernized_app_path", ""),
        run_id=state.get("run_id", ""),
        units=units,
    )
    deterministic_approval_summary = (
        f"Planning generated {len(units)} migration units for profile "
        f"{state.get('profile', '')}."
    )

    write_approval_request(
        modernized_app_path=state.get("modernized_app_path", ""),
        payload=ApprovalRequestPayload(
            run_id=state.get("run_id", ""),
            summary=deterministic_approval_summary,
            units=units,
            blockers=(),
            warnings=tuple(compatibility.warnings),
        ),
    )
    write_plan_summary(
        modernized_app_path=state.get("modernized_app_path", ""),
        payload=PlanSummaryPayload(
            run_id=state.get("run_id", ""),
            profile=state.get("profile", ""),
            source_stack=compatibility.source_stack,
            target_stack=compatibility.target_stack,
            risks=tuple(risk_messages),
            warnings=tuple(compatibility.warnings),
            units=units,
        ),
    )
    validation_result = validate_planning_outputs(
        modernized_app_path=state.get("modernized_app_path", ""),
        run_id=state.get("run_id", ""),
    )
    if validation_result.status != "PASS":
        return {
            "planning_status": "FAIL",
            "current_unit": "planning",
            "errors": list(validation_result.reasons),
            "warnings": compatibility.warnings,
            "risks": risk_messages,
            "planning_assist_status": "SKIPPED",
            "planning_assist_error": "Planning output validation failed.",
            "planning_assist_warnings": compatibility.warnings,
        }
    unit_payload = [
        {
            "id": unit.id,
            "goal": unit.goal,
            "writes_source": unit.writes_source,
            "tools": list(unit.tools),
            "validation": list(unit.validation),
            "required": unit.required,
        }
        for unit in units
    ]

    config = load_planning_assist_config()
    assist_result = PlanningAssistResult(status="SKIPPED")
    if not config.enabled:
        assist_result_status = "SKIPPED"
        assist_result_error = None
        assist_result_warnings = ["Planning assist disabled by config."]
    else:
        request = PlanningAssistRequest(
            run_id=state.get("run_id", ""),
            agent="planning_agent",
            phase="planning",
            model=config.model_override,
            prompt="Review planning output for advisory feedback only.",
            context={
                "profile": state.get("profile", ""),
                "source_stack": compatibility.source_stack,
                "target_stack": compatibility.target_stack,
                "risks": risk_messages,
                "warnings": list(compatibility.warnings),
                "migration_units": unit_payload,
                "approval_summary": deterministic_approval_summary,
            },
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
        assist_result_status = assist_result.status
        assist_result_error = assist_result.error
        assist_result_warnings = assist_result.warnings
    merged_output = merge_advisory_assist_suggestions(
        deterministic_approval_summary=deterministic_approval_summary,
        deterministic_warnings=list(compatibility.warnings),
        assist_result=assist_result,
    )
    if assist_result.status == "USED":
        assist_result_warnings = [
            *assist_result_warnings,
            (
                "[WARNING] Ignored attempted structural changes if present: unit_order, "
                "tools, blockers, approval_required, executable."
            ),
        ]

    return {
        "planning_status": "PASS",
        "current_unit": "planning",
        "warnings": merged_output.warnings,
        "planning_assist_status": assist_result_status,
        "planning_assist_error": assist_result_error,
        "risks": risk_messages,
        "migration_units": unit_payload,
        "planning_approval_summary": merged_output.approval_summary,
        "planning_operator_notes": merged_output.operator_notes,
        "planning_risk_explanations": merged_output.risk_explanations,
        "planning_assist_warnings": assist_result_warnings,
    }
