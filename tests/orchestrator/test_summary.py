from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import build_initial_state
from migration_factory.orchestrator.summary import (
    build_orchestration_summary,
    write_orchestration_summary,
)


def _state(tmp_path: Path):
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java17",
    )
    state.update(
        {
            "current_phase": "assessment",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "stop_reason": "approved",
            "blockers": ["manual follow-up"],
            "warnings": ["warning"],
            "errors": ["error"],
            "artifact_refs": {"assessment_report": "assessment_report.json"},
        }
    )
    return state


def test_summary_includes_phase_statuses_and_stop_reason(tmp_path: Path) -> None:
    summary = build_orchestration_summary(_state(tmp_path))

    assert summary["run_id"] == "run-001"
    assert summary["final_status"] == "FAILED"
    assert summary["current_phase"] == "assessment"
    assert summary["analysis_status"] == "PASS"
    assert summary["planning_status"] == "PASS"
    assert summary["assessment_status"] == "PASS"
    assert summary["approval_status"] == "COMPLETED"
    assert summary["stop_reason"] == "approved"
    assert summary["blockers"] == ["manual follow-up"]
    assert summary["warnings"] == ["warning"]
    assert summary["errors"] == ["error"]
    assert summary["artifact_refs"] == {"assessment_report": "assessment_report.json"}


def test_summary_includes_approval_decision_when_present(tmp_path: Path) -> None:
    summary = build_orchestration_summary(_state(tmp_path))

    assert summary["approval_decision"] == "approved"


def test_summary_has_false_execution_claims_and_no_completion_claim(tmp_path: Path) -> None:
    summary = build_orchestration_summary(_state(tmp_path))

    assert summary["transformation_executed"] is False
    assert summary["openrewrite_apply_executed"] is False
    assert summary["migrated_build_executed"] is False
    assert summary["migrated_tests_executed"] is False
    assert summary["final_migration_executed"] is False
    assert "migration_complete" not in summary


def test_summary_excludes_transformation_status(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state["transformation_status"] = "PASS"

    assert "transformation_status" not in build_orchestration_summary(state)


def test_summary_includes_full_sandbox_migration_outputs(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.update(
        {
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "sandbox_path": str(tmp_path / "run" / "workspaces" / "sandbox"),
            "transform_log_path": str(tmp_path / "run" / "logs" / "phase2_transform.log"),
            "stop_reason": "Sandbox migration candidate ready.",
        }
    )

    summary = build_orchestration_summary(state)

    assert summary["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert summary["approval_decision"] == "approved"
    assert summary["transform_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert summary["build_status"] == "BUILD_PASSED_IN_SANDBOX"
    assert summary["sandbox_path"].endswith("workspaces\\sandbox") or summary["sandbox_path"].endswith("workspaces/sandbox")
    assert summary["log_path"].endswith("phase2_transform.log")
    assert summary["stop_reason"] == "Sandbox migration candidate ready."
    assert summary["transformation_executed"] is True
    assert summary["migrated_build_executed"] is True
    assert summary["final_migration_executed"] is False


def test_write_orchestration_summary_uses_orchestration_dir_under_run_dir(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    summary_path = write_orchestration_summary(state)

    assert summary_path == (
        Path(state["run_dir"]) / "orchestration" / "orchestration_summary.json"
    )
    assert summary_path.is_file()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["run_id"] == "run-001"
