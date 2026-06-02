import json
from pathlib import Path

import yaml

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.node import planning_node
from migration_factory.agents.planning_agent.profile_compatibility import validate_profile_compatibility
from migration_factory.agents.planning_agent.profile_reader import LoadedMigrationProfile, load_migration_profile


def _artifacts(java: str | None, spring_boot: str | None, build_tool: str | None = "maven") -> LoadedAnalysisArtifacts:
    source_stack = {}
    if java is not None:
        source_stack["java"] = java
    if spring_boot is not None:
        source_stack["spring_boot"] = spring_boot
    if build_tool is not None:
        source_stack["build_tool"] = build_tool
    return LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": {"source_stack": source_stack},
            "dependency_graph.json": {},
            "test_inventory.json": {},
        }
    )


def _legacy_profile() -> LoadedMigrationProfile:
    return LoadedMigrationProfile(
        profile={
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
            "rules": {},
        }
    )


def _route_profile() -> LoadedMigrationProfile:
    return LoadedMigrationProfile(
        profile={
            "routes": [
                {
                    "id": "boot-2.1-to-3.5-java17",
                    "strategy": "multi_hop",
                    "risk_level": "high",
                    "production_allowed": False,
                    "preferred": True,
                    "recommended_intermediate": {"spring_boot": "2.7.18"},
                    "hops": [
                        {
                            "id": "boot-2.1-to-2.7-java11",
                            "source": {
                                "java": {"allowed_versions": ["8", "11"]},
                                "spring_boot": {"allowed_version_prefixes": ["2.1"]},
                                "build": {"allowed_tools": ["maven"]},
                            },
                            "target": {
                                "java": "11",
                                "spring_boot": "2.7.18",
                                "build": "maven",
                            },
                            "validation": {"build_required": True, "tests_required": True},
                            "approval": {"required": True},
                        },
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
                            "validation": {"build_required": True, "tests_required": True},
                            "approval": {"required": True},
                        },
                    ],
                },
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
                    "strategy": "direct_standard",
                    "risk_level": "medium",
                    "production_allowed": True,
                },
            ],
            "rules": {},
            "requirements": {},
            "openrewrite": {"catalog_path": "catalog.yaml"},
            "policies": {"safety": "strict", "planning": "deterministic", "transformation": "sandbox"},
        }
    )


def _write_route_profile(ai_hub_dir: Path, profile_id: str = "routes-java17") -> None:
    profiles_dir = ai_hub_dir / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / f"{profile_id}.yaml").write_text(
        """
id: routes-java17
routes:
  - id: boot-2.1-to-3.5-java17
    strategy: multi_hop
    risk_level: high
    production_allowed: false
    preferred: true
    recommended_intermediate:
      spring_boot: "2.7.18"
    hops:
      - id: boot-2.1-to-2.7-java11
        source:
          java:
            allowed_versions: ["8", "11"]
          spring_boot:
            allowed_version_prefixes: ["2.1"]
          build:
            allowed_tools: ["maven"]
        target:
          java: "11"
          spring_boot: "2.7.18"
          build: maven
        validation:
          build_required: true
          tests_required: true
        approval:
          required: true
      - id: boot-2.7-to-3.5-java17
        source:
          java:
            allowed_versions: ["11"]
          spring_boot:
            allowed_version_prefixes: ["2.7"]
          build:
            allowed_tools: ["maven"]
        target:
          java: "17"
          spring_boot: "3.5.14"
          spring_framework: "6.2.18"
          build: maven
        validation:
          build_required: true
          tests_required: true
        approval:
          required: true
  - id: boot-2.7-to-3.5-java17
    source:
      java:
        allowed_versions: ["11"]
      spring_boot:
        allowed_version_prefixes: ["2.7"]
      build:
        allowed_tools: ["maven"]
    target:
      java: "17"
      spring_boot: "3.5.14"
      spring_framework: "6.2.18"
      build: maven
    strategy: direct_standard
    risk_level: medium
    production_allowed: true
rules: {}
requirements: {}
openrewrite:
  catalog_path: catalog.yaml
policies:
  safety: strict
  planning: deterministic
  transformation: sandbox
""".strip()
        + "\n",
        encoding="utf-8",
    )


def _write_analysis_fixture(analysis_dir: Path, java: str, spring_boot: str, build_tool: str = "maven") -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "source_stack": {
                    "java": java,
                    "spring_boot": spring_boot,
                    "build_tool": build_tool,
                }
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "test_inventory.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "analysis_summary.md").write_text("analysis ok\n", encoding="utf-8")


def test_legacy_profile_without_routes_still_works_for_boot_27() -> None:
    result = validate_profile_compatibility(_artifacts("11", "2.7.18"), _legacy_profile())

    assert result.ok
    assert result.selected_route_id is None
    assert result.target_stack.spring_boot == "3.5.14"


def test_route_profile_matches_boot_21_to_35() -> None:
    result = validate_profile_compatibility(_artifacts("11", "2.1.6.RELEASE"), _route_profile())

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
    assert any("high risk" in warning.lower() for warning in result.warnings)


def test_route_profile_matches_boot_27_to_35() -> None:
    result = validate_profile_compatibility(_artifacts("11", "2.7.18"), _route_profile())

    assert result.ok
    assert result.selected_route_id == "boot-2.7-to-3.5-java17"
    assert result.route_strategy == "direct_standard"
    assert result.route_risk_level == "medium"
    assert result.route_production_allowed is True


def test_no_matching_route_produces_clear_compatibility_error() -> None:
    result = validate_profile_compatibility(_artifacts("11", "2.3.9.RELEASE"), _route_profile())

    assert result.ok is False
    assert any("No migration route matched detected source stack." in error for error in result.errors)
    assert any("java=11" in error for error in result.errors)
    assert any("spring_boot=2.3.9.RELEASE" in error for error in result.errors)
    assert any("build_tool=maven" in error for error in result.errors)
    assert any("boot-2.1-to-3.5-java17" in error and "boot-2.7-to-3.5-java17" in error for error in result.errors)


def test_unknown_spring_boot_version_keeps_unknown_warning_and_route_blocker() -> None:
    result = validate_profile_compatibility(_artifacts("11", None), _route_profile())

    assert result.ok is False
    assert any("Source Spring Boot version missing or unknown" in warning for warning in result.warnings)
    assert any("spring_boot=unknown" in error for error in result.errors)


def test_selected_route_metadata_appears_in_migration_plan_yaml(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "route-plan"

    _write_analysis_fixture(app_dir / ".migration" / "runs" / run_id / "analysis", "11", "2.1.6.RELEASE")
    _write_route_profile(hub_dir)

    result = planning_node(
        {
            "run_id": run_id,
            "profile": "routes-java17",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(hub_dir),
        }
    )

    assert result["planning_status"] == "PASS"
    plan_payload = yaml.safe_load(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "migration_plan.yaml").read_text(encoding="utf-8")
    )
    assert plan_payload["selected_route_id"] == "boot-2.1-to-3.5-java17"
    assert plan_payload["route_strategy"] == "multi_hop"
    assert plan_payload["route_risk_level"] == "high"
    assert plan_payload["production_allowed"] is False
    assert plan_payload["recommended_intermediate"] == {"spring_boot": "2.7.18"}
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


def test_selected_hops_order_is_deterministic() -> None:
    result = validate_profile_compatibility(_artifacts("11", "2.1.6.RELEASE"), _route_profile())

    assert [hop["id"] for hop in result.selected_hops] == [
        "boot-2.1-to-2.7-java11",
        "boot-2.7-to-3.5-java17",
    ]


def test_route_profile_fixture_loads_from_profile_reader(tmp_path: Path) -> None:
    hub_dir = tmp_path / "ai-hub"
    _write_route_profile(hub_dir)

    loaded = load_migration_profile(hub_dir, "routes-java17")

    assert loaded.ok
    assert loaded.profile["routes"][0]["id"] == "boot-2.1-to-3.5-java17"


def test_route_profile_without_special_mapping_keeps_default_units(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "route-default-units"

    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    _write_analysis_fixture(analysis_dir, "11", "2.7.18")
    _write_route_profile(hub_dir)

    result = planning_node(
        {
            "run_id": run_id,
            "profile": "routes-java17",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(hub_dir),
        }
    )

    assert result["planning_status"] == "PASS"
    units_payload = yaml.safe_load(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "migration_units.yaml").read_text(encoding="utf-8")
    )
    assert [unit["id"] for unit in units_payload["units"]] == [
        "baseline",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "dependency-cleanup",
        "existing-test-migration",
    ]
