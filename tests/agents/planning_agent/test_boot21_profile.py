import json
from pathlib import Path

import jsonschema
import yaml

from migration_factory.agents.planning_agent.node import planning_node
from migration_factory.agents.planning_agent.output_validator import validate_planning_outputs
from migration_factory.agents.planning_agent.profile_compatibility import validate_profile_compatibility
from migration_factory.agents.planning_agent.profile_reader import load_migration_profile
from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts


REPO_ROOT = Path(__file__).resolve().parents[3]
AI_HUB = REPO_ROOT / "modernizer-solution-ai-hub"
PROFILE_ID = "springboot-2.1-to-3.5-java17"
PROFILE_PATH = AI_HUB / "profiles" / f"{PROFILE_ID}.yaml"
SCHEMA_PATH = AI_HUB / "schemas" / "migration-profile.schema.json"


def _analysis_artifacts() -> LoadedAnalysisArtifacts:
    return LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": {
                "source_stack": {
                    "java": "11",
                    "spring_boot": "2.1.6.RELEASE",
                    "build_tool": "maven",
                }
            },
            "dependency_graph.json": {},
            "test_inventory.json": {},
        }
    )


def _write_analysis_fixture(analysis_dir: Path) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "source_stack": {
                    "java": "11",
                    "spring_boot": "2.1.6.RELEASE",
                    "build_tool": "maven",
                }
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "test_inventory.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "analysis_summary.md").write_text("analysis ok\n", encoding="utf-8")


def test_boot21_profile_file_exists() -> None:
    assert PROFILE_PATH.exists()


def test_boot21_profile_loads_successfully() -> None:
    loaded = load_migration_profile(AI_HUB, PROFILE_ID)

    assert loaded.ok
    assert loaded.profile["id"] == PROFILE_ID
    assert loaded.profile["source_jdk_home_env"] == "JAVA_HOME_11"
    assert loaded.profile["target_jdk_home_env"] == "JAVA_HOME_17"
    assert loaded.profile["tooling_versions"]["lombok"] == "1.18.34"
    assert loaded.profile["tooling_versions"]["jacoco"] == "0.8.12"
    assert loaded.profile["tooling_versions"]["maven_compiler_plugin"] == "3.14.1"
    assert loaded.profile["framework_versions"]["jackson"] == "2.21.2"
    assert loaded.profile["framework_versions"]["jackson_annotations"] == "2.21"
    assert loaded.profile["framework_versions"]["jjwt"] == "0.13.0"
    assert loaded.profile["framework_versions"]["thymeleaf"] == "3.1.3.RELEASE"
    assert loaded.profile["framework_versions"]["jakarta_validation_api"] == "3.0.2"
    assert loaded.profile["framework_versions"]["slf4j_api"] == "2.0.17"
    assert loaded.profile["framework_versions"]["spring_security"] == "6.5.10"


def test_boot21_profile_passes_schema_validation() -> None:
    profile = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(profile, schema)


def test_boot21_profile_route_matches_source_stack() -> None:
    loaded = load_migration_profile(AI_HUB, PROFILE_ID)

    result = validate_profile_compatibility(_analysis_artifacts(), loaded)

    assert result.ok
    assert result.selected_route_id == "boot-2.1-to-3.5-java17"
    assert result.selected_route_strategy == "multi_hop"
    assert result.route_strategy == "multi_hop"
    assert result.route_risk_level == "high"
    assert result.route_production_allowed is False
    assert result.recommended_intermediate == {"spring_boot": "2.7.18"}
    assert [hop["id"] for hop in result.selected_hops] == [
        "boot-2.1-to-2.7-java11",
        "boot-2.7-to-3.5-java17",
    ]


def test_boot21_profile_planning_includes_selected_route_and_warning(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    run_id = "boot21-plan"
    _write_analysis_fixture(app_dir / ".migration" / "runs" / run_id / "analysis")

    result = planning_node(
        {
            "run_id": run_id,
            "profile": PROFILE_ID,
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(AI_HUB),
        }
    )

    assert result["planning_status"] == "PASS"
    assert not result["blockers"]
    assert any("high risk" in warning.lower() for warning in result["warnings"])

    plan_payload = yaml.safe_load(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "migration_plan.yaml").read_text(encoding="utf-8")
    )
    assert plan_payload["selected_route_id"] == "boot-2.1-to-3.5-java17"
    assert plan_payload["route_strategy"] == "multi_hop"
    assert plan_payload["route_risk_level"] == "high"
    assert plan_payload["production_allowed"] is False
    assert plan_payload["recommended_intermediate"] == {"spring_boot": "2.7.18"}
    assert plan_payload["tooling_versions"] == {
        "lombok": "1.18.34",
        "jacoco": "0.8.12",
        "maven_compiler_plugin": "3.14.1",
    }
    assert plan_payload["framework_versions"] == {
        "jackson": "2.21.2",
        "jackson_annotations": "2.21",
        "jjwt": "0.13.0",
        "thymeleaf": "3.1.3.RELEASE",
        "jakarta_validation_api": "3.0.2",
        "slf4j_api": "2.0.17",
        "spring_security": "6.5.10",
    }
    assert [hop["id"] for hop in plan_payload["selected_hops"]] == [
        "boot-2.1-to-2.7-java11",
        "boot-2.7-to-3.5-java17",
    ]
    assert plan_payload["unit_references"] == [
        "baseline",
        "spring-boot-2-7-stabilization",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "jaxb-jakarta",
        "dependency-cleanup",
        "contract-compatibility-review",
        "existing-test-migration",
    ]

    units_payload = yaml.safe_load(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "migration_units.yaml").read_text(encoding="utf-8")
    )
    assert [unit["id"] for unit in units_payload["units"]] == plan_payload["unit_references"]
    baseline = next(unit for unit in units_payload["units"] if unit["id"] == "baseline")
    java17 = next(unit for unit in units_payload["units"] if unit["id"] == "java-17")
    assert next(unit for unit in units_payload["units"] if unit["id"] == "contract-compatibility-review")["writes_source"] is False
    assert next(unit for unit in units_payload["units"] if unit["id"] == "jaxb-jakarta")["writes_source"] is True
    stabilization = next(unit for unit in units_payload["units"] if unit["id"] == "spring-boot-2-7-stabilization")
    jakarta = next(unit for unit in units_payload["units"] if unit["id"] == "jakarta")
    jaxb = next(unit for unit in units_payload["units"] if unit["id"] == "jaxb-jakarta")
    assert baseline["java_home_env"] == "JAVA_HOME_11"
    assert baseline["hop_id"] == "boot-2.1-to-2.7-java11"
    assert stabilization["java_home_env"] == "JAVA_HOME_11"
    assert stabilization["hop_id"] == "boot-2.1-to-2.7-java11"
    assert java17["java_home_env"] == "JAVA_HOME_17"
    assert java17["hop_id"] == "boot-2.7-to-3.5-java17"
    assert stabilization["openrewrite"]["active_recipes"] == [
        "org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7"
    ]
    assert jakarta["openrewrite"]["active_recipes"] == [
        "org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta"
    ]
    assert jaxb["openrewrite"]["active_recipes"] == [
        "org.openrewrite.java.migrate.jakarta.JavaxXmlBindMigrationToJakartaXmlBind"
    ]

    validation = validate_planning_outputs(str(app_dir), run_id)
    assert validation.status == "PASS"


def test_java21_profile_planning_outputs_validate_supported_route_order(tmp_path: Path) -> None:
    app_dir = tmp_path / "app-java21"
    run_id = "boot21-java21-plan"
    _write_analysis_fixture(app_dir / ".migration" / "runs" / run_id / "analysis")

    result = planning_node(
        {
            "run_id": run_id,
            "profile": "springboot-2.1-to-3.5-java21",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(AI_HUB),
        }
    )

    assert result["planning_status"] == "PASS"
    validation = validate_planning_outputs(str(app_dir), run_id)
    assert validation.status == "PASS"


def test_schema_accepts_direct_route_without_hops_and_legacy_profile_shape() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    direct_profile = {
        "id": "direct-profile",
        "source": {
            "java": {"allowed_versions": ["11"]},
            "spring_boot": {"allowed_version_prefixes": ["2.7"]},
            "build": {"allowed_tools": ["maven"]},
        },
        "target": {
            "java": "17",
            "spring_boot": "3.5.14",
            "spring_framework": "6.2.18",
            "build": "maven",
        },
        "routes": [
            {
                "id": "boot-2.7-to-3.5-java17",
                "source": {
                    "java": {"allowed_versions": ["11"]},
                    "spring_boot": {"allowed_version_prefixes": ["2.7"]},
                    "build": {"allowed_tools": ["maven"]},
                },
                "target": {
                    "java": "17",
                    "spring_boot": "3.5.14",
                    "spring_framework": "6.2.18",
                    "build": "maven",
                },
            }
        ],
        "requirements": {
            "human_approval_required": True,
            "baseline_tests_required": False,
            "dependency_graph_unavailable_fatal": False,
        },
        "rules": {
            "human_approval_required": True,
            "baseline_tests_required": False,
            "dependency_graph_unavailable_fatal": False,
            "openrewrite_preview_allowed": True,
            "openrewrite_apply_allowed": False,
        },
        "openrewrite": {
            "preview_allowed": True,
            "apply_allowed": False,
            "catalog_path": "catalogs/openrewrite/springboot-3.5-java17.yaml",
        },
        "policies": {
            "safety": "policies/safety.yaml",
            "planning": "policies/planning.yaml",
            "transformation": "policies/transformation.yaml",
        },
    }
    legacy_profile = {
        key: value
        for key, value in direct_profile.items()
        if key != "routes"
    }

    jsonschema.validate(direct_profile, schema)
    jsonschema.validate(legacy_profile, schema)
