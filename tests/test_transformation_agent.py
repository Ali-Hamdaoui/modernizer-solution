from __future__ import annotations

import json
import os
import unittest
from unittest import mock
import io
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

import yaml

from migration_factory.contracts.build import BuildRunResult
from migration_factory.agents.build_agent.classifier import BuildClassification, BuildResultKind
from migration_factory.agents.build_agent.runner import ProcessRunResult
from migration_factory.agents.transformation_agent.agent import (
    TransformationAgentError,
    TransformationRunResult,
)
from helpers import workspace_temp_dir
from migration_factory.agents.transformation_agent.execution_plan import (
    TransformationExecutionPlanError,
    write_transformation_execution_plan,
)
from migration_factory.agents.transformation_agent import execution_plan as execution_plan_module
from migration_factory.agents.transformation_agent.executor import CommandResult
from migration_factory.agents.transformation_agent.plan import load_migration_plan
from migration_factory.agents.transformation_agent.rewrite import (
    OpenRewriteExecutionContext,
    RewritePluginError,
    build_rewrite_run_command,
    default_openrewrite_policy,
    openrewrite_policy_from_mapping,
)
from migration_factory.agents.transformation_agent.pom_patches import (
    patch_forbidden_source_patterns_allow_jakarta,
    patch_batch_config_flat_file_item_reader_constructor,
    patch_jjwt_api_parser_builder_compatibility,
    patch_junit_assertthat_to_hamcrest_matcherassert,
    patch_maven_enforcer_java_version,
    patch_mockito_initmocks_to_openmocks,
    patch_pom_property,
    patch_quality_rules_allow_jakarta,
    patch_security_config_authorize_http_requests,
    patch_spring_boot_test_mockbean_to_mockitobean,
    patch_spring_data_sort_constructor_usage,
    patch_spring6_exception_handler_override_signatures,
    patch_test_javax_servlet_imports_to_jakarta,
)
from migration_factory.agents.transformation_agent.review_gates import (
    review_azure_sdk_migration_playbook,
    review_jjwt_api_migration,
    review_jakarta_hybrid_strategy,
    review_powermock_legacy_test_strategy,
)
from migration_factory.approval import write_approval_decision, write_approved_plan_lock
from migration_factory.agents.transformation_agent import run_transformation_agent
from migration_factory.agents.transformation_agent.workspace import (
    TransformationWorkspaceError,
    prepare_sandbox_workspace,
)
from migration_factory.agents.test_agent.agent import TestAgentResult as _TestAgentResult
from migration_factory.agents.transformation_agent import workspace as workspace_module
from migration_factory import transform_v1_after_approval as transform_module
from migration_factory.contracts.migration import (
    BuildValidationStatus,
    LedgerStatus,
    initialize_ledger,
    load_ledger,
    mark_build_failed,
    mark_build_passed,
    mark_unit_awaiting_build,
    mark_unit_in_progress,
)
from migration_factory.transform_v1_after_approval import main as transform_v1_after_approval_main


PLUGIN_XML = """<plugin>
  <groupId>org.openrewrite.maven</groupId>
  <artifactId>rewrite-maven-plugin</artifactId>
  <version>6.23.0</version>
</plugin>
"""


PLAN_YAML = """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: unit-001
    title: First Unit
    expected_files:
      - pom.xml
    transformations:
      - type: custom_code_change
        description: record only
    checks:
      - id: compile
        command: mvn clean compile
        required: true
"""


class TransformationAgentTests(unittest.TestCase):
    def test_execution_plan_adapter_writes_current_transformer_yaml(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            loaded_plan = load_migration_plan(output_path)

            self.assertEqual(
                output_path,
                app
                / ".migration"
                / "runs"
                / run_id
                / "transformation"
                / "transformation_execution_plan.yaml",
            )
            self.assertEqual(payload["schema_version"], "1.3")
            self.assertEqual(payload["migration"]["id"], run_id)
            self.assertEqual(payload["workspaces"]["target"]["path"], str(app.resolve()))
            self.assertEqual([unit["id"] for unit in payload["migration_units"]], ["baseline", "java-17"])
            self.assertEqual(payload["migration_units"][0]["checks"][0]["command"], "mvn clean test")
            self.assertEqual(
                payload["policies"]["openrewrite"],
                {
                    "preview_allowed": True,
                    "apply_allowed": False,
                    "sandbox_apply_allowed": True,
                    "sandbox_apply_requires_approval": True,
                    "sandbox_apply_requires_plan_lock": True,
                    "sandbox_apply_requires_workspace_under_run": True,
                    "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                },
            )
            self.assertEqual(payload["migration_units"][1]["transformations"][0]["type"], "openrewrite")
            self.assertEqual(
                payload["migration_units"][1]["transformations"][0]["active_recipes"],
                ["org.openrewrite.java.migrate.UpgradeToJava17"],
            )
            self.assertEqual(
                payload["migration_units"][1]["transformations"][0]["recipe_artifacts"],
                ["org.openrewrite.recipe:rewrite-migrate-java:3.20.0"],
            )
            self.assertEqual(loaded_plan.migration_id, run_id)
            self.assertEqual([unit.id for unit in loaded_plan.units], ["baseline", "java-17"])

    def test_execution_plan_adapter_loads_openrewrite_policy_from_ai_hub_transformation_policy(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            policy_payload = yaml.safe_load(
                (Path(__file__).resolve().parent / ".." / "modernizer-solution-ai-hub" / "policies" / "transformation.yaml").resolve().read_text(encoding="utf-8")
            )

            self.assertEqual(payload["policies"]["openrewrite"], policy_payload["openrewrite"])
            self.assertFalse(payload["policies"]["openrewrite"]["apply_allowed"])

    def test_execution_plan_adapter_carries_sandbox_execution_metadata(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            run_dir = app / ".migration" / "runs" / run_id

            self.assertEqual(payload["workspaces"]["sandbox"]["path"], str((run_dir / "workspaces" / "sandbox").resolve()))
            self.assertEqual(payload["execution_context"]["run_dir"], str(run_dir.resolve()))
            self.assertTrue(payload["execution_context"]["sandbox_execution"])
            self.assertEqual(
                payload["execution_context"]["workspace_path"],
                str((run_dir / "workspaces" / "sandbox").resolve()),
            )
            self.assertEqual(
                payload["execution_context"]["approved_plan_lock_path"],
                str((run_dir / "approval" / "approved_plan_lock.json").resolve()),
            )

    def test_execution_plan_adapter_falls_back_to_fail_safe_default_when_ai_hub_policy_unavailable(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)
            default_policy = {
                "preview_allowed": True,
                "apply_allowed": False,
                "sandbox_apply_allowed": False,
                "sandbox_apply_requires_approval": True,
                "sandbox_apply_requires_plan_lock": True,
                "sandbox_apply_requires_workspace_under_run": True,
                "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                "allowed_sandbox_apply_goals": [],
                "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
            }

            missing_path = tmp / "missing-hub" / "policies" / "transformation.yaml"
            with self.subTest("missing"):
                with mock.patch.object(
                    execution_plan_module,
                    "_canonical_transformation_policy_path",
                    return_value=missing_path,
                ):
                    output_path = write_transformation_execution_plan(app, run_id)
                payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["policies"]["openrewrite"], default_policy)

            malformed_path = tmp / "malformed-hub" / "policies" / "transformation.yaml"
            malformed_path.parent.mkdir(parents=True, exist_ok=True)
            malformed_path.write_text("openrewrite: [\n", encoding="utf-8")
            with self.subTest("malformed"):
                with mock.patch.object(
                    execution_plan_module,
                    "_canonical_transformation_policy_path",
                    return_value=malformed_path,
                ):
                    output_path = write_transformation_execution_plan(app, run_id)
                payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["policies"]["openrewrite"], default_policy)

            unreadable_path = tmp / "unreadable-hub" / "policies" / "transformation.yaml"
            unreadable_path.parent.mkdir(parents=True, exist_ok=True)
            unreadable_path.write_text("openrewrite: {}\n", encoding="utf-8")
            with self.subTest("unreadable"):
                original_read_yaml_file = execution_plan_module._read_yaml_file

                def read_yaml_side_effect(path: Path) -> dict[str, object]:
                    if path == unreadable_path:
                        raise OSError("denied")
                    return original_read_yaml_file(path)

                with mock.patch.object(
                    execution_plan_module,
                    "_canonical_transformation_policy_path",
                    return_value=unreadable_path,
                ):
                    with mock.patch.object(
                        execution_plan_module,
                        "_read_yaml_file",
                        side_effect=read_yaml_side_effect,
                    ):
                        output_path = write_transformation_execution_plan(app, run_id)
                payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
                self.assertEqual(payload["policies"]["openrewrite"], default_policy)

    def test_execution_plan_adapter_uses_per_unit_openrewrite_on_matching_unit(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools: ["maven", "junit"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    expected_artifacts: ["target/surefire-reports"]
  - id: "spring-boot-2-7-stabilization"
    goal: "Stabilize Spring Boot 2.7."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    expected_artifacts: ["target/classes"]
    openrewrite:
      active_recipes:
        - org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
""",
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            transformations = payload["migration_units"][1]["transformations"]

            self.assertEqual(transformations[0]["type"], "openrewrite")
            self.assertEqual(
                transformations[0]["active_recipes"],
                ["org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7"],
            )

    def test_execution_plan_adapter_attaches_multiple_unit_level_openrewrite_transformations(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=True,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools: ["maven", "junit"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    expected_artifacts: ["target/surefire-reports"]
  - id: "spring-boot-2-7-stabilization"
    goal: "Stabilize Spring Boot 2.7."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    expected_artifacts: ["target/classes"]
    openrewrite:
      active_recipes:
        - org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
  - id: "jakarta"
    goal: "Migrate to Jakarta."
    tools: ["maven", "jdeps"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    expected_artifacts: ["target/classes"]
    openrewrite:
      active_recipes:
        - org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta
      recipe_artifacts:
        - org.openrewrite.recipe:rewrite-migrate-java:3.34.1
      apply_goal: run
      apply_maven_args:
        - -DskipTests
      analysis_preview_maven_args:
        - -DsomeFlag=true
""",
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))

            boot_transform = payload["migration_units"][1]["transformations"][0]
            jakarta_transform = payload["migration_units"][2]["transformations"][0]

            self.assertEqual(boot_transform["type"], "openrewrite")
            self.assertEqual(
                boot_transform["active_recipes"],
                ["org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7"],
            )
            self.assertEqual(
                boot_transform["recipe_artifacts"],
                ["org.openrewrite.recipe:rewrite-migrate-java:3.20.0"],
            )
            self.assertEqual(jakarta_transform["type"], "openrewrite")
            self.assertEqual(
                jakarta_transform["active_recipes"],
                ["org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta"],
            )
            self.assertEqual(
                jakarta_transform["recipe_artifacts"],
                ["org.openrewrite.recipe:rewrite-migrate-java:3.34.1"],
            )
            self.assertEqual(jakarta_transform["apply_goal"], "run")
            self.assertEqual(jakarta_transform["apply_maven_args"], ["-DskipTests"])
            self.assertEqual(jakarta_transform["analysis_preview_maven_args"], ["-DsomeFlag=true"])

    def test_load_migration_plan_without_policy_uses_fail_safe_openrewrite_defaults(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: baseline
    title: Baseline
    transformations:
      - type: custom_code_change
        description: record only
    checks: []
""",
                encoding="utf-8",
            )

            loaded = load_migration_plan(plan, app)

            self.assertEqual(loaded.openrewrite_policy, default_openrewrite_policy())

    def test_execution_plan_checks_convert_required_semantics_and_legacy_booleans(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-required"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-required"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "required-auto"
    goal: "Auto check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "auto"
    expected_artifacts: ["target/surefire-reports"]
  - id: "required-no"
    goal: "No check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "no"
    expected_artifacts: ["target/surefire-reports"]
  - id: "required-false"
    goal: "False check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: false
    expected_artifacts: ["target/surefire-reports"]
  - id: "required-yes"
    goal: "Yes check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    expected_artifacts: ["target/surefire-reports"]
  - id: "required-true"
    goal: "True check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: true
    expected_artifacts: ["target/surefire-reports"]
  - id: "required-missing"
    goal: "Missing check."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    expected_artifacts: ["target/surefire-reports"]
""",
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            checks_by_id = {unit["id"]: unit["checks"][0]["required"] for unit in payload["migration_units"]}

            self.assertFalse(checks_by_id["required-auto"])
            self.assertFalse(checks_by_id["required-no"])
            self.assertFalse(checks_by_id["required-false"])
            self.assertTrue(checks_by_id["required-yes"])
            self.assertTrue(checks_by_id["required-true"])
            self.assertTrue(checks_by_id["required-missing"])

    def test_execution_plan_adapter_includes_per_unit_jdk_metadata(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            java11_home = tmp / "jdk11"
            java17_home = tmp / "jdk17"
            with mock.patch.dict(
                "os.environ",
                {"JAVA_HOME_11": str(java11_home), "JAVA_HOME_17": str(java17_home)},
                clear=False,
            ):
                _write_approved_run_artifacts(
                    app,
                    run_id,
                    include_rewrite_plan=False,
                    planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools: ["maven", "junit"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_artifacts: ["target/surefire-reports"]
  - id: "java-17"
    goal: "Upgrade Java."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_17"
    hop_id: "boot-2.7-to-3.5-java17"
    expected_artifacts: ["target/classes"]
""",
                )

                output_path = write_transformation_execution_plan(app, run_id)

            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            baseline = payload["migration_units"][0]
            java17 = payload["migration_units"][1]
            self.assertEqual(baseline["java_home_env"], "JAVA_HOME_11")
            self.assertEqual(baseline["java_home_used"], str(java11_home))
            self.assertEqual(baseline["hop_id"], "boot-2.1-to-2.7-java11")
            self.assertEqual(java17["java_home_env"], "JAVA_HOME_17")
            self.assertEqual(java17["java_home_used"], str(java17_home))
            self.assertEqual(java17["hop_id"], "boot-2.7-to-3.5-java17")

    def test_execution_plan_adapter_adds_sort_compile_fix_to_boot27_stabilization(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "spring-boot-2-7-stabilization"
    goal: "Stabilize Spring Boot 2.7."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_artifacts: ["target/classes"]
""",
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            transformations = payload["migration_units"][0]["transformations"]

            self.assertEqual(transformations[0]["type"], "spring_data_sort_by_factory_method")
            self.assertEqual(transformations[1]["type"], "maven_pom_patch")
            self.assertEqual(
                transformations[1]["operations"][0],
                {"op": "align_jackson_dependency_management", "version": "2.13.5"},
            )
            self.assertEqual(
                transformations[1]["operations"][1],
                {
                    "op": "remove_dependency_if_version_matches",
                    "group_id": "org.mockito",
                    "artifact_id": "mockito-inline",
                    "version_pattern": r"^[0-9]+(?:\.[0-9]+)*\.x$",
                },
            )

    def test_execution_plan_adapter_passes_optional_jackson_artifacts_from_dependency_graph(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "spring-boot-2-7-stabilization"
    goal: "Stabilize Spring Boot 2.7."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_artifacts: ["target/classes"]
""",
                dependency_graph_payload={
                    "root": {
                        "name": "com.example:demo",
                        "dependencies": [
                            {
                                "name": "com.fasterxml.jackson.dataformat:jackson-dataformat-xml",
                                "dependencies": [],
                            },
                            {
                                "name": "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
                                "dependencies": [],
                            },
                        ],
                    }
                },
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            operation = payload["migration_units"][0]["transformations"][1]["operations"][0]

            self.assertEqual(
                operation["present_artifacts"],
                [
                    "com.fasterxml.jackson.dataformat:jackson-dataformat-xml",
                    "com.fasterxml.jackson.module:jackson-module-jaxb-annotations",
                ],
            )

    def test_execution_plan_adapter_adds_lombok_alignment_to_java17_when_tooling_version_configured(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "java-17"
    goal: "Upgrade Java."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_17"
    hop_id: "boot-2.7-to-3.5-java17"
    expected_artifacts: ["target/classes"]
""",
                tooling_versions_payload={
                    "lombok": "1.18.34",
                    "jacoco": "0.8.12",
                    "maven_compiler_plugin": "3.14.1",
                },
                framework_versions_payload={
                    "jackson": "2.21.2",
                    "jackson_annotations": "2.21",
                    "jjwt": "0.13.0",
                    "juneau": "9.0.0",
                    "thymeleaf": "3.1.3.RELEASE",
                    "slf4j_api": "2.0.17",
                    "spring_security": "6.5.10",
                },
                analysis_report_payload={
                    "project_metadata": {"imports": ["javax.validation.Valid"]},
                    "dependencies": [],
                },
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            transformations = payload["migration_units"][0]["transformations"]

            self.assertEqual(transformations[0]["type"], "maven_pom_patch")
            self.assertEqual(transformations[0]["operations"][0], {"op": "align_lombok_version", "version": "1.18.34"})
            self.assertEqual(transformations[0]["operations"][1], {"op": "align_jacoco_version", "version": "0.8.12"})

    def test_write_transformation_execution_plan_adds_thymeleaf_alignment_for_boot35_unit(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "spring-boot-3-5-14"
    goal: "Upgrade Spring Boot."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_17"
    hop_id: "boot-2.7-to-3.5-java17"
    expected_artifacts: ["target/classes"]
""",
                framework_versions_payload={
                    "jackson": "2.21.2",
                    "jackson_annotations": "2.21",
                    "jjwt": "0.13.0",
                    "juneau": "9.0.0",
                    "thymeleaf": "3.1.3.RELEASE",
                    "slf4j_api": "2.0.17",
                    "spring_security": "6.5.10",
                },
                tooling_versions_payload={
                    "maven_compiler_plugin": "3.14.1",
                },
                analysis_report_payload={
                    "project_metadata": {"imports": ["javax.validation.Valid"]},
                    "dependencies": [],
                },
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            transformations = payload["migration_units"][0]["transformations"]

            self.assertEqual(transformations[0]["type"], "maven_pom_patch")
            self.assertEqual(transformations[1]["type"], "jjwt_api_compatibility_migration")
            self.assertEqual(transformations[2]["type"], "spring6_exception_handler_override_alignment")
            self.assertEqual(transformations[3]["type"], "spring_boot_test_mockbean_to_mockitobean")
            self.assertEqual(transformations[4]["type"], "mockito_initmocks_to_openmocks")
            self.assertEqual(transformations[5]["type"], "test_javax_servlet_imports_to_jakarta")
            self.assertEqual(transformations[6]["type"], "junit_assertthat_to_hamcrest_matcherassert")
            self.assertEqual(transformations[7]["type"], "jakarta_hybrid_strategy_gate")
            self.assertEqual(transformations[8]["type"], "powermock_legacy_test_strategy_gate")
            self.assertEqual(transformations[9]["type"], "azure_sdk_migration_playbook_gate")
            self.assertEqual(
                transformations[0]["operations"][0],
                {
                    "op": "align_jackson_dependency_management",
                    "version": "2.21.2",
                    "version_overrides": {
                        "com.fasterxml.jackson.core:jackson-annotations": "2.21",
                    },
                },
            )
            self.assertEqual(
                transformations[0]["operations"][1],
                {
                    "op": "align_jjwt_version",
                    "version": "0.13.0",
                },
            )
            self.assertEqual(
                transformations[0]["operations"][2],
                {
                    "op": "align_juneau_version",
                    "version": "9.0.0",
                },
            )
            self.assertEqual(
                transformations[0]["operations"][3],
                {
                    "op": "align_thymeleaf_dependencies",
                    "version": "3.1.3.RELEASE",
                    "prefer_bom_managed": True,
                },
            )
            self.assertEqual(transformations[0]["operations"][4]["op"], "align_validation_dependencies")
            self.assertEqual(transformations[0]["operations"][4]["prefer_boot_starter"], True)
            self.assertIn("javax.validation.Valid", transformations[0]["operations"][4]["detected_validation_usage"])
            self.assertEqual(transformations[0]["operations"][5], {"op": "align_slf4j_logging", "slf4j_api_version": "2.0.17"})
            self.assertEqual(
                transformations[0]["operations"][6],
                {
                    "op": "align_spring_security_dependencies",
                    "present_artifacts": [],
                    "spring_security_version": "6.5.10",
                },
            )
            self.assertEqual(
                transformations[0]["operations"][7],
                {
                    "op": "align_maven_compiler_parameters",
                    "plugin_version": "3.14.1",
                },
            )

    def test_patch_spring6_exception_handler_override_updates_httpstatus_parameter(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "Advice.java"
            java_file.write_text(
                """package com.example;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

public class Advice extends ResponseEntityExceptionHandler {
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(
            Exception ex, Object body, org.springframework.http.HttpHeaders headers, HttpStatus status, WebRequest request) {
        return super.handleExceptionInternal(ex, body, headers, status, request);
    }
}
""",
                encoding="utf-8",
            )

            before = java_file.read_text(encoding="utf-8")
            patches = patch_spring6_exception_handler_override_signatures(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("@Override", after)
            self.assertIn("HttpStatusCode status", after)
            self.assertIn("import org.springframework.http.HttpStatusCode;", after)
            self.assertIn("return super.handleExceptionInternal(ex, body, headers, status, request);", after)
            self.assertNotEqual(before, after)

    def test_patch_spring6_exception_handler_override_updates_constraint_violation_type(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "Advice.java"
            java_file.write_text(
                """package com.example;

import jakarta.validation.ConstraintViolationException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.context.request.NativeWebRequest;
import org.zalando.problem.Problem;

public class Advice {
    @Override
    public ResponseEntity<Problem> handleConstraintViolation(final ConstraintViolationException exception, final NativeWebRequest request) {
        return null;
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_spring6_exception_handler_override_signatures(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("import javax.validation.ConstraintViolationException;", after)
            self.assertIn("@Override", after)
            self.assertIn("handleConstraintViolation(final javax.validation.ConstraintViolationException exception", after)

    def test_patch_spring6_exception_handler_override_is_noop_for_unrelated_class(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "Plain.java"
            java_file.write_text(
                """package com.example;
public class Plain {
    public void ok() {}
}
""",
                encoding="utf-8",
            )

            patches = patch_spring6_exception_handler_override_signatures(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])

    def test_patch_spring6_exception_handler_override_is_noop_when_already_spring6_compatible(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "Advice.java"
            java_file.write_text(
                """package com.example;

import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

public class Advice extends ResponseEntityExceptionHandler {
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(
            Exception ex, Object body, org.springframework.http.HttpHeaders headers, HttpStatusCode status, WebRequest request) {
        return super.handleExceptionInternal(ex, body, headers, status, request);
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_spring6_exception_handler_override_signatures(app, unit_id="spring-boot-3-5-14")
            self.assertEqual(patches, [])

    def test_patch_mockbean_import_updates_to_mockitobean_import(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            java_file.write_text(
                """package com.example;

import org.springframework.boot.test.mock.mockito.MockBean;

class ExampleTest {
    @MockBean
    private Object dependency;
}
""",
                encoding="utf-8",
            )

            patches = patch_spring_boot_test_mockbean_to_mockitobean(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn(
                "import org.springframework.test.context.bean.override.mockito.MockitoBean;",
                after,
            )
            self.assertNotIn(
                "import org.springframework.boot.test.mock.mockito.MockBean;",
                after,
            )

    def test_patch_mockbean_annotation_updates_to_mockitobean_and_preserves_parameters(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "integrationTest" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleIT.java"
            java_file.write_text(
                """package com.example;

import org.springframework.boot.test.mock.mockito.MockBean;

class ExampleIT {
    @MockBean(name = "x")
    private Object dependency;
}
""",
                encoding="utf-8",
            )

            patches = patch_spring_boot_test_mockbean_to_mockitobean(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("@MockitoBean(name = \"x\")", after)

    def test_patch_mockbean_is_noop_when_already_mockitobean(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            original = """package com.example;

import org.springframework.test.context.bean.override.mockito.MockitoBean;

class ExampleTest {
    @MockitoBean
    private Object dependency;
}
"""
            java_file.write_text(original, encoding="utf-8")

            patches = patch_spring_boot_test_mockbean_to_mockitobean(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_patch_mockbean_skips_file_without_mockbean(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            original = """package com.example;

class ExampleTest {}
"""
            java_file.write_text(original, encoding="utf-8")

            patches = patch_spring_boot_test_mockbean_to_mockitobean(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_patch_initmocks_updates_this_to_openmocks(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            java_file.write_text(
                """package com.example;

import org.mockito.MockitoAnnotations;

class ExampleTest {
    void setUp() {
        MockitoAnnotations.initMocks(this);
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_mockito_initmocks_to_openmocks(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("MockitoAnnotations.openMocks(this);", after)
            self.assertNotIn("MockitoAnnotations.initMocks(this);", after)

    def test_patch_initmocks_updates_target_to_openmocks(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            java_file.write_text(
                """package com.example;

import org.mockito.MockitoAnnotations;

class ExampleTest {
    void setUp(Object target) {
        MockitoAnnotations.initMocks(target);
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_mockito_initmocks_to_openmocks(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("MockitoAnnotations.openMocks(target);", after)

    def test_patch_initmocks_is_noop_when_already_openmocks(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleTest.java"
            original = """package com.example;

import org.mockito.MockitoAnnotations;

class ExampleTest {
    void setUp() {
        MockitoAnnotations.openMocks(this);
    }
}
"""
            java_file.write_text(original, encoding="utf-8")

            patches = patch_mockito_initmocks_to_openmocks(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_patch_test_javax_servlet_import_updates_to_jakarta(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ServletTest.java"
            java_file.write_text(
                """package com.example;

import javax.servlet.ServletRequest;

class ServletTest {}
""",
                encoding="utf-8",
            )

            patches = patch_test_javax_servlet_imports_to_jakarta(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("import jakarta.servlet.ServletRequest;", after)
            self.assertNotIn("import javax.servlet.ServletRequest;", after)

    def test_patch_test_javax_servlet_http_import_updates_in_test_helper(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "testHelpers" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ServletHelper.java"
            java_file.write_text(
                """package com.example;

import javax.servlet.http.HttpServletRequest;

class ServletHelper {}
""",
                encoding="utf-8",
            )

            patches = patch_test_javax_servlet_imports_to_jakarta(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("import jakarta.servlet.http.HttpServletRequest;", after)
            self.assertNotIn("import javax.servlet.http.HttpServletRequest;", after)

    def test_patch_junit_assertthat_static_import_updates_to_matcherassert(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "AssertTest.java"
            java_file.write_text(
                """package com.example;

import static org.junit.Assert.assertThat;

class AssertTest {}
""",
                encoding="utf-8",
            )

            patches = patch_junit_assertthat_to_hamcrest_matcherassert(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("import static org.hamcrest.MatcherAssert.assertThat;", after)
            self.assertNotIn("import static org.junit.Assert.assertThat;", after)

    def test_patch_junit_assertthat_fqcn_updates_to_matcherassert(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "AssertTest.java"
            java_file.write_text(
                """package com.example;

class AssertTest {
    void check(Object actual, Object matcher) {
        org.junit.Assert.assertThat(actual, matcher);
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_junit_assertthat_to_hamcrest_matcherassert(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("org.hamcrest.MatcherAssert.assertThat(actual, matcher);", after)
            self.assertNotIn("org.junit.Assert.assertThat(actual, matcher);", after)

    def test_patch_junit_assertthat_leaves_unrelated_assert_methods_unchanged(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "AssertTest.java"
            original = """package com.example;

import static org.junit.Assert.assertEquals;

class AssertTest {
    void check() {
        org.junit.Assert.assertEquals(1, 1);
    }
}
"""
            java_file.write_text(original, encoding="utf-8")

            patches = patch_junit_assertthat_to_hamcrest_matcherassert(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_patch_jjwt_parser_assignment_adds_build_for_simple_parser_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "JwtSupport.java"
            java_file.write_text(
                """package com.example;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser() {
        JwtParser parser = Jwts.parser();
        return parser;
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_jjwt_api_parser_builder_compatibility(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("JwtParser parser = Jwts.parser().build();", after)
            self.assertIn("import io.jsonwebtoken.JwtParser;", after)
            self.assertIn("import io.jsonwebtoken.Jwts;", after)

    def test_patch_jjwt_parser_return_adds_build_for_safe_builder_chain(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "JwtSupport.java"
            java_file.write_text(
                """package com.example;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser() {
        return Jwts.parser().setSigningKeyResolver(new Object());
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_jjwt_api_parser_builder_compatibility(app, unit_id="spring-boot-3-5-14")
            after = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("return Jwts.parser().setSigningKeyResolver(new Object()).build();", after)

    def test_patch_jjwt_parser_is_noop_when_already_compatible(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "JwtSupport.java"
            original = """package com.example;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser() {
        return Jwts.parser().build();
    }
}
"""
            java_file.write_text(original, encoding="utf-8")

            patches = patch_jjwt_api_parser_builder_compatibility(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_review_jjwt_api_migration_writes_artifact_for_unresolved_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "JwtSupport.java"
            java_file.write_text(
                """package com.example;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser(Object value) {
        return Jwts.parser().unsupportedCustomizer(value);
    }
}
""",
                encoding="utf-8",
            )

            patches = patch_jjwt_api_parser_builder_compatibility(app, unit_id="spring-boot-3-5-14")
            review = review_jjwt_api_migration(app, unit_id="spring-boot-3-5-14", run_id="run-1")
            payload = json.loads(review.artifact_path.read_text(encoding="utf-8"))

            self.assertEqual(patches, [])
            self.assertTrue(review.detected)
            self.assertTrue(payload["human_review_required"])
            self.assertEqual(payload["gate_id"], "JJWT_API_MIGRATION_REVIEW")
            self.assertIn("JWT_PARSER_RETURN", payload["usage_patterns"])

    def test_test_modernization_does_not_modify_production_source(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            java_file = source / "ExampleService.java"
            original = """package com.example;

import org.mockito.MockitoAnnotations;
import org.springframework.boot.test.mock.mockito.MockBean;
import javax.servlet.http.HttpServletRequest;

class ExampleService {
    void setUp() {
        MockitoAnnotations.initMocks(this);
        org.junit.Assert.assertThat("x", "x");
    }

    @MockBean
    private Object dependency;

    HttpServletRequest request;
}
"""
            java_file.write_text(original, encoding="utf-8")

            mockbean_patches = patch_spring_boot_test_mockbean_to_mockitobean(app, unit_id="spring-boot-3-5-14")
            initmocks_patches = patch_mockito_initmocks_to_openmocks(app, unit_id="spring-boot-3-5-14")
            servlet_patches = patch_test_javax_servlet_imports_to_jakarta(app, unit_id="spring-boot-3-5-14")
            assertthat_patches = patch_junit_assertthat_to_hamcrest_matcherassert(app, unit_id="spring-boot-3-5-14")

            self.assertEqual(mockbean_patches, [])
            self.assertEqual(initmocks_patches, [])
            self.assertEqual(servlet_patches, [])
            self.assertEqual(assertthat_patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_powermock_review_detects_dependencies_in_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-module-junit4</artifactId>
      <version>2.0.9</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14", run_id="run-1")
            payload = json.loads(review.artifact_path.read_text(encoding="utf-8"))

            self.assertTrue(review.detected)
            self.assertEqual(review.dependencies, ["org.powermock:powermock-module-junit4"])
            self.assertTrue(payload["human_review_required"])

    def test_powermock_review_detects_runner_and_prepare_for_test(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            (source / "ExampleTest.java").write_text(
                """package com.example;

import org.junit.runner.RunWith;
import org.powermock.modules.junit4.PowerMockRunner;
import org.powermock.core.classloader.annotations.PrepareForTest;

@RunWith(PowerMockRunner.class)
@PrepareForTest({Example.class})
class ExampleTest {}
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")

            self.assertTrue(review.detected)
            self.assertIn("POWERMOCK_RUNNER", review.usage_patterns)
            self.assertIn("POWERMOCK_PREPARE_FOR_TEST", review.usage_patterns)

    def test_powermock_review_detects_static_mocking(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            (source / "ExampleTest.java").write_text(
                """package com.example;

import org.powermock.api.mockito.PowerMockito;

class ExampleTest {
    void test() {
        PowerMockito.mockStatic(Example.class);
    }
}
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")

            self.assertIn("POWERMOCK_API", review.usage_patterns)
            self.assertIn("POWERMOCK_STATIC_MOCKING", review.usage_patterns)

    def test_powermock_review_detects_whennew(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            (source / "ExampleTest.java").write_text(
                """package com.example;

class ExampleTest {
    void test() {
        whenNew(Example.class);
    }
}
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")

            self.assertIn("POWERMOCK_CONSTRUCTOR_MOCKING", review.usage_patterns)

    def test_powermock_review_detects_whitebox(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "test" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            (source / "ExampleTest.java").write_text(
                """package com.example;

class ExampleTest {
    void test() {
        Whitebox.setInternalState(this, "x", 1);
    }
}
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")

            self.assertIn("POWERMOCK_WHITEBOX", review.usage_patterns)

    def test_powermock_review_dependency_present_without_usage_recommends_cleanup(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-api-mockito2</artifactId>
      <version>2.0.9</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")

            self.assertTrue(any("dependency cleanup" in item.lower() for item in review.recommended_next_actions))

    def test_powermock_review_no_usage_returns_detected_false(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")

            review = review_powermock_legacy_test_strategy(app, unit_id="spring-boot-3-5-14")
            payload = json.loads(review.artifact_path.read_text(encoding="utf-8"))

            self.assertFalse(review.detected)
            self.assertFalse(payload["human_review_required"])

    def test_jakarta_hybrid_strategy_detects_xml_bind_as_deterministic_candidate(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Example.java").write_text(
                "import javax.xml.bind.JAXBContext;\nclass Example {}\n",
                encoding="utf-8",
            )

            review = review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14")
            payload = json.loads(review.artifact_path.read_text(encoding="utf-8"))

            assert payload["namespaces"]["javax.xml.bind"]["classification"] == "DETERMINISTIC_SAFE_MIGRATION_CANDIDATE"
            assert payload["namespaces"]["javax.xml.bind"]["safe_to_auto_apply"] is True

    def test_jakarta_hybrid_strategy_detects_validation_as_dependency_candidate(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Example.java").write_text(
                "import javax.validation.Valid;\nclass Example {}\n",
                encoding="utf-8",
            )

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["namespaces"]["javax.validation"]["classification"] == "DETERMINISTIC_PLUS_DEPENDENCY_ALIGNMENT"
            assert payload["namespaces"]["javax.validation"]["dependency_recommendations"]

    def test_jakarta_hybrid_strategy_detects_servlet_as_dependency_candidate(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Example.java").write_text(
                "import javax.servlet.http.HttpServletRequest;\nclass Example {}\n",
                encoding="utf-8",
            )

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["namespaces"]["javax.servlet"]["classification"] == "DETERMINISTIC_PLUS_DEPENDENCY_ALIGNMENT"

    def test_jakarta_hybrid_strategy_detects_persistence_as_human_review(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Entity.java").write_text(
                "import javax.persistence.Entity;\n@Entity class EntityType {}\n",
                encoding="utf-8",
            )

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["namespaces"]["javax.persistence"]["requires_human_approval"] is True
            assert payload["human_review_required"] is True

    def test_jakarta_hybrid_strategy_detects_unknown_namespace_as_human_review(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Example.java").write_text(
                "import javax.mail.Message;\nclass Example {}\n",
                encoding="utf-8",
            )

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["detected"] is True
            assert payload["namespaces"]["javax.mail.Message"]["requires_human_approval"] is True

    def test_jakarta_hybrid_strategy_detects_public_api_dto_consumer_warning(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example" / "dto"
            source.mkdir(parents=True)
            (source / "CustomerDto.java").write_text(
                "import javax.validation.Valid;\nclass CustomerDto {}\n",
                encoding="utf-8",
            )

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["consumer_compatibility_warning"] is True
            assert any("consumer compatibility review required" in warning.lower() for warning in payload["warnings"])

    def test_jakarta_hybrid_strategy_no_usage_returns_detected_false(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()

            payload = json.loads(
                review_jakarta_hybrid_strategy(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            assert payload["detected"] is False
            assert payload["human_review_required"] is False

    def test_azure_sdk_review_detects_old_dependencies_in_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.microsoft.azure</groupId>
      <artifactId>azure-servicebus</artifactId>
      <version>3.6.7</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )

            review = review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14")
            payload = json.loads(review.artifact_path.read_text(encoding="utf-8"))

            self.assertTrue(review.detected)
            self.assertEqual(payload["migration_mode"], "OLD_SDK_ONLY")
            self.assertEqual(payload["risk_level"], "HIGH")
            self.assertTrue(payload["human_review_required"])
            self.assertFalse(payload["safe_to_auto_apply"])

    def test_azure_sdk_review_detects_new_dependencies_in_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.azure</groupId>
      <artifactId>azure-storage-blob</artifactId>
      <version>12.25.3</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )

            payload = json.loads(
                review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            self.assertEqual(payload["migration_mode"], "NEW_SDK_ONLY")
            self.assertEqual(payload["risk_level"], "INFO")
            self.assertFalse(payload["human_review_required"])

    def test_azure_sdk_review_detects_mixed_old_and_new_dependencies(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.microsoft.azure</groupId>
      <artifactId>azure-servicebus</artifactId>
      <version>3.6.7</version>
    </dependency>
    <dependency>
      <groupId>com.azure</groupId>
      <artifactId>azure-messaging-servicebus</artifactId>
      <version>7.17.9</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )

            payload = json.loads(
                review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            self.assertEqual(payload["migration_mode"], "MIXED_OLD_AND_NEW")
            self.assertTrue(payload["human_review_required"])
            self.assertTrue(any("mixed old and new azure sdk" in warning.lower() for warning in payload["warnings"]))

    def test_azure_sdk_review_detects_old_imports_and_service_bus_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "BusClient.java").write_text(
                """package demo;
import com.microsoft.azure.servicebus.QueueClient;
class BusClient {
    QueueClient client;
}
""",
                encoding="utf-8",
            )

            review = review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14")

            self.assertIn("AZURE_OLD_IMPORT", review.usage_patterns)
            self.assertIn("SERVICE_BUS_USAGE", review.usage_patterns)

    def test_azure_sdk_review_detects_modern_imports_and_blob_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "BlobClient.java").write_text(
                """package demo;
import com.azure.storage.blob.BlobContainerClient;
class BlobClient {
    BlobContainerClient client;
}
""",
                encoding="utf-8",
            )

            review = review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14")

            self.assertIn("AZURE_NEW_IMPORT", review.usage_patterns)
            self.assertIn("BLOB_STORAGE_USAGE", review.usage_patterns)

    def test_azure_sdk_review_no_usage_returns_detected_false(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()

            payload = json.loads(
                review_azure_sdk_migration_playbook(app, unit_id="spring-boot-3-5-14").artifact_path.read_text(encoding="utf-8")
            )

            self.assertFalse(payload["detected"])
            self.assertEqual(payload["migration_mode"], "NOT_DETECTED")

    def test_openrewrite_transformation_uses_unit_level_java_home_env(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: ".migration/ledger.json"
migration_units:
  - id: "spring-boot-2-7-stabilization"
    title: "Stabilize"
    java_home_env: "JAVA_HOME_11"
    java_home_used: "C:/fake/jdk11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_files: ["target/classes"]
    transformations:
      - type: openrewrite
        active_recipes:
          - org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult(command="mvn", exit_code=0, stdout=[], stderr=[], duration_seconds=0.01),
            ) as run_command_mock:
                with mock.patch("builtins.input", return_value=""):
                    run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            env = run_command_mock.call_args.kwargs["env"]
            self.assertEqual(env["JAVA_HOME"], "C:/fake/jdk11")
            self.assertTrue(env["PATH"].startswith(str(Path("C:/fake/jdk11") / "bin") + os.pathsep))

    def test_sort_constructor_patch_replaces_simple_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            java_file = source / "Demo.java"
            java_file.write_text(
                """
package demo;
import org.springframework.data.domain.Sort;
import org.springframework.data.domain.Sort.Direction;
class Demo {
    Sort build() {
        return new Sort(Direction.ASC, "name");
    }
}
""".strip(),
                encoding="utf-8",
            )

            patches = patch_spring_data_sort_constructor_usage(app, unit_id="spring-boot-2-7-stabilization")
            updated = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn('Sort.by(Direction.ASC, "name")', updated)
            self.assertNotIn('new Sort(Direction.ASC, "name")', updated)

    def test_sort_constructor_patch_replaces_variable_property_expression(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            java_file = source / "Demo.java"
            java_file.write_text(
                """
package demo;
import org.springframework.data.domain.Sort;
class Demo {
    Sort build(Sort.Direction direction, String property) {
        return new Sort(direction, property);
    }
}
""".strip(),
                encoding="utf-8",
            )

            patches = patch_spring_data_sort_constructor_usage(app, unit_id="spring-boot-2-7-stabilization")
            updated = java_file.read_text(encoding="utf-8")

            self.assertEqual(len(patches), 1)
            self.assertIn("Sort.by(direction, property)", updated)

    def test_sort_constructor_patch_does_not_modify_unrelated_constructor(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            java_file = source / "Demo.java"
            original = """
package demo;
class Demo {
    Object build(Direction direction, String property) {
        return new Something(direction, property);
    }
}
""".strip()
            java_file.write_text(original, encoding="utf-8")

            patches = patch_spring_data_sort_constructor_usage(app, unit_id="spring-boot-2-7-stabilization")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_sort_constructor_patch_skips_files_without_spring_data_sort_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "app"
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            java_file = source / "Demo.java"
            original = """
package demo;
class Demo {
    Object build() {
        return new Sort(Direction.ASC, "name");
    }
}
""".strip()
            java_file.write_text(original, encoding="utf-8")

            patches = patch_spring_data_sort_constructor_usage(app, unit_id="spring-boot-2-7-stabilization")

            self.assertEqual(patches, [])
            self.assertEqual(java_file.read_text(encoding="utf-8"), original)

    def test_sort_constructor_patch_records_applied_file_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "Demo.java").write_text(
                """
package demo;
import org.springframework.data.domain.Sort;
class Demo {
    Sort build(Sort.Direction direction, String property) {
        return new Sort(direction, property);
    }
}
""".strip(),
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-2-7-stabilization"
    title: "Stabilize"
    expected_files: ["target/classes"]
    transformations:
      - type: spring_data_sort_by_factory_method
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["spring-boot-2-7-stabilization"]["transformations"][0]
            self.assertEqual(transformation["type"], "spring_data_sort_by_factory_method")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\main\\java\\demo\\Demo.java")

    def test_mockbean_to_mockitobean_records_changed_test_file_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "test" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "DemoTest.java").write_text(
                """package demo;

import org.springframework.boot.test.mock.mockito.MockBean;

class DemoTest {
    @MockBean
    Object dependency;
}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    expected_files: ["target/test-classes"]
    transformations:
      - type: spring_boot_test_mockbean_to_mockitobean
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "spring_boot_test_mockbean_to_mockitobean")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\test\\java\\demo\\DemoTest.java")

    def test_initmocks_to_openmocks_records_changed_test_file_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "test" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "DemoTest.java").write_text(
                """package demo;

import org.mockito.MockitoAnnotations;

class DemoTest {
    void setUp() {
        MockitoAnnotations.initMocks(this);
    }
}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    expected_files: ["target/test-classes"]
    transformations:
      - type: mockito_initmocks_to_openmocks
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "mockito_initmocks_to_openmocks")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\test\\java\\demo\\DemoTest.java")

    def test_openrewrite_runs_from_nested_maven_project_root(self) -> None:
        with workspace_temp_dir() as tmp:
            sandbox = tmp / "sandbox"
            module = sandbox / "common-utils"
            module.mkdir(parents=True)
            (module / "pom.xml").write_text("<project />", encoding="utf-8")
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-2-7-stabilization"
    title: "Stabilize"
    expected_files: ["target/classes"]
    transformations:
      - type: openrewrite
        active_recipes:
          - org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
        recipe_artifacts:
          - org.openrewrite.recipe:rewrite-spring:6.30.4
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult("mvn rewrite", 0, ["ok"], [], 0.1),
            ) as run_command_mock:
                result = run_transformation_agent(sandbox, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(run_command_mock.call_args.kwargs["cwd"], module)

    def test_test_javax_servlet_import_records_changed_test_file_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "test" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "DemoTest.java").write_text(
                """package demo;

import javax.servlet.http.HttpServletRequest;

class DemoTest {
    HttpServletRequest request;
}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    expected_files: ["target/test-classes"]
    transformations:
      - type: test_javax_servlet_imports_to_jakarta
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "test_javax_servlet_imports_to_jakarta")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\test\\java\\demo\\DemoTest.java")

    def test_junit_assertthat_records_changed_test_file_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "test" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "DemoTest.java").write_text(
                """package demo;

import static org.junit.Assert.assertThat;

class DemoTest {}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    expected_files: ["target/test-classes"]
    transformations:
      - type: junit_assertthat_to_hamcrest_matcherassert
    checks:
      - id: validation
        command: mvn clean test
        required: true
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "junit_assertthat_to_hamcrest_matcherassert")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\test\\java\\demo\\DemoTest.java")

    def test_jjwt_api_compatibility_records_patch_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "JwtSupport.java").write_text(
                """package demo;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser() {
        return Jwts.parser();
    }
}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    transformations:
      - type: jjwt_api_compatibility_migration
    checks: []
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "jjwt_api_compatibility_migration")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["patches"][0]["file"], "src\\main\\java\\demo\\JwtSupport.java")
            self.assertFalse(transformation["human_review_required"])

    def test_jjwt_api_compatibility_records_review_artifact_for_unsafe_usage(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "JwtSupport.java").write_text(
                """package demo;

import io.jsonwebtoken.JwtParser;
import io.jsonwebtoken.Jwts;

class JwtSupport {
    JwtParser parser(Object value) {
        return Jwts.parser().unsupportedCustomizer(value);
    }
}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    transformations:
      - type: jjwt_api_compatibility_migration
    checks: []
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "jjwt_api_compatibility_migration")
            self.assertEqual(transformation["status"], "review_only")
            self.assertTrue(transformation["human_review_required"])
            self.assertTrue(Path(transformation["artifact_path"]).is_file())

    def test_powermock_gate_records_review_artifact_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.powermock</groupId>
      <artifactId>powermock-module-junit4</artifactId>
      <version>2.0.9</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            source = app / "src" / "test" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "DemoTest.java").write_text(
                """package demo;

import org.junit.runner.RunWith;
import org.powermock.modules.junit4.PowerMockRunner;

@RunWith(PowerMockRunner.class)
class DemoTest {}
""",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    transformations:
      - type: powermock_legacy_test_strategy_gate
    checks: []
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "powermock_legacy_test_strategy_gate")
            self.assertEqual(transformation["status"], "review_only")
            self.assertTrue(transformation["human_review_required"])
            self.assertTrue(Path(transformation["artifact_path"]).is_file())

    def test_jakarta_hybrid_gate_records_review_artifact_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            source = app / "src" / "main" / "java" / "demo" / "dto"
            source.mkdir(parents=True)
            (source / "DemoDto.java").write_text(
                "import javax.persistence.Entity;\nclass DemoDto {}\n",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    transformations:
      - type: jakarta_hybrid_strategy_gate
    checks: []
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "jakarta_hybrid_strategy_gate")
            self.assertEqual(transformation["status"], "review_only")
            self.assertTrue(transformation["human_review_required"])
            self.assertTrue(Path(transformation["artifact_path"]).is_file())

    def test_azure_sdk_gate_records_review_artifact_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>com.microsoft.azure</groupId>
      <artifactId>azure-storage</artifactId>
      <version>8.6.6</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            source = app / "src" / "main" / "java" / "demo"
            source.mkdir(parents=True)
            (source / "StorageClient.java").write_text(
                "import com.microsoft.azure.storage.CloudStorageAccount;\nclass StorageClient {}\n",
                encoding="utf-8",
            )
            plugin = tmp / "plugin.xml"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")
            plan_path = tmp / "plan.yaml"
            plan_path.write_text(
                """
schema_version: "1.3"
migration:
  id: "run-1"
  name: "Test"
workspaces:
  target:
    path: "."
    migration_dir: ".migration"
    ledger_file: .migration/ledger.json
migration_units:
  - id: "spring-boot-3-5-14"
    title: "Upgrade"
    transformations:
      - type: azure_sdk_migration_playbook_gate
    checks: []
""".lstrip(),
                encoding="utf-8",
            )

            with mock.patch("builtins.input", return_value=""):
                result = run_transformation_agent(app, plugin, plan_path, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            self.assertEqual(transformation["type"], "azure_sdk_migration_playbook_gate")
            self.assertEqual(transformation["status"], "review_only")
            self.assertEqual(transformation["migration_mode"], "OLD_SDK_ONLY")
            self.assertTrue(transformation["human_review_required"])
            self.assertTrue(Path(transformation["artifact_path"]).is_file())

    def test_execution_plan_adapter_units_without_openrewrite_do_not_receive_openrewrite_transformation(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools: ["maven", "junit"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    expected_artifacts: ["target/surefire-reports"]
  - id: "dependency-cleanup"
    goal: "Cleanup dependencies."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    expected_artifacts: ["target/dependency"]
""",
            )

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))

            for unit in payload["migration_units"]:
                self.assertEqual([item["type"] for item in unit["transformations"]], ["custom_code_change"])

    def test_execution_plan_adapter_no_recipes_means_no_openrewrite_transformation(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=False)

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))

            for unit in payload["migration_units"]:
                self.assertEqual([item["type"] for item in unit["transformations"]], ["custom_code_change"])

    def test_execution_plan_adapter_rejects_missing_approval_decision(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_run_artifacts(app, run_id)
            write_approved_plan_lock(_run_dir(app, run_id), run_id)

            with self.assertRaisesRegex(
                TransformationExecutionPlanError,
                "approval_decision.json missing",
            ):
                write_transformation_execution_plan(app, run_id)

    def test_execution_plan_adapter_rejects_invalid_plan_lock(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id)
            units_path = _run_dir(app, run_id) / "planning" / "migration_units.yaml"
            units_path.write_text(units_path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

            with self.assertRaisesRegex(
                TransformationExecutionPlanError,
                "approved_plan_lock.json artifact hashes do not match current run artifacts",
            ):
                write_transformation_execution_plan(app, run_id)

    def test_transformation_agent_initializes_ledger_and_waits_for_build(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(PLAN_YAML, encoding="utf-8")
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, dry_run=True, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(ledger["current_unit"], "unit-001")
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PENDING)

    def test_baseline_unit_does_not_inject_openrewrite_plugin_into_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                PLAN_YAML.replace("unit-001", "baseline").replace("First Unit", "Baseline"),
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, dry_run=True, wait_for_continue=False)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertNotIn("rewrite-maven-plugin", (app / "pom.xml").read_text(encoding="utf-8"))

    def test_openrewrite_transform_uses_fully_qualified_concrete_plugin_goal(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: java-17
    title: Java 17
    transformations:
      - type: openrewrite
        active_recipes:
          - org.openrewrite.java.migrate.UpgradeToJava17
        recipe_artifacts:
          - org.openrewrite.recipe:rewrite-migrate-java:RELEASE
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(
                PLUGIN_XML.replace("<version>6.23.0</version>", "<version>RELEASE</version>"),
                encoding="utf-8",
            )

            result = run_transformation_agent(app, plugin, plan, dry_run=True, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)
            command = ledger["units"]["java-17"]["commands"][0]["command"]

            self.assertIn("org.openrewrite.maven:rewrite-maven-plugin:6.39.0:dryRun", command)
            self.assertIn("-Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:RELEASE", command)
            self.assertNotIn("rewrite:run", command)
            self.assertNotIn("rewrite-maven-plugin:RELEASE", command)

    def test_openrewrite_command_builder_rejects_forbidden_apply_goals_when_apply_not_allowed(self) -> None:
        policy = default_openrewrite_policy()
        active_recipes = ["org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5"]
        forbidden_goals = [
            "run",
            "runNoFork",
            "rewrite:run",
            "rewrite:runNoFork",
            "org.openrewrite.maven:rewrite-maven-plugin:6.23.0:run",
            "org.openrewrite.maven:rewrite-maven-plugin:6.23.0:runNoFork",
        ]

        for goal in forbidden_goals:
            with self.subTest(goal=goal):
                with self.assertRaisesRegex(RewritePluginError, "OPENREWRITE_GOAL_FORBIDDEN"):
                    build_rewrite_run_command(
                        active_recipes,
                        plugin_version="6.23.0",
                        apply_goal=goal,
                        policy=policy,
                    )

    def test_openrewrite_command_builder_defaults_to_safe_preview_goal(self) -> None:
        command = build_rewrite_run_command(
            ["org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5"],
            plugin_version="6.23.0",
            policy=default_openrewrite_policy(),
        )

        self.assertIn("rewrite-maven-plugin:6.23.0:dryRun", command)
        self.assertNotIn("rewrite-maven-plugin:6.23.0:run", command)

    def test_openrewrite_command_builder_accepts_allowed_preview_goals(self) -> None:
        policy = openrewrite_policy_from_mapping(
            {
                "preview_allowed": True,
                "apply_allowed": False,
                "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
            }
        )
        active_recipes = ["org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5"]

        for goal in ("dryRun", "dryRunNoFork", "discover"):
            with self.subTest(goal=goal):
                command = build_rewrite_run_command(
                    active_recipes,
                    plugin_version="6.23.0",
                    apply_goal=goal,
                    policy=policy,
                )
                self.assertIn(f"rewrite-maven-plugin:6.23.0:{goal}", command)

    def test_openrewrite_command_builder_blocks_apply_outside_sandbox_when_global_apply_forbidden(self) -> None:
        policy = openrewrite_policy_from_mapping(
            {
                "preview_allowed": True,
                "apply_allowed": False,
                "sandbox_apply_allowed": True,
                "sandbox_apply_requires_approval": True,
                "sandbox_apply_requires_plan_lock": True,
                "sandbox_apply_requires_workspace_under_run": True,
                "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
            }
        )

        with self.assertRaisesRegex(RewritePluginError, "sandbox execution context is missing"):
            build_rewrite_run_command(
                ["org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5"],
                plugin_version="6.23.0",
                apply_goal="run",
                policy=policy,
            )

    def test_openrewrite_command_builder_blocks_sandbox_apply_without_approval(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            sandbox = run_dir / "workspaces" / "sandbox"
            approval_lock = run_dir / "approval" / "approved_plan_lock.json"
            sandbox.mkdir(parents=True)
            approval_lock.parent.mkdir(parents=True)
            approval_lock.write_text("{}\n", encoding="utf-8")
            policy = openrewrite_policy_from_mapping(
                {
                    "preview_allowed": True,
                    "apply_allowed": False,
                    "sandbox_apply_allowed": True,
                    "sandbox_apply_requires_approval": True,
                    "sandbox_apply_requires_plan_lock": True,
                    "sandbox_apply_requires_workspace_under_run": True,
                    "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                }
            )
            context = OpenRewriteExecutionContext(
                unit_id="java-17",
                run_dir=run_dir,
                workspace_path=sandbox,
                approved_plan_lock_path=approval_lock,
                approval_decision="rejected",
                approval_approved=False,
                sandbox_execution=True,
            )

            with self.assertRaisesRegex(RewritePluginError, "approval is not approved"):
                build_rewrite_run_command(
                    ["org.openrewrite.java.migrate.UpgradeToJava17"],
                    plugin_version="6.23.0",
                    apply_goal="run",
                    policy=policy,
                    context=context,
                )

    def test_openrewrite_command_builder_blocks_sandbox_apply_without_plan_lock(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            sandbox = run_dir / "workspaces" / "sandbox"
            sandbox.mkdir(parents=True)
            policy = openrewrite_policy_from_mapping(
                {
                    "preview_allowed": True,
                    "apply_allowed": False,
                    "sandbox_apply_allowed": True,
                    "sandbox_apply_requires_approval": True,
                    "sandbox_apply_requires_plan_lock": True,
                    "sandbox_apply_requires_workspace_under_run": True,
                    "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                }
            )
            context = OpenRewriteExecutionContext(
                unit_id="java-17",
                run_dir=run_dir,
                workspace_path=sandbox,
                approved_plan_lock_path=run_dir / "approval" / "approved_plan_lock.json",
                approval_decision="approved",
                approval_approved=True,
                sandbox_execution=True,
            )

            with self.assertRaisesRegex(RewritePluginError, "approved plan lock not found"):
                build_rewrite_run_command(
                    ["org.openrewrite.java.migrate.UpgradeToJava17"],
                    plugin_version="6.23.0",
                    apply_goal="run",
                    policy=policy,
                    context=context,
                )

    def test_openrewrite_command_builder_blocks_sandbox_apply_outside_sandbox_workspace(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            outside = tmp / "outside-workspace"
            approval_lock = run_dir / "approval" / "approved_plan_lock.json"
            outside.mkdir(parents=True)
            approval_lock.parent.mkdir(parents=True)
            approval_lock.write_text("{}\n", encoding="utf-8")
            policy = openrewrite_policy_from_mapping(
                {
                    "preview_allowed": True,
                    "apply_allowed": False,
                    "sandbox_apply_allowed": True,
                    "sandbox_apply_requires_approval": True,
                    "sandbox_apply_requires_plan_lock": True,
                    "sandbox_apply_requires_workspace_under_run": True,
                    "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                }
            )
            context = OpenRewriteExecutionContext(
                unit_id="java-17",
                run_dir=run_dir,
                workspace_path=outside,
                approved_plan_lock_path=approval_lock,
                approval_decision="approved",
                approval_approved=True,
                sandbox_execution=True,
            )

            with self.assertRaisesRegex(RewritePluginError, "outside sandbox root"):
                build_rewrite_run_command(
                    ["org.openrewrite.java.migrate.UpgradeToJava17"],
                    plugin_version="6.23.0",
                    apply_goal="runNoFork",
                    policy=policy,
                    context=context,
                )

    def test_openrewrite_command_builder_allows_sandbox_apply_when_governed_conditions_pass(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            sandbox = run_dir / "workspaces" / "sandbox"
            approval_lock = run_dir / "approval" / "approved_plan_lock.json"
            sandbox.mkdir(parents=True)
            approval_lock.parent.mkdir(parents=True)
            approval_lock.write_text("{}\n", encoding="utf-8")
            policy = openrewrite_policy_from_mapping(
                {
                    "preview_allowed": True,
                    "apply_allowed": False,
                    "sandbox_apply_allowed": True,
                    "sandbox_apply_requires_approval": True,
                    "sandbox_apply_requires_plan_lock": True,
                    "sandbox_apply_requires_workspace_under_run": True,
                    "allowed_preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "allowed_sandbox_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                }
            )
            context = OpenRewriteExecutionContext(
                unit_id="java-17",
                run_dir=run_dir,
                workspace_path=sandbox,
                approved_plan_lock_path=approval_lock,
                approval_decision="approved",
                approval_approved=True,
                sandbox_execution=True,
            )

            command = build_rewrite_run_command(
                ["org.openrewrite.java.migrate.UpgradeToJava17"],
                plugin_version="6.23.0",
                apply_goal="rewrite:runNoFork",
                policy=policy,
                context=context,
            )

            self.assertIn("rewrite-maven-plugin:6.23.0:runNoFork", command)

    def test_openrewrite_apply_goal_is_blocked_before_command_execution(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
policies:
  openrewrite:
    preview_allowed: true
    apply_allowed: false
    allowed_preview_goals:
      - dryRun
      - dryRunNoFork
      - discover
    forbidden_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
migration_units:
  - id: java-21
    title: Java 21
    transformations:
      - type: openrewrite
        apply_goal: runNoFork
        apply_maven_args:
          - -Denforcer.skip=true
        active_recipes:
          - org.openrewrite.java.migrate.UpgradeToJava21
        recipe_artifacts:
          - org.openrewrite.recipe:rewrite-migrate-java:RELEASE
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with mock.patch("migration_factory.agents.transformation_agent.agent.run_command") as run_command:
                with self.assertRaisesRegex(
                    TransformationAgentError,
                    "OPENREWRITE_GOAL_FORBIDDEN unit=java-21 requested_goal=runNoFork",
                ):
                    run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(app / ".migration" / "ledger.json")
            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "java-21")
            self.assertEqual(
                ledger["units"]["java-21"]["blocking_reason"],
                "OPENREWRITE_GOAL_FORBIDDEN unit=java-21 requested_goal=runNoFork normalized_goal=runNoFork",
            )
            self.assertEqual(ledger["units"]["java-21"]["transformations"][0]["error_code"], "OPENREWRITE_GOAL_FORBIDDEN")
            self.assertEqual(ledger["units"]["java-21"]["commands"], [])
            run_command.assert_not_called()

    def test_openrewrite_apply_goal_is_blocked_before_command_execution_when_sandbox_lock_missing(self) -> None:
        with workspace_temp_dir() as tmp:
            sandbox = tmp / "run" / "workspaces" / "sandbox"
            sandbox.mkdir(parents=True)
            (sandbox / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                f"""
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: {sandbox.as_posix()}
    migration_dir: .migration
    ledger_file: .migration/ledger.json
  sandbox:
    path: {sandbox.as_posix()}
execution_context:
  run_dir: {(tmp / "run").as_posix()}
  sandbox_execution: true
  workspace_path: {sandbox.as_posix()}
  approval_decision: approved
  approved_plan_lock_path: {(tmp / "run" / "approval" / "approved_plan_lock.json").as_posix()}
policies:
  openrewrite:
    preview_allowed: true
    apply_allowed: false
    sandbox_apply_allowed: true
    sandbox_apply_requires_approval: true
    sandbox_apply_requires_plan_lock: true
    sandbox_apply_requires_workspace_under_run: true
    allowed_preview_goals:
      - dryRun
      - dryRunNoFork
      - discover
    allowed_sandbox_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
    forbidden_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
migration_units:
  - id: jakarta
    title: Jakarta
    transformations:
      - type: openrewrite
        apply_goal: run
        active_recipes:
          - org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with mock.patch("migration_factory.agents.transformation_agent.agent.run_command") as run_command:
                with self.assertRaisesRegex(
                    TransformationAgentError,
                    "OPENREWRITE_GOAL_FORBIDDEN unit=jakarta requested_goal=run",
                ):
                    run_transformation_agent(sandbox, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(sandbox / ".migration" / "ledger.json")
            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "jakarta")
            self.assertIn("approved plan lock not found", ledger["units"]["jakarta"]["transformations"][0]["error_message"])
            run_command.assert_not_called()

    def test_openrewrite_apply_goal_executes_in_approved_sandbox_and_targets_sandbox_workspace(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            sandbox = run_dir / "workspaces" / "sandbox"
            approval_lock = run_dir / "approval" / "approved_plan_lock.json"
            approval_decision = run_dir / "approval" / "approval_decision.json"
            sandbox.mkdir(parents=True)
            approval_lock.parent.mkdir(parents=True)
            approval_lock.write_text("{}\n", encoding="utf-8")
            approval_decision.write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
            (sandbox / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                f"""
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: {sandbox.as_posix()}
    migration_dir: .migration
    ledger_file: .migration/ledger.json
  sandbox:
    path: {sandbox.as_posix()}
execution_context:
  run_dir: {run_dir.as_posix()}
  sandbox_execution: true
  workspace_path: {sandbox.as_posix()}
  approval_decision_path: {approval_decision.as_posix()}
  approved_plan_lock_path: {approval_lock.as_posix()}
policies:
  openrewrite:
    preview_allowed: true
    apply_allowed: false
    sandbox_apply_allowed: true
    sandbox_apply_requires_approval: true
    sandbox_apply_requires_plan_lock: true
    sandbox_apply_requires_workspace_under_run: true
    allowed_preview_goals:
      - dryRun
      - dryRunNoFork
      - discover
    allowed_sandbox_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
    forbidden_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
migration_units:
  - id: jakarta
    title: Jakarta
    transformations:
      - type: openrewrite
        apply_goal: runNoFork
        active_recipes:
          - org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult(
                    command="mvn",
                    exit_code=0,
                    stdout=[],
                    stderr=[],
                    duration_seconds=0.01,
                ),
            ) as run_command:
                result = run_transformation_agent(sandbox, plugin, plan, wait_for_continue=False)

            self.assertEqual(run_command.call_args.kwargs["cwd"], sandbox)
            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertIn("runNoFork", run_command.call_args.args[0])

    def test_non_openrewrite_transformation_still_behaves_as_before(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                PLAN_YAML,
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, dry_run=True, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(ledger["status"], LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(ledger["units"]["unit-001"]["commands"], [])

    def test_openrewrite_apply_settings_are_loaded_from_profile_and_catalog(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=True,
                source_unit_id="java-21",
                source_unit_goal="Upgrade project runtime to Java 21.",
            )
            ai_hub = tmp / "ai-hub"
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
  apply_goal: runNoFork
  apply_maven_args:
    - -Denforcer.skip=true
""",
            )
            plan_path = write_transformation_execution_plan(app, run_id)
            transform_module._apply_openrewrite_apply_settings(plan_path, str(ai_hub), "java17")
            plan = load_migration_plan(plan_path, app)
            transformation = plan.units[1].transformations[0]

            self.assertEqual(transformation["apply_goal"], "runNoFork")
            self.assertEqual(transformation["apply_maven_args"], ["-Denforcer.skip=true"])

    def test_maven_enforcer_java8_range_patch_updates_to_java21_range(self) -> None:
        for legacy_range in ("[1.8,1.9)", "[8,9)", "1.8", "8"):
            with self.subTest(legacy_range=legacy_range), workspace_temp_dir() as tmp:
                app = tmp / "modernized-app"
                app.mkdir()
                (app / "pom.xml").write_text(
                    f"""<project>
  <build>
    <plugins>
      <plugin>
        <artifactId>maven-enforcer-plugin</artifactId>
        <configuration>
          <rules>
            <requireJavaVersion>
              <version>{legacy_range}</version>
            </requireJavaVersion>
          </rules>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
""",
                    encoding="utf-8",
                )

                patches = patch_maven_enforcer_java_version(app, unit_id="java-21")

                self.assertEqual(len(patches), 1)
                self.assertEqual(patches[0].old_range, legacy_range)
                self.assertEqual(patches[0].new_range, "[21,)")
                self.assertIn("<version>[21,)</version>", (app / "pom.xml").read_text(encoding="utf-8"))

    def test_maven_enforcer_java_range_patch_falls_back_to_nested_single_module_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            module = app / "common-utils"
            module.mkdir(parents=True)
            (module / "pom.xml").write_text(
                """<project>
  <build>
    <plugins>
      <plugin>
        <artifactId>maven-enforcer-plugin</artifactId>
        <configuration>
          <rules>
            <requireJavaVersion>
              <version>[1.8,1.9)</version>
            </requireJavaVersion>
          </rules>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
""",
                encoding="utf-8",
            )

            patches = patch_maven_enforcer_java_version(app, unit_id="java-21")

            self.assertEqual(len(patches), 1)
            self.assertEqual(patches[0].file, "common-utils/pom.xml")
            self.assertIn("<version>[21,)</version>", (module / "pom.xml").read_text(encoding="utf-8"))

    def test_pom_property_patch_updates_archunit_java21_version(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project>
  <properties>
    <archunit.version>0.23.1</archunit.version>
  </properties>
</project>
""",
                encoding="utf-8",
            )

            patches = patch_pom_property(
                app,
                unit_id="java-21",
                property_name="archunit.version",
                old_value="0.23.1",
                new_value="1.4.1",
            )

            self.assertEqual(len(patches), 1)
            self.assertEqual(patches[0].property, "archunit.version")
            self.assertEqual(patches[0].old_value, "0.23.1")
            self.assertEqual(patches[0].new_value, "1.4.1")
            self.assertIn(
                "<archunit.version>1.4.1</archunit.version>",
                (app / "pom.xml").read_text(encoding="utf-8"),
            )

    def test_pom_property_patch_falls_back_to_nested_single_module_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            module = app / "common-utils"
            module.mkdir(parents=True)
            (module / "pom.xml").write_text(
                """<project>
  <properties>
    <archunit.version>0.23.1</archunit.version>
  </properties>
</project>
""",
                encoding="utf-8",
            )

            patches = patch_pom_property(
                app,
                unit_id="java-21",
                property_name="archunit.version",
                old_value="0.23.1",
                new_value="1.4.1",
            )

            self.assertEqual(len(patches), 1)
            self.assertEqual(patches[0].file, "common-utils/pom.xml")
            self.assertIn(
                "<archunit.version>1.4.1</archunit.version>",
                (module / "pom.xml").read_text(encoding="utf-8"),
            )

    def test_boot4_source_patches_update_security_and_batch_config(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            security = app / "src/main/java/com/example/flightapp/config/SecurityConfig.java"
            batch = app / "src/main/java/com/example/flightapp/batch/config/BatchConfig.java"
            security.parent.mkdir(parents=True)
            batch.parent.mkdir(parents=True)
            security.write_text(
                "return new InMemoryUserDetailsManager(User.builder().username(\"viewer\").build());\n"
                "http.authorizeRequests(auth -> auth.requestMatchers(\"/actuator/health\").permitAll());\n",
                encoding="utf-8",
            )
            batch.write_text(
                "FlatFileItemReader<FlightCsvRow> reader = new FlatFileItemReader<FlightCsvRow>();\n"
                "reader.setResource(resolveInput(fileName));\n"
                "reader.setLinesToSkip(1);\n"
                "DefaultLineMapper<FlightCsvRow> lineMapper = new DefaultLineMapper<FlightCsvRow>();\n"
                "lineMapper.setLineTokenizer(tokenizer);\n"
                "lineMapper.setFieldSetMapper(fieldSetMapper);\n"
                "reader.setLineMapper(lineMapper);\n"
                "return reader;\n",
                encoding="utf-8",
            )

            security_patches = patch_security_config_authorize_http_requests(app, unit_id="java-21")
            batch_patches = patch_batch_config_flat_file_item_reader_constructor(app, unit_id="java-21")

            self.assertEqual(len(security_patches), 1)
            self.assertIn(".authorizeHttpRequests(", security.read_text(encoding="utf-8"))
            self.assertIn('.roles("ADMIN")', security.read_text(encoding="utf-8"))
            self.assertIn('.roles("AGENT")', security.read_text(encoding="utf-8"))
            self.assertIn('.roles("VIEWER")', security.read_text(encoding="utf-8"))
            self.assertEqual(len(batch_patches), 1)
            self.assertIn(
                "new FlatFileItemReader<FlightCsvRow>(lineMapper)",
                batch.read_text(encoding="utf-8"),
            )

    def test_boot3_policy_patches_allow_jakarta_after_migration(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            architecture = app / "shoppoc-app" / "src" / "test" / "java" / "com" / "shoppoc" / "architecture"
            architecture.mkdir(parents=True)
            forbidden = architecture / "ForbiddenSourcePatternsTest.java"
            quality = architecture / "QualityRulesTest.java"
            forbidden.write_text(
                """class ForbiddenSourcePatternsTest {
    void check(String line) {
        if (line.startsWith("import jakarta.")) {
            throw new IllegalStateException(" uses jakarta import");
        }
    }
}
""",
                encoding="utf-8",
            )
            quality.write_text(
                """class QualityRulesTest {
    String ruleName = "no_jakarta_imports";
    String packageName = "jakarta..";
}
""",
                encoding="utf-8",
            )

            forbidden_patches = patch_forbidden_source_patterns_allow_jakarta(app, unit_id="java-17")
            quality_patches = patch_quality_rules_allow_jakarta(app, unit_id="java-17")

            self.assertEqual(len(forbidden_patches), 1)
            self.assertIn('line.startsWith("import javax.")', forbidden.read_text(encoding="utf-8"))
            self.assertIn(" uses javax import", forbidden.read_text(encoding="utf-8"))
            self.assertEqual(len(quality_patches), 1)
            self.assertIn("no_javax_imports", quality.read_text(encoding="utf-8"))
            self.assertIn('"javax.."', quality.read_text(encoding="utf-8"))

    def test_boot4_java21_profile_adds_post_openrewrite_enforcer_patch(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            run_id = "run-1"
            _write_approved_run_artifacts(
                app,
                run_id,
                include_rewrite_plan=True,
                source_unit_id="java-21",
                source_unit_goal="Upgrade project runtime to Java 21.",
            )
            ai_hub = tmp / "ai-hub"
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
  apply_goal: runNoFork
  apply_maven_args:
    - -Denforcer.skip=true
  post_apply_patches:
    - type: maven_enforcer_java_version
      target_range: "[21,)"
    - type: pom_property
      property: archunit.version
      old_value: 0.23.1
      new_value: 1.4.1
""",
            )
            plan_path = write_transformation_execution_plan(app, run_id)

            transform_module._apply_openrewrite_apply_settings(plan_path, str(ai_hub), "java17")
            plan = load_migration_plan(plan_path, app)
            transformations = plan.units[1].transformations

            self.assertEqual(transformations[0]["type"], "openrewrite")
            self.assertEqual(transformations[1]["type"], "maven_enforcer_java_version")
            self.assertEqual(transformations[1]["target_range"], "[21,)")
            self.assertEqual(transformations[2]["type"], "pom_property")
            self.assertEqual(transformations[2]["property"], "archunit.version")

    def test_openrewrite_then_pom_property_patch_runs_before_java21_validation(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                "<project><properties><archunit.version>0.23.1</archunit.version></properties>"
                "<build><plugins><plugin><artifactId>maven-enforcer-plugin</artifactId>"
                "<configuration><rules><requireJavaVersion><version>[1.8,1.9)</version>"
                "</requireJavaVersion></rules></configuration></plugin></plugins></build></project>",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
policies:
  openrewrite:
    preview_allowed: true
    apply_allowed: true
    allowed_preview_goals:
      - dryRun
      - dryRunNoFork
      - discover
    forbidden_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
migration_units:
  - id: java-21
    title: Java 21
    transformations:
      - type: openrewrite
        apply_goal: runNoFork
        apply_maven_args:
          - -Denforcer.skip=true
        active_recipes:
          - org.openrewrite.java.migrate.UpgradeToJava21
      - type: maven_enforcer_java_version
        target_range: "[21,)"
      - type: pom_property
        property: archunit.version
        old_value: 0.23.1
        new_value: 1.4.1
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult(
                    command="mvn",
                    exit_code=0,
                    stdout=[],
                    stderr=[],
                    duration_seconds=0.01,
                ),
            ) as run_command:
                result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            command = run_command.call_args.args[0]
            transformations = ledger["units"]["java-21"]["transformations"]
            self.assertIn("-Denforcer.skip=true", command)
            self.assertEqual(transformations[0]["type"], "maven_enforcer_java_version")
            self.assertEqual(transformations[0]["status"], "applied")
            self.assertEqual(transformations[0]["patches"][0]["old_range"], "[1.8,1.9)")
            self.assertEqual(transformations[1]["type"], "pom_property")
            self.assertEqual(transformations[1]["status"], "applied")
            self.assertEqual(transformations[1]["patches"][0]["property"], "archunit.version")
            self.assertEqual(transformations[1]["patches"][0]["old_value"], "0.23.1")
            self.assertEqual(transformations[1]["patches"][0]["new_value"], "1.4.1")
            self.assertEqual(ledger["build_validation"]["unit_id"], "java-21")
            self.assertIn("<version>[21,)</version>", (app / "pom.xml").read_text(encoding="utf-8"))
            self.assertIn(
                "<archunit.version>1.4.1</archunit.version>",
                (app / "pom.xml").read_text(encoding="utf-8"),
            )
            run_command.assert_called_once()

    def test_maven_pom_patch_updates_sandbox_pom_and_records_ledger_operations(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project>
  <properties>
    <java.version>11</java.version>
    <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>javax.xml.bind</groupId>
      <artifactId>jaxb-api</artifactId>
      <version>2.3.1</version>
    </dependency>
    <dependency>
      <groupId>javax.xml.bind</groupId>
      <artifactId>jaxb-api</artifactId>
      <version>2.3.1</version>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: update_property
            name: java.version
            value: "17"
          - op: update_property
            name: spring-boot.version
            value: "3.5.14"
          - op: replace_dependency
            old_group_id: javax.xml.bind
            old_artifact_id: jaxb-api
            new_group_id: jakarta.xml.bind
            new_artifact_id: jakarta.xml.bind-api
            new_version: "4.0.2"
          - op: remove_duplicate_dependencies
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            pom_text = (app / "pom.xml").read_text(encoding="utf-8")

            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(transformation["transformation_type"], "maven_pom_patch")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(transformation["operation_count"], 4)
            self.assertEqual(len(transformation["operations_applied"]), 4)
            self.assertEqual(transformation["files_changed"], ["pom.xml"])
            self.assertIsNone(transformation["error_message"])
            self.assertIn("<java.version>17</java.version>", pom_text)
            self.assertIn("<spring-boot.version>3.5.14</spring-boot.version>", pom_text)
            self.assertIn("<groupId>jakarta.xml.bind</groupId>", pom_text)
            self.assertEqual(pom_text.count("<artifactId>jakarta.xml.bind-api</artifactId>"), 1)

    def test_maven_pom_patch_failure_blocks_unit_when_path_escapes_sandbox(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: java-17
    title: Java 17
    transformations:
      - type: maven_pom_patch
        pom_path: ../legacy/pom.xml
        operations:
          - op: update_property
            name: java.version
            value: "17"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with self.assertRaisesRegex(
                TransformationAgentError,
                "MAVEN_POM_PATCH_FAILED POM_PATH_OUTSIDE_SANDBOX",
            ):
                run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(app / ".migration" / "ledger.json")
            transformation = ledger["units"]["java-17"]["transformations"][0]
            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "java-17")
            self.assertEqual(transformation["status"], "failed")
            self.assertEqual(transformation["error_code"], "POM_PATH_OUTSIDE_SANDBOX")

    def test_maven_pom_patch_records_jackson_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <fasterxml-jackson.version>2.10.0</fasterxml-jackson.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.dataformat</groupId>
      <artifactId>jackson-dataformat-csv</artifactId>
      <version>${fasterxml-jackson.version}</version>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-2-7-stabilization
    title: Spring Boot 2.7 Stabilization
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_jackson_dependency_management
            version: "2.13.5"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-2-7-stabilization"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(transformation["status"], "applied")
            self.assertEqual(operation["op"], "align_jackson_dependency_management")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["target_version"], "2.13.5")
            self.assertIn("fasterxml-jackson.version", operation["updated_properties"])
            self.assertIn(
                "com.fasterxml.jackson.dataformat:jackson-dataformat-csv",
                operation["managed_artifacts"],
            )

    def test_maven_pom_patch_records_boot3_jackson_alignment_separately_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-databind</artifactId>
        <version>2.13.5</version>
      </dependency>
      <dependency>
        <groupId>com.fasterxml.jackson.core</groupId>
        <artifactId>jackson-core</artifactId>
        <version>2.13.5</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.13.5</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_jackson_dependency_management
            version: "2.21.2"
            version_overrides:
              com.fasterxml.jackson.core:jackson-annotations: "2.21"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(operation["op"], "align_jackson_dependency_management")
            self.assertEqual(operation["target_version"], "2.21.2")
            self.assertEqual(operation["detected_versions"], ["2.13.5"])
            self.assertEqual(
                operation["version_overrides"],
                {"com.fasterxml.jackson.core:jackson-annotations": "2.21"},
            )

    def test_maven_pom_patch_records_lombok_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.projectlombok</groupId>
      <artifactId>lombok</artifactId>
      <version>0.11.8</version>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: java-17
    title: Java 17
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_lombok_version
            version: "1.18.34"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["java-17"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_lombok_version")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.11.8"])
            self.assertEqual(operation["new_version"], "1.18.34")
            self.assertEqual(transformation["files_changed"], ["pom.xml"])

    def test_maven_pom_patch_records_jacoco_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <jacoco-maven-plugin.version>0.8.2</jacoco-maven-plugin.version>
  </properties>
  <build>
    <pluginManagement>
      <plugins>
        <plugin>
          <groupId>org.jacoco</groupId>
          <artifactId>jacoco-maven-plugin</artifactId>
          <version>${jacoco-maven-plugin.version}</version>
        </plugin>
      </plugins>
    </pluginManagement>
  </build>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: java-17
    title: Java 17
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_jacoco_version
            version: "0.8.12"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["java-17"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_jacoco_version")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.8.2"])
            self.assertEqual(operation["new_version"], "0.8.12")
            self.assertEqual(operation["updated_properties"], ["jacoco-maven-plugin.version"])
            self.assertEqual(transformation["files_changed"], ["pom.xml"])

    def test_maven_pom_patch_records_thymeleaf_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.thymeleaf</groupId>
      <artifactId>thymeleaf-spring5</artifactId>
      <version>3.0.11.RELEASE</version>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_thymeleaf_dependencies
            version: "3.1.3.RELEASE"
            prefer_bom_managed: true
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_thymeleaf_dependencies")
            self.assertEqual(operation["status"], "updated")
            self.assertTrue(operation["used_bom_management"])
            self.assertEqual(operation["replacements"][0]["old_artifact_id"], "thymeleaf-spring5")
            self.assertEqual(operation["replacements"][0]["new_artifact_id"], "thymeleaf-spring6")
            self.assertEqual(transformation["files_changed"], ["pom.xml"])

    def test_maven_pom_patch_records_validation_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-dependencies</artifactId>
        <version>3.5.14</version>
        <type>pom</type>
        <scope>import</scope>
      </dependency>
    </dependencies>
  </dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_validation_dependencies
            prefer_boot_starter: true
            detected_validation_usage:
              - jakarta.validation.Valid
              - ConstraintViolationException
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_validation_dependencies")
            self.assertEqual(operation["status"], "added")
            self.assertEqual(
                operation["dependency_added"],
                "org.springframework.boot:spring-boot-starter-validation",
            )
            self.assertIn("jakarta.validation.Valid", operation["detected_validation_usage"])
            self.assertEqual(transformation["files_changed"], ["pom.xml"])

    def test_maven_pom_patch_records_slf4j_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <org.slf4j.version>1.7.25</org.slf4j.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.slf4j</groupId>
      <artifactId>slf4j-api</artifactId>
      <version>${org.slf4j.version}</version>
    </dependency>
  </dependencies>
</project>""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_slf4j_logging
            slf4j_api_version: "2.0.17"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_slf4j_logging")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["1.7.25"])
            self.assertEqual(operation["new_versions"], ["2.0.17"])

    def test_maven_pom_patch_records_spring_security_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <spring-security.version>5.8.16</spring-security.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.security</groupId>
      <artifactId>spring-security-test</artifactId>
      <version>${spring-security.version}</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_spring_security_dependencies
            spring_security_version: "6.5.10"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_spring_security_dependencies")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["5.8.16"])
            self.assertEqual(operation["new_versions"], ["6.5.10"])

    def test_maven_pom_patch_records_jjwt_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <properties>
    <jjwt.version>0.10.5</jjwt.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>io.jsonwebtoken</groupId>
      <artifactId>jjwt-jackson</artifactId>
      <version>${jjwt.version}</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_jjwt_version
            version: "0.13.0"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_jjwt_version")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["old_versions"], ["0.10.5"])
            self.assertEqual(operation["new_version"], "0.13.0")
            self.assertEqual(operation["updated_properties"], ["jjwt.version"])
            self.assertEqual(operation["updated_dependencies"], ["io.jsonwebtoken:jjwt-jackson"])

    def test_maven_pom_patch_records_juneau_review_only_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-marshall</artifactId>
      <version>8.2.0</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_juneau_version
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(transformation["status"], "no_change")
            self.assertEqual(operation["op"], "align_juneau_version")
            self.assertEqual(operation["status"], "review_only")
            self.assertEqual(operation["action_taken"], "REVIEW_ONLY")
            self.assertTrue(operation["human_review_required"])

    def test_maven_pom_patch_records_juneau_update_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <dependencies>
    <dependency>
      <groupId>org.apache.juneau</groupId>
      <artifactId>juneau-marshall</artifactId>
      <version>8.2.0</version>
    </dependency>
  </dependencies>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_juneau_version
            version: "9.0.0"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_juneau_version")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["new_version"], "9.0.0")
            self.assertEqual(operation["updated_dependencies"], ["org.apache.juneau:juneau-marshall"])

    def test_maven_pom_patch_records_maven_compiler_parameters_alignment_operations_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-compiler-plugin</artifactId>
        <version>3.8.1</version>
        <configuration>
          <source>17</source>
          <target>17</target>
        </configuration>
      </plugin>
    </plugins>
  </build>
</project>
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: align_maven_compiler_parameters
            plugin_version: "3.14.1"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            operation = transformation["operations_applied"][0]
            self.assertEqual(transformation["type"], "maven_pom_patch")
            self.assertEqual(operation["op"], "align_maven_compiler_parameters")
            self.assertEqual(operation["status"], "updated")
            self.assertEqual(operation["new_version"], "3.14.1")
            self.assertEqual(operation["new_compiler_configuration_summary"]["parameters_enabled"], True)

    def test_spring6_exception_handler_override_alignment_records_signature_patch_in_ledger(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            source = app / "src" / "main" / "java" / "com" / "example"
            source.mkdir(parents=True)
            (source / "Advice.java").write_text(
                """package com.example;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

public class Advice extends ResponseEntityExceptionHandler {
    @Override
    protected ResponseEntity<Object> handleExceptionInternal(
            Exception ex, Object body, org.springframework.http.HttpHeaders headers, HttpStatus status, WebRequest request) {
        return super.handleExceptionInternal(ex, body, headers, status, request);
    }
}
""",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: spring-boot-3-5-14
    title: Spring Boot 3.5.14
    transformations:
      - type: spring6_exception_handler_override_alignment
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(result.ledger_file)
            transformation = ledger["units"]["spring-boot-3-5-14"]["transformations"][0]
            patch = transformation["patches"][0]
            self.assertEqual(transformation["type"], "spring6_exception_handler_override_alignment")
            self.assertEqual(transformation["status"], "applied")
            self.assertIn("HttpStatus status", patch["old_signature"])
            self.assertIn("HttpStatusCode status", patch["new_signature"])

    def test_required_enforcer_patch_missing_match_fails_before_validation(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text(
                "<project><build><plugins><plugin><artifactId>maven-enforcer-plugin</artifactId>"
                "<configuration><rules><requireJavaVersion><version>[17,)</version>"
                "</requireJavaVersion></rules></configuration></plugin></plugins></build></project>",
                encoding="utf-8",
            )
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
policies:
  openrewrite:
    preview_allowed: true
    apply_allowed: true
    allowed_preview_goals:
      - dryRun
      - dryRunNoFork
      - discover
    forbidden_apply_goals:
      - run
      - runNoFork
      - rewrite:run
      - rewrite:runNoFork
migration_units:
  - id: java-21
    title: Java 21
    transformations:
      - type: openrewrite
        apply_goal: runNoFork
        active_recipes:
          - org.openrewrite.java.migrate.UpgradeToJava21
      - type: maven_enforcer_java_version
        target_range: "[21,)"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult(
                    command="mvn",
                    exit_code=0,
                    stdout=[],
                    stderr=[],
                    duration_seconds=0.01,
                ),
            ):
                with self.assertRaisesRegex(
                    TransformationAgentError,
                    "REQUIRED_POM_PATCH_NOT_APPLIED maven_enforcer_java_version",
                ):
                    run_transformation_agent(app, plugin, plan, wait_for_continue=False)

            ledger = load_ledger(app / ".migration" / "ledger.json")
            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "java-21")
            self.assertEqual(
                ledger["units"]["java-21"]["blocking_reason"],
                "REQUIRED_POM_PATCH_NOT_APPLIED maven_enforcer_java_version",
            )
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.NOT_REQUIRED)

    def test_baseline_unit_leaves_pom_untouched_before_baseline_validation(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            original_pom = (
                "<project><build><plugins><plugin><artifactId>maven-enforcer-plugin</artifactId>"
                "<configuration><rules><requireJavaVersion><version>[1.8,1.9)</version>"
                "</requireJavaVersion></rules></configuration></plugin></plugins></build></project>"
            )
            (app / "pom.xml").write_text(original_pom, encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(
                """
schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: baseline
    title: Baseline
    transformations:
      - type: custom_code_change
        description: baseline validation only
    checks: []
  - id: java-21
    title: Java 21
    transformations:
      - type: maven_enforcer_java_version
        target_range: "[21,)"
    checks: []
""",
                encoding="utf-8",
            )
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)

            self.assertEqual(ledger["build_validation"]["unit_id"], "baseline")
            self.assertEqual((app / "pom.xml").read_text(encoding="utf-8"), original_pom)

    def test_java17_profile_adds_boot3_policy_patches_but_not_enforcer_patch(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)
            ai_hub = tmp / "ai-hub"
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
  post_apply_patches:
    - type: forbidden_source_patterns_allow_jakarta
    - type: quality_rules_allow_jakarta
""",
            )
            plan_path = write_transformation_execution_plan(app, run_id)

            transform_module._apply_openrewrite_apply_settings(plan_path, str(ai_hub), "java17")
            payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

            self.assertNotIn(
                "maven_enforcer_java_version",
                json.dumps(payload),
            )
            self.assertIn(
                "forbidden_source_patterns_allow_jakarta",
                json.dumps(payload),
            )
            self.assertIn(
                "quality_rules_allow_jakarta",
                json.dumps(payload),
            )

    def test_build_ledger_pass_marks_unit_completed(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")

            mark_build_passed(ledger_file, result_kind="success", message="Application started")
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))

            self.assertEqual(ledger["status"], LedgerStatus.BUILD_VALIDATED)
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PASSED)
            self.assertEqual(ledger["completed_units"], ["unit-001"])

    def test_build_ledger_failure_blocks_unit(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")

            mark_build_failed(
                ledger_file,
                result_kind="compilation_error",
                message="Compile failed",
                error_contract_path=tmp / "build-error.json",
            )
            ledger = load_ledger(ledger_file)

            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "unit-001")
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.FAILED)

    def test_prepare_sandbox_workspace_copies_legacy_with_exclusions_and_checkpoint(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (legacy / ".git").mkdir()
            (legacy / ".git" / "config").write_text("source git", encoding="utf-8")
            (legacy / ".migration").mkdir()
            (legacy / ".migration" / "ledger.json").write_text("{}", encoding="utf-8")
            (legacy / "target").mkdir()
            (legacy / "target" / "classes.txt").write_text("compiled", encoding="utf-8")
            (legacy / "build").mkdir()
            (legacy / "build" / "output.txt").write_text("built", encoding="utf-8")
            (legacy / "node_modules").mkdir()
            (legacy / "node_modules" / "package.txt").write_text("dependency", encoding="utf-8")
            (legacy / "__pycache__").mkdir()
            (legacy / "__pycache__" / "module.pyc").write_text("cache", encoding="utf-8")
            (modernized / "marker.txt").write_text("do not change", encoding="utf-8")

            sandbox = prepare_sandbox_workspace(
                legacy_app_path=legacy,
                modernized_app_path=modernized,
                run_dir=run_dir,
            )

            self.assertEqual(sandbox.path, run_dir / "workspaces" / "sandbox")
            self.assertEqual((sandbox.path / "pom.xml").read_text(encoding="utf-8"), "<project />")
            self.assertFalse((sandbox.path / ".migration").exists())
            self.assertFalse((sandbox.path / "target").exists())
            self.assertFalse((sandbox.path / "build").exists())
            self.assertFalse((sandbox.path / "node_modules").exists())
            self.assertFalse((sandbox.path / "__pycache__").exists())
            self.assertEqual((legacy / "pom.xml").read_text(encoding="utf-8"), "<project />")
            self.assertEqual((modernized / "marker.txt").read_text(encoding="utf-8"), "do not change")
            self.assertIn(sandbox.checkpoint_type, {"git", "manifest"})
            if sandbox.checkpoint_type == "git":
                self.assertTrue((sandbox.path / ".git").is_dir())
                self.assertRegex(sandbox.checkpoint_ref, r"^[0-9a-f]{40}$")
            else:
                self.assertTrue(Path(sandbox.checkpoint_ref).is_file())

    def test_prepare_sandbox_workspace_writes_manifest_without_git(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")

            with mock.patch("migration_factory.agents.transformation_agent.workspace.shutil.which", return_value=None):
                sandbox = prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

            manifest_path = sandbox.path / "baseline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(sandbox.checkpoint_type, "manifest")
            self.assertEqual(Path(sandbox.checkpoint_ref), manifest_path)
            self.assertEqual([entry["path"] for entry in manifest["files"]], ["pom.xml"])

    def test_prepare_sandbox_workspace_rejects_sandbox_outside_run_dir(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            outside = tmp / "outside"
            legacy.mkdir()
            modernized.mkdir()
            run_dir.mkdir(parents=True)
            outside.mkdir()
            _symlink_or_skip(self, run_dir / "workspaces", outside, target_is_directory=True)

            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must stay inside run_dir"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

    def test_prepare_sandbox_workspace_rejects_sandbox_equal_to_source_or_target(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            legacy = run_dir / "workspaces" / "sandbox"
            modernized = tmp / "modernized-app"
            legacy.mkdir(parents=True)
            modernized.mkdir()

            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must not be the legacy_app_path"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

            modernized = legacy
            legacy = tmp / "legacy-app"
            legacy.mkdir()
            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must not be the modernized_app_path"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

    def test_prepare_sandbox_workspace_rejects_symlink_escape(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            outside = tmp / "outside.txt"
            legacy.mkdir()
            modernized.mkdir()
            outside.write_text("outside", encoding="utf-8")
            _symlink_or_skip(self, legacy / "escape.txt", outside)

            with self.assertRaisesRegex(TransformationWorkspaceError, "Symlink escapes"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=modernized / ".migration" / "runs" / "run-1",
                )

    def test_prepare_sandbox_workspace_wraps_cleanup_permission_error(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            sandbox = run_dir / "workspaces" / "sandbox"
            legacy.mkdir()
            modernized.mkdir()
            sandbox.mkdir(parents=True)
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (sandbox / "locked.txt").write_text("locked", encoding="utf-8")

            with mock.patch(
                "migration_factory.agents.transformation_agent.workspace.shutil.rmtree",
                side_effect=PermissionError("[WinError 5] Access is denied"),
            ):
                with self.assertRaisesRegex(TransformationWorkspaceError, "SANDBOX_CLEAN_FAILED") as raised:
                    prepare_sandbox_workspace(
                        legacy_app_path=legacy,
                        modernized_app_path=modernized,
                        run_dir=run_dir,
                    )

            message = str(raised.exception)
            self.assertIn(str(sandbox), message)
            self.assertIn("stop Java process / close terminals/editors", message)
            self.assertIn("delete sandbox manually", message)
            self.assertIn("use a new run id", message)

    def test_sandbox_cleanup_refuses_target_outside_run_dir(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            outside = tmp / "outside-sandbox"
            run_dir.mkdir()
            outside.mkdir()

            with mock.patch("migration_factory.agents.transformation_agent.workspace.shutil.rmtree") as rmtree:
                with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must stay inside run_dir"):
                    workspace_module._remove_existing_sandbox(outside, run_dir)

            rmtree.assert_not_called()

    def test_transform_v1_after_approval_runs_transformer_against_sandbox(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("OPENREWRITE_FULL_LOG should be quiet by default")
                unit_id = str(kwargs.get("start_unit") or "baseline")
                _write_awaiting_build_ledger(ledger_file, unit_id)
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ) as run_agent:
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=lambda **kwargs: (
                        print("MAVEN_FULL_LOG should be quiet by default")
                        or BuildRunResult(
                            succeeded=True,
                            result_kind="success",
                            message="Application started successfully",
                        )
                    ),
                ) as run_build:
                    with mock.patch(
                        "migration_factory.transform_v1_after_approval.run_test_agent",
                        return_value=_passed_test_result(run_dir),
                    ) as run_test:
                        with redirect_stdout(stdout):
                            result = transform_v1_after_approval_main(
                                [
                                    "--run-dir",
                                    str(run_dir),
                                    "--legacy-app",
                                    str(legacy),
                                    "--modernized-app",
                                    str(modernized),
                                    "--ai-hub",
                                    str(ai_hub),
                                    "--profile",
                                    "java17",
                                    "--approved-by",
                                    "human",
                                ]
                            )

            sandbox_path = run_dir / "workspaces" / "sandbox"
            plan_path = run_dir / "transformation" / "transformation_execution_plan.yaml"
            plugin_path = run_dir / "transformation" / "openrewrite-plugin.xml"
            log_file = run_dir / "logs" / "phase2_transform.log"
            plan_payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(result, 0)
            self.assertIn("APPROVED_FOR_TRANSFORM", stdout.getvalue())
            self.assertIn("SANDBOX_PREPARED", stdout.getvalue())
            self.assertIn("TRANSFORM_RUNNING", stdout.getvalue())
            self.assertIn("BUILD_RUNNING_IN_SANDBOX", stdout.getvalue())
            self.assertIn("BUILD_PASSED_IN_SANDBOX", stdout.getvalue())
            self.assertEqual(stdout.getvalue().count("BUILD_PASSED_IN_SANDBOX"), 2)
            self.assertIn("TRANSFORM_APPLIED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("OPENREWRITE_FULL_LOG", stdout.getvalue())
            self.assertNotIn("MAVEN_FULL_LOG", stdout.getvalue())
            self.assertIn("OPENREWRITE_FULL_LOG", log_file.read_text(encoding="utf-8"))
            self.assertIn("MAVEN_FULL_LOG", log_file.read_text(encoding="utf-8"))
            first_build_passed = stdout.getvalue().index("BUILD_PASSED_IN_SANDBOX")
            second_transform_running = stdout.getvalue().index("TRANSFORM_RUNNING", stdout.getvalue().index("TRANSFORM_RUNNING") + 1)
            self.assertLess(first_build_passed, second_transform_running)
            self.assertEqual(stdout.getvalue().count("TRANSFORM_RUNNING"), 2)
            self.assertGreater(
                stdout.getvalue().index("TRANSFORM_APPLIED_IN_SANDBOX"),
                stdout.getvalue().rindex("BUILD_PASSED_IN_SANDBOX"),
            )
            self.assertEqual(plan_payload["workspaces"]["target"]["path"], str(sandbox_path.resolve()))
            self.assertTrue((sandbox_path / "pom.xml").is_file())
            self.assertIn("<artifactId>rewrite-maven-plugin</artifactId>", plugin_path.read_text(encoding="utf-8"))
            self.assertNotIn("<version>RELEASE</version>", plugin_path.read_text(encoding="utf-8"))
            run_agent.assert_has_calls(
                [
                    mock.call(
                        sandbox_path,
                        plugin_path,
                        plan_path,
                        start_unit=None,
                        dry_run=False,
                        stream_output=True,
                        wait_for_continue=False,
                    ),
                    mock.call(
                        sandbox_path,
                        plugin_path,
                        plan_path,
                        start_unit="java-17",
                        dry_run=False,
                        stream_output=True,
                        wait_for_continue=False,
                    ),
                ]
            )
            self.assertEqual(run_build.call_count, 2)
            run_test.assert_called_once()
            self.assertNotIn("enforcer.skip", str(run_test.call_args.kwargs.get("command")))
            self.assertNotIn("apply_goal", plan_payload["migration_units"][1]["transformations"][0])
            self.assertNotIn("apply_maven_args", plan_payload["migration_units"][1]["transformations"][0])
            run_build.assert_has_calls(
                [
                    mock.call(
                        project_path=sandbox_path,
                        ledger_file=ledger_file,
                        output_dir=run_dir / "build",
                        stream_output=True,
                        validation_unit_id="baseline",
                        source_changing_unit=False,
                        validation_command="mvn clean test",
                    ),
                    mock.call(
                        project_path=sandbox_path,
                        ledger_file=ledger_file,
                        output_dir=run_dir / "build",
                        stream_output=True,
                        validation_unit_id="java-17",
                        source_changing_unit=True,
                        validation_command="mvn clean test",
                    ),
                ]
            )
            for call_args in run_build.call_args_list:
                self.assertNotIn("enforcer.skip", str(call_args.kwargs.get("validation_command")))

    def test_transform_v1_after_approval_defaults_openrewrite_apply_goal_from_sandbox_policy(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            (ai_hub / "policies").mkdir(parents=True, exist_ok=True)
            (ai_hub / "policies" / "transformation.yaml").write_text(
                """
id: transformation
openrewrite:
  preview_allowed: true
  apply_allowed: false
  sandbox_apply_allowed: true
  allowed_preview_goals:
    - dryRun
    - dryRunNoFork
    - discover
  allowed_sandbox_apply_goals:
    - run
    - runNoFork
    - rewrite:run
    - rewrite:runNoFork
  forbidden_apply_goals:
    - run
    - runNoFork
    - rewrite:run
    - rewrite:runNoFork
""".strip()
                + "\n",
                encoding="utf-8",
            )
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                unit_id = str(kwargs.get("start_unit") or "baseline")
                _write_awaiting_build_ledger(ledger_file, unit_id)
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=lambda **kwargs: BuildRunResult(
                        succeeded=True,
                        result_kind="success",
                        message="Application started successfully",
                    ),
                ):
                    with mock.patch(
                        "migration_factory.transform_v1_after_approval.run_test_agent",
                        return_value=_passed_test_result(run_dir),
                    ):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 0)
            plan_payload = yaml.safe_load(
                (run_dir / "transformation" / "transformation_execution_plan.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(plan_payload["migration_units"][1]["transformations"][0]["apply_goal"], "runNoFork")

    def test_transform_v1_java21_validation_sees_patched_sandbox_pom(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text(
                "<project><build><plugins><plugin><artifactId>maven-enforcer-plugin</artifactId>"
                "<configuration><rules><requireJavaVersion><version>[1.8,1.9)</version>"
                "</requireJavaVersion></rules></configuration></plugin></plugins></build></project>",
                encoding="utf-8",
            )
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
  apply_goal: runNoFork
  apply_maven_args:
    - -Denforcer.skip=true
  post_openrewrite_patches:
    - type: maven_enforcer_java_version
      target_range: "[21,)"
""",
            )
            _write_approved_run_artifacts(
                modernized,
                run_id,
                include_rewrite_plan=True,
                rewrite_plugin_plan_payload={
                    "plugin": "org.openrewrite.maven:rewrite-maven-plugin:6.39.0",
                    "recipe_artifacts": ["org.openrewrite.recipe:rewrite-migrate-java:3.20.0"],
                    "active_recipes": ["org.openrewrite.java.migrate.UpgradeToJava17"],
                    "preview_goals": ["dryRun", "dryRunNoFork", "discover"],
                    "forbidden_apply_goals": ["run", "runNoFork", "rewrite:run", "rewrite:runNoFork"],
                    "apply_allowed": True,
                },
                source_unit_id="java-21",
                source_unit_goal="Upgrade project runtime to Java 21.",
            )
            policy_path = tmp / "governed-ai-hub" / "policies" / "transformation.yaml"
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_text(
                """
id: transformation
agent: transformer
openrewrite:
  preview_allowed: true
  apply_allowed: true
  allowed_preview_goals:
    - dryRun
    - dryRunNoFork
    - discover
  forbidden_apply_goals:
    - run
    - runNoFork
    - rewrite:run
    - rewrite:runNoFork
""".strip()
                + "\n",
                encoding="utf-8",
            )

            seen_java21_validation = False

            def build_side_effect(**kwargs: object) -> BuildRunResult:
                nonlocal seen_java21_validation
                ledger_file = Path(str(kwargs["ledger_file"]))
                unit_id = str(kwargs["validation_unit_id"])
                if unit_id == "java-21":
                    pom_text = (run_dir / "workspaces" / "sandbox" / "pom.xml").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("<version>[21,)</version>", pom_text)
                    seen_java21_validation = True
                mark_build_passed(ledger_file, result_kind="success", message="ok")
                return BuildRunResult(succeeded=True, result_kind="success", message="ok")

            with mock.patch(
                "migration_factory.agents.transformation_agent.agent.run_command",
                return_value=CommandResult(
                    command="mvn",
                    exit_code=0,
                    stdout=[],
                    stderr=[],
                    duration_seconds=0.01,
                ),
            ):
                with mock.patch.object(
                    execution_plan_module,
                    "_canonical_transformation_policy_path",
                    return_value=policy_path,
                ):
                    with mock.patch(
                        "migration_factory.transform_v1_after_approval.run_build_agent",
                        side_effect=build_side_effect,
                    ):
                        with mock.patch(
                            "migration_factory.transform_v1_after_approval.run_test_agent",
                            return_value=_passed_test_result(run_dir),
                        ):
                            result = transform_v1_after_approval_main(
                                [
                                    "--run-dir",
                                    str(run_dir),
                                    "--legacy-app",
                                    str(legacy),
                                    "--modernized-app",
                                    str(modernized),
                                    "--ai-hub",
                                    str(ai_hub),
                                    "--profile",
                                    "java17",
                                    "--approved-by",
                                    "human",
                                ]
                            )

            ledger = load_ledger(run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json")
            self.assertEqual(result, 0)
            self.assertTrue(seen_java21_validation)
            self.assertEqual(
                ledger["units"]["java-21"]["transformations"][0]["patches"][0]["old_range"],
                "[1.8,1.9)",
            )

    def test_generated_openrewrite_plugin_xml_replaces_release_plugin_version(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            ai_hub = tmp / "ai-hub"
            analysis_dir = run_dir / "analysis"
            analysis_dir.mkdir(parents=True)
            _write_ai_hub_profile(ai_hub)
            (analysis_dir / "rewrite_plugin_plan.json").write_text(
                json.dumps(
                    {
                        "plugin": "org.openrewrite.maven:rewrite-maven-plugin:RELEASE",
                        "recipe_artifacts": ["org.openrewrite.recipe:rewrite-migrate-java:RELEASE"],
                    }
                ),
                encoding="utf-8",
            )

            plugin_path = transform_module._write_openrewrite_plugin_xml(run_dir, str(ai_hub), "java17")
            plugin_xml = plugin_path.read_text(encoding="utf-8")

            self.assertIn("<artifactId>rewrite-maven-plugin</artifactId>", plugin_xml)
            self.assertIn("<version>6.39.0</version>", plugin_xml)
            self.assertNotIn("<artifactId>rewrite-maven-plugin</artifactId>\n  <version>RELEASE</version>", plugin_xml)

    def test_profile_jdk_env_names_are_loaded_from_ai_hub_profile(self) -> None:
        with workspace_temp_dir() as tmp:
            ai_hub = tmp / "ai-hub"
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
source_jdk_home_env: JAVA8_HOME
target_jdk_home_env: JAVA21_HOME
""",
            )

            env = transform_module._profile_jdk_env(str(ai_hub), "java17")

            self.assertEqual(
                env,
                {
                    "source_jdk_home_env": "JAVA8_HOME",
                    "target_jdk_home_env": "JAVA21_HOME",
                },
            )

    def test_transform_v1_after_approval_validates_spring_boot_source_unit_from_reactor_root(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            _write_multi_module_project(legacy)
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(
                modernized,
                run_id,
                include_rewrite_plan=True,
                source_unit_id="spring-boot-3-5-14",
                source_unit_goal="Upgrade Spring Boot runtime.",
            )
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                _write_awaiting_build_ledger(ledger_file, "spring-boot-3-5-14")
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            process_result = ProcessRunResult(
                classification=BuildClassification(
                    BuildResultKind.SUCCESS,
                    "Build completed successfully",
                ),
                exit_code=0,
            )

            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.agents.build_agent.agent.run_until_exit",
                    return_value=process_result,
                ) as run_process:
                    with mock.patch(
                        "migration_factory.agents.build_agent.agent.run_until_build_result"
                    ) as run_startup:
                        with mock.patch(
                            "migration_factory.transform_v1_after_approval.run_test_agent",
                            return_value=_passed_test_result(run_dir),
                        ):
                            result = transform_v1_after_approval_main(
                                [
                                    "--run-dir",
                                    str(run_dir),
                                    "--legacy-app",
                                    str(legacy),
                                    "--modernized-app",
                                    str(modernized),
                                    "--ai-hub",
                                    str(ai_hub),
                                    "--profile",
                                    "java17",
                                    "--approved-by",
                                    "human",
                                ]
                            )

            sandbox_path = run_dir / "workspaces" / "sandbox"
            self.assertEqual(result, 0)
            run_startup.assert_not_called()
            run_process.assert_called_once()
            command = run_process.call_args.kwargs["command"]
            self.assertEqual(run_process.call_args.kwargs["cwd"], sandbox_path)
            self.assertEqual(run_process.call_args.kwargs["timeout_seconds"], 300)
            self.assertEqual(command[1:], ["clean", "test"])
            self.assertNotIn("spring-boot:run", command)
            self.assertNotIn("-f", command)
            self.assertNotIn("shoppoc-app/pom.xml", command)
            ledger = load_ledger(ledger_file)
            self.assertEqual(ledger["build_validation"]["unit_id"], "spring-boot-3-5-14")
            self.assertEqual(ledger["build_validation"]["command"], command)
            self.assertEqual(ledger["build_validation"]["cwd"], str(sandbox_path))

    def test_transform_v1_after_approval_passes_unit_level_java_home_env_to_build_agent(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(
                ai_hub,
                extra_profile_yaml="""
source_jdk_home_env: JAVA_HOME_11
target_jdk_home_env: JAVA_HOME_17
""",
            )
            _write_approved_run_artifacts(
                modernized,
                run_id,
                include_rewrite_plan=False,
                planning_units_yaml="""
schema_version: "1.0.0"
run_id: "run-1"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Baseline."
    tools: ["maven", "junit"]
    validation: ["mvn", "clean", "test"]
    writes_source: false
    required: "yes"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_artifacts: ["target/surefire-reports"]
  - id: "spring-boot-2-7-stabilization"
    goal: "Stabilize."
    tools: ["maven"]
    validation: ["mvn", "clean", "test"]
    writes_source: true
    required: "yes"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
    expected_artifacts: ["target/classes"]
""",
            )
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                start_unit = kwargs.get("start_unit")
                if start_unit is None:
                    _write_awaiting_build_ledger(ledger_file, "baseline")
                else:
                    _write_awaiting_build_ledger(ledger_file, "spring-boot-2-7-stabilization")
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            build_calls: list[dict[str, object]] = []

            def build_side_effect(**kwargs: object) -> BuildRunResult:
                build_calls.append(dict(kwargs))
                unit_id = str(kwargs["validation_unit_id"])
                mark_build_passed(Path(str(kwargs["ledger_file"])), result_kind="success", message="ok")
                if unit_id == "spring-boot-2-7-stabilization":
                    return BuildRunResult(succeeded=True, result_kind="success", message="ok")
                return BuildRunResult(succeeded=True, result_kind="success", message="ok")

            completed_once = {"done": False}

            def run_agent_completed(*args: object, **kwargs: object) -> TransformationRunResult:
                start_unit = kwargs.get("start_unit")
                if start_unit is None:
                    _write_awaiting_build_ledger(ledger_file, "baseline")
                    return TransformationRunResult(
                        ledger_file=ledger_file,
                        status=LedgerStatus.AWAITING_BUILD_AGENT,
                        completed_units=[],
                    )
                if not completed_once["done"]:
                    completed_once["done"] = True
                    _write_awaiting_build_ledger(ledger_file, "spring-boot-2-7-stabilization")
                    return TransformationRunResult(
                        ledger_file=ledger_file,
                        status=LedgerStatus.AWAITING_BUILD_AGENT,
                        completed_units=["baseline"],
                    )
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.COMPLETED,
                    completed_units=["baseline", "spring-boot-2-7-stabilization"],
                )

            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_completed,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=build_side_effect,
                ):
                    with mock.patch(
                        "migration_factory.transform_v1_after_approval.run_test_agent",
                        return_value=_passed_test_result(run_dir),
                    ):
                        result = transform_v1_after_approval_main(
                                [
                                    "--run-dir",
                                    str(run_dir),
                                    "--legacy-app",
                                    str(legacy),
                                    "--modernized-app",
                                    str(modernized),
                                    "--ai-hub",
                                    str(ai_hub),
                                    "--profile",
                                    "java17",
                                    "--approved-by",
                                    "human",
                                ]
                            )

            self.assertEqual(result, 0)
            self.assertEqual([call["validation_unit_id"] for call in build_calls], ["baseline", "spring-boot-2-7-stabilization"])
            self.assertTrue(all(call["java_home_env"] == "JAVA_HOME_11" for call in build_calls))

    def test_transform_v1_after_approval_reports_build_failure(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            error_contract = run_dir / "build" / "build-error.json"
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                if kwargs.get("start_unit") is None:
                    _write_awaiting_build_ledger(ledger_file, "baseline")
                    return TransformationRunResult(
                        ledger_file=ledger_file,
                        status=LedgerStatus.AWAITING_BUILD_AGENT,
                        completed_units=[],
                    )
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.COMPLETED,
                    completed_units=["baseline"],
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=lambda **kwargs: (
                        print("[ERROR] COMPILATION ERROR full Maven output")
                        or BuildRunResult(
                            succeeded=False,
                            result_kind="compilation_error",
                            message="Compilation failed",
                            error_contract_path=error_contract,
                        )
                    ),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertNotIn("TRANSFORM_APPLIED_IN_SANDBOX", stdout.getvalue())
            self.assertIn("BUILD_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertEqual(stdout.getvalue().count("TRANSFORM_RUNNING"), 1)
            self.assertNotIn("[ERROR] COMPILATION ERROR", stdout.getvalue())
            self.assertIn("Build result kind: compilation_error", stderr.getvalue())
            self.assertIn("Build message: Compilation failed", stderr.getvalue())
            self.assertIn(f"Build error contract: {error_contract}", stderr.getvalue())
            self.assertIn("log_file:", stderr.getvalue())
            self.assertIn("[ERROR] COMPILATION ERROR full Maven output", stderr.getvalue())
            self.assertTrue((run_dir / "performance" / "timing_report.json").is_file())

    def test_transform_v1_after_approval_blocks_candidate_when_test_reports_missing(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                if kwargs.get("start_unit") is None:
                    _write_awaiting_build_ledger(ledger_file, "baseline")
                    return TransformationRunResult(
                        ledger_file=ledger_file,
                        status=LedgerStatus.AWAITING_BUILD_AGENT,
                        completed_units=[],
                    )
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.COMPLETED,
                    completed_units=["baseline"],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    return_value=BuildRunResult(
                        succeeded=True,
                        result_kind="success",
                        message="ok",
                    ),
                ):
                    with redirect_stdout(stdout):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertIn("TEST_ERROR", stdout.getvalue())
            self.assertNotIn("Sandbox migration candidate ready.", stdout.getvalue())

    def test_transform_v1_after_approval_reports_transform_failure(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            stdout = io.StringIO()
            stderr = io.StringIO()
            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("OpenRewrite failure output")
                raise TransformationAgentError("boom")

            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_build_agent") as run_build:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertIn("TRANSFORM_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("OpenRewrite failure output", stdout.getvalue())
            self.assertIn("ERROR: boom", stderr.getvalue())
            self.assertIn("log_file:", stderr.getvalue())
            self.assertIn("OpenRewrite failure output", stderr.getvalue())
            run_build.assert_not_called()

    def test_transform_v1_after_approval_writes_custom_log_file(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            custom_log = tmp / "custom" / "phase2.log"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("CUSTOM_LOG_OPENREWRITE_OUTPUT")
                return TransformationRunResult(
                    ledger_file=run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json",
                    status=LedgerStatus.COMPLETED,
                    completed_units=["java-17"],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_build_agent") as run_build:
                    with mock.patch(
                        "migration_factory.transform_v1_after_approval.run_test_agent",
                        return_value=_passed_test_result(run_dir),
                    ):
                        with redirect_stdout(stdout):
                            result = transform_v1_after_approval_main(
                                [
                                    "--run-dir",
                                    str(run_dir),
                                    "--legacy-app",
                                    str(legacy),
                                    "--modernized-app",
                                    str(modernized),
                                    "--ai-hub",
                                    str(ai_hub),
                                    "--profile",
                                    "java17",
                                    "--approved-by",
                                    "human",
                                    "--log-file",
                                    str(custom_log),
                                ]
                            )

            self.assertEqual(result, 0)
            self.assertNotIn("CUSTOM_LOG_OPENREWRITE_OUTPUT", stdout.getvalue())
            self.assertIn("CUSTOM_LOG_OPENREWRITE_OUTPUT", custom_log.read_text(encoding="utf-8"))
            self.assertFalse((run_dir / "logs" / "phase2_transform.log").exists())
            run_build.assert_not_called()

    def test_transform_v1_after_approval_verbose_streams_subprocess_output(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("VERBOSE_OPENREWRITE_OUTPUT")
                return TransformationRunResult(
                    ledger_file=run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json",
                    status=LedgerStatus.COMPLETED,
                    completed_units=["java-17"],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_test_agent",
                    return_value=_passed_test_result(run_dir),
                ):
                    with redirect_stdout(stdout):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                                "--verbose",
                            ]
                        )

            log_file = run_dir / "logs" / "phase2_transform.log"
            self.assertEqual(result, 0)
            self.assertIn("VERBOSE_OPENREWRITE_OUTPUT", stdout.getvalue())
            self.assertIn("Transformer status: completed", stdout.getvalue())
            self.assertIn("VERBOSE_OPENREWRITE_OUTPUT", log_file.read_text(encoding="utf-8"))

    def test_transform_v1_after_approval_reports_sandbox_cleanup_failure_without_traceback(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            sandbox = run_dir / "workspaces" / "sandbox"
            legacy.mkdir()
            modernized.mkdir()
            sandbox.mkdir(parents=True)
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (sandbox / "locked.txt").write_text("locked", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "migration_factory.agents.transformation_agent.workspace.shutil.rmtree",
                side_effect=PermissionError("[WinError 5] Access is denied"),
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_transformation_agent") as run_agent:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertIn("TRANSFORM_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertIn("SANDBOX_CLEAN_FAILED", stderr.getvalue())
            self.assertIn(str(sandbox), stderr.getvalue())
            self.assertIn("stop Java process / close terminals/editors", stderr.getvalue())
            self.assertIn("delete sandbox manually", stderr.getvalue())
            self.assertIn("use a new run id", stderr.getvalue())
            run_agent.assert_not_called()


def _run_dir(app: Path, run_id: str) -> Path:
    return app / ".migration" / "runs" / run_id


def _symlink_or_skip(
    test_case: unittest.TestCase,
    link_path: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link_path.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            test_case.skipTest("Windows symlink privilege is not available")
        raise


def _write_awaiting_build_ledger(ledger_file: Path, unit_id: str) -> None:
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    ledger_file.write_text(
        json.dumps(
            {
                "status": LedgerStatus.AWAITING_BUILD_AGENT,
                "current_unit": unit_id,
                "blocked_unit": None,
                "completed_units": [],
                "build_validation": {
                    "required": True,
                    "status": BuildValidationStatus.PENDING,
                    "unit_id": unit_id,
                },
            }
        ),
        encoding="utf-8",
    )


def _passed_test_result(run_dir: Path) -> _TestAgentResult:
    test_dir = run_dir / "test" / "post_transform"
    test_dir.mkdir(parents=True, exist_ok=True)
    report = test_dir / "test_report.json"
    summary = test_dir / "test_summary.md"
    log = test_dir / "test_agent.log"
    report.write_text("{}\n", encoding="utf-8")
    summary.write_text("# summary\n", encoding="utf-8")
    log.write_text("ok\n", encoding="utf-8")
    return _TestAgentResult(
        test_status="TEST_PASSED",
        severity="INFO",
        message="Surefire reports parsed successfully.",
        totals={"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
        report_path=report,
        summary_path=summary,
        log_path=log,
        report_paths=[str(report)],
        parse_duration_seconds=0.01,
        warnings=[],
    )


def _write_multi_module_project(project: Path) -> None:
    (project / "pom.xml").write_text(
        """<project>
  <modelVersion>4.0.0</modelVersion>
  <packaging>pom</packaging>
  <modules>
    <module>shoppoc-user</module>
    <module>shoppoc-app</module>
  </modules>
</project>""",
        encoding="utf-8",
    )
    (project / "shoppoc-user").mkdir()
    (project / "shoppoc-user" / "pom.xml").write_text("<project />", encoding="utf-8")
    app = project / "shoppoc-app"
    app.mkdir()
    (app / "pom.xml").write_text("<project />", encoding="utf-8")
    source = app / "src" / "main" / "java" / "com" / "shoppoc" / "app"
    source.mkdir(parents=True)
    (source / "ShoppocApplication.java").write_text(
        """package com.shoppoc.app;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class ShoppocApplication {
    public static void main(String[] args) {
        SpringApplication.run(ShoppocApplication.class, args);
    }
}
""",
        encoding="utf-8",
    )


def _write_approved_run_artifacts(
    app: Path,
    run_id: str,
    *,
    include_rewrite_plan: bool = False,
    rewrite_plugin_plan_payload: dict[str, object] | None = None,
    source_unit_id: str = "java-17",
    source_unit_goal: str = "Upgrade project runtime to Java 17.",
    planning_units_yaml: str | None = None,
    dependency_graph_payload: dict[str, object] | None = None,
    tooling_versions_payload: dict[str, str] | None = None,
    framework_versions_payload: dict[str, str] | None = None,
    analysis_report_payload: dict[str, object] | None = None,
) -> None:
    _write_run_artifacts(
        app,
        run_id,
        include_rewrite_plan=include_rewrite_plan,
        rewrite_plugin_plan_payload=rewrite_plugin_plan_payload,
        source_unit_id=source_unit_id,
        source_unit_goal=source_unit_goal,
        planning_units_yaml=planning_units_yaml,
        dependency_graph_payload=dependency_graph_payload,
        tooling_versions_payload=tooling_versions_payload,
        framework_versions_payload=framework_versions_payload,
        analysis_report_payload=analysis_report_payload,
    )
    run_dir = _run_dir(app, run_id)
    write_approved_plan_lock(run_dir, run_id)
    write_approval_decision(
        run_dir,
        run_id,
        "approved",
        plan_lock_ref="approved_plan_lock.json",
    )


def _write_run_artifacts(
    app: Path,
    run_id: str,
    *,
    include_rewrite_plan: bool = False,
    rewrite_plugin_plan_payload: dict[str, object] | None = None,
    source_unit_id: str = "java-17",
    source_unit_goal: str = "Upgrade project runtime to Java 17.",
    planning_units_yaml: str | None = None,
    dependency_graph_payload: dict[str, object] | None = None,
    tooling_versions_payload: dict[str, str] | None = None,
    framework_versions_payload: dict[str, str] | None = None,
    analysis_report_payload: dict[str, object] | None = None,
) -> None:
    run_dir = _run_dir(app, run_id)
    planning_dir = run_dir / "planning"
    assessment_dir = run_dir / "assessment"
    analysis_dir = run_dir / "analysis"
    planning_dir.mkdir(parents=True, exist_ok=True)
    assessment_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(
        json.dumps(analysis_report_payload or {"status": "PASS"}),
        encoding="utf-8",
    )

    (planning_dir / "migration_plan.yaml").write_text(
        f"""
schema_version: "1.0.0"
run_id: "{run_id}"
status: "PASS"
risk: "LOW"
profile: "java17"
tooling_versions:
{_tooling_versions_yaml(tooling_versions_payload)}
framework_versions:
{_tooling_versions_yaml(framework_versions_payload)}
artifact_refs:
  self: "migration_plan.yaml"
""".lstrip(),
        encoding="utf-8",
    )
    units_yaml = planning_units_yaml or f"""
schema_version: "1.0.0"
run_id: "{run_id}"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools:
      - "maven"
      - "junit"
    validation:
      - "mvn"
      - "clean"
      - "test"
    writes_source: false
    required: "yes"
    expected_artifacts:
      - "target/surefire-reports"
  - id: "{source_unit_id}"
    goal: "{source_unit_goal}"
    tools:
      - "maven"
    validation:
      - "mvn"
      - "clean"
      - "test"
    writes_source: true
    required: "yes"
    expected_artifacts:
      - "target/classes"
""".lstrip()
    (planning_dir / "migration_units.yaml").write_text(
        units_yaml,
        encoding="utf-8",
    )
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"profile": "java17"}),
        encoding="utf-8",
    )
    if dependency_graph_payload is not None:
        (analysis_dir / "dependency_graph.json").write_text(
            json.dumps(dependency_graph_payload),
            encoding="utf-8",
        )
    if include_rewrite_plan:
        (analysis_dir / "rewrite_plugin_plan.json").write_text(
            json.dumps(
                rewrite_plugin_plan_payload
                or {
                    "plugin": "org.openrewrite.maven:rewrite-maven-plugin:6.39.0",
                    "recipe_artifacts": ["org.openrewrite.recipe:rewrite-migrate-java:3.20.0"],
                    "active_recipes": ["org.openrewrite.java.migrate.UpgradeToJava17"],
                }
            ),
            encoding="utf-8",
        )


def _write_ai_hub_profile(ai_hub: Path, extra_profile_yaml: str = "") -> None:
    profiles = ai_hub / "profiles"
    catalogs = ai_hub / "catalogs"
    profiles.mkdir(parents=True)
    catalogs.mkdir(parents=True)
    (profiles / "java17.yaml").write_text(
        f"""
id: java17
openrewrite:
  catalog_path: catalogs/openrewrite.yaml
{extra_profile_yaml}
""".lstrip(),
        encoding="utf-8",
    )
    (catalogs / "openrewrite.yaml").write_text(
        """
id: openrewrite-java17
plugin:
  group_id: org.openrewrite.maven
  artifact_id: rewrite-maven-plugin
  version: 6.39.0
recipe_artifacts:
  - group_id: org.openrewrite.recipe
    artifact_id: rewrite-migrate-java
    version: 3.20.0
""".lstrip(),
        encoding="utf-8",
    )


def _tooling_versions_yaml(values: dict[str, str] | None) -> str:
    if not values:
        return "  {}\n"
    return "".join(f'  {key}: "{value}"\n' for key, value in values.items())


if __name__ == "__main__":
    unittest.main()
