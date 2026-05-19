from pathlib import Path

from migration_factory.orchestrator.state import (
    APPROVAL_DECISION_VALUES,
    APPROVAL_STATUS_VALUES,
    PHASE_STATUS_VALUES,
    READ_ONLY_ASSESSMENT_MODE,
    build_initial_state,
)


def test_initial_state_has_required_read_only_assessment_fields(tmp_path: Path) -> None:
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java-17",
        thread_id="thread-001",
    )

    assert state["mode"] == READ_ONLY_ASSESSMENT_MODE
    assert state["run_id"] == "run-001"
    assert state["legacy_app_path"] == str(tmp_path / "legacy")
    assert state["modernized_app_path"] == str(tmp_path / "modernized")
    assert state["ai_hub_path"] == str(tmp_path / "ai-hub")
    assert state["profile_id"] == "java-17"
    assert state["thread_id"] == "thread-001"
    assert state["current_unit"] == ""
    assert state["stop_reason"] is None
    assert state["blockers"] == []
    assert state["warnings"] == []
    assert state["errors"] == []
    assert state["artifact_refs"] == {}


def test_initial_state_statuses_and_artifact_flags_are_defaults(tmp_path: Path) -> None:
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
    )

    assert PHASE_STATUS_VALUES == {"PENDING", "RUNNING", "PASS", "FAIL", "SKIPPED"}
    assert APPROVAL_STATUS_VALUES == {"PENDING", "INTERRUPTED", "COMPLETED", "FAILED"}
    assert state["analysis_status"] == "PENDING"
    assert state["planning_status"] == "PENDING"
    assert state["assessment_status"] == "PENDING"
    assert state["orchestration_status"] == "PENDING"
    assert state["approval_status"] == "PENDING"
    assert state["approval_decision"] is None
    assert state["analysis_artifacts_valid"] is False
    assert state["planning_artifacts_valid"] is False
    assert state["assessment_artifacts_valid"] is False
    assert state["orchestration_artifacts_valid"] is False


def test_approval_decision_values_are_exact() -> None:
    assert APPROVAL_DECISION_VALUES == {"approved", "rejected", "replan_required"}


def test_initial_state_derives_json_safe_path_strings(tmp_path: Path) -> None:
    modernized_app_path = tmp_path / "modernized"
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(modernized_app_path),
    )

    run_dir = modernized_app_path / ".migration" / "runs" / "run-001"
    assert state["run_dir"] == str(run_dir)
    assert state["analysis_dir"] == str(run_dir / "analysis")
    assert state["planning_dir"] == str(run_dir / "planning")
    assert state["assessment_dir"] == str(run_dir / "assessment")
    assert state["orchestration_dir"] == str(run_dir / "orchestration")
    assert all(isinstance(state[key], str) for key in (
        "run_dir",
        "analysis_dir",
        "planning_dir",
        "assessment_dir",
        "orchestration_dir",
    ))


def test_initial_state_has_no_transformation_status(tmp_path: Path) -> None:
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
    )

    assert "transformation_status" not in state
