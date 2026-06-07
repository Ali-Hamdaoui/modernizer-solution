from dataclasses import replace

import yaml

from migration_factory.agents.planning_agent.assist_config import build_assist_policy
from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.plan_writer import (
    MigrationPlanPayload,
    write_migration_plan,
    write_migration_units,
)
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.agents.planning_agent.risk_classifier import classify_planning_risks
from migration_factory.agents.planning_agent.unit_builder import MigrationUnit, build_migration_units


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


def test_write_migration_units_preserves_auto_required_semantics(tmp_path) -> None:
    app_dir = tmp_path / "app"
    run_id = "required-auto"
    units = build_migration_units()

    units_path = write_migration_units(str(app_dir), run_id, units)
    payload = yaml.safe_load(units_path.read_text(encoding="utf-8"))

    existing_test = next(unit for unit in payload["units"] if unit["id"] == "existing-test-migration")
    assert existing_test["required"] == "auto"
    assert 'required: "auto"' in units_path.read_text(encoding="utf-8")


def test_write_migration_units_normalizes_required_yes_true_and_no_false(tmp_path) -> None:
    app_dir = tmp_path / "app"
    run_id = "required-normalization"
    assist_policy = build_assist_policy()
    units = (
        MigrationUnit(
            id="required-yes",
            goal="Required yes.",
            writes_source=False,
            tools=("maven",),
            validation=("mvn", "test"),
            expected_artifacts=("target/surefire-reports",),
            rollback_strategy="none",
            blocking_gate="none",
            required=True,  # type: ignore[arg-type]
            assist_policy=assist_policy,
        ),
        MigrationUnit(
            id="required-no",
            goal="Required no.",
            writes_source=False,
            tools=("maven",),
            validation=("mvn", "test"),
            expected_artifacts=("target/surefire-reports",),
            rollback_strategy="none",
            blocking_gate="none",
            required=False,  # type: ignore[arg-type]
            assist_policy=assist_policy,
        ),
        replace(build_migration_units()[0], id="required-auto-unknown", required="maybe"),  # type: ignore[arg-type]
    )

    units_path = write_migration_units(str(app_dir), run_id, units)
    payload = yaml.safe_load(units_path.read_text(encoding="utf-8"))
    required_by_id = {unit["id"]: unit["required"] for unit in payload["units"]}
    text = units_path.read_text(encoding="utf-8")

    assert required_by_id["required-yes"] == "yes"
    assert required_by_id["required-no"] == "no"
    assert required_by_id["required-auto-unknown"] == "yes"
    assert 'required: "yes"' in text
    assert 'required: "no"' in text
    assert "required: true" not in text
    assert "required: false" not in text
