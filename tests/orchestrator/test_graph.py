from pathlib import Path

from migration_factory.orchestrator import graph as graph_module
from migration_factory.orchestrator.artifact_validation import ArtifactValidationResult
from migration_factory.orchestrator.phase_services import PhaseServices
from migration_factory.orchestrator.state import build_initial_state


def _state(tmp_path: Path):
    return build_initial_state(
        run_id="run-001",
        legacy_app_path=str(tmp_path / "legacy"),
        modernized_app_path=str(tmp_path / "modernized"),
    )


def _validation(valid: bool = True) -> ArtifactValidationResult:
    return ArtifactValidationResult(
        valid=valid,
        artifact_refs={"validated": "artifact.json"} if valid else {},
        blockers=[] if valid else ["invalid artifacts"],
        warnings=[],
    )


def _services(calls: list[str], *, analysis="PASS", planning="PASS", assessment="PASS") -> PhaseServices:
    def run_analysis_phase(state):
        calls.append("analysis")
        return {"analysis_status": analysis, "artifact_refs": {"analysis": "analysis.json"}}

    def run_planning_phase(state):
        calls.append("planning")
        return {"planning_status": planning, "artifact_refs": {"planning": "planning.yaml"}}

    def run_assessment_phase(state):
        calls.append("assessment")
        return {"assessment_status": assessment, "artifact_refs": {"assessment": "assessment.json"}}

    return PhaseServices(
        run_analysis_phase=run_analysis_phase,
        run_planning_phase=run_planning_phase,
        run_assessment_phase=run_assessment_phase,
    )


def _patch_validators(monkeypatch, *, analysis=True, planning=True, assessment=True) -> None:
    monkeypatch.setattr(graph_module, "validate_analysis_artifacts", lambda state: _validation(analysis))
    monkeypatch.setattr(graph_module, "validate_planning_artifacts", lambda state: _validation(planning))
    monkeypatch.setattr(graph_module, "validate_assessment_artifacts", lambda state: _validation(assessment))


def _patch_approval(monkeypatch, calls: list[str]) -> None:
    def fake_approval(state):
        calls.append("approval")
        return {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "stop_reason": "approved",
        }

    monkeypatch.setattr(graph_module, "approval_node", fake_approval)


def test_graph_compiles_without_transformation_node(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    _patch_approval(monkeypatch, calls)

    app = graph_module.build_graph(phase_services=_services(calls))
    graph = app.get_graph()

    assert "transformation" not in graph.nodes
    assert all("transformation" not in edge.source for edge in graph.edges)
    assert all("transformation" not in edge.target for edge in graph.edges)


def test_graph_runs_read_only_phases_then_approval(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis", "planning", "assessment", "approval"]
    assert result["analysis_artifacts_valid"] is True
    assert result["planning_artifacts_valid"] is True
    assert result["assessment_artifacts_valid"] is True
    assert result["approval_status"] == "COMPLETED"


def test_analysis_failure_stops_before_planning(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls, analysis="FAIL"))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis"]
    assert result["analysis_status"] == "FAIL"
    assert result["analysis_artifacts_valid"] is True


def test_analysis_artifact_failure_stops_before_planning(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch, analysis=False)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis"]
    assert result["analysis_status"] == "PASS"
    assert result["analysis_artifacts_valid"] is False
    assert result["blockers"] == ["invalid artifacts"]


def test_planning_failure_stops_before_assessment(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls, planning="FAIL"))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis", "planning"]
    assert result["planning_status"] == "FAIL"
    assert result["planning_artifacts_valid"] is True


def test_planning_artifact_failure_stops_before_assessment(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch, planning=False)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis", "planning"]
    assert result["planning_status"] == "PASS"
    assert result["planning_artifacts_valid"] is False
    assert result["blockers"] == ["invalid artifacts"]


def test_assessment_failure_stops_before_approval(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls, assessment="FAIL"))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis", "planning", "assessment"]
    assert result["assessment_status"] == "FAIL"
    assert result["assessment_artifacts_valid"] is True


def test_assessment_artifact_failure_stops_before_approval(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    _patch_validators(monkeypatch, assessment=False)
    _patch_approval(monkeypatch, calls)
    app = graph_module.build_graph(phase_services=_services(calls))

    result = app.invoke(_state(tmp_path))

    assert calls == ["analysis", "planning", "assessment"]
    assert result["assessment_status"] == "PASS"
    assert result["assessment_artifacts_valid"] is False
    assert result["blockers"] == ["invalid artifacts"]
