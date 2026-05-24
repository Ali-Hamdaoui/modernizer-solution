from __future__ import annotations

import inspect
from pathlib import Path

import migration_factory.orchestrator.copilot_assist as copilot_node_module
from migration_factory.orchestrator import graph as graph_module
from migration_factory.orchestrator.artifact_validation import ArtifactValidationResult
from migration_factory.orchestrator.phase_services import PhaseServices
from migration_factory.orchestrator.state import build_initial_state


def _state(tmp_path: Path, *, assist_mode: str) -> dict:
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
    )
    state["copilot_assist_mode"] = assist_mode
    state["copilot_provider"] = "deterministic"
    return state


def _validation(*, valid: bool = True, warnings: list[str] | None = None) -> ArtifactValidationResult:
    return ArtifactValidationResult(
        valid=valid,
        artifact_refs={"validated": "artifact.json"} if valid else {},
        blockers=[] if valid else ["invalid artifacts"],
        warnings=list(warnings or []),
    )


def _patch_validators(monkeypatch, *, analysis_warnings: list[str] | None = None) -> None:
    monkeypatch.setattr(graph_module, "validate_analysis_artifacts", lambda state: _validation(warnings=analysis_warnings))
    monkeypatch.setattr(graph_module, "validate_planning_artifacts", lambda state: _validation())
    monkeypatch.setattr(graph_module, "validate_assessment_artifacts", lambda state: _validation())


def _services(calls: list[str], *, analysis: str = "PASS", planning: str = "FAIL") -> PhaseServices:
    def run_analysis_phase(state):
        calls.append("analysis")
        result = {"analysis_status": analysis}
        if analysis == "FAIL":
            result.update(
                {
                    "blockers": ["deterministic blocker"],
                    "warnings": ["deterministic warning"],
                    "errors": ["deterministic error"],
                }
            )
        return result

    def run_planning_phase(state):
        calls.append("planning")
        return {"planning_status": planning}

    def run_assessment_phase(state):
        calls.append("assessment")
        return {"assessment_status": "FAIL"}

    return PhaseServices(
        run_analysis_phase=run_analysis_phase,
        run_planning_phase=run_planning_phase,
        run_assessment_phase=run_assessment_phase,
    )


class _MutatingCopilotService:
    def __init__(self, state):
        self.state = state

    def generate_phase_assist(self, state, phase):
        state["copilot_phase_statuses"] = {**dict(state.get("copilot_phase_statuses", {}) or {}), phase: "generated"}
        state["copilot_artifact_refs"] = {
            **dict(state.get("copilot_artifact_refs", {}) or {}),
            f"{phase}_copilot_assist": f"{phase}/copilot_assist.json",
        }
        state["analysis_status"] = "PASS"
        state["blockers"] = []
        state["warnings"] = []
        state["errors"] = []


def test_fail_with_failures_mode_routes_to_copilot_assist_then_end(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    monkeypatch.setattr(copilot_node_module, "CopilotAssistService", _MutatingCopilotService)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="FAIL"))

    result = app.invoke(_state(tmp_path, assist_mode="failures"))

    assert calls == ["analysis"]
    assert result["copilot_phase_statuses"]["analysis"] == "generated"
    assert result["analysis_status"] == "FAIL"
    assert result["blockers"] == ["deterministic blocker"]
    assert result["warnings"] == ["deterministic warning"]
    assert result["errors"] == ["deterministic error"]
    assert "planning_status" in result
    assert result["planning_status"] == "PENDING"


def test_fail_with_off_mode_routes_directly_to_end(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    monkeypatch.setattr(copilot_node_module, "CopilotAssistService", _MutatingCopilotService)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="FAIL"))

    result = app.invoke(_state(tmp_path, assist_mode="off"))

    assert calls == ["analysis"]
    assert result["analysis_status"] == "FAIL"
    assert result["copilot_phase_statuses"] == {}


def test_pass_with_warnings_mode_routes_to_copilot_assist_then_next_phase(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch, analysis_warnings=["review generated plan"])
    monkeypatch.setattr(copilot_node_module, "CopilotAssistService", _MutatingCopilotService)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="PASS", planning="FAIL"))

    result = app.invoke(_state(tmp_path, assist_mode="warnings"))

    assert calls == ["analysis", "planning"]
    assert result["copilot_phase_statuses"]["analysis"] == "generated"
    assert result["planning_status"] == "FAIL"
    assert result["warnings"] == ["review generated plan"]


def test_pass_without_warnings_skips_assist_unless_always(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    monkeypatch.setattr(copilot_node_module, "CopilotAssistService", _MutatingCopilotService)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="PASS", planning="FAIL"))

    result = app.invoke(_state(tmp_path, assist_mode="warnings"))

    assert calls == ["analysis", "planning"]
    assert result["copilot_phase_statuses"] == {}


def test_always_mode_routes_validated_phase_through_assist(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    monkeypatch.setattr(copilot_node_module, "CopilotAssistService", _MutatingCopilotService)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="PASS", planning="FAIL"))

    result = app.invoke(_state(tmp_path, assist_mode="always"))

    assert calls == ["analysis", "planning"]
    assert result["copilot_phase_statuses"]["analysis"] == "generated"


def test_copilot_phase_assist_does_not_call_interrupt() -> None:
    source = inspect.getsource(copilot_node_module)

    assert "interrupt(" not in source
