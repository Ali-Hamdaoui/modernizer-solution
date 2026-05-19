from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from migration_factory.orchestrator.approval import approval_node
from migration_factory.orchestrator.artifact_validation import (
    ArtifactValidationResult,
    validate_analysis_artifacts,
    validate_assessment_artifacts,
    validate_planning_artifacts,
)
from migration_factory.orchestrator.phase_services import (
    PhaseServices,
    default_phase_services,
    record_approval_decision_phase,
    run_sandbox_transform_phase,
)
from migration_factory.orchestrator.state import MigrationState
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE


ValidationCallable = Callable[[MigrationState], ArtifactValidationResult]


def build_graph(
    checkpointer=None,
    phase_services: PhaseServices | None = None,
    approval_record_service=None,
    sandbox_transform_service=None,
):
    services = phase_services or default_phase_services()

    graph = StateGraph(MigrationState)
    graph.add_node(
        "analysis",
        _phase_node(
            services.run_analysis_phase,
            validate_analysis_artifacts,
            artifacts_valid_key="analysis_artifacts_valid",
        ),
    )
    graph.add_node(
        "planning",
        _phase_node(
            services.run_planning_phase,
            validate_planning_artifacts,
            artifacts_valid_key="planning_artifacts_valid",
        ),
    )
    graph.add_node(
        "assessment",
        _phase_node(
            services.run_assessment_phase,
            validate_assessment_artifacts,
            artifacts_valid_key="assessment_artifacts_valid",
        ),
    )
    graph.add_node("approval", approval_node)
    graph.add_node(
        "approval_record",
        approval_record_service or record_approval_decision_phase,
    )
    graph.add_node(
        "sandbox_transform",
        sandbox_transform_service or run_sandbox_transform_phase,
    )

    graph.add_edge(START, "analysis")
    graph.add_conditional_edges(
        "analysis",
        _route_analysis,
        {"planning": "planning", END: END},
    )
    graph.add_conditional_edges(
        "planning",
        _route_planning,
        {"assessment": "assessment", END: END},
    )
    graph.add_conditional_edges(
        "assessment",
        _route_assessment,
        {"approval": "approval", END: END},
    )
    graph.add_conditional_edges(
        "approval",
        _route_after_approval,
        {"approval_record": "approval_record", END: END},
    )
    graph.add_conditional_edges(
        "approval_record",
        _route_after_approval_record,
        {"sandbox_transform": "sandbox_transform", END: END},
    )
    graph.add_edge("sandbox_transform", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def _phase_node(
    run_phase: Callable[[MigrationState], MigrationState],
    validate_artifacts: ValidationCallable,
    *,
    artifacts_valid_key: str,
):
    def node(state: MigrationState) -> MigrationState:
        result = dict(state)
        result.update(run_phase(state))

        validation = validate_artifacts(result)  # type: ignore[arg-type]
        result[artifacts_valid_key] = validation.valid
        result["artifact_refs"] = {
            **dict(result.get("artifact_refs", {}) or {}),
            **validation.artifact_refs,
        }
        result["blockers"] = [
            *list(result.get("blockers", []) or []),
            *validation.blockers,
        ]
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *validation.warnings,
        ]
        return result  # type: ignore[return-value]

    return node


def _route_analysis(state: MigrationState) -> str:
    if state.get("analysis_status") == "PASS" and state.get("analysis_artifacts_valid") is True:
        return "planning"
    return END


def _route_planning(state: MigrationState) -> str:
    if state.get("planning_status") == "PASS" and state.get("planning_artifacts_valid") is True:
        return "assessment"
    return END


def _route_assessment(state: MigrationState) -> str:
    if state.get("assessment_status") == "PASS" and state.get("assessment_artifacts_valid") is True:
        return "approval"
    return END


def _route_after_approval(state: MigrationState) -> str:
    if state.get("mode") == FULL_SANDBOX_MIGRATION_MODE and state.get("approval_status") == "COMPLETED":
        return "approval_record"
    return END


def _route_after_approval_record(state: MigrationState) -> str:
    if (
        state.get("mode") == FULL_SANDBOX_MIGRATION_MODE
        and state.get("approval_status") == "COMPLETED"
        and state.get("approval_decision") == "approved"
        and not state.get("errors")
        and state.get("orchestration_status") != "FAIL"
    ):
        return "sandbox_transform"
    return END
