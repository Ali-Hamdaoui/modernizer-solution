from dataclasses import fields
from pathlib import Path

import pytest

from migration_factory.orchestrator.phase_services import (
    PhaseServices,
    default_phase_services,
    run_analysis_phase,
)
from migration_factory.orchestrator.state import MigrationState, build_initial_state


def _state(tmp_path: Path) -> MigrationState:
    return build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
        ai_hub_path=str(tmp_path / "ai-hub"),
        profile_id="java17",
    )


def test_default_phase_services_has_exact_three_phases() -> None:
    services = default_phase_services()

    assert [field.name for field in fields(PhaseServices)] == [
        "run_analysis_phase",
        "run_planning_phase",
        "run_assessment_phase",
    ]
    assert services.run_analysis_phase is run_analysis_phase
    assert callable(services.run_planning_phase)
    assert callable(services.run_assessment_phase)


def test_fake_phase_services_injection_works(tmp_path: Path) -> None:
    def fake_analysis(state: MigrationState) -> MigrationState:
        return {**state, "analysis_status": "PASS", "current_phase": "analysis"}

    def fake_planning(state: MigrationState) -> MigrationState:
        return {**state, "planning_status": "PASS", "current_phase": "planning"}

    def fake_assessment(state: MigrationState) -> MigrationState:
        return {**state, "assessment_status": "PASS", "current_phase": "assessment"}

    services = PhaseServices(
        run_analysis_phase=fake_analysis,
        run_planning_phase=fake_planning,
        run_assessment_phase=fake_assessment,
    )

    state = services.run_assessment_phase(
        services.run_planning_phase(services.run_analysis_phase(_state(tmp_path)))
    )

    assert state["analysis_status"] == "PASS"
    assert state["planning_status"] == "PASS"
    assert state["assessment_status"] == "PASS"
    assert state["current_phase"] == "assessment"


def test_phase_services_has_no_transformation_service_or_attr() -> None:
    services = default_phase_services()

    assert "run_transformation_phase" not in [field.name for field in fields(PhaseServices)]
    assert not hasattr(services, "run_transformation_phase")


def test_phase_failure_sets_fail_and_blocker_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_analysis(state: MigrationState) -> MigrationState:
        raise RuntimeError("analysis exploded")

    monkeypatch.setattr(
        "migration_factory.orchestrator.phase_services._run_analysis_service",
        fail_analysis,
    )

    state = run_analysis_phase(_state(tmp_path))

    assert state["analysis_status"] == "FAIL"
    assert state["current_phase"] == "analysis"
    assert state["current_unit"] == "analysis"
    assert state["errors"] == ["analysis phase failed: analysis exploded"]
    assert state["blockers"] == ["analysis phase failed: analysis exploded"]
