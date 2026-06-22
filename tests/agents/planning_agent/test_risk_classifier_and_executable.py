import yaml

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.plan_writer import (
    MigrationPlanPayload,
    write_migration_plan,
)
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.agents.planning_agent.risk_classifier import classify_planning_risks
from migration_factory.agents.planning_agent.unit_builder import build_migration_units


def test_unreadable_or_invalid_pom_metadata_creates_blocker() -> None:
    loaded = LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": {
                "build_metadata_readable": False,
                "build_metadata_valid": False,
            },
            "dependency_graph.json": {},
            "test_inventory.json": {},
            "analysis_summary.md": "ok\n",
        },
        optional={},
        errors=[],
        ok=True,
    )

    result = classify_planning_risks(
        loaded,
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.7"),
    )

    assert result.ok is False
    assert any(r.code == "UNREADABLE_BUILD_METADATA" and r.severity == "BLOCKER" for r in result.risks)


def test_unknown_source_spring_boot_creates_warning() -> None:
    result = classify_planning_risks(
        LoadedAnalysisArtifacts(required={}, optional={}, errors=[], ok=True),
        StackFingerprint(build_tool="maven", java="11", spring_boot=None),
    )

    assert any(r.code == "UNKNOWN_SOURCE_SPRING_BOOT" and r.severity == "WARNING" for r in result.risks)


def test_javax_count_creates_jakarta_warning() -> None:
    loaded = LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": {"inventory": {"javax_count": 3}},
            "dependency_graph.json": {},
            "test_inventory.json": {},
            "analysis_summary.md": "ok\n",
        },
        optional={},
        errors=[],
        ok=True,
    )

    result = classify_planning_risks(
        loaded,
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.7"),
    )

    assert any(
        r.code == "JAKARTA_MIGRATION_REQUIRED"
        and r.severity == "WARNING"
        and "Detected javax usage count: 3." in r.message
        for r in result.risks
    )


def test_internal_dependency_candidates_create_route_review_warning() -> None:
    loaded = LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": {
                "internal_dependencies": [
                    {
                        "groupId": "acme.internal",
                        "artifactId": "billing-core",
                        "version": "1.0.0",
                    }
                ],
                "dependency_graph.json": {},
                "test_inventory.json": {},
                "analysis_summary.md": "ok\n",
            },
            "dependency_graph.json": {},
            "test_inventory.json": {},
            "analysis_summary.md": "ok\n",
        },
        optional={},
        errors=[],
        ok=True,
    )

    result = classify_planning_risks(
        loaded,
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.7"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert any(
        r.code == "INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW"
        and r.severity == "WARNING"
        and "internal dependency candidate" in r.message.lower()
        for r in result.risks
    )


def test_deterministic_blocker_sets_migration_plan_executable_false(tmp_path) -> None:
    app_dir = tmp_path / "app"
    run_id = "risk-blocker"
    units = build_migration_units()

    plan_path = write_migration_plan(
        modernized_app_path=str(app_dir),
        payload=MigrationPlanPayload(
            run_id=run_id,
            profile="java17",
            source_stack=StackFingerprint(build_tool="maven", java="11", spring_boot="2.7"),
            target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
            risks=("[BLOCKER] UNREADABLE_BUILD_METADATA: Build metadata unreadable or invalid from analysis artifacts.",),
            blockers=("UNREADABLE_BUILD_METADATA: Build metadata unreadable or invalid from analysis artifacts.",),
            warnings=(),
            units=units,
        ),
    )

    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert payload["executable"] is False
