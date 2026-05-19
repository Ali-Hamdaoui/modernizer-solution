from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from migration_factory.orchestrator.state import MigrationState


EXECUTION_CLAIMS = {
    "transformation_executed": False,
    "openrewrite_apply_executed": False,
    "migrated_build_executed": False,
    "migrated_tests_executed": False,
    "final_migration_executed": False,
}


def build_orchestration_summary(state: MigrationState) -> dict:
    return {
        "run_id": state.get("run_id", ""),
        "final_status": _final_status(state),
        "current_phase": state.get("current_phase", state.get("current_unit", "")),
        "analysis_status": state.get("analysis_status", ""),
        "planning_status": state.get("planning_status", ""),
        "assessment_status": state.get("assessment_status", ""),
        "approval_status": state.get("approval_status", ""),
        "approval_decision": state.get("approval_decision"),
        "stop_reason": state.get("stop_reason"),
        "blockers": list(state.get("blockers", []) or []),
        "warnings": list(state.get("warnings", []) or []),
        "errors": list(state.get("errors", []) or []),
        "artifact_refs": dict(state.get("artifact_refs", {}) or {}),
        **EXECUTION_CLAIMS,
    }


def write_orchestration_summary(state: MigrationState) -> Path:
    summary_path = Path(state["orchestration_dir"]) / "orchestration_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            _to_json_safe(build_orchestration_summary(state)),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary_path


def _final_status(state: MigrationState) -> str:
    if state.get("approval_status") == "FAILED":
        return "FAILED"
    if state.get("errors") or state.get("blockers"):
        return "FAILED"
    if any(
        state.get(status_key) == "FAIL"
        for status_key in ("analysis_status", "planning_status", "assessment_status")
    ):
        return "FAILED"
    if state.get("approval_status") == "INTERRUPTED":
        return "INTERRUPTED"
    if state.get("approval_status") == "COMPLETED":
        return "COMPLETED"
    return "COMPLETED"


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
