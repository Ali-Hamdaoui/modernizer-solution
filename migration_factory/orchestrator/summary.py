from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from migration_factory.agents.copilot_doc_agent import generate_copilot_documentation_package
from migration_factory.final_report import (
    detect_copilot_cli_status,
    generate_final_migration_report,
    write_report_context,
)
from migration_factory.final_report import copilot as copilot_report_module
from migration_factory.orchestrator.artifact_validation import (
    validate_successful_full_sandbox_orchestration,
)
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE
from migration_factory.orchestrator.state import MigrationState
from migration_factory.orchestrator.timing import record_phase_duration, write_timing_artifacts


EXECUTION_CLAIMS = {
    "transformation_executed": False,
    "openrewrite_apply_executed": False,
    "migrated_build_executed": False,
    "migrated_tests_executed": False,
    "final_migration_executed": False,
}
_COPILOT_REPORT_ENV = "AI_MIGRATION_ENABLE_COPILOT_REPORT"
_COPILOT_PROVIDER_ENV = "AI_MIGRATION_COPILOT_PROVIDER"
_COPILOT_TRUE_VALUES = {"1", "true", "yes", "on"}
_COPILOT_CLI_PROVIDER = "copilot_cli"


def build_orchestration_summary(state: MigrationState) -> dict:
    execution_claims = _execution_claims(state)
    return {
        "run_id": state.get("run_id", ""),
        "final_status": _final_status(state),
        "current_phase": state.get("current_phase", state.get("current_unit", "")),
        "analysis_status": state.get("analysis_status", ""),
        "planning_status": state.get("planning_status", ""),
        "assessment_status": state.get("assessment_status", ""),
        "orchestration_status": state.get("orchestration_status", ""),
        "approval_status": state.get("approval_status", ""),
        "approval_decision": state.get("approval_decision"),
        "approved_by": state.get("approved_by", ""),
        "transform_status": state.get("transform_status", ""),
        "build_status": state.get("build_status", ""),
        "test_status": state.get("test_status", ""),
        "test_totals": dict(state.get("test_totals", {}) or {}),
        "test_report_path": state.get("test_report_path", ""),
        "test_summary_path": state.get("test_summary_path", ""),
        "test_log_path": state.get("test_log_path", ""),
        "test_phase": state.get("test_phase", ""),
        "sandbox_path": state.get("sandbox_path", ""),
        "log_path": state.get("transform_log_path", ""),
        "stop_reason": state.get("stop_reason"),
        "blockers": list(state.get("blockers", []) or []),
        "warnings": list(state.get("warnings", []) or []),
        "errors": list(state.get("errors", []) or []),
        "artifact_refs": dict(state.get("artifact_refs", {}) or {}),
        "copilot_phase_statuses": dict(state.get("copilot_phase_statuses", {}) or {}),
        "copilot_artifact_refs": dict(state.get("copilot_artifact_refs", {}) or {}),
        "copilot_warnings": list(state.get("copilot_warnings", []) or []),
        "copilot_errors": list(state.get("copilot_errors", []) or []),
        "copilot_fallback_used": bool(state.get("copilot_fallback_used", False)),
        "timing": dict(state.get("timing", {}) or {}),
        **execution_claims,
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


def finalize_orchestration_state(
    state: MigrationState,
    *,
    summary_writer=write_orchestration_summary,
) -> MigrationState:
    result = dict(state)
    summary_path = Path(str(result.get("orchestration_dir", ""))) / "orchestration_summary.json"
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    artifact_refs["orchestration_summary"] = str(summary_path)
    result["artifact_refs"] = artifact_refs

    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**result["artifact_refs"], **timing_refs}

    if not _is_successful_full_sandbox_migration(result):  # type: ignore[arg-type]
        result["orchestration_artifacts_valid"] = False
        summary_writer(result)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]

    summary_writer(result)  # type: ignore[arg-type]
    final_report_started = time.monotonic()
    final_report = generate_final_migration_report(result)
    record_phase_duration(result, phase="final_report", duration_seconds=time.monotonic() - final_report_started)
    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**dict(result.get("artifact_refs", {}) or {}), **timing_refs}
    if final_report.blockers:
        result["blockers"] = [
            *list(result.get("blockers", []) or []),
            *final_report.blockers,
        ]
        result["orchestration_status"] = "FAIL"
        result["final_status"] = "FAILED"
        result["orchestration_artifacts_valid"] = False
        summary_writer(result)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]
    if final_report.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *final_report.warnings,
        ]
    artifact_refs = {
        **dict(result.get("artifact_refs", {}) or {}),
        **final_report.artifact_refs,
    }
    result["artifact_refs"] = artifact_refs

    report_context_path = write_report_context(result["run_dir"])
    result["artifact_refs"] = {
        **dict(result.get("artifact_refs", {}) or {}),
        "copilot_report_context": str(report_context_path),
    }
    _maybe_generate_copilot_final_report(result)
    _generate_copilot_docs(result)

    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**dict(result.get("artifact_refs", {}) or {}), **timing_refs}
    summary_writer(result)  # type: ignore[arg-type]
    validation = validate_successful_full_sandbox_orchestration(result)  # type: ignore[arg-type]
    result["orchestration_artifacts_valid"] = validation.valid
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    result["artifact_refs"] = {
        **artifact_refs,
        **validation.artifact_refs,
    }
    if validation.blockers:
        result["blockers"] = [
            *list(result.get("blockers", []) or []),
            *validation.blockers,
        ]
    if validation.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *validation.warnings,
        ]
    summary_writer(result)  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


def _maybe_generate_copilot_final_report(state: dict[str, Any]) -> None:
    if os.getenv(_COPILOT_REPORT_ENV, "").strip().lower() not in _COPILOT_TRUE_VALUES:
        return

    try:
        status = None
        if os.getenv(_COPILOT_PROVIDER_ENV, "").strip().lower() == _COPILOT_CLI_PROVIDER:
            status = detect_copilot_cli_status(
                timeout_seconds=15.0,
                env=os.environ,
            )
        else:
            status = copilot_report_module.CopilotAdapterStatus(
                model=str(state.get("copilot_model") or "gpt-5-mini"),
                connectivity="not_configured",
                report_status="generated",
            )
        result = getattr(copilot_report_module, "generate_copilot_report")(
            state.get("run_dir", ""),
            _copilot_report_ai_hub(state),
            context=_copilot_report_context(state),
            status=status,
            timeout_seconds=float(state.get("copilot_timeout_seconds") or 300),
            env=os.environ,
        )
    except Exception as exc:
        fallback = copilot_report_module.write_failed_copilot_report_response(
            state.get("run_dir", ""),
            _copilot_report_ai_hub(state),
            warning=f"copilot final report generation failed: {exc}",
        )
        _merge_copilot_report_result(state, fallback)
        return

    _merge_copilot_report_result(state, result)


def _merge_copilot_report_result(state: dict[str, Any], result: dict[str, Any]) -> None:
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    state["artifact_refs"] = {
        **dict(state.get("artifact_refs", {}) or {}),
        **artifact_refs,
    }
    if result.get("warnings"):
        state["warnings"] = [
            *list(state.get("warnings", []) or []),
            *list(result.get("warnings", []) or []),
        ]


def _generate_copilot_docs(state: dict[str, Any]) -> None:
    result = generate_copilot_documentation_package(state)
    if result.blockers:
        state["warnings"] = [
            *list(state.get("warnings", []) or []),
            "copilot documentation generation skipped: " + "; ".join(result.blockers),
            *result.warnings,
        ]
        return
    state["artifact_refs"] = {
        **dict(state.get("artifact_refs", {}) or {}),
        **result.artifact_refs,
    }
    if result.warnings:
        state["warnings"] = [
            *list(state.get("warnings", []) or []),
            *result.warnings,
        ]


def _copilot_report_context(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": state.get("run_id", ""),
        "profile_id": state.get("profile_id", ""),
        "mode": state.get("mode", ""),
        "legacy_app_path": state.get("legacy_app_path", ""),
        "sandbox_path": state.get("sandbox_path", ""),
        "preflight_status": state.get("preflight_status", ""),
        "analysis_status": state.get("analysis_status", ""),
        "planning_status": state.get("planning_status", ""),
        "assessment_status": state.get("assessment_status", ""),
        "final_verdict": state.get("final_status", ""),
    }


def _copilot_report_ai_hub(state: dict[str, Any]) -> str:
    configured = Path(str(state.get("ai_hub_path") or ""))
    manifest = configured / "templates" / "reports" / "copilot_final_migration_report_v1.yaml"
    if configured.is_dir() and manifest.is_file():
        return str(configured)
    repo_hub = Path(__file__).resolve().parents[2] / "modernizer-solution-ai-hub"
    return str(repo_hub)


def _final_status(state: MigrationState) -> str:
    if state.get("final_status"):
        return str(state.get("final_status"))
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


def _is_successful_full_sandbox_migration(state: MigrationState) -> bool:
    return (
        state.get("mode") == FULL_SANDBOX_MIGRATION_MODE
        and state.get("approval_status") == "COMPLETED"
        and state.get("approval_decision") == "approved"
        and state.get("orchestration_status") == "PASS"
        and state.get("transform_status") == "TRANSFORM_APPLIED_IN_SANDBOX"
        and state.get("build_status") == "BUILD_PASSED_IN_SANDBOX"
        and state.get("test_status") == "TEST_PASSED"
        and _final_status(state) == "TRANSFORM_APPLIED_IN_SANDBOX"
    )


def _execution_claims(state: MigrationState) -> dict[str, bool]:
    claims = dict(EXECUTION_CLAIMS)
    if state.get("transform_status") == "TRANSFORM_APPLIED_IN_SANDBOX":
        claims["transformation_executed"] = True
        claims["openrewrite_apply_executed"] = True
    if state.get("build_status") == "BUILD_PASSED_IN_SANDBOX":
        claims["migrated_build_executed"] = True
    if state.get("test_status") == "TEST_PASSED":
        claims["migrated_tests_executed"] = True
    return claims


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
