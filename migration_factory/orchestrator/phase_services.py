from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.orchestrator.state import MigrationState


PhaseCallable = Callable[[MigrationState], MigrationState]


@dataclass(frozen=True)
class PhaseServices:
    run_analysis_phase: PhaseCallable
    run_planning_phase: PhaseCallable
    run_assessment_phase: PhaseCallable


def default_phase_services() -> PhaseServices:
    return PhaseServices(
        run_analysis_phase=run_analysis_phase,
        run_planning_phase=run_planning_phase,
        run_assessment_phase=run_assessment_phase,
    )


def run_analysis_phase(state: MigrationState) -> MigrationState:
    return _run_phase(
        state,
        phase="analysis",
        status_key="analysis_status",
        service=_run_analysis_service,
    )


def run_planning_phase(state: MigrationState) -> MigrationState:
    return _run_phase(
        state,
        phase="planning",
        status_key="planning_status",
        service=_run_planning_service,
    )


def run_assessment_phase(state: MigrationState) -> MigrationState:
    return _run_phase(
        state,
        phase="assessment",
        status_key="assessment_status",
        service=_run_assessment_service,
    )


def _run_phase(
    state: MigrationState,
    *,
    phase: str,
    status_key: str,
    service: PhaseCallable,
) -> MigrationState:
    running_state = _with_phase_status(state, phase=phase, status_key=status_key, status="RUNNING")
    try:
        service_result = service(running_state)
    except Exception as exc:
        message = f"{phase} phase failed: {exc}"
        return _with_phase_failure(
            running_state,
            phase=phase,
            status_key=status_key,
            message=message,
        )

    result = _merge_state(running_state, service_result)
    if result.get(status_key) == "FAIL":
        message = f"{phase} phase failed"
        return _ensure_failure_details(
            result,
            phase=phase,
            status_key=status_key,
            message=message,
        )

    result[status_key] = "PASS"  # type: ignore[literal-required]
    result["current_phase"] = phase  # type: ignore[typeddict-unknown-key]
    return result


def _run_analysis_service(state: MigrationState) -> MigrationState:
    analysis_root = Path(__file__).resolve().parents[1] / "agents" / "analysis_agent" / "analysis_agent"
    sys.path.insert(0, str(analysis_root))
    try:
        context_module = importlib.import_module("context_manager")
        main_module = importlib.import_module("main")
        context = context_module.MigrationContext(
            state.get("run_id", ""),
            state.get("legacy_app_path", ""),
            state.get("modernized_app_path", ""),
            state.get("ai_hub_path") or None,
            state.get("profile_id") or None,
        )
        result = main_module.run_analysis_agent(context)
    finally:
        try:
            sys.path.remove(str(analysis_root))
        except ValueError:
            pass

    errors = list(getattr(result, "errors", []) or [])
    warnings = list(getattr(result, "warnings", []) or [])
    status = "PASS" if getattr(result, "status", "") == "COMPLETED" and not errors else "FAIL"
    return {
        "analysis_status": status,
        "current_unit": "analysis",
        "errors": errors,
        "blockers": list(errors),
        "warnings": warnings,
        "artifact_refs": dict(getattr(result, "artifact_paths", {}) or {}),
    }


def _run_planning_service(state: MigrationState) -> MigrationState:
    from migration_factory.agents.planning_agent.node import planning_node

    return planning_node(state)


def _run_assessment_service(state: MigrationState) -> MigrationState:
    from migration_factory.assessment import write_assessment_artifacts

    result = write_assessment_artifacts(
        Path(state.get("modernized_app_path", "")),
        state.get("run_id", ""),
    )
    artifact_refs = dict(state.get("artifact_refs", {}) or {})
    artifact_refs.update(
        {
            "assessment_report": str(result.report_path),
            "assessment_summary": str(result.summary_path),
        }
    )
    return {
        "assessment_status": "PASS",
        "current_unit": "assessment",
        "artifact_refs": artifact_refs,
    }


def _with_phase_status(
    state: MigrationState,
    *,
    phase: str,
    status_key: str,
    status: str,
) -> MigrationState:
    result = dict(state)
    result[status_key] = status
    result["current_phase"] = phase
    return result  # type: ignore[return-value]


def _with_phase_failure(
    state: MigrationState,
    *,
    phase: str,
    status_key: str,
    message: str,
) -> MigrationState:
    result = _with_phase_status(state, phase=phase, status_key=status_key, status="FAIL")
    result["errors"] = [*list(state.get("errors", []) or []), message]
    result["blockers"] = [*list(state.get("blockers", []) or []), message]
    result["current_unit"] = phase
    return result


def _ensure_failure_details(
    state: MigrationState,
    *,
    phase: str,
    status_key: str,
    message: str,
) -> MigrationState:
    result = _with_phase_status(state, phase=phase, status_key=status_key, status="FAIL")
    errors = list(result.get("errors", []) or [])
    blockers = list(result.get("blockers", []) or [])
    if not errors:
        errors.append(message)
    if not blockers:
        blockers.append(message)
    result["errors"] = errors
    result["blockers"] = blockers
    result["current_unit"] = phase
    return result


def _merge_state(state: MigrationState, service_result: MigrationState | dict[str, Any]) -> MigrationState:
    result = dict(state)
    result.update(service_result)
    return result  # type: ignore[return-value]
