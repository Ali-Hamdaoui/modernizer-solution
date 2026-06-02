import json
from pathlib import Path

import yaml

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.node import planning_node
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.agents.planning_agent.risk_classifier import classify_planning_risks
from migration_factory.assessment.writer import write_assessment_artifacts


def _loaded_artifacts(
    *,
    java_imports: list[str] | None = None,
    dependencies: list[dict] | None = None,
    project_kind: str | None = None,
    has_juneau_contracts: bool | None = None,
    internal_dependencies: list[dict] | None = None,
    javax_count: int | None = None,
    build_metadata_valid: bool = True,
) -> LoadedAnalysisArtifacts:
    report = {
        "source_stack": {"java": "11", "spring_boot": "2.1.6.RELEASE", "build_tool": "maven"},
        "project_metadata": {
            "import_stats": {"javax_count": javax_count or 0},
            "imports": java_imports or [],
        },
        "dependencies": dependencies or [],
        "project_kind": project_kind or "shared_library",
        "has_juneau_contracts": bool(has_juneau_contracts),
        "internal_dependencies": internal_dependencies or [],
        "build_metadata_valid": build_metadata_valid,
        "build_metadata_readable": build_metadata_valid,
    }
    return LoadedAnalysisArtifacts(
        required={
            "analysis_report.json": report,
            "dependency_graph.json": {},
            "test_inventory.json": {},
        },
        optional={},
        errors=[],
        ok=True,
    )


def _risk(result, code: str):
    return next((item for item in result.risks if item.code == code), None)


def test_boot21_to_boot35_direct_route_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        selected_route_id="boot-2.1-direct-to-3.5-java17",
        route_strategy="direct_sandbox",
    )

    risk = _risk(result, "BOOT_PRE_27_TO_BOOT3_DIRECT_SANDBOX")
    assert risk is not None
    assert risk.severity == "HIGH"
    assert "sandbox-only" in risk.message


def test_boot21_to_boot35_multi_hop_route_is_high_but_not_blocked() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        selected_route_id="boot-2.1-to-3.5-java17",
        route_strategy="multi_hop",
        selected_hops=(
            {"id": "boot-2.1-to-2.7-java11", "target": {"spring_boot": "2.7.18"}},
            {"id": "boot-2.7-to-3.5-java17", "target": {"spring_boot": "3.5.14"}},
        ),
    )

    risk = _risk(result, "BOOT_PRE_27_TO_BOOT3_MULTI_HOP")
    assert risk is not None
    assert risk.severity == "HIGH"
    assert "boot-2.1-to-2.7-java11 -> boot-2.7-to-3.5-java17" in risk.message
    assert result.ok is True


def test_boot_pre27_to_boot3_without_mitigation_blocks() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    risk = _risk(result, "BOOT_PRE_27_TO_BOOT3_WITHOUT_MITIGATION")
    assert risk is not None
    assert risk.severity == "BLOCKER"
    assert result.ok is False


def test_javax_persistence_without_jakarta_unit_becomes_blocker() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["javax.persistence.Entity"], javax_count=1),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        planned_unit_ids=(),
    )

    assert _risk(result, "JAVAX_PERSISTENCE_BOOT3").severity == "HIGH"
    assert _risk(result, "JAKARTA_UNIT_MISSING_FOR_JPA").severity == "BLOCKER"


def test_javax_xml_bind_without_jaxb_unit_becomes_blocker() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["javax.xml.bind.JAXBContext"], javax_count=1),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        planned_unit_ids=("jakarta",),
    )

    assert _risk(result, "JAVAX_XML_BIND_BOOT3").severity == "HIGH"
    assert _risk(result, "JAXB_JAKARTA_UNIT_MISSING").severity == "BLOCKER"


def test_javax_servlet_without_jakarta_unit_becomes_blocker() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["javax.servlet.Filter"], javax_count=1),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        planned_unit_ids=(),
    )

    assert _risk(result, "JAVAX_SERVLET_BOOT3").severity == "HIGH"
    assert _risk(result, "JAKARTA_UNIT_MISSING_FOR_SERVLET").severity == "BLOCKER"


def test_javax_annotation_without_jakarta_unit_becomes_blocker() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["javax.annotation.PostConstruct"], javax_count=1),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        planned_unit_ids=(),
    )

    assert _risk(result, "JAVAX_ANNOTATION_BOOT3").severity == "HIGH"
    assert _risk(result, "JAKARTA_UNIT_MISSING_FOR_ANNOTATION").severity == "BLOCKER"


def test_javax_validation_without_jakarta_unit_becomes_blocker() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["javax.validation.Valid"], javax_count=1),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
        planned_unit_ids=(),
    )

    assert _risk(result, "JAVAX_VALIDATION_BOOT3").severity == "HIGH"
    assert _risk(result, "JAKARTA_UNIT_MISSING_FOR_VALIDATION").severity == "BLOCKER"


def test_apache_juneau_usage_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(has_juneau_contracts=True),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "APACHE_JUNEAU_HUMAN_REVIEW").severity == "HIGH"


def test_spring_security_legacy_usage_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(
            java_imports=[
                "org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter"
            ]
        ),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "SPRING_SECURITY_LEGACY_HUMAN_REVIEW").severity == "HIGH"


def test_old_azure_sdk_usage_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(java_imports=["com.microsoft.azure.storage.CloudStorageAccount"]),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "AZURE_LEGACY_SDK_HUMAN_REVIEW").severity == "HIGH"


def test_old_lombok_usage_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(
            dependencies=[{"groupId": "org.projectlombok", "artifactId": "lombok", "version": "1.16.20"}]
        ),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "LOMBOK_VERSION_REVIEW").severity == "HIGH"


def test_contract_library_is_high() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(project_kind="contract_library"),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "CONTRACT_LIBRARY_HUMAN_REVIEW").severity == "HIGH"


def test_internal_dependencies_are_warning() -> None:
    result = classify_planning_risks(
        _loaded_artifacts(
            internal_dependencies=[{"groupId": "com.total.corp", "artifactId": "contract-lib", "version": "1.0.0"}]
        ),
        StackFingerprint(build_tool="maven", java="11", spring_boot="2.1.6.RELEASE"),
        target_stack=StackFingerprint(build_tool="maven", java="17", spring_boot="3.5.14"),
    )

    assert _risk(result, "INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW").severity == "WARNING"


def test_high_risks_do_not_automatically_block_planning(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "high-risk-pass"
    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "source_stack": {"java": "11", "spring_boot": "2.1.6.RELEASE", "build_tool": "maven"},
                "project_kind": "contract_library",
                "project_metadata": {
                    "import_stats": {"javax_count": 1},
                    "imports": ["javax.persistence.Entity"],
                },
                "internal_dependencies": [
                    {"groupId": "com.total.corp", "artifactId": "contract-lib", "version": "1.0.0"}
                ],
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "test_inventory.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "analysis_summary.md").write_text("ok\n", encoding="utf-8")
    profiles = hub_dir / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "boot21.yaml").write_text(
        """
id: boot21
routes:
  - id: boot-2.1-to-3.5-java17
    strategy: multi_hop
    risk_level: high
    production_allowed: false
    preferred: true
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
source:
  java:
    allowed_versions: ["8", "11"]
  spring_boot:
    allowed_version_prefixes: ["2.1"]
  build:
    allowed_tools: ["maven"]
target:
  java: "17"
  spring_boot: "3.5.14"
  spring_framework: "6.2.18"
  build: maven
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

    result = planning_node(
        {
            "run_id": run_id,
            "profile": "boot21",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(hub_dir),
        }
    )

    assert result["planning_status"] == "PASS"
    plan_payload = yaml.safe_load(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "migration_plan.yaml").read_text(encoding="utf-8")
    )
    approval_payload = json.loads(
        (app_dir / ".migration" / "runs" / run_id / "planning" / "approval_request.json").read_text(encoding="utf-8")
    )
    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in plan_payload["risks"])
    assert any("CONTRACT_LIBRARY_HUMAN_REVIEW" in risk for risk in plan_payload["risks"])
    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in approval_payload["risks"])


def test_true_blocker_still_blocks_planning(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "blocker-fail"
    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "source_stack": {"java": "11", "spring_boot": "2.7.18", "build_tool": "maven"},
                "build_metadata_valid": False,
                "build_metadata_readable": False,
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "test_inventory.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "analysis_summary.md").write_text("ok\n", encoding="utf-8")
    profiles = hub_dir / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "java17.yaml").write_text(
        """
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
rules: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    result = planning_node(
        {
            "run_id": run_id,
            "profile": "java17",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(hub_dir),
        }
    )

    assert result["planning_status"] == "FAIL"
    assert any("UNREADABLE_BUILD_METADATA" in blocker for blocker in result["blockers"])


def test_assessment_report_propagates_planning_risks(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    hub_dir = tmp_path / "ai-hub"
    run_id = "assessment-risks"
    analysis_dir = app_dir / ".migration" / "runs" / run_id / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "run_id": run_id,
                "status": "PASS",
                "source_stack": {"java": "11", "spring_boot": "2.1.6.RELEASE", "build_tool": "maven"},
                "project_kind": "contract_library",
                "project_metadata": {
                    "import_stats": {"javax_count": 1},
                    "imports": ["javax.persistence.Entity"],
                },
                "artifact_refs": {"self": "analysis_report.json"},
            }
        ),
        encoding="utf-8",
    )
    (analysis_dir / "dependency_graph.json").write_text(json.dumps({}), encoding="utf-8")
    (analysis_dir / "test_inventory.json").write_text(json.dumps({"tests": []}), encoding="utf-8")
    (analysis_dir / "analysis_summary.md").write_text("ok\n", encoding="utf-8")
    (analysis_dir / "rewrite_impact_summary.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "run_id": run_id,
                "status": "PASS",
                "overall_impact": "LOW",
                "changed_files": [],
                "high_risk_files": [],
                "blocked_reasons": [],
            }
        ),
        encoding="utf-8",
    )
    profiles = hub_dir / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "boot21.yaml").write_text(
        """
id: boot21
routes:
  - id: boot-2.1-to-3.5-java17
    strategy: multi_hop
    risk_level: high
    production_allowed: false
    preferred: true
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
source:
  java:
    allowed_versions: ["8", "11"]
  spring_boot:
    allowed_version_prefixes: ["2.1"]
  build:
    allowed_tools: ["maven"]
target:
  java: "17"
  spring_boot: "3.5.14"
  spring_framework: "6.2.18"
  build: maven
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

    planning_result = planning_node(
        {
            "run_id": run_id,
            "profile": "boot21",
            "modernized_app_path": str(app_dir),
            "ai_hub_path": str(hub_dir),
        }
    )
    assert planning_result["planning_status"] == "PASS"
    write_assessment_artifacts(app_dir, run_id)
    assessment_payload = json.loads(
        (app_dir / ".migration" / "runs" / run_id / "assessment" / "assessment_report.json").read_text(
            encoding="utf-8"
        )
    )

    assert assessment_payload["overall_risk"] == "HIGH"
    assert any("BOOT_PRE_27_TO_BOOT3_MULTI_HOP" in risk for risk in assessment_payload["planning_risks"])
