from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from migration_factory.copilot_assist.service import COPILOT_STATE_FIELDS, CopilotAssistService
from migration_factory.orchestrator.state import MigrationState
from migration_factory.orchestrator.summary import write_orchestration_summary


OFFICIAL_STATE_FIELDS = {
    "analysis_status",
    "planning_status",
    "assessment_status",
    "orchestration_status",
    "approval_status",
    "approval_decision",
    "approved_by",
    "approval_comments",
    "final_status",
    "transform_status",
    "build_status",
    "test_status",
    "test_totals",
    "test_report_path",
    "test_summary_path",
    "test_log_path",
    "test_phase",
    "sandbox_path",
    "transform_log_path",
    "stop_reason",
    "blockers",
    "warnings",
    "errors",
    "artifact_refs",
    "analysis_artifacts_valid",
    "planning_artifacts_valid",
    "assessment_artifacts_valid",
    "orchestration_artifacts_valid",
}

COPILOT_GRAPH_FIELDS = {
    *COPILOT_STATE_FIELDS,
    "copilot_assist_phase",
    "copilot_route_after_assist",
    "copilot_validation_had_warnings",
}


def copilot_phase_assist(state: MigrationState) -> MigrationState:
    """Run advisory phase assist without allowing official state mutation."""

    phase = str(state.get("copilot_assist_phase") or state.get("current_phase") or state.get("current_unit") or "")
    result: dict[str, Any] = dict(state)
    official_before = _snapshot_official(result)

    working = deepcopy(result)
    CopilotAssistService(working).generate_phase_assist(working, phase)
    _copy_copilot_fields(result, working)
    _restore_official_fields(result, official_before)
    return result  # type: ignore[return-value]


def copilot_final_report(state: MigrationState) -> MigrationState:
    """Run optional advisory final report after deterministic report context exists."""

    result: dict[str, Any] = dict(state)
    official_before = _snapshot_official(result)
    context_path = Path(str(result.get("run_dir") or "")) / "final" / "report_context.json"

    working = deepcopy(result)
    if context_path.is_file():
        CopilotAssistService(working).generate_final_report(working)
    else:
        working.setdefault("copilot_phase_statuses", {})
        working.setdefault("copilot_errors", [])
        working.setdefault("copilot_warnings", [])
        working["copilot_phase_statuses"]["final"] = "skipped"
        warning = "missing required final/report_context.json"
        working["copilot_errors"].append(warning)
        working["copilot_warnings"].append(warning)

    _copy_copilot_fields(result, working)
    _restore_official_fields(result, official_before)
    write_orchestration_summary(result)  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


def _snapshot_official(state: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(state.get(key)) for key in OFFICIAL_STATE_FIELDS if key in state}


def _restore_official_fields(state: dict[str, Any], snapshot: dict[str, Any]) -> None:
    for key in OFFICIAL_STATE_FIELDS:
        if key in snapshot:
            state[key] = deepcopy(snapshot[key])
        else:
            state.pop(key, None)


def _copy_copilot_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in COPILOT_GRAPH_FIELDS:
        if key in source:
            target[key] = deepcopy(source[key])
